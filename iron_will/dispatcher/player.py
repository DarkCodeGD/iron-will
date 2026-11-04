"""Random track selection + non-blocking, overlap-safe playback (Qt-free).

Overlap protection uses an ``flock`` on a file in ``$XDG_RUNTIME_DIR`` that is
held for the whole duration of playback. Because it's a kernel lock it works
*across processes* (daemon vs. the settings app's "test" button vs. the CLI)
and can never go stale — if a process dies the kernel releases it.

Each play runs on a short-lived worker thread, walking a backend fallback chain
(pw-play → paplay → ffplay → mpv) until one exits successfully.

Any process can ask "what's playing?" (``now_playing``) and stop it
(``request_stop``) — that's how the notification's Stop button, the settings
app and ``iron-will-audio --stop`` all reach a sound started elsewhere.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import random
import secrets
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .. import paths

log = logging.getLogger("iron_will.player")

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".oga", ".flac", ".opus"})
BACKENDS = ("pw-play", "paplay", "ffplay", "mpv")
MAX_TRACKS = 5000

DoneCallback = Callable[[bool, str], None]


def list_tracks(directory: Path) -> list[Path]:
    """All supported audio files below *directory*, sorted, capped at MAX_TRACKS."""
    if not directory.is_dir():
        return []
    tracks: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() in AUDIO_EXTENSIONS and path.is_file():
            tracks.append(path)
            if len(tracks) >= MAX_TRACKS:
                break
    return tracks


def pick_track(tracks: list[Path], avoid_repeat: bool = True) -> Path:
    """Random choice; optionally never the same track twice in a row
    (remembered on disk so it holds across daemon restarts)."""
    state = paths.state_dir() / "last_track"
    try:
        last = state.read_text(encoding="utf-8")
    except OSError:
        last = ""
    pool = [t for t in tracks if str(t) != last] if avoid_repeat and len(tracks) > 1 else tracks
    choice = random.choice(pool)
    try:
        state.write_text(str(choice), encoding="utf-8")
    except OSError:
        pass
    return choice


def build_command(backend: str, track: Path, volume: float) -> list[str]:
    volume = max(0.0, min(1.0, volume))
    match backend:
        case "pw-play":
            return ["pw-play", f"--volume={volume:.3f}", str(track)]
        case "paplay":
            return ["paplay", f"--volume={round(volume * 65536)}", str(track)]
        case "ffplay":
            return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-volume", str(round(volume * 100)), str(track)]
        case "mpv":
            return ["mpv", "--no-video", "--really-quiet", f"--volume={round(volume * 100)}", str(track)]
    raise ValueError(f"unknown backend {backend!r}")


def tie_to_owner(cmd: list[str]) -> list[str]:
    """Make the kernel SIGTERM the player if the thread that started it dies.

    The playback lock dies with its owner, so a player child that outlived it
    would be a sound nobody can see or stop (closing the settings app mid
    test-sound used to do exactly that). ``setpriv --pdeathsig`` sets
    PR_SET_PDEATHSIG and then execs the player in place (same PID, same argv
    tail), so even a SIGKILLed owner takes its sound down with it. The worker
    thread that spawns the child blocks in ``communicate()`` until the child
    exits, so the "parent thread died" signal can't fire early.
    """
    setpriv = shutil.which("setpriv")
    return [setpriv, "--pdeathsig", "TERM", "--", *cmd] if setpriv else cmd


def resolve_chain(preferred: str = "auto") -> list[str]:
    """Installed backends in try-order, preferred one first."""
    available = [b for b in BACKENDS if shutil.which(b)]
    if preferred in available:
        available.remove(preferred)
        available.insert(0, preferred)
    return available


def wait_for_sink(timeout: float, cancelled: Callable[[], bool]) -> bool:
    """Poll WirePlumber until a default output exists (after resume the audio
    graph can take a few seconds to come back). Returns True if one appeared.
    Without ``wpctl`` we can't check, so we just trust the configured delay."""
    if not shutil.which("wpctl"):
        return True
    deadline = time.monotonic() + timeout
    while not cancelled():
        try:
            probe = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            if probe.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.3)
    return False


# ── cross-process "now playing" + stop ─────────────────────────────────────
#
# The flock says *whether* a sound is playing; a small JSON file next to it
# says *what* and *who*. A stop request writes the playback's random token to
# STOP_FILE (so a request can never hit a later, different playback) and then
# SIGTERMs the player child. The owner notices the token between steps too,
# so a sound that's still waiting for an audio device is cancelled as well.

STATE_FILE = "playback.json"
STOP_FILE = "playback.stop"
STOPPED = "stopped"  # on_done message when a user / suspend stopped playback


def _lock_path() -> Path:
    return paths.runtime_dir() / "playback.lock"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def is_playing() -> bool:
    """True while any Iron Will process holds the playback lock."""
    try:
        fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)  # also drops our probe lock if we got it


def now_playing() -> dict | None:
    """``{"track", "event", "owner", ...}`` for the sound playing right now, else None.

    An *orphan* (a player child still running after its owner died without
    taking it down, e.g. on a system without ``setpriv``) counts as playing
    too, flagged ``"orphan": True``, so it can still be seen and stopped.
    """
    state = _read_json(paths.runtime_dir() / STATE_FILE)
    if is_playing():
        return state if state.get("track") else {"track": "", "event": ""}
    child, track = state.get("child"), state.get("track", "")
    if isinstance(child, int) and _is_player_process(child, track):
        return {**state, "orphan": True}
    return None   # nothing playing (a leftover state file from a dead owner is just ignored)


def _is_player_process(pid: int, track: str) -> bool:
    """Guard against PID reuse: only signal a process whose argv has our track."""
    if not track:   # b"" would match the empty field after argv's trailing NUL
        return False
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return track.encode() in argv


def request_stop() -> str | None:
    """Stop whatever Iron Will is playing, in any process.

    Returns the stopped track's file name, or None if nothing was playing.
    """
    playing = now_playing()
    if playing is None:
        return None
    token = playing.get("token")
    if token and not playing.get("orphan"):   # an orphan's owner is gone; nobody reads the file
        _write_atomic(paths.runtime_dir() / STOP_FILE, token)
    child, track = playing.get("child"), playing.get("track", "")
    if isinstance(child, int) and _is_player_process(child, track):
        try:
            os.kill(child, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return Path(track).name if track else ""


class Player:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._proc_mutex = threading.Lock()
        self._cancel = threading.Event()

    def play(self, track: Path, *, volume: float = 1.0, backend: str = "auto", wait_sink: float = 0.0,
             event: str = "test", on_done: DoneCallback | None = None) -> bool:
        """Start playing *track* in the background.

        Returns False immediately (without playing) if any Iron Will process is
        already playing a sound. ``on_done(ok, message)`` fires from the worker
        thread when playback finishes; *message* is ``STOPPED`` when it was
        stopped on request.
        """
        fd = os.open(_lock_path(), os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._cancel.clear()
        state = {"track": str(track), "event": event, "owner": os.getpid(), "child": None,
                 "token": secrets.token_hex(8), "started": time.time()}
        self._write_state(state)
        threading.Thread(target=self._run, args=(fd, state, volume, backend, wait_sink, on_done),
                         name="iron-will-playback", daemon=True).start()
        return True

    def stop(self) -> None:
        """Cancel this player's pending/ongoing playback."""
        self._cancel.set()
        with self._proc_mutex:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    # ── worker ────────────────────────────────────────────────────────────
    @staticmethod
    def _write_state(state: dict) -> None:
        try:
            _write_atomic(paths.runtime_dir() / STATE_FILE, json.dumps(state))
        except OSError as exc:
            log.debug("cannot write playback state: %s", exc)

    def _cancelled(self, token: str) -> bool:
        if self._cancel.is_set():
            return True
        try:
            return (paths.runtime_dir() / STOP_FILE).read_text(encoding="utf-8") == token
        except OSError:
            return False

    def _run(self, lock_fd: int, state: dict, volume: float, backend: str,
             wait_sink: float, on_done: DoneCallback | None) -> None:
        track, token = Path(state["track"]), state["token"]
        cancelled = lambda: self._cancelled(token)  # noqa: E731
        ok, message = False, ""
        try:
            if wait_sink > 0 and not wait_for_sink(wait_sink, cancelled):
                if cancelled():
                    message = STOPPED
                    return
                log.warning("no audio output after %.0fs — trying anyway", wait_sink)

            chain = resolve_chain(backend)
            if not chain:
                message = "no audio player found (install pipewire-utils)"
                return
            for name in chain:
                if cancelled():
                    message = STOPPED
                    return
                try:
                    proc = subprocess.Popen(tie_to_owner(build_command(name, track, volume)), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                except OSError as exc:
                    log.warning("%s could not start: %s", name, exc)
                    continue
                with self._proc_mutex:
                    self._proc = proc
                self._write_state({**state, "child": proc.pid})
                if cancelled():          # a stop raced in before the child pid was published
                    proc.terminate()
                _, err = proc.communicate()
                with self._proc_mutex:
                    self._proc = None
                if proc.returncode == 0:
                    ok, message = True, f"played {track.name} via {name}"
                    return
                if cancelled():
                    message = STOPPED
                    return
                log.warning("%s failed (exit %s): %s — trying next backend",
                            name, proc.returncode, err.decode(errors="replace").strip()[-300:])
            message = "every audio backend failed, see the log"
        finally:
            run = paths.runtime_dir()
            if _read_json(run / STATE_FILE).get("token") == token:
                (run / STATE_FILE).unlink(missing_ok=True)
            (run / STOP_FILE).unlink(missing_ok=True)
            os.close(lock_fd)  # releases the flock → next sound may play
            if message and not ok:
                log.info("playback: %s", message)
            if on_done:
                on_done(ok, message)
