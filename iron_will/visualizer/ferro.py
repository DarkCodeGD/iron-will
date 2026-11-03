"""Ferrofluid mode's "ears": spectrum frames → liquid controls for the shader (Qt-free).

The GPU shader (``shaders/ferro.frag``) draws a pool of glossy black
magnetic liquid; this module decides what the liquid does.

The analogy: a pool of ferrofluid on an electromagnet, and the music drives
the magnet. Above a critical field the flat surface becomes unstable and
pulls up into spikes (the Rosensweig instability, the reason real
ferrofluid grows those spiky crowns). The liquid has mass and surface
tension, so the spikes ride **under-damped springs**: they shoot up,
overshoot, wobble and slump back into the pool.

=================  ===========================  ===============================
group (spectrum)   in a metal mix               becomes
=================  ===========================  ===============================
low   0 – 20 %     kick drum, bass guitar       **surge**: the magnet kicks and
                                                every spike snaps up, tallest
                                                over the magnet (the middle)
mid  20 – 65 %     rhythm guitars, vocals       **field**: holds a forest of
                                                spikes up while the riff plays
high 70 – 100 %    snare crack, cymbals         **shimmer**: the surface ripples
                                                and the tips quiver
=================  ===========================  ===============================

Like fire, it reacts to *hits* (transients), not loudness, so brick-wall
mastered metal still moves it (see ``dynamics.py``). ``reaction`` scales
every time constant; ``wobble`` sets how under-damped the liquid is.
"""

from __future__ import annotations

import math

from .dynamics import (COLUMNS, HIGH, LOW, MID, BandSmoother, Spring, Transient, band_mean,
                       columns_from_bands, ema, rate)

# Liquid model (seconds, at reaction = 0.5; ``reaction`` scales them).
SURGE_FALL = 0.32     # a kick's pull on the liquid fades
SURGE_CAP = 1.3       # diminishing returns: double bass holds the spikes high, not past the top
BED_TAU = 0.25        # the guitars' steady field
BAND_TAU = 0.06       # pre-smoothing of the spectrum for the spike profile
SHIMMER_FALL = 0.25   # cymbal shimmer dies away
PULSE_RISE = 0.03     # the backlight flashes with each kick…
PULSE_FALL = 0.30     # …and fades
DRIVE_TAU = 0.8       # overall energy → how fast the surface ripples
CRITICAL = 0.06       # field needed before a spike forms (below it: a flat pool)
SPIKE_OMEGA = 15.0    # rad/s — spike springs going up
SPIKE_FALL = 0.6      # spikes slump back faster than fire dies down: liquid is heavy
SPREAD = 3.0          # 1/s — surface tension pulls neighbouring spikes together

# Rim colors for palette = "chrome": cool steel rim, near-white backlight.
CHROME = ("#9FB4D6", "#E6EEFF", "#FFFFFF")   # rim, backlight, highlight


class FerroAnalyzer:
    """Turns spectrum frames into the shader's liquid controls.

    Outputs (roughly 0..1), refreshed by :meth:`step`:

    ``columns``  spike heights across the width (``COLUMNS``, bass in the middle)
    ``surge``    the magnet's kick: extra pull on every spike
    ``bed``      steady field from the guitars (pool level, spike forest)
    ``shimmer``  surface ripple and tip quiver (cymbals)
    ``pulse``    backlight flash (leads the spikes, like fire's heat)
    ``phase``    accumulated ripple time (never jumps)

    The GPU mode contract (shared with ``FireAnalyzer``, used by the
    renderer): :meth:`apply` reads the config, then ``look``, ``palette`` and
    ``param`` hold the style and :meth:`motion` / :meth:`extra` the per-frame
    uniforms.
    """

    def __init__(self) -> None:
        self.intensity = 1.0
        self.response = 0.5
        self.wobble = 0.6
        self.look = (0.85, 0.5, 1.0)
        self.palette = ("#FF9A1F", "#E8262E", "#FFF4E6")
        self.param = 0.6
        self._rim = 0.7
        self._gloss = 0.8
        self.reset()

    # ── configuration ─────────────────────────────────────────────────────
    def configure(self, intensity: float, response: float = 0.5, wobble: float = 0.6) -> None:
        self.intensity = intensity
        self.response = response
        self.wobble = wobble

    def apply(self, cfg: dict, colors: list[str]) -> None:
        """Read the ``[ferro]`` settings and the resolved gradient colors."""
        self.configure(cfg["ferro.intensity"], cfg["ferro.reaction"], cfg["ferro.wobble"])
        self.look = (cfg["ferro.height"], cfg["ferro.density"], 1.0 if cfg["layout.direction"] == "up" else 0.0)
        self.param = cfg["ferro.sharpness"]
        self._rim, self._gloss = cfg["ferro.rim"], cfg["ferro.gloss"]
        if cfg["ferro.palette"] == "chrome" or not colors:
            self.palette = CHROME
        else:
            # Rim from the first gradient stop, backlight from the last; the
            # highlights stay near-white with a hint of the rim color.
            self.palette = (colors[0], colors[-1], "#FFF4E6")

    def reset(self) -> None:
        self.columns = [0.0] * COLUMNS
        self.surge = self.bed = self.shimmer = self.pulse = self.drive = 0.0
        self.phase = 0.0
        self._kick = Transient(floor=0.10)
        self._crack = Transient(floor=0.08)
        self._prev_kick = 0.0
        self._bands = BandSmoother(BAND_TAU)
        self._spikes = [Spring() for _ in range(COLUMNS)]

    # ── per-frame uniforms ────────────────────────────────────────────────
    def motion(self) -> tuple[float, float, float, float]:
        """x = phase, y = pulse (backlight), z = shimmer, w = bed (field)."""
        return (self.phase, self.pulse, self.shimmer, self.bed)

    def extra(self) -> tuple[float, float, float, float]:
        """x = surge, y = rim setting, z = gloss setting, w = unused."""
        return (self.surge, self._rim, self._gloss, 0.0)

    # ── physics ───────────────────────────────────────────────────────────
    def step(self, raw: list[float], dt: float) -> None:
        """Advance by *dt* seconds with the latest cava frame *raw* (0..1 bands)."""
        if dt <= 0:
            return
        k, r = self.intensity, rate(self.response)
        low, mid, high = (band_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))

        # ── the magnet: kicks surge, guitars hold a steady field ──────────
        kick = self._kick.step(low, dt)
        inject = max(0.0, kick - self._prev_kick)
        self._prev_kick = kick
        self.surge = self.surge * math.exp(-dt / (SURGE_FALL * r)) \
            + 0.9 * inject * k * max(0.0, 1.0 - self.surge / SURGE_CAP)
        self.bed = ema(self.bed, min(1.0, mid * 1.1 * k), dt, BED_TAU * r)
        crack = self._crack.step(high, dt)
        self.shimmer = max(min(1.0, crack * 0.9 * k), self.shimmer * math.exp(-dt / SHIMMER_FALL))
        pulse_target = min(1.0, 1.0 - math.exp(-2.2 * self.surge))
        self.pulse = ema(self.pulse, pulse_target, dt, PULSE_RISE if pulse_target > self.pulse else PULSE_FALL * r)

        # ── ripples speed up as the music gets busier ─────────────────────
        self.drive = ema(self.drive, min(1.0, 0.5 * self.bed + 0.6 * self.pulse), dt, DRIVE_TAU)
        self.phase += dt * (0.8 + 1.2 * self.drive)
        if self.phase > 1000.0:  # keep float precision in the shader
            self.phase -= 1000.0

        # ── spikes: field per column → critical threshold → liquid springs ─
        surge = 1.0 - math.exp(-1.4 * self.surge)          # soft knee: 0 → 1
        bands = columns_from_bands(self._bands.step(raw, dt))
        zeta = 0.60 - 0.44 * self.wobble                   # 0.60 stiff … 0.16 jelly
        half = (COLUMNS - 1) / 2
        heights = []
        for i, (spring, band) in enumerate(zip(self._spikes, bands)):
            over_magnet = 1.0 - 0.45 * abs(i - half) / half   # the magnet sits in the middle
            field = k * (0.55 * band + 0.35 * self.bed * (0.4 + 0.6 * band)) \
                + 0.60 * surge * over_magnet * (0.55 + 0.45 * band)
            target = max(0.0, field - CRITICAL) / (1.0 - CRITICAL)
            heights.append(spring.step(min(1.1, target), dt, SPIKE_OMEGA / r, zeta, SPIKE_FALL))
        d = min(0.45, SPREAD * dt)   # surface tension: explicit diffusion, clamped for stability
        self.columns = [h + d * ((heights[i - 1] if i else h) + (heights[i + 1] if i + 1 < COLUMNS else h) - 2 * h)
                        for i, h in enumerate(heights)]
        for spring, h in zip(self._spikes, self.columns):
            spring.x = h

    def settled(self) -> bool:
        return max(self.surge, self.bed, self.shimmer, self.pulse, max(self.columns, default=0.0)) < 0.01
