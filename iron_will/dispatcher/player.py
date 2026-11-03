"""Random track selection + non-blocking, overlap-safe playback (Qt-free).

Overlap protection uses an ``flock`` on a file in ``$XDG_RUNTIME_DIR`` that is
held for the whole duration of playback. Because it's a kernel lock it works
*across processes* (daemon vs. the settings app's "test" button vs. the CLI)
and can never go stale — if a process dies the kernel releases it.

Each play runs on a short-lived worker thread, walking a backend fallback chain
(pw-play → paplay → ffplay → mpv) until one exits successfully.
"""

from __future__ import annotations

import fcntl
import logging
import os
import random
import shutil
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


def resolve_chain(preferred: str = "auto") -> list[str]:
    """Installed backends in try-order, preferred one first."""
    available = [b for b in BACKENDS if shutil.which(b)]
    if preferred in available:
        available.remove(preferred)
        available.insert(0, preferred)
    return available


def wait_for_sink(timeout: float, cancel: threading.Event) -> bool:
    """Poll WirePlumber until a default output exists (after resume the audio
    graph can take a few seconds to come back). Returns True if one appeared.
    Without ``wpctl`` we can't check, so we just trust the configured delay."""
    if not shutil.which("wpctl"):
        return True
    deadline = time.monotonic() + timeout
    while not cancel.is_set():
        try:
            probe = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            if probe.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() >= deadline:
            return False
        cancel.wait(0.4)
    return False


class Player:
    def __init__(self) -> None:
        self._lock_path = paths.runtime_dir() / "playback.lock"
        self._proc: subprocess.Popen | None = None
        self._proc_mutex = threading.Lock()
        self._cancel = threading.Event()

    def play(self, track: Path, *, volume: float = 1.0, backend: str = "auto",
             wait_sink: float = 0.0, on_done: DoneCallback | None = None) -> bool:
        """Start playing *track* in the background.

        Returns False immediately (without playing) if any Iron Will process is
        already playing a sound. ``on_done(ok, message)`` fires from the worker
        thread when playback finishes.
        """
        fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._cancel.clear()
        threading.Thread(target=self._run, args=(fd, track, volume, backend, wait_sink, on_done),
                         name="iron-will-playback", daemon=True).start()
        return True

    def stop(self) -> None:
        """Cancel a pending/ongoing playback (e.g. we're about to suspend)."""
        self._cancel.set()
        with self._proc_mutex:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()

    def _run(self, lock_fd: int, track: Path, volume: float, backend: str,
             wait_sink: float, on_done: DoneCallback | None) -> None:
        ok, message = False, ""
        try:
            if wait_sink > 0 and not wait_for_sink(wait_sink, self._cancel):
                if self._cancel.is_set():
                    message = "cancelled"
                    return
                log.warning("no audio output after %.0fs — trying anyway", wait_sink)

            chain = resolve_chain(backend)
            if not chain:
                message = "no audio player found (install pipewire-utils)"
                return
            for name in chain:
                if self._cancel.is_set():
                    message = "cancelled"
                    return
                try:
                    proc = subprocess.Popen(build_command(name, track, volume), stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                except OSError as exc:
                    log.warning("%s could not start: %s", name, exc)
                    continue
                with self._proc_mutex:
                    self._proc = proc
                _, err = proc.communicate()
                with self._proc_mutex:
                    self._proc = None
                if proc.returncode == 0:
                    ok, message = True, f"played {track.name} via {name}"
                    return
                if self._cancel.is_set():
                    message = "cancelled"
                    return
                log.warning("%s failed (exit %s): %s — trying next backend",
                            name, proc.returncode, err.decode(errors="replace").strip()[-300:])
            message = "every audio backend failed, see the log"
        finally:
            os.close(lock_fd)  # releases the flock → next sound may play
            if message and not ok:
                log.info("playback: %s", message)
            if on_done:
                on_done(ok, message)
