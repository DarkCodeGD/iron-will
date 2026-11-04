"""Desktop visualizer entry point: config store → cava → VisualizerItem.

Data flow::

    config.toml ──watch──▶ ConfigStore ──changed──▶ LayoutModel ──▶ window geometry
                                   │                  VisualizerItem (look, physics)
                                   └─ cava keys? ──▶ CavaProcess.restart
    PipeWire ──▶ cava (stdout pipe) ──frame──▶ VisualizerItem.feed ──▶ paint
    suspend / output loss / lock / covering windows ──▶ WindowGuardian ──▶ pause, then re-show + restart cava
    visualizer.gpu / AC power ──▶ GpuSupervisor ──▶ quit + exec self on the other GPU
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .. import config
from ..qtcommon import ConfigStore, install_signal_handlers
from ..util import acquire_lock, setup_logging
from . import gpuselect
from .cava import CavaProcess
from .coverwatch import CoverWatcher
from .guardian import Hooks, WindowGuardian
from .layout import LayoutModel
from .lockwatch import LockWatcher
from .renderer import VisualizerItem, register_qml_types

log = logging.getLogger("iron_will.visualizer")
QML_DIR = Path(__file__).resolve().parent / "qml"
EXIT_ALREADY_RUNNING = 3  # the unit's RestartPreventExitStatus — don't restart-loop on it


def _load(engine: QQmlApplicationEngine, name: str):
    before = len(engine.rootObjects())
    engine.load(QUrl.fromLocalFile(str(QML_DIR / name)))
    roots = engine.rootObjects()
    return roots[-1] if len(roots) > before else None


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    lock = acquire_lock("visualizer")
    if lock is None:
        log.error("the visualizer is already running")
        return EXIT_ALREADY_RUNNING
    config.ensure_exists()
    gpu = gpuselect.choose()   # sets the GPU environment, so it must come before any Qt GUI

    app = QGuiApplication(sys.argv if argv is None else argv)
    app.setApplicationName("iron-will-visualizer")
    app.setDesktopFileName("iron-will-settings")  # shares the app menu entry's identity
    install_signal_handlers(app)
    register_qml_types()

    store = ConfigStore(parent=app)
    store.watch_file()
    store.watch_accent()
    layout = LayoutModel(store, app)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("configStore", store)
    engine.rootContext().setContextProperty("layoutModel", layout)

    wayland = app.platformName().startswith("wayland")
    root = _load(engine, "WaylandWindow.qml") if wayland else None
    mode = "layer-shell"
    if root is None:
        if wayland:
            log.warning("LayerShellQt QML module unavailable — falling back to a normal window "
                        "(position settings will be ignored). Install layer-shell-qt.")
        root = _load(engine, "X11Window.qml")
        mode = app.platformName()
    if root is None:
        log.error("could not create the visualizer window")
        return 1
    log.info("visualizer window up (%s)", mode)
    supervisor = gpuselect.GpuSupervisor(gpu, root, store, parent=app)

    item = root.findChild(VisualizerItem, "visualizer")
    cava = CavaProcess(app)
    cava.frame.connect(item.feed)

    def restart_cava() -> None:
        v = store.values()
        analysis = {f.key: v[f.path] for f in config.FIELDS if f.section == "analysis"}
        cava.start(config.cava_bar_count(v), v["visualizer.fps"], analysis)

    restart_cava()

    def resume_drawing() -> None:
        item.reset()               # no stale pre-sleep frame: start at zero, fade in
        item.setVisible(True)

    # Survive suspend / lid close / monitor unplug instead of quitting with the
    # last window, and stay paused behind the lock screen and behind windows
    # that cover it (fullscreen, maximized...). Hiding the item stops its
    # render timer, so a paused visualizer costs nothing.
    cover = CoverWatcher(enabled=store.values()["motion.pause_when_covered"], parent=app)
    guardian = WindowGuardian(
        root,
        Hooks(pause=lambda: item.setVisible(False), resume=resume_drawing,
              stop_audio=cava.stop, start_audio=restart_cava),
        lock=LockWatcher(app), cover=cover, parent=app)

    def on_settings_changed(keys: set) -> None:
        if keys & config.CAVA_KEYS:
            guardian.request_audio_restart()
        if "motion.pause_when_covered" in keys:
            cover.set_enabled(store.values()["motion.pause_when_covered"])

    store.changed.connect(on_settings_changed)
    guardian.setObjectName("guardian")
    app.aboutToQuit.connect(cava.stop)
    app.aboutToQuit.connect(cover.shutdown)
    code = app.exec()
    supervisor.relaunch_if_requested(lock)   # GPU choice changed: exec ourselves (no return)
    return code
