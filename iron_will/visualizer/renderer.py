"""``VisualizerItem`` — the Qt Quick item that paints the visualization.

Shared by the desktop visualizer (fed by cava) and the settings GUI's live
preview (``demo: true`` → synthetic signal), so the preview is pixel-identical
to the real thing.

Render loop & idle behaviour
----------------------------
A precise QTimer ticks at the configured fps: physics step → fade step →
``update()``. Once audio has been silent long enough that the bars have
settled *and* the fade-out finished, the timer stops completely: zero
repaints and near-zero CPU while nothing is playing. The next loud frame from
cava restarts it.

Fire mode
---------
Fire is drawn by a GPU shader (``shaders/fire.frag``, hosted in
``qml/Visualizer.qml``), not by ``paint()``: per-pixel flames would melt the
CPU. In fire mode this item still runs the clock, physics and fade, feeds a
``FireAnalyzer``, and publishes its output as properties the shader binds to
(``fire*``). It skips ``update()`` entirely, so no CPU texture is rasterised
or uploaded. On a software-rendered scene graph (no GPU, no shaders) QML
sets ``fireFallback`` and fire mode simply draws bars.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QPointF, QRectF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QVector4D
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickPaintedItem

from .. import config, presets
from .demo import DemoSignal
from .fire import FireAnalyzer
from .physics import BarPhysics

LOUD_THRESHOLD = 0.02   # a frame above this counts as "audio is playing"
FADE_TAU = 0.35         # seconds — fade in/out time constant
QML_URI = "IronWill"
QML_DIR = Path(__file__).resolve().parent / "qml"
log = logging.getLogger("iron_will.visualizer")

# Fire palette when fire.palette = "natural": deep red tips → orange → amber body.
# Saturated all the way down — dark, desaturated oranges read as brown.
NATURAL_FIRE = ("#FF8C1A", "#FF4A12", "#C8141E")  # body (base), mid, tip


def _mirror(values: list[float], total: int) -> list[float]:
    """[b0 b1 b2] → [b2 b1 b0 b0 b1 b2] (bass in the middle), trimmed to *total*."""
    left = values[::-1]
    return left + (values[1:] if total % 2 else values)


def _fire_palette(colors: list[str], palette: str) -> tuple[QColor, QColor, QColor]:
    """(body, mid, tip). Gradient stop 0 sits at the base — same as the bars —
    so it becomes the flame body and the last stop the tongue tips."""
    if palette == "natural" or not colors:
        return tuple(QColor(c) for c in NATURAL_FIRE)  # type: ignore[return-value]
    return QColor(colors[0]), QColor(colors[len(colors) // 2] if len(colors) > 2 else colors[-1]), QColor(colors[-1])


def _vec4(values: list[float], start: int) -> QVector4D:
    return QVector4D(*values[start:start + 4])


class VisualizerItem(QQuickPaintedItem):
    storeChanged = Signal()
    demoChanged = Signal()
    fireStyleChanged = Signal()   # config-driven fire values (rare)
    fireFrame = Signal()          # per-frame fire values (every tick in fire mode)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self._store: QObject | None = None
        self._demo = False
        self._demo_signal = DemoSignal()
        self._physics = BarPhysics()
        self._fire = FireAnalyzer()
        self._fire_fallback = False
        self._fire_colors = _fire_palette([], "natural")
        self._cfg = config.defaults()
        self._colors: list[str] = list(self._cfg["visualizer.colors"])
        self._targets: list[float] = []
        self._fade = 0.0
        self._last_loud = float("-inf")
        self._last_tick = 0.0
        self._brush: QBrush | None = None
        self._brush_key: tuple | None = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self.visibleChanged.connect(self._on_visible_changed)
        self._apply_config()

    # ── QML properties ────────────────────────────────────────────────────
    def _get_store(self):
        return self._store

    def _set_store(self, store) -> None:
        if store is self._store:
            return
        if self._store is not None:
            self._store.changed.disconnect(self._on_store_changed)
        self._store = store
        if store is not None:
            store.changed.connect(self._on_store_changed)
        self._apply_config()
        self.storeChanged.emit()

    store = Property(QObject, _get_store, _set_store, notify=storeChanged)

    def _get_demo(self) -> bool:
        return self._demo

    def _set_demo(self, demo: bool) -> None:
        if demo != self._demo:
            self._demo = demo
            self._wake()
            self.demoChanged.emit()

    demo = Property(bool, _get_demo, _set_demo, notify=demoChanged)

    # ── fire mode → shader uniforms ───────────────────────────────────────
    def _is_fire(self) -> bool:
        return self._cfg["visualizer.mode"] == "fire" and not self._fire_fallback

    def _get_fallback(self) -> bool:
        return self._fire_fallback

    def _set_fallback(self, fallback: bool) -> None:
        if fallback != self._fire_fallback:
            self._fire_fallback = fallback
            if fallback and self._cfg["visualizer.mode"] == "fire":
                log.warning("no GPU shaders (software rendering) — fire mode draws bars instead")
            self.fireStyleChanged.emit()
            self._wake()
            self.update()

    fireFallback = Property(bool, _get_fallback, _set_fallback, notify=fireStyleChanged)
    fireActive = Property(bool, _is_fire, notify=fireStyleChanged)
    fireBody = Property(QColor, lambda self: self._fire_colors[0], notify=fireStyleChanged)
    fireMid = Property(QColor, lambda self: self._fire_colors[1], notify=fireStyleChanged)
    fireTip = Property(QColor, lambda self: self._fire_colors[2], notify=fireStyleChanged)
    # look: x = max flame height, y = spark amount, z = 1 if flames grow up (w = aspect, set in QML)
    fireLook = Property(QVector4D, lambda self: QVector4D(
        self._cfg["fire.height"], self._cfg["fire.sparks"],
        1.0 if self._cfg["visualizer.direction"] == "up" else 0.0, 0.0), notify=fireStyleChanged)
    fireTranslucency = Property(float, lambda self: self._cfg["fire.translucency"], notify=fireStyleChanged)
    fireColsA = Property(QVector4D, lambda self: _vec4(self._fire.columns, 0), notify=fireFrame)
    fireColsB = Property(QVector4D, lambda self: _vec4(self._fire.columns, 4), notify=fireFrame)
    fireColsC = Property(QVector4D, lambda self: _vec4(self._fire.columns, 8), notify=fireFrame)
    fireColsD = Property(QVector4D, lambda self: _vec4(self._fire.columns, 12), notify=fireFrame)
    # motion: x = phase, y = kick surge, z = spark burst, w = guitar bed
    fireMotion = Property(QVector4D, lambda self: QVector4D(
        self._fire.phase, self._fire.surge, self._fire.sparks, self._fire.bed), notify=fireFrame)
    fireOpacity = Property(float, lambda self: self._cfg["visualizer.opacity"] * self._fade, notify=fireFrame)

    # ── data input ────────────────────────────────────────────────────────
    @Slot(list)
    def feed(self, values: list) -> None:
        """New spectrum frame (0..1 per band) from cava."""
        self._targets = values
        if values and max(values) > LOUD_THRESHOLD:
            self._last_loud = time.monotonic()
            self._wake()

    @Slot()
    def reset(self) -> None:
        """Forget everything on screen and fade back in from nothing.

        Used when the window comes back after a suspend: the last frame from
        before the sleep is stale, and popping it up only to drop it looks
        like a glitch. Starting at zero with fade 0 gives a soft fade-in."""
        self._physics.reset()
        self._fire.reset()
        self._targets = []
        self._fade = 0.0
        self._last_loud = float("-inf")
        self.update()
        self.fireFrame.emit()

    # ── config ────────────────────────────────────────────────────────────
    def _on_store_changed(self, _keys) -> None:
        self._apply_config()

    def _apply_config(self) -> None:
        if self._store is not None:
            self._cfg = self._store.values()
            self._colors = self._store.resolved_colors()
        c = self._cfg
        self._physics.configure(c["motion.attack_ms"], c["motion.decay_ms"],
                                c["motion.peak_hold_ms"], c["motion.peak_gravity"])
        self._physics.resize(config.cava_bar_count(c))
        self._fire.configure(c["fire.intensity"], c["fire.speed"])
        self._fire_colors = _fire_palette(self._colors, c["fire.palette"])
        self.fireStyleChanged.emit()
        self._demo_signal.style = presets.demo_style_for(c)
        self._timer.setInterval(max(1, round(1000 / c["visualizer.fps"])))
        self._brush_key = None
        self._wake()
        self.update()

    # ── animation loop ────────────────────────────────────────────────────
    def _on_visible_changed(self) -> None:
        if self.isVisible():
            self._wake()
        else:
            self._timer.stop()  # hidden preview pages cost nothing

    def _wake(self) -> None:
        if not self._timer.isActive() and self.isVisible():
            self._last_tick = time.monotonic()
            self._timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.1)  # clamp after stalls
        self._last_tick = now
        c = self._cfg
        n = config.cava_bar_count(c)

        if self._demo:
            self._targets = self._demo_signal.sample(n, dt)
            self._last_loud = now
        self._physics.step(self._targets, dt)
        fire = self._is_fire()
        if fire:
            self._fire.step(self._targets, self._physics.values, dt)

        silent_for = now - self._last_loud
        idle = c["motion.idle_fade"] and silent_for > c["motion.idle_timeout"]
        goal = 0.0 if idle else 1.0
        self._fade += (goal - self._fade) * (1.0 - math.exp(-dt / FADE_TAU))
        if abs(goal - self._fade) < 0.003:
            self._fade = goal

        if fire:
            self.fireFrame.emit()  # the shader redraws; nothing to paint here
            # Flames keep flickering through silence (a pilot light) until
            # the idle fade has taken them out completely.
            quiet = silent_for > 0.5 and self._fade == 0.0
        else:
            self.update()
            quiet = silent_for > 0.5 and self._physics.settled() and self._fade == goal
        if not self._demo and quiet:
            self._timer.stop()

    # ── painting ──────────────────────────────────────────────────────────
    def _get_brush(self, w: float, h: float, up: bool) -> QBrush:
        c = self._cfg
        key = (w, h, up, tuple(self._colors), c["visualizer.gradient_direction"])
        if key != self._brush_key:
            colors = self._colors
            if len(colors) == 1:
                self._brush = QBrush(QColor(colors[0]))
            else:
                if c["visualizer.gradient_direction"] == "horizontal":
                    grad = QLinearGradient(0, 0, w, 0)
                else:  # first stop sits at the bars' base
                    grad = QLinearGradient(0, h, 0, 0) if up else QLinearGradient(0, 0, 0, h)
                for i, color in enumerate(colors):
                    grad.setColorAt(i / (len(colors) - 1), QColor(color))
                self._brush = QBrush(grad)
            self._brush_key = key
        return self._brush

    def paint(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        c = self._cfg
        alpha = c["visualizer.opacity"] * self._fade
        if w < 2 or h < 2 or alpha <= 0.003 or not self._physics.values or self._is_fire():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(alpha)

        up = c["visualizer.direction"] == "up"
        brush = self._get_brush(w, h, up)
        values, peaks = self._physics.values, self._physics.peaks
        mode = c["visualizer.mode"]
        if mode == "mirror":
            total = c["visualizer.bar_count"]
            values, peaks = _mirror(values, total), _mirror(peaks, total)

        if mode == "wave":
            self._paint_wave(painter, values, w, h, up, brush, alpha)
        else:
            self._paint_bars(painter, values, peaks, w, h, up, brush, alpha)

    def _bar_metrics(self, n: int, w: float) -> tuple[float, float]:
        spacing = float(self._cfg["visualizer.spacing"])
        if n > 1 and (w - spacing * (n - 1)) / n < 1.0:
            spacing = max(0.0, (w - n) / (n - 1))  # too dense: shrink gaps first
        bar_w = max(1.0, (w - spacing * (n - 1)) / n)
        return bar_w, spacing

    def _paint_bars(self, painter, values, peaks, w, h, up, brush, alpha) -> None:
        c = self._cfg
        n = len(values)
        bar_w, spacing = self._bar_metrics(n, w)
        radius = c["visualizer.roundness"] * bar_w / 2
        min_h = float(c["visualizer.min_height"])
        span = h - min_h

        bars = QPainterPath()
        for i, v in enumerate(values):
            bh = min_h + v * span
            if bh < 0.5:
                continue
            r = min(radius, bh / 2)
            bars.addRoundedRect(QRectF(i * (bar_w + spacing), h - bh if up else 0.0, bar_w, bh), r, r)
        painter.fillPath(bars, brush)

        if not c["visualizer.peaks"]:
            return
        cap = max(2.0, min(4.0, bar_w * 0.35))
        cap_r = min(radius, cap / 2)
        caps = QPainterPath()
        for i, (v, p) in enumerate(zip(values, peaks)):
            if p - v < 0.015:
                continue  # cap is sitting on its bar — skip
            offset = min(h - cap, min_h + p * span + cap)
            y = h - offset - cap if up else offset
            caps.addRoundedRect(QRectF(i * (bar_w + spacing), max(0.0, y), bar_w, cap), cap_r, cap_r)
        painter.setOpacity(alpha * 0.85)
        painter.fillPath(caps, brush)

    def _paint_wave(self, painter, values, w, h, up, brush, alpha) -> None:
        n = len(values)
        min_h = float(self._cfg["visualizer.min_height"])
        span = h - min_h - 2  # keep the 2px stroke inside the item
        step = w / n
        points = [QPointF(0.0, 0.0)]
        for i, v in enumerate(values):
            offset = min_h + v * span
            points.append(QPointF((i + 0.5) * step, h - offset - 1 if up else offset + 1))
        points[0] = QPointF(0.0, points[1].y())
        points.append(QPointF(w, points[-1].y()))

        # Catmull-Rom → cubic Bézier: a smooth curve through every point.
        line = QPainterPath(points[0])
        for i in range(len(points) - 1):
            p0 = points[i - 1] if i > 0 else points[i]
            p1, p2 = points[i], points[i + 1]
            p3 = points[i + 2] if i + 2 < len(points) else p2
            line.cubicTo(p1 + (p2 - p0) / 6.0, p2 - (p3 - p1) / 6.0, p2)

        base = h if up else 0.0
        fill = QPainterPath(line)
        fill.lineTo(w, base)
        fill.lineTo(0.0, base)
        fill.closeSubpath()
        painter.setOpacity(alpha * 0.35)
        painter.fillPath(fill, brush)

        pen = QPen(brush, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setOpacity(alpha)
        painter.strokePath(line, pen)


def register_qml_types() -> None:
    """``VisualizerItem`` (the CPU painter + clock) and ``Visualizer`` (the
    component windows and the preview use: that item plus the fire shader)."""
    qmlRegisterType(VisualizerItem, QML_URI, 1, 0, "VisualizerItem")
    qmlRegisterType(QUrl.fromLocalFile(str(QML_DIR / "Visualizer.qml")), QML_URI, 1, 0, "Visualizer")
