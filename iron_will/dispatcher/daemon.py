"""Session sound daemon: plays a random track on login, resume and unlock.

Runs as a *user* systemd service (no root). It listens on D-Bus:

* system bus  ``org.freedesktop.login1.Manager.PrepareForSleep(b)``
      True  → about to suspend: cancel anything pending, stop what's playing
      False → resumed: play (after a delay + waiting for an audio sink)
* session bus ``org.freedesktop.ScreenSaver.ActiveChanged(b)``
      True → False → screen unlocked (a real locked→unlocked transition only)
* daemon start → login (once per session; a crash-restart won't replay it)

Resume is held back while the lock screen is up: on a laptop "resume" means
"the lock screen appeared", and you're only really back once you've typed
your password. So after a resume with a locked screen, the resume sound
plays right after the unlock instead (one sound, not resume + unlock).

Between PrepareForSleep(True) and (False) we're "sleeping": KDE locks the
screen and the lock screen can flap ActiveChanged while the machine goes
down, so unlocks are ignored there — otherwise a sound starts, freezes
mid-suspend and plays on after wake (and eats the resume sound's cooldown).

While a sound plays, a notification offers a Stop button, and the sound shows
up in Plasma's media controls (MPRIS) like any player, so the media widget,
the lock screen and the media keys stop it too; ``--stop`` (and the settings
app) stop it from anywhere. With ``sounds.yield_to_media`` it makes way for
real music: no sound while a player is playing, and starting one stops it.

Config is re-read on every event, so edits apply without a restart.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib

from .. import config, paths
from ..util import acquire_lock, setup_logging
from .mpris import MediaPlayer, MediaWatcher
from .notify import Notifier
from .player import STOPPED, Player, list_tracks, now_playing, pick_track, request_stop

log = logging.getLogger("iron_will.dispatcher")

EVENTS = ("login", "resume", "unlock")
# After the configured delay, how long we'll additionally wait for PipeWire to
# expose a default output before giving it a go anyway.
SINK_WAIT = {"login": 15.0, "resume": 10.0, "unlock": 3.0, "test": 0.0}
SCREENSAVER = "org.freedesktop.ScreenSaver"


def _now() -> float:
    # CLOCK_BOOTTIME keeps counting while suspended. CLOCK_MONOTONIC does NOT,
    # which would make "played 5s before an 8-hour sleep" look like "5s ago"
    # and wrongly swallow the resume sound via the cooldown.
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _session_fingerprint() -> str:
    return f"{_boot_id()}:{os.environ.get('XDG_SESSION_ID', '')}"


class Dispatcher:
    def __init__(self) -> None:
        self.player = Player()
        self._pending: dict[str, int] = {}  # event -> GLib source id
        self._last_played = float("-inf")
        self._subscriptions: list[tuple[Gio.DBusConnection, int]] = []
        self._session: Gio.DBusConnection | None = None
        self._notifier: Notifier | None = None
        self._media: MediaPlayer | None = None
        self._watcher: MediaWatcher | None = None
        self._sleeping = False
        self._resume_waiting = False   # resumed behind the lock screen; play once unlocked
        # Is the screen locked? None = unknown (then any unlock signal counts).
        self._locked: bool | None = None

    # ── wiring ────────────────────────────────────────────────────────────
    def start(self) -> None:
        system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._subscriptions.append((system, system.signal_subscribe(
            "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
            "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, self._on_prepare_for_sleep)))
        # Only the real screensaver (KWin on Plasma) — the bus resolves the
        # well-known name to its owner, so other apps can't fake an unlock.
        self._subscriptions.append((session, session.signal_subscribe(
            SCREENSAVER, SCREENSAVER, "ActiveChanged",
            None, None, Gio.DBusSignalFlags.NONE, self._on_screensaver)))
        self._session = session
        self._notifier = Notifier(session, on_stop=self._stop_playback)
        self._media = MediaPlayer(session, on_stop=self._stop_playback)
        self._watcher = MediaWatcher(session, on_started=self._on_other_player_started)
        self._sync_lock_state()
        log.info("listening for resume (logind) and unlock (ScreenSaver) events")
        if self._first_start_this_session():
            self.trigger("login")

    def shutdown(self) -> None:
        for conn, sub_id in self._subscriptions:
            conn.signal_unsubscribe(sub_id)
        self._cancel_pending()
        self.player.stop()
        if self._notifier:
            self._notifier.shutdown()
        if self._media:
            self._media.shutdown()
        if self._watcher:
            self._watcher.shutdown()

    def _first_start_this_session(self) -> bool:
        marker = paths.runtime_dir() / "login-played"
        fingerprint = _session_fingerprint()
        try:
            if marker.read_text() == fingerprint:
                log.info("restarted within the same session — skipping the login sound")
                return False
        except OSError:
            pass
        marker.write_text(fingerprint)
        return True

    def _sync_lock_state(self, then=None) -> None:
        """Ask the screensaver whether the screen is locked right now (async).
        *then(locked)* runs with the answer (None when it can't be known)."""
        def reply(bus, result) -> None:
            try:
                (self._locked,) = bus.call_finish(result).unpack()
                log.debug("screen locked: %s", self._locked)
            except GLib.Error as exc:
                log.debug("ScreenSaver.GetActive failed: %s", exc.message)
                self._locked = None
            if then:
                then(self._locked)
        self._session.call(SCREENSAVER, "/org/freedesktop/ScreenSaver", SCREENSAVER, "GetActive", None,
                           GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None, reply)

    # ── D-Bus handlers ────────────────────────────────────────────────────
    def _on_prepare_for_sleep(self, _conn, _sender, _path, _iface, _signal, params, *_):
        (going_to_sleep,) = params.unpack()
        if going_to_sleep:
            log.info("suspending — cancelling pending sounds")
            self._sleeping = True
            self._resume_waiting = False
            self._cancel_pending()
            self._stop_playback()   # any Iron Will sound, not just ours
        else:
            self._sleeping = False
            # Lock-screen signals during suspend may have been missed (or were
            # ghosts), so ask for the truth before deciding when to play.
            self._sync_lock_state(then=self._after_resume)

    def _after_resume(self, locked: bool | None) -> None:
        if self._sleeping:          # went straight back to sleep
            return
        if locked:
            log.info("resumed behind the lock screen — the sound will play after you unlock")
            self._resume_waiting = True
        else:
            self.trigger("resume")

    def _on_screensaver(self, _conn, _sender, _path, _iface, _signal, params, *_):
        (active,) = params.unpack()
        was_locked, self._locked = self._locked, active
        if active:
            if "resume" in self._pending and not self._sleeping:
                # The lock screen showed up just after the resume: wait for it.
                GLib.source_remove(self._pending.pop("resume"))
                self._resume_waiting = True
                log.info("screen locked after resume — the sound will play after you unlock")
            return
        if was_locked is False:
            log.debug("ActiveChanged(false) without a lock — ignored")  # e.g. KDE's duplicate path
        elif self._sleeping:
            log.info("unlock signal while suspending — ignored")
        elif self._resume_waiting:
            self._resume_waiting = False
            self._welcome_back()
        else:
            self.trigger("unlock")

    def _welcome_back(self) -> None:
        """First unlock after a resume: play *one* sound, now that you're back."""
        log.info("unlocked after resume — welcome back")
        cfg = config.load(fallback=True)
        if cfg["sounds.on_resume"]:
            # The audio devices have long woken up by now: use the short unlock delay.
            self.trigger("resume", delay=cfg["sounds.unlock_delay"])
        else:
            self.trigger("unlock")

    # ── scheduling ────────────────────────────────────────────────────────
    def trigger(self, event: str, delay: float | None = None) -> None:
        cfg = config.load(fallback=True)
        if not cfg[f"sounds.on_{event}"]:
            log.debug("%s: disabled in config", event)
            return
        if event in self._pending:
            # KDE emits ActiveChanged on two object paths; collapse duplicates.
            return
        delay_ms = int((cfg[f"sounds.{event}_delay"] if delay is None else delay) * 1000)
        log.info("%s detected — playing in %.1fs", event, delay_ms / 1000)
        self._pending[event] = GLib.timeout_add(delay_ms, self._fire, event)

    def _cancel_pending(self) -> None:
        for source_id in self._pending.values():
            GLib.source_remove(source_id)
        self._pending.clear()

    def _fire(self, event: str) -> bool:
        self._pending.pop(event, None)
        if self._sleeping:
            return GLib.SOURCE_REMOVE
        cfg = config.load(fallback=True)
        now = _now()
        if now - self._last_played < cfg["sounds.cooldown"]:
            log.info("%s: within the %ss cooldown — skipped", event, cfg["sounds.cooldown"])
            return GLib.SOURCE_REMOVE
        busy = self._watcher.others_playing() if cfg["sounds.yield_to_media"] and self._watcher else []
        if busy:
            log.info("%s: %s is playing — making way for your music", event, _player_label(busy[0]))
            return GLib.SOURCE_REMOVE
        directory = paths.expand(cfg["sounds.directory"])
        tracks = list_tracks(directory)
        if not tracks:
            log.warning("%s: no audio files in %s", event, directory)
            return GLib.SOURCE_REMOVE
        track = pick_track(tracks, cfg["sounds.avoid_repeat"])
        started = self.player.play(track, volume=cfg["sounds.volume"], backend=cfg["sounds.backend"],
                                   wait_sink=SINK_WAIT[event], event=event, on_done=self._on_played)
        if started:
            self._last_played = now
            log.info("%s → %s", event, track.name)
            if cfg["sounds.notify"] and self._notifier:
                self._notifier.show(track.stem, event)
            if self._media:
                self._media.show(track.stem, event, cfg["sounds.volume"])
        else:
            log.info("%s: a sound is already playing — skipped", event)
        return GLib.SOURCE_REMOVE

    # ── playback lifecycle ────────────────────────────────────────────────
    def _stop_playback(self) -> None:
        stopped = request_stop()
        if stopped:
            log.info("stopped %s", stopped)
        self._hide_controls()

    def _hide_controls(self) -> None:
        if self._notifier:
            self._notifier.close()
        if self._media:
            self._media.hide()

    def _on_other_player_started(self, name: str) -> None:
        """Another MPRIS player went to Playing (you started a song or a video)."""
        if not (self._media and self._media.active):
            return   # we aren't playing anything
        if not config.load(fallback=True)["sounds.yield_to_media"]:
            return
        log.info("%s started playing — making way for your music", _player_label(name))
        self._stop_playback()

    def _on_played(self, _ok: bool, message: str) -> None:
        # Player worker thread → hop onto the GLib loop before touching D-Bus state.
        def done() -> bool:
            self._hide_controls()
            if message == STOPPED:
                log.info("playback stopped")
            return GLib.SOURCE_REMOVE
        GLib.idle_add(done)


def _player_label(bus_name: str) -> str:
    """``org.mpris.MediaPlayer2.elisa`` → ``elisa`` (browsers add ``.instance123``)."""
    return bus_name.removeprefix("org.mpris.MediaPlayer2.").split(".instance")[0] or bus_name


def play_once(event: str = "test") -> int:
    """CLI helper: play a random track right now and wait for it to finish."""
    cfg = config.load(fallback=True)
    directory = paths.expand(cfg["sounds.directory"])
    tracks = list_tracks(directory)
    if not tracks:
        log.error("no audio files in %s", directory)
        return 1
    track = pick_track(tracks, cfg["sounds.avoid_repeat"])
    done = threading.Event()
    result: list[bool] = []

    stopped = [False]

    def finished(ok: bool, message: str) -> None:
        stopped[0] = message == STOPPED  # stopped on request isn't a failure
        result.append(ok)
        log.info("%s", message)
        done.set()

    log.info("playing %s", track)
    if not Player().play(track, volume=cfg["sounds.volume"], backend=cfg["sounds.backend"],
                         wait_sink=SINK_WAIT.get(event, 0.0), event=event, on_done=finished):
        log.error("another sound is already playing")
        return 1
    done.wait()
    return 0 if result and (result[0] or stopped[0]) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iron-will-audio", description="Iron Will session sound daemon")
    parser.add_argument("--play", action="store_true", help="play one random track now and exit")
    parser.add_argument("--list", action="store_true", help="list the tracks that would be used")
    parser.add_argument("--stop", action="store_true", help="stop the sound Iron Will is playing")
    parser.add_argument("--status", action="store_true", help="print what is playing (exit 1 if nothing)")
    args = parser.parse_args(argv)
    setup_logging()

    if args.stop:
        stopped = request_stop()
        print(f"stopped {stopped}" if stopped else "nothing is playing")
        return 0
    if args.status:
        playing = now_playing()
        if playing is None:
            print("nothing is playing")
            return 1
        print(f"playing {Path(playing['track']).name} ({playing.get('event') or 'unknown'})")
        return 0

    if args.list:
        directory = paths.expand(config.load(fallback=True)["sounds.directory"])
        tracks = list_tracks(directory)
        print(f"{len(tracks)} track(s) in {directory}")
        for track in tracks:
            print(f"  {track.relative_to(directory)}")
        return 0
    if args.play:
        return play_once()

    lock = acquire_lock("dispatcher")
    if lock is None:
        log.error("another iron-will-audio daemon is already running")
        return 1
    config.ensure_exists()

    loop = GLib.MainLoop()
    dispatcher = Dispatcher()
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
    try:
        dispatcher.start()
    except GLib.Error as exc:
        log.error("cannot connect to D-Bus: %s", exc.message)
        return 1
    loop.run()
    dispatcher.shutdown()
    log.info("bye")
    return 0
