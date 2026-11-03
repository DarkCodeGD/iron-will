"""Is the screen locked? (``org.freedesktop.ScreenSaver`` via QtDBus.)

The visualizer has no business running behind the lock screen: on a laptop,
"resume" means "the lock screen appeared", and the user is only really back
once they've typed their password. ``LockWatcher.locked`` tracks that, with
``changed(bool)`` firing on real transitions only. KWin emits ActiveChanged
on two object paths, so repeats of the same value are collapsed.

No screensaver service (other desktops, a bare X session)? Then we report
"unlocked" forever and the visualizer behaves exactly as before.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import SLOT, QObject, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher

log = logging.getLogger("iron_will.visualizer")

SERVICE = "org.freedesktop.ScreenSaver"
PATH = "/org/freedesktop/ScreenSaver"


class LockWatcher(QObject):
    changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._locked = False
        self._bus = QDBusConnection.sessionBus()
        self._pending: QDBusPendingCallWatcher | None = None
        if not self._bus.isConnected():
            log.debug("no session bus — assuming the screen is never locked")
            return
        # Empty path = any object path; sender is resolved to the bus owner of
        # the well-known name, so only the real screensaver can lock us.
        # PySide needs the old-style SLOT() signature string here; a bound
        # method or plain "onActive(bool)" silently fails to connect.
        if not self._bus.connect(SERVICE, "", SERVICE, "ActiveChanged", self, SLOT("_on_active(bool)")):
            log.warning("cannot watch the screen lock (%s)", self._bus.lastError().message())
        self.refresh()

    @property
    def locked(self) -> bool:
        return self._locked

    def refresh(self) -> None:
        """Re-read the lock state (signals can be missed around a suspend)."""
        call = self._bus.asyncCall(QDBusMessage.createMethodCall(SERVICE, PATH, SERVICE, "GetActive"))
        self._pending = QDBusPendingCallWatcher(call, self)
        self._pending.finished.connect(self._on_reply)

    def _on_reply(self, watcher: QDBusPendingCallWatcher) -> None:
        reply = watcher.reply()
        watcher.deleteLater()
        if watcher is self._pending:
            self._pending = None
        if reply.type() == QDBusMessage.MessageType.ReplyMessage and reply.arguments():
            self._set(bool(reply.arguments()[0]))
        else:
            log.debug("ScreenSaver.GetActive unavailable: %s", reply.errorMessage())

    @Slot(bool)
    def _on_active(self, active: bool) -> None:
        self._set(active)

    def _set(self, locked: bool) -> None:
        if locked != self._locked:
            self._locked = locked
            log.info("screen %s", "locked — visualizer paused" if locked else "unlocked")
            self.changed.emit(locked)
