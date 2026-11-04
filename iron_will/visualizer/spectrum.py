"""``SpectrumTexture``: the bar heights as a tiny texture, for the GPU bars / mirror / wave shader.

A Qt Quick ``ShaderEffect`` can't take arrays, and bars go up to 256 values
plus 256 peak caps: far too many for uniforms. So each frame packs them into
an image of ``n × 2`` pixels, and the shader reads it like a lookup table::

    row 0   bar heights     texel i = value of bar i
    row 1   peak caps       texel i = peak of bar i

One 8-bit channel would give only 256 height steps (at full screen height
that's a visible ~3 px staircase), so each value is a 16-bit number split
over two channels: R = high byte, G = low byte. B is unused and A is always
255, which keeps premultiplication from ever touching R and G.

How it reaches the shader: this item stays hidden and is wrapped in a
``ShaderEffectSource`` (``qml/Visualizer.qml``). Both have their texture
size pinned to exactly n × 2 pixels, so nothing gets scaled or filtered on
the way, at any display scale. A painted item used directly as a texture
source comes out empty under PySide6; the ShaderEffectSource route was
verified bit-exact at 1×, 1.25× and 1.5×.

Cost per frame: one list comprehension over 2n values (~50 µs at n = 256)
and a 2 KB texture upload, against a full-window raster plus a
window-sized upload for the CPU painter.
"""

from __future__ import annotations

from array import array

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickPaintedItem

ROWS = 2
_OPAQUE = 0xFF000000   # A = 255; little-endian RGBA8888 words read R | G << 8 | B << 16 | A << 24


def pack(values: list[float]) -> list[int]:
    """0..1 floats → RGBA8888 words: R = high byte, G = low byte of round(v · 65535)."""
    words = []
    for v in values:
        q = 0 if v <= 0.0 else 65535 if v >= 1.0 else int(v * 65535.0 + 0.5)
        words.append(_OPAQUE | (q & 0xFF) << 8 | q >> 8)
    return words


class SpectrumTexture(QQuickPaintedItem):
    """Hidden n × 2 item whose pixels are the current bar heights and peaks."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(False)
        self.setSmooth(False)            # nearest filtering: texels are data, not pixels
        self.setOpaquePainting(True)
        self._count = 0
        self._buffer = b""               # QImage borrows this memory; keep it alive
        self._image: QImage | None = None
        self._resize(1)

    @property
    def count(self) -> int:
        return self._count

    def _resize(self, n: int) -> None:
        self._count = n
        self.setSize(QSize(n, ROWS).toSizeF())
        self.setTextureSize(QSize(n, ROWS))   # exactly one texel per value, whatever the display scale

    def upload(self, values: list[float], peaks: list[float]) -> None:
        """Publish one frame. Both lists have the same length (the number of bars)."""
        n = max(1, len(values))
        if n != self._count:
            self._resize(n)
        words = pack(values) + pack(peaks)
        if len(words) < n * ROWS:              # empty frame (before audio): all zero
            words = [_OPAQUE] * (n * ROWS)
        self._buffer = array("I", words).tobytes()
        self._image = QImage(self._buffer, n, ROWS, QImage.Format.Format_RGBA8888)
        self.update()

    def paint(self, painter: QPainter) -> None:
        if self._image is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(0, 0, self._image)
