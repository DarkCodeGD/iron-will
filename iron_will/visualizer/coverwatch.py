"""Is the visualizer hidden behind other windows? (KWin script + QtDBus.)

A fullscreen game, a fullscreen video or a maximized browser hides the
visualizer completely, so drawing it (and running cava for it) back there is
pure waste: up to a third of a CPU core in the painted modes.
``CoverWatcher.covered`` tracks that, with ``changed(bool)`` firing on real
transitions only, the same contract as ``LockWatcher`` so the guardian treats
both alike.

How we know: a Wayland client can't see other windows, but KWin can. We load
``kwin/coverwatch.js`` into KWin over D-Bus (a runtime copy stamped with our
PID, so it can find our surface). It watches every window and calls our
``SetCovered`` method whenever the answer flips: are the windows stacked above
us hiding our whole rectangle? That one geometric rule covers fullscreen,
maximized, tiled side by side, or a big window parked on top, and it respects
the layer setting (with layer = top nothing can cover us). Show Desktop (which
sweeps every window aside) comes straight from KWin's own D-Bus signal, since
scripts can't see it.

The script is unloaded when the visualizer quits (and replaced on the next
start if a crash left it behind). If KWin restarts, the script is loaded again.
No KWin at all (another desktop)? Then we report "not covered" forever and the
visualizer behaves exactly as before.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import SLOT, ClassInfo, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage, QDBusPendingCallWatcher, QDBusServiceWatcher

from .. import paths

log = logging.getLogger("iron_will.visualizer")

SERVICE = "org.ironwill.Visualizer"     # must match kwin/coverwatch.js
OBJECT_PATH = "/Visualizer"
KWIN = "org.kde.KWin"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"
KWIN_PATH, KWIN_IFACE = "/KWin", "org.kde.KWin"
PLUGIN_NAME = "iron-will-coverwatch"
SCRIPT_TEMPLATE = Path(__file__).resolve().parent / "kwin" / "coverwatch.js"

# Pausing late costs nothing, but restarting cava for a window that's only
# being dragged across the bars does. Coming back should feel instant.
PAUSE_DELAY_MS = 500
RESUME_DELAY_MS = 150
UNLOAD_TIMEOUT_MS = 300    # at quit/shutdown: never hold up the exit for KWin
# KWin deletes an unloaded script on its next event-loop pass; a same-named
# script loaded before that never runs. Give it a beat after removing one.
RELOAD_AFTER_UNLOAD_MS = 300
# The script reports once as soon as it runs. No word by then = it didn't run.
CHECK_IN_MS = 2000
MAX_LOAD_ATTEMPTS = 3


@ClassInfo({"D-Bus Interface": SERVICE})
class _Receiver(QObject):
    """The D-Bus object the KWin script calls. Only forwards the report."""

    reported = Signal(bool)

    @Slot(bool)
    def SetCovered(self, covered: bool) -> None:   # noqa: N802 (D-Bus method name)
        self.reported.emit(covered)


class CoverWatcher(QObject):
    changed = Signal(bool)

    def __init__(self, enabled: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._available = False                # our D-Bus endpoint is up
        self._enabled = False
        self._covered = False                  # the debounced answer we've announced
        self._script_covered = False           # the latest word from KWin
        self._showing_desktop = False
        self._attempts = 0                     # loads since the script last checked in
        self._pending: set[QDBusPendingCallWatcher] = set()
        self._bus = QDBusConnection.sessionBus()
        self._debounce = QTimer(self, singleShot=True)
        self._debounce.timeout.connect(self._settle)
        self._reload = QTimer(self, singleShot=True, interval=RELOAD_AFTER_UNLOAD_MS)
        self._reload.timeout.connect(self._load_fresh)
        self._check_in = QTimer(self, singleShot=True, interval=CHECK_IN_MS)
        self._check_in.timeout.connect(self._on_silent_script)
        if not self._bus.isConnected():
            log.debug("no session bus — covering windows can't be detected")
            return

        self._receiver = _Receiver(self)
        self._receiver.reported.connect(self._on_report)
        if not (self._bus.registerObject(OBJECT_PATH, self._receiver, QDBusConnection.RegisterOption.ExportAllSlots)
                and self._bus.registerService(SERVICE)):
            log.warning("cannot register %s on the session bus (%s); pause-when-covered disabled",
                        SERVICE, self._bus.lastError().message())
            return
        self._available = True
        # KWin restarted (X11 `kwin --replace`, or a crash): our script went with it.
        self._kwin_watch = QDBusServiceWatcher(KWIN, self._bus, QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange, self)
        self._kwin_watch.serviceOwnerChanged.connect(self._on_kwin_changed)
        # Old-style SLOT() signature, as in LockWatcher: PySide's bound-method form silently fails here.
        if not self._bus.connect(KWIN, KWIN_PATH, KWIN_IFACE, "showingDesktopChanged", self,
                                 SLOT("_on_showing_desktop(bool)")):
            log.debug("cannot follow Show Desktop (%s)", self._bus.lastError().message())
        self.set_enabled(enabled)

    @property
    def covered(self) -> bool:
        return self._covered

    def set_enabled(self, enabled: bool) -> None:
        """Turn detection on (load the KWin script) or off (unload it, report uncovered)."""
        if enabled == self._enabled or not self._available:
            return
        self._enabled = enabled
        if enabled:
            self._attempts = 0
            self._load_script()
        else:
            self._reload.stop()
            self._check_in.stop()
            self._unload_script()
            self._script_covered = False
            self._evaluate()

    def shutdown(self) -> None:
        """Take our script out of KWin (aboutToQuit). Bounded, so a busy or
        dying compositor at logout can't stall the exit."""
        if self._enabled:
            self._enabled = False
            self._reload.stop()
            self._check_in.stop()
            self._unload_script()

    # ── the KWin side ─────────────────────────────────────────────────────
    def _call(self, method: str, *args, timeout: int = 2000) -> QDBusMessage:
        msg = QDBusMessage.createMethodCall(KWIN, SCRIPTING_PATH, SCRIPTING_IFACE, method)
        msg.setArguments(list(args))
        return self._bus.call(msg, QDBus.CallMode.Block, timeout)

    @staticmethod
    def _write_script() -> Path | None:
        """The template, stamped with our PID so the script can find our surface."""
        try:
            body = SCRIPT_TEMPLATE.read_text(encoding="utf-8")
            script = paths.runtime_dir() / "kwin-coverwatch.js"
            script.write_text(f"const VISUALIZER_PID = {os.getpid()};\n{body}", encoding="utf-8")
            return script
        except OSError as exc:
            log.warning("cannot prepare the KWin script (%s); pause-when-covered disabled", exc)
            return None

    def _load_script(self) -> None:
        """Start from a clean slate: a visualizer that crashed (or a quick
        off/on toggle) can leave a copy behind, and KWin won't run two
        scripts under one plugin name."""
        self._fetch_showing_desktop()
        stale = self._call("unloadScript", PLUGIN_NAME)
        if stale.type() == QDBusMessage.MessageType.ReplyMessage and stale.arguments() == [True]:
            log.debug("removed a leftover cover-watch script from KWin")
            self._reload.start()
        else:
            self._load_fresh()

    def _load_fresh(self) -> None:
        if not self._enabled:
            return                         # switched off while we waited
        script = self._write_script()
        if script is None:
            return
        self._attempts += 1
        reply = self._call("loadScript", str(script), PLUGIN_NAME)
        script_id = reply.arguments()[0] if reply.type() == QDBusMessage.MessageType.ReplyMessage else -1
        if not isinstance(script_id, int) or script_id < 0:
            log.info("KWin scripting unavailable (%s); pause-when-covered disabled",
                     reply.errorMessage() or f"loadScript returned {script_id}")
            return
        # Not Script<id>.run: KWin numbers scripts by list size, so after any
        # other script was unloaded our id can belong to someone else's. start()
        # runs every loaded script that isn't running yet, i.e. ours.
        start = QDBusMessage.createMethodCall(KWIN, SCRIPTING_PATH, SCRIPTING_IFACE, "start")
        watcher = QDBusPendingCallWatcher(self._bus.asyncCall(start), self)
        self._pending.add(watcher)
        watcher.finished.connect(self._on_start_reply)
        self._check_in.start()
        log.info("watching for windows that cover the visualizer (KWin script)")

    def _on_silent_script(self) -> None:
        if not self._enabled:
            return
        if self._attempts >= MAX_LOAD_ATTEMPTS:
            log.warning("the KWin cover-watch script never checked in; pause-when-covered disabled")
            return
        log.info("the KWin cover-watch script didn't check in; loading it again")
        self._load_script()

    def _on_start_reply(self, watcher: QDBusPendingCallWatcher) -> None:
        self._pending.discard(watcher)
        reply = watcher.reply()
        watcher.deleteLater()
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            log.warning("KWin would not start the cover-watch script: %s", reply.errorMessage())

    def _unload_script(self) -> None:
        self._call("unloadScript", PLUGIN_NAME, timeout=UNLOAD_TIMEOUT_MS)

    def _on_kwin_changed(self, _name: str, _old: str, new: str) -> None:
        self._script_covered = False       # whatever the old KWin said no longer holds
        self._showing_desktop = False
        self._evaluate()
        if new and self._enabled:
            log.info("KWin restarted; reloading the cover-watch script")
            self._attempts = 0
            self._load_script()

    def _fetch_showing_desktop(self) -> None:
        msg = QDBusMessage.createMethodCall(KWIN, KWIN_PATH, "org.freedesktop.DBus.Properties", "Get")
        msg.setArguments([KWIN_IFACE, "showingDesktop"])
        watcher = QDBusPendingCallWatcher(self._bus.asyncCall(msg), self)
        self._pending.add(watcher)
        watcher.finished.connect(self._on_showing_desktop_reply)

    def _on_showing_desktop_reply(self, watcher: QDBusPendingCallWatcher) -> None:
        self._pending.discard(watcher)
        reply = watcher.reply()
        watcher.deleteLater()
        if reply.type() == QDBusMessage.MessageType.ReplyMessage and reply.arguments():
            value = reply.arguments()[0]
            self._on_showing_desktop(bool(getattr(value, "variant", lambda: value)()))

    @Slot(bool)
    def _on_showing_desktop(self, showing: bool) -> None:
        log.debug("KWin: Show Desktop %s", "on" if showing else "off")
        if showing != self._showing_desktop:
            self._showing_desktop = showing
            self._evaluate()

    # ── the answer ────────────────────────────────────────────────────────
    def _on_report(self, covered: bool) -> None:
        log.debug("KWin: visualizer %s", "covered" if covered else "visible")
        if not self._enabled:
            return                         # a late call from a script we just unloaded
        self._check_in.stop()              # it's alive
        self._attempts = 0
        self._script_covered = bool(covered)
        self._evaluate()

    def _target(self) -> bool:
        # Show Desktop sweeps every window aside.
        return self._script_covered and not self._showing_desktop

    def _evaluate(self) -> None:
        # (Re)start the debounce on every change; settle once it's been stable.
        target = self._target()
        if target == self._covered:
            self._debounce.stop()          # flipped back before it counted
        else:
            self._debounce.start(PAUSE_DELAY_MS if target else RESUME_DELAY_MS)

    def _settle(self) -> None:
        covered = self._target()
        if covered != self._covered:
            self._covered = covered
            log.info("%s", "windows cover the visualizer — paused" if covered
                     else "visualizer uncovered — back")
            self.changed.emit(covered)
