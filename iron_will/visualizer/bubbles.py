"""Bubbles mode: a little soap-bubble simulation driven by the music (Qt-free).

Unlike fire and ferrofluid, bubbles are *objects*: each one has its own
position, size, age and fate, and a popped bubble must stay gone. A shader
can't remember that, so the bubbles live here, and the shader
(``shaders/bubbles.frag``) only draws them: each frame the live bubbles go
out as up to ``PARTICLE_SLOTS`` particle slots (``particles()``).

=================  ===========================  ===============================
group (spectrum)   in the mix                   becomes
=================  ===========================  ===============================
low   0 – 20 %     kick drum, bass              **blow**: a big bubble or two,
                                                and the whole field jiggles
mid  20 – 65 %     guitars, vocals, keys        **stream**: a steady flow of
                                                bubbles, born where the music is
high 70 – 100 %    snare crack, cymbals         **pops**, and tiny fizz bubbles
=================  ===========================  ===============================

Physics, kept simple and soft: bubbles rise at a terminal speed that grows
with their size (big bubbles are more buoyant), sway side to side as they
go, and pop when they reach the far edge, get old, or a snare hit picks
them. A kick sets off one shared jelly *jiggle* (a signed, under-damped
oscillator) that squishes every bubble. All of it happens in pixels, so a
bubble is the same size in a short strip and on a full-screen window.

Particle slot format (what the shader reads), in window units:
``(x / width, distance from the base / height, radius / height, state)``,
``state`` in [0, 1) = alive (the fraction is the bubble's seed, which varies
its film swirl), ``1 + t`` = popping, ``t`` = 0 … 1 through the pop.
"""

from __future__ import annotations

import math
import random

from .dynamics import COLUMNS, HIGH, LOW, MID, BandSmoother, Transient, band_mean, columns_from_bands, ema

PARTICLE_SLOTS = 24   # bubbles the shader can draw at once (shared GPU contract)

POP_TIME = 0.30       # s — a pop: ring, droplets, sparkle
BAND_TAU = 0.10       # pre-smoothing of the spectrum (where bubbles are born)
BED_TAU = 0.35        # the steady stream follows the guitars slowly
ENERGY_TAU = 0.6      # overall liveliness: rise speed and fizz
MIN_AGE_TO_POP = 0.5  # s — a newborn bubble never pops straight away
JIGGLE_OMEGA = 13.0   # rad/s — the shared jelly wobble
EDGE = 1.25           # × radius: room a bubble keeps from the window edges (its squish stretches it ~23 %)

# Palette choices → shader param (bubbles.frag reads it).
PALETTES = {"iridescent": 0.0, "pastel": 1.0, "colors": 2.0}
POP_SHAPES = {"sparkles": 0.0, "hearts": 1.0}
HEART_PINK = "#FF6FAE"


class Bubble:
    __slots__ = ("x", "y", "r", "vy", "seed", "sway", "age", "life", "pop")

    def __init__(self, x: float, y: float, r: float, vy: float, rng: random.Random) -> None:
        self.x, self.y, self.r, self.vy = x, y, r, vy
        self.seed = rng.random()
        self.sway = rng.uniform(0.6, 1.4)          # sway rate multiplier
        self.age = 0.0
        self.life = rng.uniform(5.0, 11.0)         # pops of old age after this
        self.pop = -1.0                            # < 0 alive, else pop progress 0..1


class Jiggle:
    """Signed under-damped oscillator: kicks give it a shove, it wobbles back
    through zero (unlike ``dynamics.Spring``, which can't go negative)."""

    def __init__(self) -> None:
        self.x = self.v = 0.0

    def kick(self, amount: float) -> None:
        self.v += amount

    def step(self, dt: float, omega: float, zeta: float) -> float:
        steps = max(1, math.ceil(dt * omega / 0.5))
        h = dt / steps
        for _ in range(steps):
            self.v += (-omega * omega * self.x - 2.0 * zeta * omega * self.v) * h
            self.x += self.v * h
        return self.x


class BubbleAnalyzer:
    """The bubble field. Follows the GPU mode contract (see ``fire.py``) plus
    ``resize(w, h)`` (the field lives in pixels) and ``particles()``."""

    def __init__(self) -> None:
        self.amount = 0.6
        self.size = 0.6
        self.speed = 1.0
        self.wobble = 0.6
        self.pops = 0.6
        self.look = (0.0, 0.0, 1.0)
        self.palette = ("#FF9A1F", "#E8262E", HEART_PINK)
        self.param = 0.0
        self._sheen = 0.8
        self._fizz = 0.5
        self._shape = 0.0
        self.w, self.h = 1400.0, 260.0
        self.reset()

    # ── configuration ─────────────────────────────────────────────────────
    def apply(self, cfg: dict, colors: list[str]) -> None:
        """Read the ``[bubbles]`` settings and the resolved gradient colors."""
        self.amount, self.size = cfg["bubbles.amount"], cfg["bubbles.size"]
        self.speed, self.wobble, self.pops = cfg["bubbles.float_speed"], cfg["bubbles.wobble"], cfg["bubbles.pops"]
        self._sheen, self._fizz = cfg["bubbles.sheen"], cfg["bubbles.fizz"]
        self._shape = POP_SHAPES[cfg["bubbles.pop_shape"]]
        self.param = PALETTES[cfg["bubbles.palette"]]
        self.look = (0.0, 0.0, 1.0 if cfg["layout.direction"] == "up" else 0.0)
        first, last = (colors[0], colors[-1]) if colors else ("#FF9A1F", "#E8262E")
        pop = first if cfg["bubbles.palette"] == "colors" else HEART_PINK
        self.palette = (first, last, pop)

    def resize(self, w: float, h: float) -> None:
        if w > 1 and h > 1:
            self.w, self.h = float(w), float(h)

    def reset(self) -> None:
        self.bubbles: list[Bubble] = []
        self.bed = self.energy = self.fizz = 0.0
        self.phase = 0.0
        self._rng = random.Random(1234)
        self._kick = Transient(floor=0.10)
        self._crack = Transient(floor=0.08)
        self._prev_kick = self._prev_crack = 0.0
        self._bands = BandSmoother(BAND_TAU)
        self._spawn_debt = 0.0
        self._jiggle = Jiggle()
        self._cols = [0.0] * COLUMNS

    # ── per-frame uniforms ────────────────────────────────────────────────
    def motion(self) -> tuple[float, float, float, float]:
        """x = phase, y = jiggle (signed squish), z = fizz amount, w = energy."""
        return (self.phase, self._jiggle.x, self.fizz, self.energy)

    def extra(self) -> tuple[float, float, float, float]:
        """x = rainbow sheen, y = pop shape (0 sparkles, 1 hearts), z = fizz setting,
        w = live particle slots."""
        return (self._sheen, self._shape, self._fizz, float(min(len(self.bubbles), PARTICLE_SLOTS)))

    @property
    def columns(self) -> list[float]:
        return self._cols

    def particles(self) -> list[tuple[float, float, float, float]]:
        out = []
        for b in self.bubbles[:PARTICLE_SLOTS]:
            state = 1.0 + b.pop if b.pop >= 0.0 else b.seed * 0.999
            out.append((b.x / self.w, b.y / self.h, b.r / self.h, state))
        return out

    # ── simulation ────────────────────────────────────────────────────────
    def _radius(self, big: bool, strength: float) -> float:
        """Bubble radius in px: independent of the window height, but never
        taller than a third of a short strip."""
        rng = self._rng
        scale = 0.55 + 0.9 * self.size
        r = (rng.uniform(17.0, 30.0) * (0.8 + 0.4 * strength) if big else rng.uniform(5.0, 13.0)) * scale
        return min(r, 0.33 * self.h)

    def _spawn(self, x: float, r: float, boost: float = 0.0) -> None:
        if len(self.bubbles) >= self._max_bubbles:
            return
        vy = self._rise(r) * (0.6 + boost)
        self.bubbles.append(Bubble(x, -r * 0.9, r, vy, self._rng))

    def _rise(self, r: float) -> float:
        """Terminal rise speed (px/s): bigger bubbles are more buoyant."""
        return self.speed * (22.0 + 6.0 * math.sqrt(r)) * (1.0 + 0.7 * self.energy)

    @property
    def _max_bubbles(self) -> int:
        return min(PARTICLE_SLOTS, round(6 + 18 * self.amount))

    def _pick_x(self, weights: list[float]) -> float:
        """A spawn position, likelier where the music is loudest."""
        rng = self._rng
        total = sum(weights)
        n = len(weights)
        if total < 1e-6:
            return rng.uniform(0.05, 0.95) * self.w
        pick = rng.random() * total
        for i, wgt in enumerate(weights):
            pick -= wgt
            if pick <= 0.0:
                return min(0.97, max(0.03, (i + rng.random()) / n)) * self.w
        return 0.5 * self.w

    def step(self, raw: list[float], dt: float) -> None:
        """Advance by *dt* seconds with the latest cava frame *raw* (0..1 bands)."""
        if dt <= 0:
            return
        rng = self._rng
        low, mid, high = (band_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))
        kick = self._kick.step(low, dt)
        crack = self._crack.step(high, dt)
        kick_hit = max(0.0, kick - self._prev_kick)
        crack_hit = max(0.0, crack - self._prev_crack)
        self._prev_kick, self._prev_crack = kick, crack
        self.bed = ema(self.bed, min(1.0, mid * 1.2), dt, BED_TAU)
        self.energy = ema(self.energy, min(1.0, 0.6 * self.bed + 0.8 * kick), dt, ENERGY_TAU)
        self.fizz = ema(self.fizz, min(1.0, 0.3 * self.bed + 0.9 * crack), dt, 0.15)
        self.phase += dt * (0.8 + 0.8 * self.energy)   # wobble and fizz liven up with the music
        if self.phase > 1000.0:
            self.phase -= 1000.0
        self._cols = columns_from_bands(self._bands.step(raw, dt))
        # Where bubbles are born: likelier where the music is, but spread over
        # the whole width (the mirrored spectrum alone would pile them up in
        # the middle, where the bass sits).
        mean = sum(self._cols) / len(self._cols)
        weights = [w + 0.6 * mean + 0.03 for w in self._cols]

        # ── kicks: blow a big bubble or two, and jiggle the whole field ───
        zeta = 0.45 - 0.33 * self.wobble          # 0.45 firm … 0.12 jelly
        if kick_hit > 0.25:
            self._jiggle.kick(2.2 * min(1.0, kick_hit) * (0.3 + self.wobble))
            for _ in range(1 + (kick_hit > 0.6)):
                self._spawn(self._pick_x(weights), self._radius(True, kick_hit), boost=0.8)
        self._jiggle.step(dt, JIGGLE_OMEGA, zeta)

        # ── the steady stream, born where the music is ────────────────────
        # Bubbles per second. Even the base trickle follows the music, so the
        # machine switches off in silence and the last bubbles float away.
        rate = self.amount * (0.5 * min(1.0, 8.0 * self.bed) + 3.0 * self.bed + 1.5 * self.energy)
        self._spawn_debt += rate * dt
        while self._spawn_debt >= 1.0:
            self._spawn_debt -= 1.0
            self._spawn(self._pick_x(weights), self._radius(False, 0.0))

        # ── snare / cymbal hits pop bubbles ────────────────────────────────
        if crack_hit > 0.3 and self.pops > 0.0:
            ripe = [b for b in self.bubbles if b.pop < 0.0 and b.age > MIN_AGE_TO_POP]
            count = min(len(ripe), int(crack_hit * (1 + 4 * self.pops) * rng.uniform(0.6, 1.2)))
            ripe.sort(key=lambda b: -(b.y + 2.0 * b.r))         # the high, big ones go first
            for b in ripe[:count]:
                if rng.random() < 0.35 + 0.6 * self.pops:
                    b.pop = 0.0

        # ── move, sway, age, pop ───────────────────────────────────────────
        alive = []
        for b in self.bubbles:
            b.age += dt
            if b.pop >= 0.0:
                b.pop += dt / POP_TIME
                if b.pop < 1.0:
                    alive.append(b)
                continue
            b.vy = ema(b.vy, self._rise(b.r), dt, 0.6)
            b.y += b.vy * dt
            b.x += math.sin(b.age * 2.1 * b.sway + b.seed * 6.283) * (6.0 + 0.6 * b.r) * dt
            # Pops as it touches the far edge (any later and the window edge
            # slices the top off), or simply of old age.
            if b.y > self.h - b.r * EDGE or b.age > b.life:
                b.pop = 0.0
            alive.append(b)
        self.bubbles = alive
        self._bump(dt)
        # The window's sides are soft walls: sway and bumps (which shove the
        # small, light bubbles hardest) never push a bubble half off-screen.
        for b in self.bubbles:
            if b.pop < 0.0:
                margin = min(b.r * EDGE, 0.5 * self.w)
                b.x = min(max(b.x, margin), self.w - margin)

    def _bump(self, dt: float) -> None:
        """Bubbles nudge each other apart instead of stacking up (soft, not
        rigid: a little overlap is fine and looks like real bubbles touching)."""
        live = [b for b in self.bubbles if b.pop < 0.0]
        push = min(1.0, 6.0 * dt)
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                reach = 0.9 * (a.r + b.r)
                d2 = dx * dx + dy * dy
                if d2 >= reach * reach:
                    continue
                d = math.sqrt(d2) or 1e-3
                shove = (reach - d) * 0.5 * push / d
                # Lighter (smaller) bubbles get pushed further.
                wa, wb = b.r / (a.r + b.r), a.r / (a.r + b.r)
                a.x -= dx * shove * wa * 2.0
                a.y -= dy * shove * wa * 2.0
                b.x += dx * shove * wb * 2.0
                b.y += dy * shove * wb * 2.0

    def settled(self) -> bool:
        return not self.bubbles and self.energy < 0.01
