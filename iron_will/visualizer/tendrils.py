"""Void Tendrils mode: shadowy tentacles that writhe with the music (Qt-free).

Black, tapered tendrils rooted along the base edge reach up, writhe and
whip, edged with a thin bright rim and a glow that hugs them, and bleed
motes of *void essence*. This is deliberately not a fire: no noise, no
smoke, no sheets of flame, no sparks rising in straight lines. Every
tendril is a discrete object with a skeleton.

How a tendril moves: a curvature spine
--------------------------------------
Each tendril is a chain of ``SEGMENTS`` equal segments. Walking from the
root to the tip, the heading turns by the local *curvature*, the way a real
tentacle's shape comes from how much each part of it bends:

    κ(u) = writhe waves travelling along it (two sines, faster with the music)
         + a hook that tightens towards the tip (the curled-over tips)
         + lash waves: every kick sends a whip-crack up from the root

``u`` runs 0 → 1 from root to tip, and the waves grow towards the tip, so
the base stays planted while the end thrashes. The integrated curve gives
the S-shapes and hooks of the reference art, and moves like a living
thing rather than a wiggling line.

=================  ===========================  ===============================
group (spectrum)   in the mix                   becomes
=================  ===========================  ===============================
low   0 – 20 %     kick drum, bass              **lash**: a whip wave up every
                                                tendril, a surge in reach, a
                                                pulse of glow
mid  20 – 65 %     guitars, vocals, keys        **energy**: how fast and how
                                                wildly they writhe
high 70 – 100 %    snare crack, cymbals         **essence**: motes peel off
                                                the tips
per tendril        its slice of the spectrum    how far it reaches (bass in
                                                the middle, like other modes)
=================  ===========================  ===============================

Void essence motes are particles: they leave a tip along its heading, then
swirl (a smooth analytic curl field), drift and dissolve. About a third are
pulled back down towards the roots, as if the void wants them back.

Everything is simulated in pixels, so a tendril is as thick in a short strip
as on a full-screen window; only its reach scales with the window.

Data texture layout (``DataTexture``, read by ``shaders/tendrils.frag``)
-----------------------------------------------------------------------
Width ``TEX_W``, height ``1 + tendrils + mote rows``. Positions are window
fractions with headroom (``enc``: −0.25 … 1.25), y measured from the base.

* row 0, the index: tendril j's box at texels 2j (x min, B = layer) and
  2j+1 (x max, B = top y); mote row r's box at ``MOTE_INDEX + 2r``
  (x min, B = y min) and +1 (x max, B = y max). The shader culls with these,
  so pixels far from a tendril cost almost nothing.
* row 1 + j, tendril j (sorted back to front): point k at texels 2k
  (x, B = radius in ⅛ px) and 2k+1 (y); then one shading texel (R = lit
  side 0…1, G = glow 0…1).
* row 1 + tendrils + r: up to ``MOTES_PER_ROW`` motes, sorted by x, three
  texels each: (x, B = size in ⅛ px), (y, B = brightness), (heading:
  R = vx, G = vy, as 0…255 around 128).
"""

from __future__ import annotations

import math
import random
from math import cos, exp, sin

from .datatex import OPAQUE, quantize, word
from .dynamics import COLUMNS, HIGH, LOW, MID, BandSmoother, Spring, Transient, band_mean, columns_from_bands, ema

MAX_TENDRILS = 40       # the shader's loop bound
SEGMENTS = 16           # segments per spine (17 points): smooth curves, no visible kinks
MAX_MOTES = 64
MOTES_PER_ROW = 8       # small rows, so the per-row boxes cull well
MOTE_ROWS = MAX_MOTES // MOTES_PER_ROW
MOTE_INDEX = 2 * MAX_TENDRILS          # where row 0 keeps the mote-row boxes
TEX_W = MOTE_INDEX + 2 * MOTE_ROWS     # 80 texels

TWO_PI = 2.0 * math.pi
# Segment lengths as shares of the tendril (sum 1): 2.5× longer at the root than at the tip.
_raw = [1.0 - 0.6 * (k + 0.5) / SEGMENTS for k in range(SEGMENTS)]
SEG_WEIGHTS = [w / sum(_raw) for w in _raw]
SEG_END = [sum(SEG_WEIGHTS[:k + 1]) for k in range(SEGMENTS)]           # u at each segment's far end
SEG_MID = [e - w / 2 for e, w in zip(SEG_END, SEG_WEIGHTS)]             # u at each segment's middle
# Per-segment shape profiles (the same every frame, so computed once):
WAVE_GAIN = [(0.35 + 1.65 * u) * w for u, w in zip(SEG_MID, SEG_WEIGHTS)]  # writhe grows towards the tip
HOOK_PROFILE = None   # filled in below, once smooth() exists
TAPER = [(1.0 - e) ** 0.75 for e in SEG_END]   # holds its body, then whips down to a fine tip
LASH_SPEED = 2.3        # spine lengths per second: how fast a whip travels up
LASH_LIFE = 0.9         # s
LASH_DELAYS = (0.0, 0.05, 0.10)   # s: lashes reach the tendrils a little apart (three groups)
BAND_TAU = 0.08
ENERGY_TAU = 0.5
RADIUS_UNIT = 6.0       # texel B = radius × 6 (⅙ px steps, up to 42 px)

# Palette → (rim, glow near / essence, glow far), and the shader's param.
PALETTES = {
    "void": ("#EE8CFF", "#B44DFF", "#6A1BDB"),    # magenta-pink rim, violet glow fading to indigo
    "ember": ("#FFC46B", "#FF6A1A", "#E8262E"),   # far glow goes crimson, never a dim (brown) orange
}
PARAMS = {"void": 0.0, "ember": 1.0, "colors": 2.0}


def smooth(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


HOOK_PROFILE = [smooth(0.6, 1.0, u) ** 2 * w for u, w in zip(SEG_MID, SEG_WEIGHTS)]  # the curl, at the tip


def enc(v: float) -> int:
    """Window fraction (−0.25 … 1.25 headroom) → 16-bit."""
    return quantize((v + 0.25) / 1.5)


def byte(v: float) -> int:
    return 0 if v <= 0.0 else 255 if v >= 1.0 else int(v * 255.0 + 0.5)


def _lighten(hex_color: str, amount: float) -> str:
    """Mix a #RRGGBB color towards white (for a rim from the user's gradient)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return "#FFFFFF"
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)   # noqa: E731
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"


class Tendril:
    __slots__ = ("root", "lean", "hfac", "thick", "layer", "curl_dir", "curl", "light",
                 "k1", "k2", "w1", "w2", "p1", "p2", "p3", "a1", "a2", "delay", "lash_dir",
                 "reach", "points", "radii", "glow", "ph1", "ph2")

    def __init__(self, root: float, layer: float, rng: random.Random) -> None:
        self.root = root
        self.layer = layer                          # 0 = far back … 1 = front
        # The front rank is mostly tall S-curves (the look of the reference
        # art); short curly ones tangle at the roots.
        kind = rng.random() * (0.85 if layer > 0.5 else 1.0)
        if kind < 0.36:                             # tall, reaching
            self.hfac, self.curl = rng.uniform(0.72, 1.0), rng.uniform(0.3, 0.8)
        elif kind < 0.68:                           # medium
            self.hfac, self.curl = rng.uniform(0.38, 0.68), rng.uniform(0.4, 1.0)
        else:                                       # short and curly, tangled at the roots
            self.hfac, self.curl = rng.uniform(0.12, 0.32), rng.uniform(0.8, 1.4)
        if layer < 0.5:                             # the back rank stands taller, like a far wall of them
            self.hfac = min(1.0, self.hfac * 1.15 + 0.08)
        self.lean = rng.uniform(-0.2, 0.2)
        self.thick = rng.uniform(0.75, 1.25)
        self.curl_dir = rng.choice((-1.0, 1.0))
        self.light = rng.choice((0.15, 0.85)) + rng.uniform(-0.1, 0.1)
        self.k1, self.k2 = rng.uniform(0.55, 0.95), rng.uniform(1.1, 1.7)   # waves per length
        self.w1, self.w2 = rng.uniform(0.8, 1.25), rng.uniform(0.55, 0.95)  # wave speed factors
        self.p1, self.p2, self.p3 = (rng.uniform(0.0, TWO_PI) for _ in range(3))
        self.a1, self.a2 = rng.uniform(0.9, 1.6), rng.uniform(0.35, 0.8)    # wave strengths (rad): S-curves, not arches
        self.delay = rng.randrange(len(LASH_DELAYS))   # which lash group: they whip a little apart
        self.lash_dir = rng.choice((-1.0, 1.0))
        # Each segment's wave phase offset along the body (constant per tendril).
        self.ph1 = [TWO_PI * self.k1 * u + self.p1 for u in SEG_MID]
        self.ph2 = [TWO_PI * self.k2 * u + self.p2 for u in SEG_MID]
        self.reach = Spring()
        self.reach.x = 0.3 * self.hfac
        self.points: list[tuple[float, float]] = []
        self.radii: list[float] = []
        self.glow = 0.0


class Mote:
    __slots__ = ("x", "y", "vx", "vy", "age", "life", "size", "seed", "pull", "home")

    def __init__(self, x, y, vx, vy, size, life, seed, pull, home) -> None:
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.size, self.life, self.seed, self.pull, self.home = size, life, seed, pull, home
        self.age = 0.0


class TendrilAnalyzer:
    """Follows the GPU mode contract (see ``fire.py``) plus ``resize(w, h)``
    and ``texture()`` (its frame goes out through the shared DataTexture)."""

    def __init__(self) -> None:
        self.reach_setting = 0.85
        self.writhe = 1.0
        self.count = 0.5
        self.essence = 0.6
        self.glow_setting = 0.7
        self.lash = 0.6
        self.curl_setting = 0.6
        self.look = (0.0, 0.0, 1.0)
        self.palette = PALETTES["void"]
        self.param = 0.0
        self.w, self.h = 1400.0, 260.0
        self._layout_key = None
        self.reset()

    # ── configuration ─────────────────────────────────────────────────────
    def apply(self, cfg: dict, colors: list[str]) -> None:
        """Read the ``[tendrils]`` settings and the resolved gradient colors."""
        self.reach_setting, self.writhe = cfg["tendrils.reach"], cfg["tendrils.writhe"]
        self.count, self.essence = cfg["tendrils.count"], cfg["tendrils.essence"]
        self.glow_setting, self.lash = cfg["tendrils.glow"], cfg["tendrils.lash"]
        self.curl_setting = cfg["tendrils.curl"]
        palette = cfg["tendrils.palette"]
        self.param = PARAMS[palette]
        if palette == "colors" and colors:
            first, last = colors[0], colors[-1]
            self.palette = (_lighten(first, 0.6), first, last)
        else:
            self.palette = PALETTES.get(palette, PALETTES["void"])
        self.look = (0.0, 0.0, 1.0 if cfg["layout.direction"] == "up" else 0.0)
        self._grow()

    def resize(self, w: float, h: float) -> None:
        if w > 1 and h > 1 and (w, h) != (self.w, self.h):
            self.w, self.h = float(w), float(h)
            self._grow()

    def reset(self) -> None:
        self.phase = 0.0
        self.energy = self.bed = self.flash = self.crack_flash = 0.0
        self._kick = Transient(floor=0.10)
        self._crack = Transient(floor=0.08)
        self._prev_kick = self._prev_crack = 0.0
        self._bands = BandSmoother(BAND_TAU)
        self._cols = [0.0] * COLUMNS
        self._lashes: list[list[float]] = []      # [age, strength]
        self._motes: list[Mote] = []
        self._mote_debt = 0.0
        self._rng = random.Random(4242)
        self._layout_key = None
        self.tendrils: list[Tendril] = []
        self._grow()

    def _grow(self) -> None:
        """(Re)create the tendril set for this width and count. Deterministic,
        so a resize or a settings change doesn't reshuffle the whole forest."""
        n = max(6, min(MAX_TENDRILS, round((16 + 36 * self.count) * self.w / 1536.0)))
        key = (n, round(self.w))
        if key == self._layout_key:
            return
        self._layout_key = key
        rng = random.Random(9001 + n)
        front = max(3, round(n * 0.55))
        back = n - front
        tendrils = []
        for rank, size, offset in ((0, back, 0.5), (1, front, 0.0)):
            spacing = self.w / max(1, size)
            for i in range(size):
                x = (i + 0.5 * (1.0 - offset) + offset * rng.uniform(0.6, 1.4) + rng.uniform(-0.32, 0.32)) * spacing
                layer = rng.uniform(0.12, 0.35) if rank == 0 else rng.uniform(0.82, 1.0)
                tendrils.append(Tendril(min(self.w - 4.0, max(4.0, x)), layer, rng))
        tendrils.sort(key=lambda t: t.layer)       # drawn back to front
        self.tendrils = tendrils

    # ── per-frame uniforms ────────────────────────────────────────────────
    def motion(self) -> tuple[float, float, float, float]:
        """x = writhe phase, y = energy, z = kick flash, w = snare/cymbal flash."""
        return (self.phase, self.energy, self.flash, self.crack_flash)

    def extra(self) -> tuple[float, float, float, float]:
        """x = tendrils, y = mote rows in use, z = glow setting, w = essence setting."""
        rows = math.ceil(len(self._motes) / MOTES_PER_ROW)
        return (float(len(self.tendrils)), float(rows), self.glow_setting, self.essence)

    @property
    def columns(self) -> list[float]:
        return self._cols

    # ── simulation ────────────────────────────────────────────────────────
    def step(self, raw: list[float], dt: float) -> None:
        if dt <= 0:
            return
        low, mid, high = (band_mean(raw, s) if raw else 0.0 for s in (LOW, MID, HIGH))
        kick = self._kick.step(low, dt)
        crack = self._crack.step(high, dt)
        kick_hit = max(0.0, kick - self._prev_kick)
        crack_hit = max(0.0, crack - self._prev_crack)
        self._prev_kick, self._prev_crack = kick, crack

        self.bed = ema(self.bed, min(1.0, mid * 1.3), dt, 0.3)
        self.energy = ema(self.energy, min(1.0, 0.65 * self.bed + 0.6 * kick + 0.25 * high), dt, ENERGY_TAU)
        self.flash = max(self.flash * math.exp(-dt / 0.22), min(1.0, kick_hit * 1.4))
        self.crack_flash = max(self.crack_flash * math.exp(-dt / 0.15), min(1.0, crack_hit * 1.4))
        # Writhing speed is the heart of it: slow and lazy in quiet parts,
        # frantic when the song goes off.
        self.phase += dt * self.writhe * (0.45 + 2.6 * self.energy)
        if self.phase > 10_000.0:
            self.phase -= 10_000.0
        self._cols = columns_from_bands(self._bands.step(raw, dt))

        if kick_hit > 0.2 and self.lash > 0.0:
            self._lashes.append([0.0, min(1.0, kick_hit) * self.lash])
            self._lashes = self._lashes[-4:]
        for lash in self._lashes:
            lash[0] += dt
        self._lashes = [l for l in self._lashes if l[0] < LASH_LIFE]

        self._move_tendrils(dt, kick)
        self._move_motes(dt, crack_hit)

    def _level_at(self, x: float) -> float:
        """The (mirrored, bass in the middle) spectrum at window position x."""
        cols = self._cols
        f = min(0.999, max(0.0, x / self.w)) * (len(cols) - 1)
        i = int(f)
        return cols[i] + (cols[min(i + 1, len(cols) - 1)] - cols[i]) * (f - i)

    def _move_tendrils(self, dt: float, kick: float) -> None:
        omega = 8.5                                        # reach spring: quick, with a little overshoot
        full = self.reach_setting * self.h
        wild = 0.75 + 1.1 * self.energy                    # louder = wilder bends
        T = self.phase
        hook_gain = 14.0 * self.curl_setting
        # The kick whips, as a turn per segment, once per delay group (not per
        # tendril: identical maths, a fraction of the work).
        lash_turn = None
        if self._lashes:
            lashes = [(age, s * math.exp(-age * 3.2)) for age, s in self._lashes]
            lash_turn = [[6.5 * SEG_WEIGHTS[k] * sum(s * exp(-((SEG_MID[k] - (age - d) * LASH_SPEED) * 5.88) ** 2)
                                                     for age, s in lashes) for k in range(SEGMENTS)]
                         for d in LASH_DELAYS]
        for td in self.tendrils:
            lvl = self._level_at(td.root)
            target = td.hfac * (0.50 + 0.50 * min(1.0, 1.35 * lvl + 0.35 * kick + 0.2 * self.bed))
            reach = td.reach.step(target, dt, omega, 0.42, 0.45)
            td.glow = min(1.0, 0.35 + 0.9 * lvl + 0.6 * self.flash)
            length = max(4.0, reach * full)
            r0 = td.thick * min(26.0, max(2.6, 0.046 * full * td.hfac))   # a body with some heft…
            # Segments shorten towards the tip, where the curl bends hardest,
            # so even a tight hook stays smooth.
            theta = math.pi / 2.0 + td.lean + 0.22 * wild * math.sin(0.6 * T * td.w2 + td.p3)
            x, y = td.root, 0.0
            pts = [(x, y)]
            radii = [r0 + 0.55]
            t1, t2 = T * 2.2 * td.w1, -T * 1.7 * td.w2
            a1, a2 = td.a1 * wild, td.a2 * wild
            hook = td.curl_dir * td.curl * hook_gain
            whip = lash_turn[td.delay] if lash_turn else None
            ph1, ph2 = td.ph1, td.ph2
            for k in range(SEGMENTS):
                turn = WAVE_GAIN[k] * (a1 * sin(ph1[k] - t1) + a2 * sin(ph2[k] - t2)) + hook * HOOK_PROFILE[k]
                if whip:                                   # a kick's whip travelling up
                    turn += td.lash_dir * whip[k]
                theta += turn
                ds = length * SEG_WEIGHTS[k]
                x += cos(theta) * ds
                y += sin(theta) * ds
                pts.append((x, y))
                radii.append(r0 * TAPER[k] + 0.5)
            td.points, td.radii = pts, radii

    def _move_motes(self, dt: float, crack_hit: float) -> None:
        rng = self._rng
        if self.essence > 0.0 and self.tendrils:
            # Snare and cymbal hits tear essence off the tips; a trickle keeps
            # bleeding while the music is going.
            burst = int(crack_hit * (2 + 12 * self.essence)) if crack_hit > 0.25 else 0
            self._mote_debt += dt * self.essence * (1.0 + 11.0 * self.energy)
            count = burst + int(self._mote_debt)
            self._mote_debt -= int(self._mote_debt)
            for _ in range(min(count, MAX_MOTES - len(self._motes))):
                self._spawn_mote(rng, strong=burst > 0)
        T = self.phase
        alive = []
        for m in self._motes:
            m.age += dt
            if m.age > m.life:
                continue
            drag = math.exp(-dt * 1.4)
            m.vx *= drag
            m.vy *= drag
            # Swirl: a smooth, divergence-free curl field (no noise), slowly
            # turning, so motes curve and eddy instead of rising straight.
            sx = math.sin(m.y * 0.017 + T * 0.9 + m.seed * 6.0)
            sy = math.cos(m.x * 0.013 - T * 0.7 + m.seed * 4.0)
            m.vx += (55.0 * sx) * dt
            m.vy += (40.0 * sy + 14.0) * dt
            if m.pull and m.age > 0.45:          # the void wants it back
                hx, hy = m.home - m.x, -m.y
                d = math.hypot(hx, hy) or 1.0
                m.vx += hx / d * 120.0 * dt
                m.vy += hy / d * 120.0 * dt
                if m.y < 2.0:
                    continue
            m.x += m.vx * dt
            m.y += m.vy * dt
            if -40.0 < m.x < self.w + 40.0 and m.y < self.h * 1.2:
                alive.append(m)
        self._motes = alive

    def _spawn_mote(self, rng: random.Random, strong: bool) -> None:
        # From a tip, likelier from the long ones.
        weights = [max(1.0, t.points[-1][1]) if t.points else 0.0 for t in self.tendrils]
        pick = rng.random() * sum(weights)
        for td, wgt in zip(self.tendrils, weights):
            pick -= wgt
            if pick <= 0.0:
                break
        if not td.points:
            return
        (x0, y0), (x1, y1) = td.points[-2], td.points[-1]
        hx, hy = x1 - x0, y1 - y0
        d = math.hypot(hx, hy) or 1.0
        speed = rng.uniform(40.0, 110.0) * (1.4 if strong else 1.0)
        self._motes.append(Mote(
            x1 + rng.uniform(-3, 3), y1 + rng.uniform(-3, 3),
            hx / d * speed + rng.uniform(-25, 25), hy / d * speed + rng.uniform(5, 30),
            size=rng.uniform(0.8, 2.1) * (1.25 if strong else 1.0), life=rng.uniform(1.6, 3.8),
            seed=rng.random(), pull=rng.random() < 0.33, home=td.root))

    def settled(self) -> bool:
        return not self._motes and self.energy < 0.01

    # ── the frame for the shader ──────────────────────────────────────────
    def texture(self) -> tuple[list[int], int, int]:
        """(words, columns, rows) for the DataTexture (layout in the module docs)."""
        w, h = self.w, self.h
        tendrils = self.tendrils
        motes = sorted(self._motes, key=lambda m: m.x)
        mote_rows = math.ceil(len(motes) / MOTES_PER_ROW)
        rows = 1 + len(tendrils) + mote_rows
        index = [OPAQUE] * TEX_W
        sx, sy, Q = 1.0 / w, 1.0 / h, 65535.0 / 1.5
        body = []
        pad = [OPAQUE] * TEX_W
        for j, td in enumerate(tendrils):
            pts, radii = td.points, td.radii
            if not pts:
                body.extend(pad)
                continue
            r_max = radii[0]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            index[2 * j] = word(enc((min(xs) - r_max) / w), byte(td.layer))
            index[2 * j + 1] = word(enc((max(xs) + r_max) / w), byte((max(ys) + r_max) / h / 1.25 + 1 / 255))
            row = []
            for (x, y), r in zip(pts, radii):          # inlined word(enc(…)): the hot loop
                qx = int((x * sx + 0.25) * Q + 0.5)
                qx = 0 if qx < 0 else 65535 if qx > 65535 else qx
                qy = int((y * sy + 0.25) * Q + 0.5)
                qy = 0 if qy < 0 else 65535 if qy > 65535 else qy
                rb = int(r * RADIUS_UNIT + 0.5)
                row.append(OPAQUE | (rb if rb < 255 else 255) << 16 | (qx & 0xFF) << 8 | qx >> 8)
                row.append(OPAQUE | (qy & 0xFF) << 8 | qy >> 8)
            row.append(OPAQUE | byte(td.glow) << 8 | byte(td.light))
            body.extend(row + pad[len(row):])
        for r in range(mote_rows):
            chunk = motes[r * MOTES_PER_ROW:(r + 1) * MOTES_PER_ROW]
            pad_r = 6.0 * max(m.size for m in chunk) + 6.0
            index[MOTE_INDEX + 2 * r] = word(enc((chunk[0].x - pad_r - 30.0) / w),
                                             byte((min(m.y for m in chunk) - pad_r - 30.0) / h / 1.25))
            index[MOTE_INDEX + 2 * r + 1] = word(enc((chunk[-1].x + pad_r + 30.0) / w),
                                                 byte((max(m.y for m in chunk) + pad_r + 30.0) / h / 1.25 + 1 / 255))
            row = []
            for m in chunk:
                fade = min(1.0, m.age / 0.25) * (1.0 - smooth(0.55, 1.0, m.age / m.life))
                sp = math.hypot(m.vx, m.vy) or 1.0
                streak = min(1.0, sp / 140.0)
                vx, vy = m.vx / sp * streak, m.vy / sp * streak
                row.append(word(enc(m.x / w), min(255, int(m.size * (1.0 - 0.4 * m.age / m.life) * RADIUS_UNIT + 0.5))))
                row.append(word(enc(m.y / h), byte(fade)))
                row.append(OPAQUE | byte(0.5 + 0.5 * vy) << 8 | byte(0.5 + 0.5 * vx))
            body.extend(row + pad[len(row):])
        return index + body, TEX_W, rows
