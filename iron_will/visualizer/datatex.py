"""``DataTexture``: per-frame data for a shader, as a tiny texture.

A Qt Quick ``ShaderEffect`` can't take arrays, and some modes need far more
numbers per frame than uniforms can carry: bars go up to 256 heights plus
256 peak caps, void tendrils send every tendril's spine plus the essence
motes. So the data goes out as a small image, and the shader reads it like a
lookup table. Each mode documents its own layout:

* spectrum modes (``shaders/spectrum.frag``): n × 2, row 0 = bar heights,
  row 1 = peak caps
* void tendrils (``tendrils.py``): spines, bounding boxes and motes

Texel format: one 8-bit channel would give only 256 steps (at full screen
height a visible ~3 px staircase), so a value is a **16-bit number split
over two channels**, R = high byte and G = low byte. B carries one extra
8-bit value, and A is always 255, which keeps premultiplication from ever
touching R, G and B. ``word(q16, b8)`` builds a texel; a shader decodes R/G
with ``(r * 65280 + g * 255) / 65535``.

How it reaches the shader: this item stays hidden and is wrapped in a
``ShaderEffectSource`` (``qml/Visualizer.qml``). Both have their texture
size pinned to exactly one texel per value, so nothing gets scaled or
filtered on the way, at any display scale. A painted item used directly as a
texture source comes out empty under PySide6; the ShaderEffectSource route
was verified bit-exact at 1×, 1.25× and 1.5×.

Cost per frame: building the word list in Python plus a texture upload of a
few KB, against a full-window raster plus a window-sized upload for a
QPainter visualizer.
"""

from __future__ import annotations

from array import array

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickPaintedItem

OPAQUE = 0xFF000000   # A = 255; little-endian RGBA8888 words read R | G << 8 | B << 16 | A << 24
EMPTY = OPAQUE


def quantize(v: float) -> int:
    """0..1 → 0..65535 (clamped)."""
    return 0 if v <= 0.0 else 65535 if v >= 1.0 else int(v * 65535.0 + 0.5)


def word(q16: int, b8: int = 0) -> int:
    """One texel: a 16-bit value in R (high byte) / G (low byte), an 8-bit one in B."""
    return OPAQUE | (b8 & 0xFF) << 16 | (q16 & 0xFF) << 8 | q16 >> 8


def pack(values: list[float]) -> list[int]:
    """0..1 floats → one texel each (B unused)."""
    return [word(quantize(v)) for v in values]


class DataTexture(QQuickPaintedItem):
    """Hidden item whose pixels are numbers for the current mode's shader."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(False)
        self.setSmooth(False)            # nearest filtering: texels are data, not pixels
        self.setOpaquePainting(True)
        self._dims = (0, 0)
        self._buffer = b""               # QImage borrows this memory; keep it alive
        self._image: QImage | None = None
        self._resize(1, 1)

    def _resize(self, columns: int, rows: int) -> None:
        self._dims = (columns, rows)
        self.setSize(QSize(columns, rows).toSizeF())
        self.setTextureSize(QSize(columns, rows))   # exactly one texel per value, whatever the display scale

    def upload(self, words: list[int], columns: int, rows: int) -> None:
        """Publish one frame: *words* is row-major, columns × rows texels (padded if short)."""
        columns, rows = max(1, columns), max(1, rows)
        if (columns, rows) != self._dims:
            self._resize(columns, rows)
        need = columns * rows
        if len(words) < need:
            words = words + [EMPTY] * (need - len(words))
        self._buffer = array("I", words[:need]).tobytes()
        self._image = QImage(self._buffer, columns, rows, QImage.Format.Format_RGBA8888)
        self.update()

    def paint(self, painter: QPainter) -> None:
        if self._image is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(0, 0, self._image)
