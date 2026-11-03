"""Fire mode's "ears": spectrum frames → flame controls for the shader (Qt-free).

The GPU shader (``shaders/fire.frag``) does the drawing; this module decides
*what* the fire does. Two ideas drive it.

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

COLUMNS = 16          # flame columns the shader interpolates between
ANALYSIS_BANDS = config.FIRE_ANALYSIS_BANDS  # cava bands requested in fire mode

# Spectrum slices as fractions of the band list (cava spaces bands
# logarithmically between the low and high cutoff).
LOW = (0.0, 0.20)
MID = (0.20, 0.65)
HIGH = (0.70, 1.0)

SLOW_TAU = 0.35       # s — "recent average" for transient detection
REF_RELEASE = 2.5     # s — how long the "biggest recent hit" reference lingers

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
SPARK_RELEASE = 0.30  # s
PILOT = 0.08          # flame height share left at silence: a pilot light


def _ema(x: float, target: float, dt: float, tau: float) -> float:
    return x + (target - x) * (1.0 - math.exp(-dt / tau))


def _mean(values: list[float], span: tuple[float, float]) -> float:
    n = len(values)
    a = int(span[0] * n)
    b = max(a + 1, int(math.ceil(span[1] * n)))
    part = values[a:b]
    return sum(part) / len(part) if part else 0.0


class Transient:
    """Detects hits in one signal: how far it pokes above its own recent
    average, scaled against the biggest recent poke (0..~1)."""

    def __init__(self, floor: float) -> None:
        self.floor = floor   # smallest jump that can ever count as a full hit
        self.reset()

    def reset(self) -> None:
        self.slow = 0.0
        self.ref = 0.0

    def step(self, x: float, dt: float) -> float:
        self.slow = _ema(self.slow, x, dt, SLOW_TAU)
        jump = max(0.0, x - self.slow)
        self.ref = max(jump, self.ref * math.exp(-dt / REF_RELEASE))
        return jump / max(self.ref, self.floor)


class Spring:
    """A damped spring chasing a target: ``x'' = ω²(target − x) − 2ζω·x'``.

    Unlike an exponential follower, it has momentum: it accelerates, can
    overshoot slightly (ζ < 1) and settles, which is what makes motion read
    as physical. Falling uses a softer spring (``fall`` × ω), so things rise
    fast and die down slowly. Semi-implicit Euler, sub-stepped for stability."""

    __slots__ = ("x", "v")

    def __init__(self) -> None:
        self.x = 0.0
        self.v = 0.0

    def step(self, target: float, dt: float, omega: float, zeta: float, fall: float) -> float:
        steps = max(1, math.ceil(dt * omega / 0.5))
        h = dt / steps
        for _ in range(steps):
            w = omega if target > self.x else omega * fall
            self.v += (w * w * (target - self.x) - 2.0 * zeta * w * self.v) * h
            self.x += self.v * h
        if self.x < 0.0:        # flames can't be negative: land softly on zero
            self.x, self.v = 0.0, max(self.v, 0.0)
        return self.x


def columns_from_bands(values: list[float], count: int = COLUMNS) -> list[float]:
    """Mirror the spectrum into *count* columns with the bass in the middle —
    a bonfire shape: kick and bass lift the centre, cymbals lick the edges."""
    half = count // 2
    n = len(values)
    if n == 0:
        return [0.0] * count
    side = []
    for i in range(half):  # average the bands that fall in each half-column
        a = i * n // half
        b = max(a + 1, (i + 1) * n // half)
        part = values[a:b]
        side.append(sum(part) / len(part))
    return side[::-1] + side


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
    """

    def __init__(self) -> None:
        self.intensity = 1.0
        self.speed = 1.0
        self.response = 0.5
        self.reset()

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
        self._bands: list[float] = []
        self._flare = Spring()
        self._cols = [Spring() for _ in range(COLUMNS)]

    @property
    def _rate(self) -> float:
        """Time-constant multiplier from ``response``: 0 → 2× slower, 1 → ~1.7× faster."""
        return 2.0 ** (1.0 - 2.0 * self.response) if self.response <= 0.5 else 1.0 / (1.0 + 1.4 * (self.response - 0.5))

    def step(self, raw: list[float], dt: float) -> None:
        """Advance by *dt* seconds with the latest cava frame *raw* (0..1 bands)."""
        if dt <= 0:
            return
        k, r = self.intensity, self._rate
        low, mid, high = (_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))

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
        self.bed = _ema(self.bed, min(1.0, mid * 1.1 * k), dt, BED_TAU * r)
        flame = 1.0 - math.exp(-1.3 * self.fuel)            # soft knee: 0 → 1
        heat_target = min(1.0, 0.30 * self.bed + 0.95 * (1.0 - math.exp(-1.8 * self.flash)))
        tau = HEAT_RISE if heat_target > self.heat else HEAT_FALL
        self.heat = _ema(self.heat, heat_target, dt, tau * r)
        self.flare = self._flare.step(flame, dt, FLARE_OMEGA / r, FLARE_ZETA, FLARE_FALL)

        # ── a strong ignition sends a heat front up through the flames ─────
        self._front_age += dt
        if inject * k > 0.22 and self._front_age >= FRONT_GAP * r:
            self.front, self.front_heat, self._front_age = 0.0, min(1.0, inject * k * 1.6), 0.0
        self.front += dt * FRONT_SPEED / r
        self.front_heat *= math.exp(-dt / (FRONT_FADE * r))

        # ── sparks: cymbal cracks, plus embers thrown by fast flare-ups ────
        thrown = max(0.0, self._flare.v) * 0.12
        self.sparks = max(min(1.0, crack * 0.7 * k + thrown), self.sparks * math.exp(-dt / SPARK_RELEASE))

        # ── speed: the fire churns harder as it gets hotter ─────────────────
        self.drive = _ema(self.drive, min(1.0, 0.5 * self.bed + 0.6 * self.heat), dt, DRIVE_TAU)
        self.phase += dt * self.speed * (0.5 + 1.3 * self.drive)
        if self.phase > 1000.0:  # keep float precision in the shader
            self.phase -= 1000.0

        # ── columns: smoothed spectrum → springs → sideways spread ─────────
        if len(self._bands) != len(raw):
            self._bands = list(raw)
        else:
            a = 1.0 - math.exp(-dt / BAND_TAU)
            self._bands = [b + (x - b) * a for b, x in zip(self._bands, raw)]
        targets = columns_from_bands(self._bands)
        heights = [s.step(min(1.0, t * k), dt, COL_OMEGA / r, COL_ZETA, COL_FALL)
                   for s, t in zip(self._cols, targets)]
        d = min(0.45, SPREAD * dt)   # explicit diffusion, clamped for stability
        self.columns = [h + d * ((heights[i - 1] if i else h) + (heights[i + 1] if i + 1 < COLUMNS else h) - 2 * h)
                        for i, h in enumerate(heights)]
        for s, h in zip(self._cols, self.columns):
            s.x = h

    def settled(self) -> bool:
        return max(self.bed, self.heat, self.flare, self.sparks, max(self.columns, default=0.0)) < 0.01
