""""Now playing" desktop notification with a Stop button (freedesktop D-Bus API).

Talks to ``org.freedesktop.Notifications`` directly through Gio, so there's no
libnotify dependency. All calls are async and every failure is non-fatal: no
notification server simply means no popup, never a broken sound.

Lifecycle::

    show(track) ──Notify──▶ id      user clicks "Stop" ──ActionInvoked──▶ on_stop()
    playback ends ──close()──▶ CloseNotification(id)

Must be used from the GLib main loop thread.
"""

from __future__ import annotations

import logging
from typing import Callable

from gi.repository import Gio, GLib

from .. import paths

log = logging.getLogger("iron_will.notify")

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
STOP_ACTION = "stop"
EVENT_TITLES = {"login": "Login sound", "resume": "Resume sound", "unlock": "Unlock sound"}


class Notifier:
    def __init__(self, bus: Gio.DBusConnection, on_stop: Callable[[], None]) -> None:
        self._bus = bus
        self._on_stop = on_stop
        self._id = 0            # server id of the visible notification (0 = none)
        self._generation = 0    # bumps on every show/close, to drop stale Notify replies
        self._sub = bus.signal_subscribe(BUS_NAME, BUS_NAME, "ActionInvoked", OBJECT_PATH, None,
                                         Gio.DBusSignalFlags.NONE, self._on_action)

    def show(self, track_name: str, event: str) -> None:
        self._generation += 1
        generation = self._generation
        hints = {
            "desktop-entry": GLib.Variant("s", "iron-will-settings"),
            "suppress-sound": GLib.Variant("b", True),   # don't ding over our own track
            "transient": GLib.Variant("b", True),        # keep it out of the history
        }
        params = GLib.Variant("(susssasa{sv}i)", (
            "Iron Will", self._id, str(paths.ASSETS_DIR / "iron-will.svg"),
            EVENT_TITLES.get(event, "Session sound"), GLib.markup_escape_text(track_name),
            [STOP_ACTION, "Stop"], hints,
            0,  # never expire on its own — we close it when the track ends
        ))

        def reply(bus, result) -> None:
            try:
                (nid,) = bus.call_finish(result).unpack()
            except GLib.Error as exc:
                log.debug("notification unavailable: %s", exc.message)
                return
            if generation == self._generation:
                self._id = nid
            else:  # playback already ended (or a newer one started) before the server answered
                self._close_id(nid)

        self._bus.call(BUS_NAME, OBJECT_PATH, BUS_NAME, "Notify", params, GLib.VariantType("(u)"),
                       Gio.DBusCallFlags.NONE, 2000, None, reply)

    def close(self) -> None:
        self._generation += 1
        if self._id:
            self._close_id(self._id)
            self._id = 0

    def shutdown(self) -> None:
        self.close()
        self._bus.signal_unsubscribe(self._sub)

    def _close_id(self, nid: int) -> None:
        self._bus.call(BUS_NAME, OBJECT_PATH, BUS_NAME, "CloseNotification", GLib.Variant("(u)", (nid,)),
                       None, Gio.DBusCallFlags.NONE, 2000, None, None)

    def _on_action(self, _conn, _sender, _path, _iface, _signal, params, *_) -> None:
        nid, action = params.unpack()
        if nid == self._id and nid and action == STOP_ACTION:
            log.info("stop requested from the notification")
            self._on_stop()
