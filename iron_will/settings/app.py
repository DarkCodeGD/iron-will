"""Settings GUI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .. import config, paths
from ..qtcommon import ConfigStore, install_signal_handlers
from ..util import setup_logging
from ..visualizer.renderer import register_qml_types
from .backend import SettingsBackend
from .icons import ModeIconProvider

log = logging.getLogger("iron_will.settings")
QML_DIR = Path(__file__).resolve().parent / "qml"


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    config.ensure_exists()
    # "Basic" is the fully-customisable Controls style; our components restyle it.
    QQuickStyle.setStyle("Basic")
    # QApplication (not QGuiApplication) so KDE can provide native file/color dialogs.
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("Iron Will")
    app.setOrganizationName("iron-will")
    app.setDesktopFileName("iron-will-settings")
    app.setWindowIcon(QIcon(str(paths.ASSETS_DIR / "iron-will.svg")))
    install_signal_handlers(app)
    register_qml_types()

    store = ConfigStore(parent=app)
    store.watch_file()
    store.watch_accent()
    store.enable_autosave()
    backend = SettingsBackend(store, app)

    engine = QQmlApplicationEngine()
    engine.addImageProvider("modeicon", ModeIconProvider())
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("configStore", store)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        log.error("failed to load the settings UI")
        return 1
    code = app.exec()
    if store.save_pending():
        store.save_now()
    return code
