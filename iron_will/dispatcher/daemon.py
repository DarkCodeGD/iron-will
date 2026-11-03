"""Session sound daemon: plays a random track on login, resume and unlock.

Runs as a *user* systemd service (no root). It listens on D-Bus:

* system bus  ``org.freedesktop.login1.Manager.PrepareForSleep(b)``
      True  → about to suspend: cancel anything pending
      False → resumed: play (after a delay + waiting for an audio sink)
* session bus ``org.freedesktop.ScreenSaver.ActiveChanged(b)``
      False → screen unlocked (KDE's kscreenlocker emits this)
* daemon start → login (once per session; a crash-restart won't replay it)

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
from .player import Player, list_tracks, pick_track

log = logging.getLogger("iron_will.dispatcher")

EVENTS = ("login", "resume", "unlock")
# After the configured delay, how long we'll additionally wait for PipeWire to
# expose a default output before giving it a go anyway.
SINK_WAIT = {"login": 15.0, "resume": 10.0, "unlock": 3.0, "test": 0.0}


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

    # ── wiring ────────────────────────────────────────────────────────────
    def start(self) -> None:
        system = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._subscriptions.append((system, system.signal_subscribe(
            "org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
            "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, self._on_prepare_for_sleep)))
        self._subscriptions.append((session, session.signal_subscribe(
            None, "org.freedesktop.ScreenSaver", "ActiveChanged",
            None, None, Gio.DBusSignalFlags.NONE, self._on_screensaver)))
        log.info("listening for resume (logind) and unlock (ScreenSaver) events")
        if self._first_start_this_session():
            self.trigger("login")

    def shutdown(self) -> None:
        for conn, sub_id in self._subscriptions:
            conn.signal_unsubscribe(sub_id)
        self._cancel_pending()
        self.player.stop()

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

    # ── D-Bus handlers ────────────────────────────────────────────────────
    def _on_prepare_for_sleep(self, _conn, _sender, _path, _iface, _signal, params, *_):
        (going_to_sleep,) = params.unpack()
        if going_to_sleep:
            log.info("suspending — cancelling pending sounds")
            self._cancel_pending()
            self.player.stop()
        else:
            self.trigger("resume")

    def _on_screensaver(self, _conn, _sender, _path, _iface, _signal, params, *_):
        (active,) = params.unpack()
        if not active:
            self.trigger("unlock")

    # ── scheduling ────────────────────────────────────────────────────────
    def trigger(self, event: str) -> None:
        cfg = config.load(fallback=True)
        if not cfg[f"sounds.on_{event}"]:
            log.debug("%s: disabled in config", event)
            return
        if event in self._pending:
            # KDE emits ActiveChanged on two object paths; collapse duplicates.
            return
        delay_ms = int(cfg[f"sounds.{event}_delay"] * 1000)
        log.info("%s detected — playing in %.1fs", event, delay_ms / 1000)
        self._pending[event] = GLib.timeout_add(delay_ms, self._fire, event)

    def _cancel_pending(self) -> None:
        for source_id in self._pending.values():
            GLib.source_remove(source_id)
        self._pending.clear()

    def _fire(self, event: str) -> bool:
        self._pending.pop(event, None)
        cfg = config.load(fallback=True)
        now = _now()
        if now - self._last_played < cfg["sounds.cooldown"]:
            log.info("%s: within the %ss cooldown — skipped", event, cfg["sounds.cooldown"])
            return GLib.SOURCE_REMOVE
        directory = paths.expand(cfg["sounds.directory"])
        tracks = list_tracks(directory)
        if not tracks:
            log.warning("%s: no audio files in %s", event, directory)
            return GLib.SOURCE_REMOVE
        track = pick_track(tracks, cfg["sounds.avoid_repeat"])
        started = self.player.play(track, volume=cfg["sounds.volume"], backend=cfg["sounds.backend"],
                                   wait_sink=SINK_WAIT[event])
        if started:
            self._last_played = now
            log.info("%s → %s", event, track.name)
        else:
            log.info("%s: a sound is already playing — skipped", event)
        return GLib.SOURCE_REMOVE


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

    def finished(ok: bool, message: str) -> None:
        result.append(ok)
        log.info("%s", message)
        done.set()

    log.info("playing %s", track)
    if not Player().play(track, volume=cfg["sounds.volume"], backend=cfg["sounds.backend"],
                         wait_sink=SINK_WAIT.get(event, 0.0), on_done=finished):
        log.error("another sound is already playing")
        return 1
    done.wait()
    return 0 if result and result[0] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iron-will-audio", description="Iron Will session sound daemon")
    parser.add_argument("--play", action="store_true", help="play one random track now and exit")
    parser.add_argument("--list", action="store_true", help="list the tracks that would be used")
    args = parser.parse_args(argv)
    setup_logging()

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
