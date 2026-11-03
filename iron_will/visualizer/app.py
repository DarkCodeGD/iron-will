"""Desktop visualizer entry point: config store → cava → VisualizerItem.

Data flow::

    config.toml ──watch──▶ ConfigStore ──changed──▶ LayoutModel ──▶ window geometry
                                   │                  VisualizerItem (look, physics)
                                   └─ cava keys? ──▶ CavaProcess.restart
    PipeWire ──▶ cava (stdout pipe) ──frame──▶ VisualizerItem.feed ──▶ paint
    suspend / output loss ──▶ WindowGuardian ──▶ re-show window, restart cava
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
from .cava import CavaProcess
from .guardian import WindowGuardian
from .layout import LayoutModel
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

    item = root.findChild(VisualizerItem, "visualizer")
    cava = CavaProcess(app)
    cava.frame.connect(item.feed)

    def restart_cava() -> None:
        v = store.values()
        analysis = {f.key: v[f.path] for f in config.FIELDS if f.section == "analysis"}
        cava.start(config.cava_bar_count(v), v["visualizer.fps"], analysis)

    store.changed.connect(lambda keys: restart_cava() if keys & config.CAVA_KEYS else None)
    restart_cava()

    # Survive suspend / lid close / monitor unplug instead of quitting with the
    # last window. Hiding the item stops its render timer while off-screen.
    guardian = WindowGuardian(root, on_hidden=lambda hidden: item.setVisible(not hidden),
                              on_resume=restart_cava, parent=app)
    guardian.setObjectName("guardian")
    app.aboutToQuit.connect(cava.stop)
    return app.exec()
