"""Shared "ears" for the GPU visualizers (Qt-free).

Every GPU mode (fire, ferrofluid, …) turns cava's spectrum frames into a few
smooth control signals for its shader. The building blocks are the same, so
they live here:

* **Spectrum slices** — kick/bass (``LOW``), guitars/vocals (``MID``) and
  snare/cymbals (``HIGH``), as fractions of the band list.
* :class:`Transient` — *hits, not loudness*: how far a signal pokes above
  its own recent average, scaled against the biggest recent poke. Rock and
  metal are mastered brick-wall loud, so plain loudness barely moves; a kick
  still pokes out of a wall of guitars like a door slam out of a fridge hum.
* :class:`Spring` — damped spring with momentum, so motion accelerates,
  overshoots and settles instead of snapping.
* :func:`columns_from_bands` — the spectrum folded into N columns with the
  bass in the middle.
* :func:`rate` — the ``reaction`` setting as a time-constant multiplier.

All steps are frame-rate independent (they take ``dt`` in seconds).
"""

from __future__ import annotations

import math

COLUMNS = 16          # columns every GPU shader interpolates between (colsA–D)

# Spectrum slices as fractions of the band list (cava spaces bands
# logarithmically between the low and high cutoff).
LOW = (0.0, 0.20)     # kick drum, bass guitar
MID = (0.20, 0.65)    # rhythm guitars, vocals
HIGH = (0.70, 1.0)    # snare crack, cymbals

SLOW_TAU = 0.35       # s — "recent average" for transient detection
REF_RELEASE = 2.5     # s — how long the "biggest recent hit" reference lingers


def ema(x: float, target: float, dt: float, tau: float) -> float:
    """One step of an exponential follower with time constant *tau*."""
    return x + (target - x) * (1.0 - math.exp(-dt / tau))


def band_mean(values: list[float], span: tuple[float, float]) -> float:
    """Average of the bands inside *span* (fractions of the list)."""
    n = len(values)
    a = int(span[0] * n)
    b = max(a + 1, int(math.ceil(span[1] * n)))
    part = values[a:b]
    return sum(part) / len(part) if part else 0.0


def rate(response: float) -> float:
    """Time-constant multiplier from a 0..1 reaction setting:
    0 → 2× slower, 0.5 → as tuned, 1 → ~1.7× faster."""
    if response <= 0.5:
        return 2.0 ** (1.0 - 2.0 * response)
    return 1.0 / (1.0 + 1.4 * (response - 0.5))


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
        self.slow = ema(self.slow, x, dt, SLOW_TAU)
        jump = max(0.0, x - self.slow)
        self.ref = max(jump, self.ref * math.exp(-dt / REF_RELEASE))
        return jump / max(self.ref, self.floor)


class Spring:
    """A damped spring chasing a target: ``x'' = ω²(target − x) − 2ζω·x'``.

    Unlike an exponential follower, it has momentum: it accelerates, can
    overshoot (ζ < 1) and settles, which is what makes motion read as
    physical. Falling uses a softer spring (``fall`` × ω), so things rise
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
        if self.x < 0.0:        # heights can't be negative: land softly on zero
            self.x, self.v = 0.0, max(self.v, 0.0)
        return self.x


def columns_from_bands(values: list[float], count: int = COLUMNS) -> list[float]:
    """Mirror the spectrum into *count* columns with the bass in the middle:
    kick and bass lift the centre, cymbals reach the edges."""
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


class BandSmoother:
    """Per-band exponential smoothing of raw cava frames (resets on size change)."""

    def __init__(self, tau: float) -> None:
        self.tau = tau
        self.bands: list[float] = []

    def step(self, raw: list[float], dt: float) -> list[float]:
        if len(self.bands) != len(raw):
            self.bands = list(raw)
        else:
            a = 1.0 - math.exp(-dt / self.tau)
            self.bands = [b + (x - b) * a for b, x in zip(self.bands, raw)]
        return self.bands
