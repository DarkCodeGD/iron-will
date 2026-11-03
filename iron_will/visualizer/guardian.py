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
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QGuiApplication, QWindow

log = logging.getLogger("iron_will.visualizer")

SLEEP_CHECK_MS = 2000
SLEEP_GAP_S = 4.0          # a ≥4s jump between the two clocks = we were suspended
CAVA_SETTLE_MS = 2500      # give PipeWire a moment to rebuild its graph after wake
RESHOW_BACKOFF_MS = (250, 1000, 2000, 5000, 10000)
HOME_DEBOUNCE_MS = 800     # screen hot-plug arrives as a burst of signals


def _sleep_offset() -> float:
    """Total time spent suspended since boot (BOOTTIME − MONOTONIC)."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


def _has_real_screen(app: QGuiApplication) -> bool:
    # With no outputs, QtWayland installs a nameless placeholder screen; a
    # surface shown there would be closed again straight away.
    return any(screen.name() for screen in app.screens())


def _screen_named(app: QGuiApplication, name: str):
    return next((s for s in app.screens() if name and s.name() == name), None)


class WindowGuardian(QObject):
    def __init__(self, window: QWindow, on_hidden: Callable[[bool], None],
                 on_resume: Callable[[], None], parent: QObject | None = None) -> None:
        """*on_hidden(hidden)* pauses/resumes rendering; *on_resume()* restarts audio."""
        super().__init__(parent)
        self._window = window
        self._on_hidden = on_hidden
        self._on_resume = on_resume
        self._quitting = False
        self._moving = False
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
        app.screenAdded.connect(self._on_screens_changed)
        window.visibleChanged.connect(self._on_visible_changed)

        self._reshow_timer = QTimer(self, singleShot=True)
        self._reshow_timer.timeout.connect(self._try_reshow)
        self._home_timer = QTimer(self, singleShot=True, interval=HOME_DEBOUNCE_MS)
        self._home_timer.timeout.connect(self._go_home)
        self._sleep_timer = QTimer(self, interval=SLEEP_CHECK_MS)
        self._sleep_timer.timeout.connect(self._check_sleep)
        self._sleep_timer.start()
        self._resume_timer = QTimer(self, singleShot=True, interval=CAVA_SETTLE_MS)
        self._resume_timer.timeout.connect(self._resumed)

    # ── window lifecycle ──────────────────────────────────────────────────
    def eventFilter(self, obj, event) -> bool:
        # Qt 6's quit() closes every window while handling QEvent.Quit, i.e.
        # before aboutToQuit; without this a normal shutdown would look like
        # "the compositor closed our surface" and schedule a re-show.
        if event.type() == QEvent.Type.Quit:
            self._about_to_quit()
        return False

    def _about_to_quit(self) -> None:
        self._quitting = True
        self._reshow_timer.stop()

    def _target_screen(self):
        """Home output if it's connected, else Qt's primary (first real) one."""
        app = QGuiApplication.instance()
        return _screen_named(app, self._home) or app.primaryScreen()

    def _on_screens_changed(self, _screen) -> None:
        if self._window.isVisible():
            self._home_timer.start()     # maybe our home output just came back
        else:
            self._schedule_reshow(reset=True)

    def _go_home(self) -> None:
        """After hot-plug, return to the home output if we got stranded on
        another one. A layer surface's output is fixed when it's created, so
        moving means re-creating it: hide → setScreen → show."""
        home = _screen_named(QGuiApplication.instance(), self._home)
        if self._quitting or not self._window.isVisible() or home is None or self._window.screen() is home:
            return
        log.info("moving the visualizer back to %s", home.name())
        self._moving = True
        try:
            self._window.hide()
            self._window.setScreen(home)
            self._window.show()
        finally:
            self._moving = False

    def _on_visible_changed(self, visible: bool) -> None:
        if self._quitting or self._moving:
            return
        self._on_hidden(not visible)
        if visible:
            self._attempt = 0
            self._reshow_timer.stop()
        else:
            log.info("visualizer surface was closed (output removed or suspended); waiting for a screen")
            self._schedule_reshow(reset=True)

    def _schedule_reshow(self, reset: bool = False) -> None:
        if self._quitting or self._window.isVisible():
            return
        if reset:
            self._attempt = 0
        delay = RESHOW_BACKOFF_MS[min(self._attempt, len(RESHOW_BACKOFF_MS) - 1)]
        self._reshow_timer.start(delay)

    def _try_reshow(self) -> None:
        if self._quitting or self._window.isVisible():
            return
        app = QGuiApplication.instance()
        self._attempt += 1
        if not _has_real_screen(app):
            log.debug("no output yet (attempt %d)", self._attempt)
            self._schedule_reshow()  # still no outputs: keep polling with backoff
            return
        screen = self._target_screen()
        if screen is not None and self._window.screen() is not screen:
            self._window.setScreen(screen)
        log.info("re-showing the visualizer on %s", screen.name() if screen else "?")
        self._window.show()
        # The compositor may close it again (e.g. that output is going away
        # too); visibleChanged would then schedule the next attempt.
        if not self._window.isVisible():
            self._schedule_reshow()

    # ── suspend detection ─────────────────────────────────────────────────
    def _check_sleep(self) -> None:
        offset = _sleep_offset()
        slept = offset - self._last_offset
        self._last_offset = offset
        if slept >= SLEEP_GAP_S:
            log.info("woke up after %.0fs of suspend; restarting audio capture shortly", slept)
            self._resume_timer.start()
            self._schedule_reshow(reset=True)

    def _resumed(self) -> None:
        self._on_resume()
