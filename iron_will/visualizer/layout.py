"""Turns the ``[layout]`` settings into window geometry for QML.

Wayland (layer-shell): we hand the compositor *anchors + margins* and it does
the placement — exactly like a panel. With ``exclusionZone = 0`` the surface
is pushed clear of panels' exclusive zones, so ``margin_y = 0`` sits flush on
top of your KDE panel; ``-1`` ignores panels and goes to the screen edge.

X11 fallback: no layer-shell, so we compute absolute x/y from the screen's
(available) geometry ourselves.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QMargins, QObject, QRect, Signal
from PySide6.QtGui import QGuiApplication

# LayerShellQt::Window enum values (window.h)
ANCHOR_TOP, ANCHOR_BOTTOM, ANCHOR_LEFT, ANCHOR_RIGHT = 1, 2, 4, 8
LAYERS = {"background": 0, "bottom": 1, "top": 2}


def full_height(v: dict, screen: QRect) -> int:
    """Window height: the configured height, or everything from the anchored
    edge to the far edge when ``full_height`` is on."""
    if v["layout.full_height"]:
        return max(1, screen.height() - v["layout.margin_y"])
    return min(v["layout.height"], screen.height())


class LayoutModel(QObject):
    changed = Signal()

    def __init__(self, store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._screen = None
        self._geometry = (0, 0, 0, 0)
        self._margins = QMargins()
        self._anchors = ANCHOR_BOTTOM
        store.changed.connect(lambda _keys: self._recompute())
        app = QGuiApplication.instance()
        app.primaryScreenChanged.connect(self._track_screen)
        self._track_screen(app.primaryScreen())

    def _track_screen(self, screen) -> None:
        if self._screen is not None:
            self._screen.geometryChanged.disconnect(self._recompute)
            self._screen.availableGeometryChanged.disconnect(self._recompute)
        self._screen = screen
        if screen is not None:
            screen.geometryChanged.connect(self._recompute)
            screen.availableGeometryChanged.connect(self._recompute)
        self._recompute()

    def _recompute(self, *_args) -> None:
        v = self._store.values()
        screen: QRect = (self._screen.availableGeometry() if v["layout.respect_panels"]
                         else self._screen.geometry()) if self._screen else QRect(0, 0, 1920, 1080)
        align, top = v["layout.align"], v["layout.anchor"] == "top"
        mx, my = v["layout.margin_x"], v["layout.margin_y"]
        height = full_height(v, screen)
        width = max(1, screen.width() - 2 * mx) if align == "stretch" else min(v["layout.width"], screen.width())

        # Horizontal placement → x relative to the screen's left edge.
        rel_x = {"left": mx, "right": screen.width() - width - mx,
                 "center": (screen.width() - width) // 2 + mx, "stretch": mx}[align]

        # Layer-shell: margins only apply on anchored edges, so "center + offset"
        # is expressed as a left anchor with a computed left margin.
        anchors = ANCHOR_TOP if top else ANCHOR_BOTTOM
        left = right = 0
        if align == "stretch":
            anchors |= ANCHOR_LEFT | ANCHOR_RIGHT
            left = right = mx
        elif align == "right":
            anchors |= ANCHOR_RIGHT
            right = mx
        elif align == "left" or mx != 0:
            anchors |= ANCHOR_LEFT
            left = rel_x
        # (plain center: no horizontal anchor → compositor centers it)

        x = screen.x() + rel_x
        y = screen.y() + my if top else screen.y() + screen.height() - height - my
        self._anchors = anchors
        self._margins = QMargins(left, my if top else 0, right, 0 if top else my)
        self._geometry = (x, y, width, height)
        self._layer = LAYERS[v["layout.layer"]]
        self._exclusion = 0 if v["layout.respect_panels"] else -1
        self.changed.emit()

    # ── QML-facing read-only properties ───────────────────────────────────
    x = Property(int, lambda s: s._geometry[0], notify=changed)
    y = Property(int, lambda s: s._geometry[1], notify=changed)
    width = Property(int, lambda s: s._geometry[2], notify=changed)
    height = Property(int, lambda s: s._geometry[3], notify=changed)
    anchorFlags = Property(int, lambda s: s._anchors, notify=changed)
    margins = Property(QMargins, lambda s: s._margins, notify=changed)
    layer = Property(int, lambda s: s._layer, notify=changed)
    exclusionZone = Property(int, lambda s: s._exclusion, notify=changed)
