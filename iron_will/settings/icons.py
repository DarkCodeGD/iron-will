"""``image://modeicon/<mode>[/grey]`` — the render-mode tile icons.

Each mode's SVG (see ``visualizer/modes.py``) is rendered with QtSvg; the
``/grey`` variant is desaturated on the CPU with its alpha kept. Doing this
here instead of with a QML shader effect means the icons also draw on the
software scene graph (no GPU), where shader effects render nothing.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

from ..visualizer.modes import MODES

DEFAULT_PX = 96


class ModeIconProvider(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._paths = {m.id: str(m.icon_path) for m in MODES}

    def requestImage(self, image_id: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802 (Qt API)
        mode, _, variant = image_id.partition("/")
        w = requested.width() if requested.width() > 0 else DEFAULT_PX
        h = requested.height() if requested.height() > 0 else w
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        renderer = QSvgRenderer(self._paths.get(mode, ""))
        if renderer.isValid():
            painter = QPainter(image)
            renderer.render(painter, QRectF(0, 0, w, h))
            painter.end()
        if variant == "grey":
            image = _greyscale(image)
        if size is not None:
            size.setWidth(w)
            size.setHeight(h)
        return image


def _greyscale(image: QImage) -> QImage:
    """Luminance-only copy that keeps the alpha (Grayscale8 alone drops it)."""
    straight = image.convertToFormat(QImage.Format.Format_ARGB32)   # un-premultiply first
    grey = straight.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32)
    grey.setAlphaChannel(straight.convertToFormat(QImage.Format.Format_Alpha8))
    return grey
