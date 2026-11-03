"""Fire mode's "ears": spectrum frames → flame controls for the shader (Qt-free).

The GPU shader (``shaders/fire.frag``) does the drawing; this module decides
*what* the fire does. Two ideas drive it. (The detectors and springs are
shared with the other GPU modes: see ``dynamics.py``.)

1 · Hits, not loudness
----------------------
Rock and metal are mastered "brick-wall" loud: the level barely moves, so
a fire that followed plain loudness would sit at full height forever. Each
instrument group instead runs a :class:`Transient` detector: how far the
group jumps above its *own* recent average (~0.35 s), scaled against the
biggest recent jump (a peak follower, ~2.5 s). A kick pokes out of a wall
of guitars the way a door slam pokes out of a fridge hum.

2 · Ignition, not scaling
-------------------------
Music never sets the flame height directly. It feeds a small combustion
model, so every reaction has the build-up and inertia of real fire:

    hit ──▶ FUEL ──burns──▶ HEAT (flash: brightness leads) ──▶ FLARE (height)
                                                     └──▶ heat front rising
                                                          through the flames

* **Fuel.** A kick or snare *throws fuel on the fire*: an impulse on the
  rising edge of the hit. It lands in two pools: *flash* fuel burns in
  ~0.18 s, *body* fuel in ~0.6 s, with diminishing returns as the fire gets
  full (a blast beat builds a big fire that still breathes).
* **Heat** follows the flash fuel with a short ignition delay (~50 ms) and
  cools in ~0.3 s. It drives brightness and the white-hot core: every hit
  visibly *ignites*, just before the flames grow.
* **Flare** (extra height) chases the fuel on a **damped spring**: it
  accelerates up, overshoots a touch, and settles — the "whoomph" — then
  sinks back on a softer spring. Analogy: a heavy door on a closer, not a
  light switch.
* **Heat front.** A strong ignition sends a band of heat travelling up
  through the flames (stretching the tongues as it passes).
* **Columns** (where along the width the fire burns) follow the spectrum
  through their own springs plus **sideways diffusion**, so a flare-up
  spreads to its neighbours like fire catching along a log.

Who drives what
---------------
=================  ===========================  =============================
group (spectrum)   in a metal mix               becomes
=================  ===========================  =============================
low   0 – 20 %     kick drum, bass guitar       fuel (big): ignitions, flares
mid  20 – 65 %     rhythm guitars, vocals       **bed**: steady body height
high 70 – 100 %    snare crack, cymbals         fuel (small) + **sparks**
=================  ===========================  =============================

Sustained double bass keeps topping up the fuel, so a blast beat builds a
roaring, towering fire rather than 16 jittery jumps per second. The
``response`` setting scales every time constant: low = slow, heavy burn,
high = snappy flare-ups. All steps are frame-rate independent.
"""

from __future__ import annotations

import math

from .. import config
from .dynamics import (COLUMNS, HIGH, LOW, MID, BandSmoother, Spring, Transient, band_mean,
                       columns_from_bands, ema, rate)

ANALYSIS_BANDS = config.GPU_ANALYSIS_BANDS  # cava bands requested in GPU modes

# Combustion model (seconds, at response = 0.5; ``response`` scales them).
FUEL_BURN = 0.60      # body fuel burns away slowly → flame height
FLASH_BURN = 0.18     # flash fuel burns fast → brightness, one flash per hit
FUEL_CAP = 1.4        # a fire this full takes no more fuel
HEAT_RISE = 0.05      # ignition delay: the flash comes first
HEAT_FALL = 0.28      # the flash cools
BED_TAU = 0.30        # guitar body: steady, never twitchy
BAND_TAU = 0.08       # pre-smoothing of the spectrum for the column shape
DRIVE_TAU = 0.8       # overall energy → churn speed
FLARE_OMEGA = 16.0    # rad/s — flare spring going up (peaks ~0.3 s after a hit)
FLARE_ZETA = 0.55     #        under-damped: a small overshoot, the "whoomph"
FLARE_FALL = 0.32     # falling spring runs at this fraction of the rise speed
COL_OMEGA = 7.0       # column springs
COL_ZETA = 0.8
COL_FALL = 0.45
SPREAD = 5.0          # 1/s — sideways diffusion between neighbouring columns
FRONT_SPEED = 2.6     # flame heights per second the heat front rises
FRONT_FADE = 0.45     # s — the front cools as it climbs
FRONT_GAP = 0.28      # s — at most one new front this often (no strobing)
SPARK_RELEASE = 0.45  # s — a shower of embers hangs in the air a moment
PILOT = 0.08          # flame height share left at silence: a pilot light

# Fire palette when fire.palette = "natural": deep red tips → orange → amber body.
# Saturated all the way down — dark, desaturated oranges read as brown.
NATURAL_FIRE = ("#FF8C1A", "#FF4A12", "#C8141E")  # body (base), mid, tip


def fire_palette(colors: list[str], palette: str) -> tuple[str, str, str]:
    """(body, mid, tip). Gradient stop 0 sits at the base — same as the bars —
    so it becomes the flame body and the last stop the tongue tips."""
    if palette == "natural" or not colors:
        return NATURAL_FIRE
    return colors[0], colors[len(colors) // 2] if len(colors) > 2 else colors[-1], colors[-1]


class FireAnalyzer:
    """Turns spectrum frames into the shader's flame controls.

    Outputs, all roughly 0..1, refreshed by :meth:`step`:

    ``columns``     flame height profile across the width (``COLUMNS``)
    ``bed``         steady body of the fire (guitars)
    ``heat``        brightness / white-hot core (leads the flare)
    ``flare``       extra height from ignitions (spring: rises, overshoots, sinks)
    ``front``       height (in flame heights) of the rising heat front
    ``front_heat``  that front's strength (0 = no front)
    ``sparks``      spark amount (cymbals + ignitions)
    ``phase``       accumulated churn (speed integrated, so it never jumps)

    GPU mode contract (shared with ``FerroAnalyzer``, used by the renderer):
    :meth:`apply` reads the config; ``look``, ``palette`` and ``param`` hold
    the style; :meth:`motion` / :meth:`extra` are the per-frame uniforms.
    """

    def __init__(self) -> None:
        self.intensity = 1.0
        self.speed = 1.0
        self.response = 0.5
        self.look = (0.9, 0.6, 1.0)
        self.palette = NATURAL_FIRE
        self.param = 0.6
        self._glow = 0.6
        self.reset()

    def apply(self, cfg: dict, colors: list[str]) -> None:
        """Read the ``[fire]`` settings and the resolved gradient colors."""
        self.configure(cfg["fire.intensity"], cfg["fire.speed"], cfg["fire.reaction"])
        # look: x = max flame height, y = spark amount, z = 1 if flames grow up
        self.look = (cfg["fire.height"], cfg["fire.sparks"], 1.0 if cfg["layout.direction"] == "up" else 0.0)
        self.palette = fire_palette(colors, cfg["fire.palette"])
        self.param = cfg["fire.translucency"]
        self._glow = cfg["fire.glow"]

    def motion(self) -> tuple[float, float, float, float]:
        """x = phase, y = heat (brightness flash), z = sparks, w = guitar bed."""
        return (self.phase, self.heat, self.sparks, self.bed)

    def extra(self) -> tuple[float, float, float, float]:
        """x = flare (height), y = heat-front height, z = front strength, w = glow setting."""
        return (self.flare, self.front, self.front_heat, self._glow)

    def configure(self, intensity: float, speed: float, response: float = 0.5) -> None:
        self.intensity = intensity
        self.speed = speed
        self.response = response

    def reset(self) -> None:
        self.columns = [0.0] * COLUMNS
        self.bed = self.heat = self.flare = self.sparks = self.drive = 0.0
        self.front, self.front_heat = 2.0, 0.0   # 2.0 = parked above the flames
        self.fuel = self.flash = 0.0
        self.phase = 0.0
        self._kick = Transient(floor=0.10)
        self._crack = Transient(floor=0.08)
        self._prev_kick = self._prev_crack = 0.0
        self._front_age = FRONT_GAP
        self._bands = BandSmoother(BAND_TAU)
        self._flare = Spring()
        self._cols = [Spring() for _ in range(COLUMNS)]

    @property
    def _rate(self) -> float:
        return rate(self.response)

    def step(self, raw: list[float], dt: float) -> None:
        """Advance by *dt* seconds with the latest cava frame *raw* (0..1 bands)."""
        if dt <= 0:
            return
        k, r = self.intensity, self._rate
        low, mid, high = (band_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))

        # ── hits → fuel impulses (only on the rising edge of a hit) ────────
        kick = self._kick.step(low, dt)
        crack = self._crack.step(high, dt)
        inject = 0.75 * max(0.0, kick - self._prev_kick) + 0.20 * max(0.0, crack - self._prev_crack)
        self._prev_kick, self._prev_crack = kick, crack
        # Diminishing returns: a roaring fire can't take fuel as fast as a small
        # one, so a blast beat builds a big fire that still breathes, not a wall.
        self.fuel = self.fuel * math.exp(-dt / (FUEL_BURN * r)) + inject * k * max(0.0, 1.0 - self.fuel / FUEL_CAP)
        self.flash = self.flash * math.exp(-dt / (FLASH_BURN * r)) + inject * k * max(0.0, 1.0 - self.flash / FUEL_CAP)

        # ── combustion: heat flashes first, the flare follows with momentum ─
        self.bed = ema(self.bed, min(1.0, mid * 1.1 * k), dt, BED_TAU * r)
        flame = 1.0 - math.exp(-1.3 * self.fuel)            # soft knee: 0 → 1
        heat_target = min(1.0, 0.30 * self.bed + 0.95 * (1.0 - math.exp(-1.8 * self.flash)))
        tau = HEAT_RISE if heat_target > self.heat else HEAT_FALL
        self.heat = ema(self.heat, heat_target, dt, tau * r)
        self.flare = self._flare.step(flame, dt, FLARE_OMEGA / r, FLARE_ZETA, FLARE_FALL)

        # ── a strong ignition sends a heat front up through the flames ─────
        self._front_age += dt
        if inject * k > 0.22 and self._front_age >= FRONT_GAP * r:
            self.front, self.front_heat, self._front_age = 0.0, min(1.0, inject * k * 1.6), 0.0
        self.front += dt * FRONT_SPEED / r
        self.front_heat *= math.exp(-dt / (FRONT_FADE * r))

        # ── sparks: cymbal cracks, plus showers thrown by ignitions ─────────
        # A hit throws embers the instant it lands (inject is the jump this
        # frame), and a fast flare-up keeps throwing them while it climbs.
        thrown = 1.6 * inject * k + max(0.0, self._flare.v) * 0.12
        self.sparks = max(min(1.0, crack * 0.8 * k + thrown), self.sparks * math.exp(-dt / SPARK_RELEASE))

        # ── speed: the fire churns harder as it gets hotter ─────────────────
        self.drive = ema(self.drive, min(1.0, 0.5 * self.bed + 0.6 * self.heat), dt, DRIVE_TAU)
        self.phase += dt * self.speed * (0.5 + 1.3 * self.drive)
        if self.phase > 1000.0:  # keep float precision in the shader
            self.phase -= 1000.0

        # ── columns: smoothed spectrum → springs → sideways spread ─────────
        targets = columns_from_bands(self._bands.step(raw, dt))
        heights = [s.step(min(1.0, t * k), dt, COL_OMEGA / r, COL_ZETA, COL_FALL)
                   for s, t in zip(self._cols, targets)]
        d = min(0.45, SPREAD * dt)   # explicit diffusion, clamped for stability
        self.columns = [h + d * ((heights[i - 1] if i else h) + (heights[i + 1] if i + 1 < COLUMNS else h) - 2 * h)
                        for i, h in enumerate(heights)]
        for s, h in zip(self._cols, self.columns):
            s.x = h

    def settled(self) -> bool:
        return max(self.bed, self.heat, self.flare, self.sparks, max(self.columns, default=0.0)) < 0.01
