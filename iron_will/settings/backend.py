"""QML-facing backend for the settings window.

QML reads settings with ``backend.get(key)`` and writes with
``backend.set(key, value)``. Every change bumps ``revision``; controls listen
to ``revisionChanged`` and re-sync, so a reset, an external edit of the file
or a change from another control all show up immediately — no per-key signal
boilerplate.

Edits auto-save (debounced) and the running desktop visualizer hot-reloads
the file, so tweaking a slider updates your desktop live.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from PySide6.QtCore import (Property, QFileSystemWatcher, QLibraryInfo, QObject, QProcess, QRect, QTimer,
                            QUrl, Signal, Slot)
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QJSValue

from .. import __version__, config, paths, presets
from ..dispatcher.player import (STOPPED, Player, list_tracks, now_playing, pick_track, request_stop,
                                resolve_chain)
from ..visualizer import layout, modes

log = logging.getLogger("iron_will.settings")

SERVICES = (
    ("iron-will-visualizer.service", "Desktop visualizer", "Animated bars on your desktop, anchored above the panel."),
    ("iron-will-audio.service", "Session sound daemon", "Plays a track on login, resume and unlock."),
)


class SettingsBackend(QObject):
    revisionChanged = Signal()
    dirtyChanged = Signal()
    servicesChanged = Signal()
    nowPlayingChanged = Signal()
    toast = Signal(str, str)  # message, kind ("info" | "error")

    def __init__(self, store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._revision = 0
        self._dirty = False
        self._player = Player()
        self._services: list[dict] = []
        self._now_playing = ""
        # Any process (daemon, CLI, this app) creating/removing playback.json
        # shows up here instantly; the debounce lets the flock settle first.
        self._playing_watch = QFileSystemWatcher([str(paths.runtime_dir())], self)
        self._playing_debounce = QTimer(self, singleShot=True, interval=120)
        self._playing_debounce.timeout.connect(self._refresh_now_playing)
        self._playing_watch.directoryChanged.connect(lambda _p: self._playing_debounce.start())
        store.changed.connect(self._on_store_changed)
        store.saved.connect(self._on_saved)
        self._service_timer = QTimer(self)
        self._service_timer.setInterval(3000)
        self._service_timer.timeout.connect(self.refreshServices)
        self._service_timer.timeout.connect(self._refresh_now_playing)  # belt and braces
        self._service_timer.start()
        self.refreshServices()
        self._refresh_now_playing()

    # ── generic settings access ───────────────────────────────────────────
    def _get_revision(self) -> int:
        return self._revision

    revision = Property(int, _get_revision, notify=revisionChanged)

    def _get_dirty(self) -> bool:
        return self._dirty

    dirty = Property(bool, _get_dirty, notify=dirtyChanged)

    def _on_store_changed(self, _keys) -> None:
        self._revision += 1
        self.revisionChanged.emit()
        if self._store.save_pending() != self._dirty:
            self._dirty = self._store.save_pending()
            self.dirtyChanged.emit()

    def _on_saved(self) -> None:
        self._dirty = False
        self.dirtyChanged.emit()

    @Slot(str, result="QVariant")
    def get(self, key: str):
        return self._store.get(key)

    @Slot(str, "QVariant")
    def set(self, key: str, value) -> None:
        # JS arrays/objects arrive as an opaque QJSValue rather than a Python
        # list/dict; unwrap them so schema validation sees real data.
        if isinstance(value, QJSValue):
            value = value.toVariant()
        self._store.set(key, value)

    @Slot(bool)
    def setFullHeight(self, on: bool) -> None:
        """Toggle the full-screen-height window without changing how big the
        fire looks: flame height is a share of the window, so rescale it by
        old/new window height (the flames just gain headroom)."""
        v = self._store.values()
        if v["layout.full_height"] == on:
            return
        screen = QGuiApplication.primaryScreen()
        geo = (screen.availableGeometry() if v["layout.respect_panels"] else screen.geometry()) \
            if screen else QRect(0, 0, 1920, 1080)
        fixed = layout.full_height({**v, "layout.full_height": False}, geo)
        full = layout.full_height({**v, "layout.full_height": True}, geo)
        old, new = (fixed, full) if on else (full, fixed)
        f = config.FIELD_MAP["fire.height"]
        reach = min(f.max, max(f.min, v["fire.height"] * old / new))
        self._store.update({"layout.full_height": on, "fire.height": round(reach, 3)})

    @Slot(str, result="QVariant")
    def field(self, key: str):
        """Schema metadata for a key: min/max/choices/default/help."""
        f = config.FIELD_MAP[key]
        return {"min": f.min, "max": f.max, "choices": list(f.choices or []),
                "default": f.default, "help": f.help}

    @Slot(str)
    def resetSection(self, section: str) -> None:
        self._store.reset([f.path for f in config.FIELDS if f.section == section])
        self.toast.emit(f"Restored defaults for {config.SECTIONS[section].split('·')[-1].strip().lower()}", "info")

    # ── render modes (from the registry: one tile per visualizer) ─────────
    renderModes = Property("QVariantList", lambda s: [
        {"id": m.id, "name": m.name, "tagline": m.tagline,
         "icon": "image://modeicon/" + m.id}   # see settings/icons.py
        for m in modes.MODES], constant=True)

    # ── genre presets ─────────────────────────────────────────────────────
    genrePresets = Property("QVariantList", lambda s: [
        {"id": p.id, "name": p.name, "tagline": p.tagline, "icon": p.icon, "details": p.details}
        for p in presets.PRESETS], constant=True)

    def _get_active_preset(self) -> str:
        preset = presets.match(self._store.values())
        return preset.id if preset else ""

    activePreset = Property(str, _get_active_preset, notify=revisionChanged)

    @Slot(str)
    def applyPreset(self, preset_id: str) -> None:
        preset = presets.BY_ID.get(preset_id)
        if preset is None:
            return
        self._store.update(preset.values)
        self.toast.emit(f"{preset.name} preset applied", "info")

    # ── environment info ──────────────────────────────────────────────────
    def _get_accent(self) -> str:
        return self._store.accent() or ""

    accentColor = Property(str, _get_accent, notify=revisionChanged)

    def _screen_size(self) -> tuple[int, int]:
        screen = QGuiApplication.primaryScreen()
        size = screen.geometry().size() if screen else None
        return (size.width(), size.height()) if size else (1920, 1080)

    screenWidth = Property(int, lambda s: s._screen_size()[0], constant=True)
    screenHeight = Property(int, lambda s: s._screen_size()[1], constant=True)
    version = Property(str, lambda s: __version__, constant=True)
    configPath = Property(str, lambda s: str(s._store.path), constant=True)

    # ── session sounds ────────────────────────────────────────────────────
    @Slot(result="QVariant")
    def soundInfo(self):
        directory = paths.expand(self._store.get("sounds.directory"))
        tracks = list_tracks(directory)
        return {"path": str(directory), "exists": directory.is_dir(), "count": len(tracks),
                "tracks": [str(t.relative_to(directory)) for t in tracks[:60]]}

    @Slot(str)
    def setSoundDirectory(self, url: str) -> None:
        path = QUrl(url).toLocalFile() or url
        home = str(Path.home())
        if path == home or path.startswith(home + "/"):
            path = "~" + path[len(home):]
        self._store.set("sounds.directory", path)

    @Slot()
    def playTest(self) -> None:
        cfg = self._store.values()
        directory = paths.expand(cfg["sounds.directory"])
        tracks = list_tracks(directory)
        if not tracks:
            self.toast.emit("No audio files found in the sound folder", "error")
            return
        if not resolve_chain(cfg["sounds.backend"]):
            self.toast.emit("No audio player found — install pipewire-utils", "error")
            return
        track = pick_track(tracks, cfg["sounds.avoid_repeat"])

        def done(ok: bool, message: str) -> None:  # runs on the player thread;
            if not ok and message != STOPPED:       # Qt queues the signal safely
                self.toast.emit(f"Playback failed: {message}", "error")

        if self._player.play(track, volume=cfg["sounds.volume"], backend=cfg["sounds.backend"], on_done=done):
            self.toast.emit(f"Playing {track.name}", "info")
        else:
            self.toast.emit("A sound is already playing", "info")
        self._refresh_now_playing()

    # ── now playing / stop (works for sounds started by any process) ─────
    def _refresh_now_playing(self) -> None:
        playing = now_playing()
        name = Path(playing["track"]).stem if playing and playing.get("track") else ("…" if playing else "")
        if name != self._now_playing:
            self._now_playing = name
            self.nowPlayingChanged.emit()

    nowPlaying = Property(str, lambda s: s._now_playing, notify=nowPlayingChanged)

    @Slot()
    def stopSound(self) -> None:
        stopped = request_stop()
        if stopped:
            self.toast.emit(f"Stopped {Path(stopped).stem}", "info")
        self._refresh_now_playing()

    @Slot(str)
    def openPath(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.expand(path))))

    # ── background services (systemd --user) ─────────────────────────────
    def _get_services(self):
        return self._services

    services = Property("QVariantList", _get_services, notify=servicesChanged)

    @Slot()
    def refreshServices(self) -> None:
        units = [unit for unit, _, _ in SERVICES]
        states: dict[str, dict[str, str]] = {}
        if shutil.which("systemctl"):
            proc = QProcess()
            proc.start("systemctl", ["--user", "show", "--property=Id,ActiveState,LoadState,UnitFileState", *units])
            if proc.waitForFinished(2000):
                block: dict[str, str] = {}
                for line in bytes(proc.readAllStandardOutput()).decode().splitlines() + [""]:
                    if not line.strip():
                        if "Id" in block:
                            states[block["Id"]] = block
                        block = {}
                    elif "=" in line:
                        key, _, value = line.partition("=")
                        block[key] = value
        result = []
        for unit, label, description in SERVICES:
            s = states.get(unit, {})
            installed = s.get("LoadState") == "loaded"
            result.append({"unit": unit, "label": label, "description": description, "installed": installed,
                           "active": s.get("ActiveState") == "active", "state": s.get("ActiveState", "unknown"),
                           "enabled": s.get("UnitFileState") == "enabled"})
        if result != self._services:
            self._services = result
            self.servicesChanged.emit()

    @Slot(str, bool)
    def setServiceRunning(self, unit: str, running: bool) -> None:
        """enable --now / disable --now: running *and* starting at login."""
        proc = QProcess(self)
        action = "enable" if running else "disable"

        def finished(code: int, _status) -> None:
            if code != 0:
                err = bytes(proc.readAllStandardError()).decode().strip()
                self.toast.emit(f"systemctl {action} failed: {err or code}", "error")
            proc.deleteLater()
            self.refreshServices()

        proc.finished.connect(finished)
        proc.start("systemctl", ["--user", action, "--now", unit])

    @Slot(result="QVariantList")
    def dependencies(self):
        qml_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath))
        try:
            import gi  # noqa: F401
            has_gi = True
        except ImportError:
            has_gi = False
        checks = [
            ("cava", bool(shutil.which("cava")), "Audio analysis for the visualizer", "cava"),
            ("pw-play", bool(shutil.which("pw-play")), "PipeWire player for session sounds", "pipewire-utils"),
            ("wpctl", bool(shutil.which("wpctl")), "Waits for audio devices after resume", "wireplumber"),
            ("LayerShellQt", (qml_dir / "org/kde/layershell/qmldir").exists(),
             "Wayland desktop-layer placement", "layer-shell-qt"),
            ("PyGObject", has_gi, "D-Bus listener for login / resume / unlock", "python3-gobject"),
            ("setpriv", bool(shutil.which("setpriv")), "Guarantees cava exits with the visualizer", "util-linux"),
        ]
        return [{"name": n, "ok": ok, "detail": d, "package": p} for n, ok, d, p in checks]
