"""MPRIS bridge: the session sound in Plasma's media controls, and making way for music.

Two small jobs on the session bus (GLib main-loop thread only):

* ``MediaPlayer``: while a session sound plays, Iron Will owns
  ``org.mpris.MediaPlayer2.ironwill``. Plasma's media widget, the lock screen
  and the keyboard media keys list it like any other player, so the place you
  naturally reach for while Elisa is open can stop it too. Stop, Pause and
  PlayPause all *stop* it (a short jingle has nothing to resume to). The name
  is released the moment the sound ends, so no dead "Iron Will" entry lingers.

* ``MediaWatcher``: follows every *other* player's PlaybackStatus, so the
  dispatcher can skip a sound while music is already playing and stop one the
  moment you start some (Elisa, a browser video, Spotify...).

Spec: https://specifications.freedesktop.org/mpris-spec/latest/
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from gi.repository import Gio, GLib

from .. import paths

log = logging.getLogger("iron_will.mpris")

NAME = "org.mpris.MediaPlayer2.ironwill"
MPRIS_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
EVENT_ALBUMS = {"login": "Login sound", "resume": "Resume sound", "unlock": "Unlock sound"}

# Players that aren't really "music playing on this machine": KDE Connect
# mirrors your *phone's* players onto the desktop bus.
IGNORED_PREFIXES = (MPRIS_PREFIX + "kdeconnect",)

INTROSPECTION = f"""
<node>
  <interface name="{ROOT_IFACE}">
    <method name="Raise"/>
    <method name="Quit"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
    <property name="HasTrackList" type="b" access="read"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="SupportedUriSchemes" type="as" access="read"/>
    <property name="SupportedMimeTypes" type="as" access="read"/>
  </interface>
  <interface name="{PLAYER_IFACE}">
    <method name="Next"/>
    <method name="Previous"/>
    <method name="Pause"/>
    <method name="PlayPause"/>
    <method name="Stop"/>
    <method name="Play"/>
    <method name="Seek"><arg direction="in" name="Offset" type="x"/></method>
    <method name="SetPosition">
      <arg direction="in" name="TrackId" type="o"/><arg direction="in" name="Position" type="x"/>
    </method>
    <method name="OpenUri"><arg direction="in" name="Uri" type="s"/></method>
    <signal name="Seeked"><arg name="Position" type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="Rate" type="d" access="read"/>
    <property name="Metadata" type="a{{sv}}" access="read"/>
    <property name="Volume" type="d" access="read"/>
    <property name="Position" type="x" access="read"/>
    <property name="MinimumRate" type="d" access="read"/>
    <property name="MaximumRate" type="d" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""

STOP_METHODS = frozenset({"Stop", "Pause", "PlayPause"})


class MediaPlayer:
    """The session sound as an MPRIS player, visible only while it plays."""

    def __init__(self, bus: Gio.DBusConnection, on_stop: Callable[[], None]) -> None:
        self._bus = bus
        self._on_stop = on_stop
        self._owner_id = 0          # bus_own_name id while visible, else 0
        self._serial = 0            # makes every sound a fresh mpris:trackid
        self._title = self._album = ""
        self._volume = 1.0
        self._started = 0.0
        # The object is always exported; Plasma only finds it through the bus
        # name, which we hold just while a sound plays.
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        # GLib 2.84 renamed the closure-based call; keep older systems working.
        register = getattr(bus, "register_object_with_closures2", None) or bus.register_object
        self._registrations = [register(OBJECT_PATH, iface, self._on_call, self._on_get, None)
                               for iface in node.interfaces]

    @property
    def active(self) -> bool:
        return bool(self._owner_id)

    def show(self, title: str, event: str, volume: float) -> None:
        self._serial += 1
        self._title, self._album = title, EVENT_ALBUMS.get(event, "Session sound")
        self._volume, self._started = volume, time.monotonic()
        if self._owner_id:          # still visible from the last sound: just swap the track
            self._emit_changed({"Metadata": self._metadata(), "PlaybackStatus": GLib.Variant("s", "Playing")})
            return
        # Plasma reads everything with GetAll once the name appears.
        self._owner_id = Gio.bus_own_name_on_connection(self._bus, NAME, Gio.BusNameOwnerFlags.NONE, None, None)

    def hide(self) -> None:
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
            self._owner_id = 0

    def shutdown(self) -> None:
        self.hide()
        for reg in self._registrations:
            self._bus.unregister_object(reg)
        self._registrations.clear()

    # ── D-Bus plumbing ────────────────────────────────────────────────────
    def _metadata(self) -> GLib.Variant:
        return GLib.Variant("a{sv}", {
            "mpris:trackid": GLib.Variant("o", f"/org/mpris/MediaPlayer2/ironwill/sound{self._serial}"),
            "xesam:title": GLib.Variant("s", self._title),
            "xesam:artist": GLib.Variant("as", ["Iron Will"]),
            "xesam:album": GLib.Variant("s", self._album),
            "mpris:artUrl": GLib.Variant("s", (paths.ASSETS_DIR / "iron-will.svg").as_uri()),
        })

    def _on_get(self, _conn, _sender, _path, iface, prop):
        if iface == ROOT_IFACE:
            return {
                "CanQuit": GLib.Variant("b", False), "CanRaise": GLib.Variant("b", False),
                "HasTrackList": GLib.Variant("b", False), "Identity": GLib.Variant("s", "Iron Will"),
                "DesktopEntry": GLib.Variant("s", "iron-will-settings"),
                "SupportedUriSchemes": GLib.Variant("as", []), "SupportedMimeTypes": GLib.Variant("as", []),
            }.get(prop)
        elapsed_us = int((time.monotonic() - self._started) * 1e6) if self._owner_id else 0
        return {
            "PlaybackStatus": GLib.Variant("s", "Playing" if self._owner_id else "Stopped"),
            "Rate": GLib.Variant("d", 1.0), "MinimumRate": GLib.Variant("d", 1.0),
            "MaximumRate": GLib.Variant("d", 1.0), "Metadata": self._metadata(),
            "Volume": GLib.Variant("d", self._volume), "Position": GLib.Variant("x", elapsed_us),
            "CanGoNext": GLib.Variant("b", False), "CanGoPrevious": GLib.Variant("b", False),
            "CanPlay": GLib.Variant("b", False), "CanPause": GLib.Variant("b", True),
            "CanSeek": GLib.Variant("b", False), "CanControl": GLib.Variant("b", True),
        }.get(prop)

    def _on_call(self, _conn, sender, _path, _iface, method, _params, invocation) -> None:
        invocation.return_value(None)   # every method is fire-and-forget
        if method in STOP_METHODS and self._owner_id:
            log.info("stop requested from the media controls (%s)", method)
            self._on_stop()

    def _emit_changed(self, changed: dict) -> None:
        self._bus.emit_signal(None, OBJECT_PATH, PROPS_IFACE, "PropertiesChanged",
                              GLib.Variant("(sa{sv}as)", (PLAYER_IFACE, changed, [])))


class MediaWatcher:
    """Knows whether any *other* MPRIS player is playing, and says when one starts."""

    def __init__(self, bus: Gio.DBusConnection, on_started: Callable[[str], None]) -> None:
        self._bus = bus
        self._on_started = on_started
        self._me = bus.get_unique_name()
        self._status: dict[str, str] = {}   # unique bus name → PlaybackStatus
        self._names: dict[str, str] = {}    # unique bus name → well-known name (for the log)
        self._subs = [
            bus.signal_subscribe(None, PROPS_IFACE, "PropertiesChanged", OBJECT_PATH, PLAYER_IFACE,
                                 Gio.DBusSignalFlags.NONE, self._on_props),
            bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                 "/org/freedesktop/DBus", "org.mpris.MediaPlayer2",
                                 Gio.DBusSignalFlags.MATCH_ARG0_NAMESPACE, self._on_owner_changed),
        ]
        bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                 None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 2000, None, self._on_names)

    def others_playing(self) -> list[str]:
        """Well-known names of the other players that are playing right now."""
        return [self._names.get(u, u) for u, s in self._status.items() if s == "Playing"]

    def shutdown(self) -> None:
        for sub in self._subs:
            self._bus.signal_unsubscribe(sub)
        self._subs.clear()

    @staticmethod
    def _relevant(name: str) -> bool:
        return name.startswith(MPRIS_PREFIX) and name != NAME and not name.startswith(IGNORED_PREFIXES)

    # ── discovery ─────────────────────────────────────────────────────────
    def _on_names(self, bus, result) -> None:
        try:
            (names,) = bus.call_finish(result).unpack()
        except GLib.Error as exc:
            log.debug("ListNames failed: %s", exc.message)
            return
        for name in filter(self._relevant, names):
            bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                     GLib.Variant("(s)", (name,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 2000, None,
                     self._on_owner, name)

    def _on_owner(self, bus, result, name: str) -> None:
        try:
            (unique,) = bus.call_finish(result).unpack()
        except GLib.Error:
            return   # it quit in the meantime
        self._track(unique, name)

    def _track(self, unique: str, name: str) -> None:
        if unique == self._me:
            return
        self._names[unique] = name

        def reply(bus, result) -> None:
            try:
                (status,) = bus.call_finish(result).unpack()
            except GLib.Error:
                return
            if unique not in self._names or unique in self._status:
                return   # gone already, or a signal beat this reply with a fresher status
            self._status[unique] = status
            if status == "Playing":   # e.g. a player launched straight into a song
                self._on_started(name)
        self._bus.call(unique, OBJECT_PATH, PROPS_IFACE, "Get", GLib.Variant("(ss)", (PLAYER_IFACE, "PlaybackStatus")),
                       GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 2000, None, reply)

    # ── signals ───────────────────────────────────────────────────────────
    def _on_owner_changed(self, _conn, _sender, _path, _iface, _signal, params, *_) -> None:
        name, old, new = params.unpack()
        if not self._relevant(name):
            return
        if old:
            self._status.pop(old, None)
            self._names.pop(old, None)
        if new:
            self._track(new, name)

    def _on_props(self, _conn, sender, _path, _iface, _signal, params, *_) -> None:
        if sender == self._me or sender not in self._names:
            return   # ourselves, or a player we don't follow (e.g. KDE Connect)
        _iface_name, changed, _invalidated = params.unpack()
        status = changed.get("PlaybackStatus")
        if status is None:
            return
        before = self._status.get(sender)
        self._status[sender] = status
        if status == "Playing" and before != "Playing":
            self._on_started(self._names.get(sender, sender))
