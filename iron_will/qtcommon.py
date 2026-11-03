"""Qt-side glue shared by the visualizer and the settings GUI.

``ConfigStore`` wraps the plain-dict config in a QObject that

* emits ``changed(set_of_keys)`` with exactly which settings changed,
* can watch the file and hot-reload (visualizer) — debounced, and ignoring the
  echo of its own writes,
* can autosave edits (settings GUI) — debounced, atomic writes,
* tracks the Plasma accent color and resolves the effective color list.
"""

from __future__ import annotations

import logging
import os
import signal
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QCoreApplication, QFileSystemWatcher, QObject, QSocketNotifier, QTimer, Signal

from . import accent, config, paths

log = logging.getLogger("iron_will.store")

ACCENT_KEY = "accent"  # pseudo-key emitted when the Plasma accent changes


def _single_shot(parent: QObject, ms: int, slot) -> QTimer:
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(ms)
    timer.timeout.connect(slot)
    return timer


class ConfigStore(QObject):
    changed = Signal(object)  # set[str] of dotted keys (or ACCENT_KEY)
    saved = Signal()

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path or paths.CONFIG_PATH)
        self._values = config.load(self._path, fallback=True)
        self._accent = accent.read_accent()
        self._last_written: str | None = None
        self._autosave = False
        # Throttle (not debounce): during a slider drag we save at most every
        # 150 ms, so the desktop visualizer follows along live.
        self._save_timer = _single_shot(self, 150, self.save_now)
        self._reload_timer = _single_shot(self, 150, self._reload)
        self._accent_timer = _single_shot(self, 300, self._reload_accent)
        self._watcher: QFileSystemWatcher | None = None
        self._accent_watcher: QFileSystemWatcher | None = None

    # ── reading ───────────────────────────────────────────────────────────
    @property
    def path(self) -> Path:
        return self._path

    def get(self, key: str) -> Any:
        value = self._values[key]
        return list(value) if isinstance(value, list) else value

    def values(self) -> dict[str, Any]:
        return dict(self._values)

    def accent(self) -> str | None:
        return self._accent

    def resolved_colors(self) -> list[str]:
        """The colors the visualizer should actually paint with."""
        if self._values["visualizer.color_source"] == "accent" and self._accent:
            return accent.accent_palette(self._accent)
        return list(self._values["visualizer.colors"])

    # ── writing ───────────────────────────────────────────────────────────
    def set(self, key: str, value: Any) -> bool:
        field = config.FIELD_MAP.get(key)
        if field is None:
            log.warning("unknown setting %s", key)
            return False
        try:
            new = field.coerce(value)
        except (ValueError, TypeError) as exc:
            log.warning("rejected %s=%r: %s", key, value, exc)
            return False
        if new == self._values[key]:
            return False
        self._values[key] = new
        self.changed.emit({key})
        self._schedule_save()
        return True

    def update(self, changes: dict[str, Any]) -> set[str]:
        """Apply several settings at once with a single ``changed`` signal —
        e.g. a genre preset touching 8 keys restarts cava once, not 8 times."""
        changed: set[str] = set()
        for key, value in changes.items():
            field = config.FIELD_MAP.get(key)
            if field is None:
                continue
            try:
                new = field.coerce(value)
            except (ValueError, TypeError):
                continue
            if new != self._values[key]:
                self._values[key] = new
                changed.add(key)
        if changed:
            self.changed.emit(changed)
            self._schedule_save()
        return changed

    def reset(self, keys: Iterable[str]) -> None:
        defaults = config.defaults()
        changed = {k for k in keys if self._values.get(k) != defaults[k]}
        for key in changed:
            self._values[key] = defaults[key]
        if changed:
            self.changed.emit(changed)
            self._schedule_save()

    def _schedule_save(self) -> None:
        if self._autosave and not self._save_timer.isActive():
            self._save_timer.start()

    def enable_autosave(self, enabled: bool = True) -> None:
        self._autosave = enabled

    def save_pending(self) -> bool:
        return self._save_timer.isActive()

    def save_now(self) -> None:
        self._save_timer.stop()
        try:
            self._last_written = config.save(self._values, self._path)
        except OSError as exc:
            log.error("could not save %s: %s", self._path, exc)
            return
        self.saved.emit()

    # ── hot reload ────────────────────────────────────────────────────────
    def watch_file(self) -> None:
        """Watch the config file *and* its directory: editors and our own
        atomic save replace the file (new inode), which silently drops a
        plain file watch."""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.addPath(str(self._path.parent))
        if self._path.exists():
            self._watcher.addPath(str(self._path))
        self._watcher.fileChanged.connect(lambda _p: self._reload_timer.start())
        self._watcher.directoryChanged.connect(lambda _p: self._reload_timer.start())

    def _reload(self) -> None:
        if self._watcher and self._path.exists() and str(self._path) not in self._watcher.files():
            self._watcher.addPath(str(self._path))
        if self._save_timer.isActive():
            return  # we're about to overwrite the file anyway
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return
        if text == self._last_written:
            return  # echo of our own save
        try:
            new = config.loads(text)
        except config.ConfigError as exc:
            log.warning("config has a syntax error, keeping current settings: %s", exc)
            return
        diff = {k for k, v in new.items() if self._values.get(k) != v}
        self._last_written = text
        self._values = new
        if diff:
            log.info("config reloaded (%d change%s)", len(diff), "" if len(diff) == 1 else "s")
            self.changed.emit(diff)

    def watch_accent(self) -> None:
        self._accent_watcher = QFileSystemWatcher(self)
        if paths.KDEGLOBALS.exists():
            self._accent_watcher.addPath(str(paths.KDEGLOBALS))
        self._accent_watcher.fileChanged.connect(lambda _p: self._accent_timer.start())

    def _reload_accent(self) -> None:
        # KDE rewrites kdeglobals atomically, so the watch must be re-armed.
        if self._accent_watcher and paths.KDEGLOBALS.exists() \
                and str(paths.KDEGLOBALS) not in self._accent_watcher.files():
            self._accent_watcher.addPath(str(paths.KDEGLOBALS))
        new = accent.read_accent()
        if new != self._accent:
            self._accent = new
            log.info("Plasma accent changed to %s", new)
            self.changed.emit({ACCENT_KEY})


def install_signal_handlers(app: QCoreApplication) -> None:
    """Make SIGINT/SIGTERM quit the Qt event loop cleanly.

    Python only runs signal handlers between bytecodes, and Qt's C++ event loop
    can sleep for a long time — so we use the self-pipe trick: the C-level
    handler writes a byte to a pipe that a QSocketNotifier watches, waking Qt.
    """
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    signal.set_wakeup_fd(write_fd)
    notifier = QSocketNotifier(read_fd, QSocketNotifier.Type.Read, app)
    notifier.activated.connect(lambda *_: os.read(read_fd, 64))
    app._iron_will_signal_notifier = notifier  # keep alive
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.quit())
