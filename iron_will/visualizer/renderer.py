"""``VisualizerItem`` — the Qt Quick item that paints the visualization.

Shared by the desktop visualizer (fed by cava) and the settings GUI's live
preview (``demo: true`` → synthetic signal), so the preview is pixel-identical
to the real thing.

Render loop & idle behaviour
----------------------------
A precise timer ticks: physics step → fade step → ``update()``. Once audio
has been silent long enough that the bars have settled *and* the fade-out
finished, the timer stops completely: zero repaints and near-zero CPU while
nothing is playing. The next loud frame from cava restarts it.

The tick rate is an even share of the display's refresh rate, the one
closest to the fps setting (``frame_period``): 72 fps on a 144 Hz screen at
fps 60, so every frame stays up for exactly two refreshes. Ticking at a
plain 60 there would show frames for 2, 3, 2, 3 … refreshes, a judder that
crisp shapes (tendrils, bars) make easy to see. Each tick is scheduled
against a running deadline (no drift from rounding to whole milliseconds),
and the simulation advances by exactly one frame period per frame, so
motion moves the same distance between every two pictures on screen
instead of following the timer's jitter. cava keeps analysing at fps.

Spectrum modes on the GPU (bars, mirror, wave)
----------------------------------------------
These used to be painted here with QPainter: a full-window raster plus a
window-sized texture upload every frame, up to a whole CPU core at full
screen height. Now the item only runs the physics and packs the bar heights
and peaks into a tiny ``DataTexture`` (``datatex.py``, n × 2 texels).
One shared shader (``shaders/spectrum.frag``) draws all three from it, with
the same geometry as the painter below. The painter stays as the fallback for
a software scene graph. Properties for that shader: ``spectrumActive``,
``spectrumShader``, ``spectrumWave``, ``spectrumBars``, ``spectrumGrad`` and
``spectrumColors``.

Analyzer modes (fire, ferrofluid, …)
------------------------------------
Modes with a ``shader`` in the registry (``modes.py``) are drawn by a GPU
fragment shader hosted in ``qml/Visualizer.qml``, not by ``paint()``:
per-pixel effects would melt the CPU. This item still runs the clock and the
fade, feeds the mode's analyzer (``GPU_ANALYZERS``), and publishes its output
through one generic set of properties the shader binds to (``gpu*``):

    gpuColsA–D   16 column values (the analyzer's ``columns``)
    gpuMotion    analyzer.motion()   per frame
    gpuExtra     analyzer.extra()    per frame
    gpuLook      analyzer.look       (QML adds the aspect ratio as w)
    gpuColorA–C  analyzer.palette
    gpuParam     analyzer.param
    dataTex      analyzer.texture() — data modes (tendrils): a whole frame of
                 numbers in the shared DataTexture (layout in the analyzer)
    gpuParticles analyzer.particles() — object modes only (bubbles): up to
                 PARTICLE_SLOTS vec4s, flattened; QML unpacks them into
                 uniforms p0…p23. Empty slots are zeros.

Each shader gives those slots its own meaning (documented in the shader and
the analyzer). In a GPU mode the item skips ``update()`` entirely, so no CPU
texture is rasterised or uploaded. On a software-rendered scene graph (no GPU,
no shaders) QML sets ``gpuFallback``: analyzer modes then draw bars, and
every spectrum mode is painted by ``paint()``.
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
from .bubbles import PARTICLE_SLOTS, BubbleAnalyzer
from .ferro import FerroAnalyzer
from .tendrils import TendrilAnalyzer
from .fire import FireAnalyzer
from .modes import BY_ID, SPECTRUM_MODE_IDS, SPECTRUM_SHADER
from .physics import BarPhysics
from .datatex import DataTexture, pack

LOUD_THRESHOLD = 0.02   # a frame above this counts as "audio is playing"
FADE_TAU = 0.35         # seconds — fade in/out time constant
QML_URI = "IronWill"
QML_DIR = Path(__file__).resolve().parent / "qml"
SHADER_DIR = Path(__file__).resolve().parent / "shaders"
log = logging.getLogger("iron_will.visualizer")

# GPU mode id → analyzer class (each follows the contract in fire.py / ferro.py).
GPU_ANALYZERS = {"fire": FireAnalyzer, "ferro": FerroAnalyzer, "bubbles": BubbleAnalyzer,
                 "tendrils": TendrilAnalyzer}
_NO_PARTICLES = [0.0] * (4 * PARTICLE_SLOTS)
SPECTRUM_STOPS = 6   # color uniforms in spectrum.frag (config.MAX_COLOR_STOPS)


def _mirror(values: list[float], total: int) -> list[float]:
    """[b0 b1 b2] → [b2 b1 b0 b0 b1 b2] (bass in the middle), trimmed to *total*."""
    left = values[::-1]
    return left + (values[1:] if total % 2 else values)


def _vec4(values: list[float], start: int) -> QVector4D:
    return QVector4D(*values[start:start + 4])


def frame_period(refresh_hz: float, fps: float) -> float:
    """Seconds per tick: the even share of the display refresh closest to fps.

    144 Hz at fps 60 → every 2nd refresh (72 fps); 60 Hz → 60; 165 Hz → 55;
    75 Hz at fps 60 → 75. Without a sane refresh rate, plain fps."""
    if not 20.0 <= refresh_hz <= 1000.0:
        return 1.0 / fps
    every = max(1, round(refresh_hz / fps))
    return every / refresh_hz


class VisualizerItem(QQuickPaintedItem):
    storeChanged = Signal()
    demoChanged = Signal()
    gpuStyleChanged = Signal()    # config-driven shader values (rare)
    gpuFrame = Signal()           # per-frame shader values (every tick in a GPU mode)
    gpuParticlesChanged = Signal()  # per frame, only in modes with particles
    fadeChanged = Signal()        # per frame in every shader mode (opacity × fade)
    spectrumChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAntialiasing(True)
        self.setOpaquePainting(False)
        self._store: QObject | None = None
        self._demo = False
        self._demo_signal = DemoSignal()
        self._physics = BarPhysics()
        self._analyzers: dict = {}    # GPU mode id → analyzer, created on first use
        self._gpu = None              # the current mode's analyzer (None for CPU modes)
        self._gpu_fallback = False
        self._spectrum: DataTexture | None = None   # set from QML (qml/Visualizer.qml); every data mode shares it
        self._particle_flat = list(_NO_PARTICLES)
        self._cfg = config.defaults()
        self._colors: list[str] = list(self._cfg["visualizer.colors"])
        self._targets: list[float] = []
        self._fade = 0.0
        self._last_loud = float("-inf")
        self._last_tick = 0.0
        self._brush: QBrush | None = None
        self._brush_key: tuple | None = None
        self._period = 1.0 / 60.0      # s per frame (frame_period)
        self._deadline = 0.0           # when the current tick was due
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setSingleShot(True)   # each tick books the next one against the deadline
        self._timer.timeout.connect(self._tick)
        self.visibleChanged.connect(self._on_visible_changed)
        self.windowChanged.connect(self._on_window_changed)
        self._apply_config()

    # ── QML properties ────────────────────────────────────────────────────
    def _get_store(self):
        return self._store

    def _set_store(self, store) -> None:
        if store is self._store:
            return
        if self._store is not None:
            try:
                self._store.changed.disconnect(self._on_store_changed)
            except RuntimeError:     # shutting down: the store is already gone (and so is the link)
                pass
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

    def _get_spectrum(self):
        return self._spectrum

    def _set_spectrum(self, item) -> None:
        if item is not self._spectrum:
            self._spectrum = item
            self.spectrumChanged.emit()
            self.gpuStyleChanged.emit()
            self._wake()

    spectrum = Property(QObject, _get_spectrum, _set_spectrum, notify=spectrumChanged)

    # ── GPU modes → shader uniforms ───────────────────────────────────────
    def _is_gpu(self) -> bool:
        """An analyzer mode on its own shader (fire, ferrofluid, bubbles)."""
        return self._gpu is not None and not self._gpu_fallback

    def _is_spectrum_gpu(self) -> bool:
        """Bars, mirror or wave, drawn by spectrum.frag."""
        return (self._spectrum is not None and not self._gpu_fallback
                and self._cfg["visualizer.mode"] in SPECTRUM_MODE_IDS)

    def _spectrum_bars(self) -> QVector4D:
        c = self._cfg
        return QVector4D(float(c["visualizer.spacing"]), float(c["visualizer.roundness"]),
                         float(c["visualizer.min_height"]), 1.0 if c["visualizer.peaks"] else 0.0)

    def _spectrum_grad(self) -> QVector4D:
        c = self._cfg
        return QVector4D(float(min(len(self._colors), SPECTRUM_STOPS) or 1),
                         1.0 if c["visualizer.gradient_direction"] == "horizontal" else 0.0,
                         1.0 if c["layout.direction"] == "up" else 0.0, 0.0)

    def _spectrum_colors(self) -> list:
        stops = (self._colors or ["#ffffff"])[:SPECTRUM_STOPS]
        return [QColor(c) for c in stops + [stops[-1]] * (SPECTRUM_STOPS - len(stops))]

    def _get_fallback(self) -> bool:
        return self._gpu_fallback

    def _set_fallback(self, fallback: bool) -> None:
        if fallback != self._gpu_fallback:
            self._gpu_fallback = fallback
            if fallback and self._gpu is not None:
                log.warning("no GPU shaders (software rendering) — %s mode draws bars instead",
                            self._cfg["visualizer.mode"])
            self.gpuStyleChanged.emit()
            self._wake()
            self.update()

    def _shader_url(self) -> str:
        mode = BY_ID.get(self._cfg["visualizer.mode"])
        return QUrl.fromLocalFile(str(SHADER_DIR / mode.shader)).toString() if mode and mode.shader else ""

    def _style(self, attr: str, default):
        return getattr(self._gpu, attr) if self._gpu is not None else default

    def _cols(self, start: int) -> QVector4D:
        return _vec4(self._gpu.columns, start) if self._gpu is not None else QVector4D()

    def _frame(self, method: str) -> QVector4D:
        return QVector4D(*getattr(self._gpu, method)()) if self._gpu is not None else QVector4D()

    gpuFallback = Property(bool, _get_fallback, _set_fallback, notify=gpuStyleChanged)
    gpuActive = Property(bool, _is_gpu, notify=gpuStyleChanged)
    gpuShader = Property(str, _shader_url, notify=gpuStyleChanged)
    gpuLook = Property(QVector4D, lambda self: QVector4D(*self._style("look", (0.0, 0.0, 1.0)), 0.0),
                       notify=gpuStyleChanged)
    gpuColorA = Property(QColor, lambda self: QColor(self._style("palette", ("#000",) * 3)[0]), notify=gpuStyleChanged)
    gpuColorB = Property(QColor, lambda self: QColor(self._style("palette", ("#000",) * 3)[1]), notify=gpuStyleChanged)
    gpuColorC = Property(QColor, lambda self: QColor(self._style("palette", ("#000",) * 3)[2]), notify=gpuStyleChanged)
    gpuParam = Property(float, lambda self: float(self._style("param", 0.0)), notify=gpuStyleChanged)
    gpuColsA = Property(QVector4D, lambda self: self._cols(0), notify=gpuFrame)
    gpuColsB = Property(QVector4D, lambda self: self._cols(4), notify=gpuFrame)
    gpuColsC = Property(QVector4D, lambda self: self._cols(8), notify=gpuFrame)
    gpuColsD = Property(QVector4D, lambda self: self._cols(12), notify=gpuFrame)
    gpuMotion = Property(QVector4D, lambda self: self._frame("motion"), notify=gpuFrame)
    gpuExtra = Property(QVector4D, lambda self: self._frame("extra"), notify=gpuFrame)
    gpuOpacity = Property(float, lambda self: self._cfg["visualizer.opacity"] * self._fade, notify=fadeChanged)
    spectrumActive = Property(bool, _is_spectrum_gpu, notify=gpuStyleChanged)
    spectrumShader = Property(str, lambda self: QUrl.fromLocalFile(str(SHADER_DIR / SPECTRUM_SHADER)).toString(),
                              constant=True)
    spectrumWave = Property(bool, lambda self: self._cfg["visualizer.mode"] == "wave", notify=gpuStyleChanged)
    spectrumBars = Property(QVector4D, _spectrum_bars, notify=gpuStyleChanged)
    spectrumGrad = Property(QVector4D, _spectrum_grad, notify=gpuStyleChanged)
    spectrumColors = Property("QVariantList", _spectrum_colors, notify=gpuStyleChanged)

    def _particles(self) -> list:
        return self._particle_flat

    # One flat list per frame (one Python call from QML, not one per slot).
    gpuParticles = Property("QVariantList", _particles, notify=gpuParticlesChanged)

    def _publish_particles(self) -> None:
        """Flatten the analyzer's particle slots, padded with empty ones."""
        flat = [v for slot in self._gpu.particles() for v in slot]
        self._particle_flat = flat + _NO_PARTICLES[len(flat):]
        self.gpuParticlesChanged.emit()

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
        for analyzer in self._analyzers.values():
            analyzer.reset()
        self._targets = []
        self._fade = 0.0
        self._last_loud = float("-inf")
        self._particle_flat = list(_NO_PARTICLES)
        self.update()
        self._upload_spectrum()
        self.gpuParticlesChanged.emit()
        self.gpuFrame.emit()
        self.fadeChanged.emit()

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
        mode = c["visualizer.mode"]
        cls = GPU_ANALYZERS.get(mode)
        if cls is None:
            self._gpu = None
        else:
            if mode not in self._analyzers:
                self._analyzers[mode] = cls()
            self._gpu = self._analyzers[mode]
            self._gpu.apply(c, self._colors)
        self.gpuStyleChanged.emit()
        self._demo_signal.style = presets.demo_style_for(c)
        self._update_period()
        self._brush_key = None
        self._wake()
        self.update()

    # ── animation loop ────────────────────────────────────────────────────
    def _on_visible_changed(self) -> None:
        if self.isVisible():
            self._wake()
        else:
            self._timer.stop()  # hidden preview pages cost nothing

    def _on_window_changed(self, window) -> None:
        if window is not None:
            window.screenChanged.connect(self._update_period)   # moved to another output
        self._update_period()

    def _update_period(self, *_args) -> None:
        window = self.window()
        screen = window.screen() if window is not None else None
        refresh = screen.refreshRate() if screen is not None else 0.0
        self._period = frame_period(refresh, self._cfg["visualizer.fps"])

    def _wake(self) -> None:
        if not self._timer.isActive() and self.isVisible():
            self._last_tick = time.monotonic()
            self._deadline = self._last_tick + self._period
            self._timer.start(max(0, round(self._period * 1000)))

    def _tick(self) -> None:
        now = time.monotonic()
        period = self._period
        if now - self._deadline > period:
            # A stall (a busy desktop, a resume): don't race to catch up, start
            # over from now, moving by the time that really passed.
            dt = min(now - self._last_tick, 0.1)
            self._deadline = now
        else:
            dt = period                       # one frame on screen = one frame of motion
        self._last_tick = now
        self._deadline += period
        self._timer.start(max(0, round((self._deadline - now) * 1000)))
        c = self._cfg
        n = config.cava_bar_count(c)

        if self._demo:
            self._targets = self._demo_signal.sample(n, dt)
            self._last_loud = now
        self._physics.step(self._targets, dt)
        gpu = self._is_gpu()
        if gpu:
            if hasattr(self._gpu, "resize"):   # object modes simulate in pixels
                self._gpu.resize(self.width(), self.height())
            self._gpu.step(self._targets, dt)  # each GPU mode has its own dynamics

        silent_for = now - self._last_loud
        idle = c["motion.idle_fade"] and silent_for > c["motion.idle_timeout"]
        goal = 0.0 if idle else 1.0
        self._fade += (goal - self._fade) * (1.0 - math.exp(-dt / FADE_TAU))
        if abs(goal - self._fade) < 0.003:
            self._fade = goal

        if gpu:
            if hasattr(self._gpu, "particles"):
                self._publish_particles()
            if hasattr(self._gpu, "texture") and self._spectrum is not None:
                self._spectrum.upload(*self._gpu.texture())   # data modes (tendrils): one small texture
            self.gpuFrame.emit()  # the shader redraws; nothing to paint here
            self.fadeChanged.emit()
            # GPU modes keep moving through silence (fire's pilot light, the
            # liquid's ripples) until the idle fade has taken them out.
            quiet = silent_for > 0.5 and self._fade == 0.0
        else:
            if self._is_spectrum_gpu():
                self._upload_spectrum()      # a 2 KB texture instead of a full-window raster
                self.fadeChanged.emit()
            else:
                self.update()                # software scene graph: paint() below
            quiet = silent_for > 0.5 and self._physics.settled() and self._fade == goal
        if not self._demo and quiet:
            self._timer.stop()

    def _spectrum_values(self) -> tuple[list[float], list[float]]:
        """The bars as drawn: mirror mode shows every band twice, bass in the middle."""
        values, peaks = self._physics.values, self._physics.peaks
        if self._cfg["visualizer.mode"] == "mirror":
            total = self._cfg["visualizer.bar_count"]
            values, peaks = _mirror(values, total), _mirror(peaks, total)
        return values, peaks

    def _upload_spectrum(self) -> None:
        if self._is_spectrum_gpu():
            values, peaks = self._spectrum_values()
            self._spectrum.upload(pack(values) + pack(peaks), max(1, len(values)), 2)

    # ── painting (software fallback) ──────────────────────────────────────
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
        if (w < 2 or h < 2 or alpha <= 0.003 or not self._physics.values
                or self._is_gpu() or self._is_spectrum_gpu()):
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(alpha)

        up = c["layout.direction"] == "up"
        brush = self._get_brush(w, h, up)
        values, peaks = self._spectrum_values()
        if c["visualizer.mode"] == "wave":
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
    """``VisualizerItem`` (clock, physics, software painter), ``DataTexture``
    (per-frame data for the shaders) and ``Visualizer`` (the component windows
    and the preview use: all of that plus the shaders)."""
    qmlRegisterType(VisualizerItem, QML_URI, 1, 0, "VisualizerItem")
    qmlRegisterType(DataTexture, QML_URI, 1, 0, "DataTexture")
    qmlRegisterType(QUrl.fromLocalFile(str(QML_DIR / "Visualizer.qml")), QML_URI, 1, 0, "Visualizer")
