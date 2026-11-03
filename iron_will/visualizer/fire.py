"""Fire mode's "ears": spectrum frames → a handful of flame controls (Qt-free).

The GPU shader (``shaders/fire.frag``) does the drawing; this module decides
*what* the fire should do each frame. It's built for loud, dense music like
rock and metal, which is mastered "brick-wall" loud: the level barely moves,
so a fire that followed plain loudness would sit at full height forever.

The trick: hits, not loudness
-----------------------------
Each instrument group gets two envelopes over its slice of the spectrum:

* a **fast** one — what is happening right now, and
* a **slow** one (~0.35 s) — its own recent average.

``fast - slow`` is how far the group just jumped *above its own normal*.
A sustained guitar wall raises both, so the difference stays ~0. A kick
drum spikes the fast one only, so it pokes out even when everything is
loud. Analogy: you don't notice a fridge hum, you notice a door slam.

Who drives what
---------------
====================  ==============================  ======================
group (spectrum %)    in a metal mix                  becomes
====================  ==============================  ======================
low    0 – 20 %       kick drum, bass guitar          **surge**: flames jump,
                                                      core flashes white-hot
mid   20 – 65 %       rhythm guitars, vocals          **bed**: base height
high  70 – 100 %      snare crack, cymbals, hi-hats   **sparks** bursts
everything            overall drive                   **speed** of the churn
====================  ==============================  ======================

How big is "a big hit"? That depends on the song, so each detector also
runs a **peak follower** on its own jumps (instant rise, ~2.5 s release):
the biggest recent kick maps to a full surge and the rest scale against it.
It's auto-gain for punches rather than for loudness. A floor keeps it from
blowing noise up into fake hits in quiet passages.

Envelopes are ``x += (target - x) * (1 - e^(-dt/tau))`` — frame-rate
independent, like ``BarPhysics``. The surge attacks instantly and releases
with a ~80 ms time constant, so 16th-note double bass at 200 BPM (one kick
every 75 ms) still reads as separate punches instead of one smeared blob.
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
BED_TAU = 0.12        # s — smoothing of the guitar bed
SURGE_RELEASE = 0.08  # s — how fast a kick surge falls back
SPARK_RELEASE = 0.16  # s — how long a cymbal spark burst lingers
DRIVE_TAU = 0.6       # s — overall drive (sets the flame speed)
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

    Outputs, all roughly 0..1 (refreshed by :meth:`step`):

    ``columns``  per-column flame height profile (``COLUMNS`` values)
    ``bed``      sustained body of the fire (guitars)
    ``surge``    kick punch — jumps instantly, falls in ~80 ms
    ``sparks``   cymbal / snare spark burst
    ``drive``    slow overall energy
    ``phase``    accumulated flame scroll (speed integrated over time, so a
                 speed change never makes the flames jump)
    """

    def __init__(self) -> None:
        self.intensity = 1.0
        self.speed = 1.0
        self.reset()

    def configure(self, intensity: float, speed: float) -> None:
        self.intensity = intensity
        self.speed = speed

    def reset(self) -> None:
        self.columns = [0.0] * COLUMNS
        self.bed = self.surge = self.sparks = self.drive = 0.0
        self.phase = 0.0
        self._kick = Transient(floor=0.10)
        self._crack = Transient(floor=0.08)

    def step(self, raw: list[float], smooth: list[float], dt: float) -> None:
        """*raw*: the latest cava frame (for transients). *smooth*: the same
        bands after the user's attack/decay physics (for the column shape)."""
        if dt <= 0:
            return
        k = self.intensity
        low, mid, high = (_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))

        kick = self._kick.step(low, dt)
        crack = self._crack.step(high, dt)

        # Surge & sparks: instant attack, exponential release. A typical
        # strong hit lands at ~0.85, so intensity > 1 can still push it to 1.
        self.surge = max(min(1.0, kick * 0.85 * k), self.surge * math.exp(-dt / SURGE_RELEASE))
        self.sparks = max(min(1.0, crack * 0.8 * k), self.sparks * math.exp(-dt / SPARK_RELEASE))

        self.bed = _ema(self.bed, min(1.0, mid * 1.15 * k), dt, BED_TAU)
        energy = min(1.0, 0.6 * (low + mid + high) / 3 * 1.6 + 0.4 * self.surge)
        self.drive = _ema(self.drive, energy, dt, DRIVE_TAU)

        # Calm music licks lazily; a blast beat roars (~0.5× → 2× base speed).
        self.phase += dt * self.speed * (0.5 + 1.5 * self.drive)
        if self.phase > 1000.0:  # keep float precision in the shader
            self.phase -= 1000.0

        cols = columns_from_bands(smooth or raw)
        self.columns = [min(1.0, c * k) for c in cols]

    def settled(self) -> bool:
        return max(self.bed, self.surge, self.sparks, max(self.columns, default=0.0)) < 0.01
