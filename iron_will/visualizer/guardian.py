"""Keeps the visualizer alive across suspend, lid close and monitor hot-plug.

Two things go wrong when the machine sleeps:

1. **The window disappears.** When its output goes away (suspend, lid close,
   unplugging a monitor) the compositor closes our layer-shell surface and
   Qt turns that into ``QWindow::close()``. With Qt's default
   ``quitOnLastWindowClosed`` the app then *exits cleanly with code 0*, which
   systemd's ``Restart=on-failure`` doesn't count as a failure, so the
   visualizer stayed dead after every wake-up.

   Fix: never quit on window close. Pause rendering instead (zero CPU while
   there is nothing to draw on) and show the window again on the primary
   screen as soon as a real output exists.

2. **The audio stream goes stale.** After a resume, PipeWire re-creates its
   devices and cava's capture stream can stop delivering frames.

   Fix: detect the sleep and restart cava. ``CLOCK_BOOTTIME`` keeps counting
   while suspended and ``CLOCK_MONOTONIC`` doesn't, so a sudden jump in
   their difference *is* a suspend. This needs no D-Bus and works anywhere.

**One calm recovery, not a flurry.** The first second after a wake is the
busiest moment the desktop has: CPUs come back online, KWin rebuilds its
outputs, PipeWire and NetworkManager reconnect. Re-creating a GL surface
and restarting cava *separately* in that window made the desktop stutter
and looked like the visualizer started twice. So every trigger (surface
closed, wake, screen added) just pokes one debounced *settle* timer. When
things have been quiet for a moment it does everything at once: restart
cava if we slept, then show the window, which fades in from zero.

**Nothing runs behind the lock screen.** On a laptop, "resume" means "the
lock screen appeared"; you're only back once you've typed your password.
While the screen is locked the visualizer is paused and cava is stopped,
and the recovery step waits for the unlock.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QGuiApplication, QWindow

log = logging.getLogger("iron_will.visualizer")

SLEEP_CHECK_MS = 2000
SLEEP_GAP_S = 4.0          # a ≥4s jump between the two clocks = we were suspended
SETTLE_MS = 1200           # act once screens/surfaces have been quiet this long
WAKE_SETTLE_S = 2.5        # …and never sooner than this after a wake-up
RETRY_BACKOFF_MS = (1000, 2000, 5000, 10000)  # still no output? poll gently
UNLOCK_SETTLE_MS = 300     # after the password: come back promptly, the desktop is ready


def _sleep_offset() -> float:
    """Total time spent suspended since boot (BOOTTIME − MONOTONIC)."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


def _has_real_screen(app: QGuiApplication) -> bool:
    # With no outputs, QtWayland installs a nameless placeholder screen; a
    # surface shown there would be closed again straight away.
    return any(screen.name() for screen in app.screens())


def _screen_named(app: QGuiApplication, name: str):
    return next((s for s in app.screens() if name and s.name() == name), None)


@dataclass
class Hooks:
    """What the guardian controls. All are called on the Qt thread."""
    pause: Callable[[], None]        # stop drawing (window gone, or screen locked)
    resume: Callable[[], None]       # start drawing again from zero, fading in
    stop_audio: Callable[[], None]   # stop cava
    start_audio: Callable[[], None]  # (re)start cava with the current settings


class WindowGuardian(QObject):
    def __init__(self, window: QWindow, hooks: Hooks, lock=None, parent: QObject | None = None) -> None:
        """*lock* is an optional LockWatcher (``.locked`` + ``changed(bool)``)."""
        super().__init__(parent)
        self._window = window
        self._hooks = hooks
        self._lock = lock
        self._quitting = False
        self._moving = False
        self._paused = False         # rendering paused by us
        self._audio_stale = False    # cava must be (re)started at the next recovery
        self._hold_until = 0.0       # monotonic time before which we don't act (still waking)
        self._attempt = 0
        self._last_offset = _sleep_offset()
        # The output we belong on: the one we started on. QtWayland's
        # "primary" is just the first output the compositor announced (it
        # can't see KDE's screen priority), so after hot-plug it can point
        # anywhere. "Go back where you were" is the predictable rule.
        self._home = window.screen().name() if window.screen() else ""

        app = QGuiApplication.instance()
        app.setQuitOnLastWindowClosed(False)
        app.aboutToQuit.connect(self._about_to_quit)
        app.installEventFilter(self)  # see QEvent.Quit *before* Qt closes our window
        app.screenAdded.connect(self._poke)
        app.primaryScreenChanged.connect(self._poke)
        window.visibleChanged.connect(self._on_visible_changed)
        if lock is not None:
            lock.changed.connect(self._on_lock_changed)

        self._settle = QTimer(self, singleShot=True)
        self._settle.timeout.connect(self._settled)
        self._sleep_timer = QTimer(self, interval=SLEEP_CHECK_MS)
        self._sleep_timer.timeout.connect(self._check_sleep)
        self._sleep_timer.start()

    # ── public ────────────────────────────────────────────────────────────
    def request_audio_restart(self) -> None:
        """Settings changed: restart cava now, or at unlock if we're locked."""
        if self._locked():
            self._audio_stale = True
        else:
            self._hooks.start_audio()

    # ── shutdown ──────────────────────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:
        # Qt 6's quit() closes every window while handling QEvent.Quit, i.e.
        # before aboutToQuit; without this a normal shutdown would look like
        # "the compositor closed our surface" and schedule a re-show.
        if event.type() == QEvent.Type.Quit:
            self._about_to_quit()
        return False

    def _about_to_quit(self) -> None:
        self._quitting = True
        self._settle.stop()

    # ── helpers ───────────────────────────────────────────────────────────
    def _locked(self) -> bool:
        return self._lock is not None and self._lock.locked

    def _pause(self) -> None:
        if not self._paused:
            self._paused = True
            self._hooks.pause()

    def _unpause(self) -> None:
        if self._paused:
            self._paused = False
            self._hooks.resume()

    # ── triggers: all of them just (re)start the settle timer ─────────────
    def _poke(self, *_args, delay: int = SETTLE_MS) -> None:
        if not self._quitting:
            self._attempt = 0
            self._settle.start(delay)

    def _on_visible_changed(self, visible: bool) -> None:
        if self._quitting or self._moving:
            return
        if visible:
            if not self._locked():
                self._unpause()
            return
        self._pause()
        log.info("visualizer surface was closed (output removed or suspended); waiting for a screen")
        self._poke()

    def _on_lock_changed(self, locked: bool) -> None:
        if self._quitting:
            return
        if locked:
            self._settle.stop()        # no recovery behind the lock screen
            self._pause()
            self._hooks.stop_audio()
            self._audio_stale = True
        else:
            self._poke(delay=UNLOCK_SETTLE_MS)

    def _check_sleep(self) -> None:
        offset = _sleep_offset()
        slept, self._last_offset = offset - self._last_offset, offset
        if slept >= SLEEP_GAP_S:
            log.info("woke up after %.0fs of suspend; waiting for the desktop to settle", slept)
            self._audio_stale = True
            self._hold_until = time.monotonic() + WAKE_SETTLE_S
            if self._lock is not None:
                self._lock.refresh()   # lock-screen signals can be missed around a suspend
            self._poke()

    # ── the one recovery step ─────────────────────────────────────────────
    def _settled(self) -> None:
        if self._quitting:
            return
        # Timers that were due during the suspend all fire the moment we're
        # thawed; make sure the wake is noticed before acting on anything.
        self._check_sleep()
        wait = self._hold_until - time.monotonic()
        if wait > 0:
            self._settle.start(int(wait * 1000) + 50)
            return
        if self._locked():
            log.info("screen is locked; the visualizer will start after you unlock")
            return                     # the unlock pokes us again
        app = QGuiApplication.instance()
        hidden = not self._window.isVisible()
        if hidden and not _has_real_screen(app):
            log.debug("no output yet (attempt %d)", self._attempt)
            self._settle.start(RETRY_BACKOFF_MS[min(self._attempt, len(RETRY_BACKOFF_MS) - 1)])
            self._attempt += 1
            return

        if self._audio_stale:      # restart capture first, so the bars come back on fresh frames
            self._audio_stale = False
            log.info("starting audio capture")
            self._hooks.start_audio()
        if hidden:
            screen = self._target_screen()
            if screen is not None and self._window.screen() is not screen:
                self._window.setScreen(screen)
            log.info("re-showing the visualizer on %s", screen.name() if screen else "?")
            self._window.show()    # → visibleChanged → fade in; if closed again, we get poked
        else:
            self._unpause()
            self._go_home()

    def _target_screen(self):
        """Home output if it's connected, else Qt's primary (first real) one."""
        app = QGuiApplication.instance()
        return _screen_named(app, self._home) or app.primaryScreen()

    def _go_home(self) -> None:
        """After hot-plug, return to the home output if we got stranded on
        another one. A layer surface's output is fixed when it's created, so
        moving means re-creating it: hide → setScreen → show."""
        home = _screen_named(QGuiApplication.instance(), self._home)
        if home is None or self._window.screen() is home:
            return
        log.info("moving the visualizer back to %s", home.name())
        self._moving = True
        try:
            self._window.hide()
            self._window.setScreen(home)
            self._window.show()
        finally:
            self._moving = False
