"""A synthetic, music-like spectrum for the settings preview (no cava needed).

Shape of real music: louder lows, a kick drum that thumps the bass bins at
~125 BPM, slow wandering "melody" bumps, and a little noise for life.
"""

from __future__ import annotations

import math
import random


class DemoSignal:
    BEAT_SECONDS = 0.48

    def __init__(self) -> None:
        self._t = 0.0
        self._kick = 0.0
        self._next_kick = 0.0
        self._rng = random.Random(7)

    def sample(self, n: int, dt: float) -> list[float]:
        self._t += dt
        self._next_kick -= dt
        if self._next_kick <= 0:
            self._kick = 1.0
            self._next_kick += self.BEAT_SECONDS
        self._kick *= math.exp(-dt / 0.12)

        t, kick, rnd = self._t, self._kick, self._rng.random
        out = []
        last = max(n - 1, 1)
        for i in range(n):
            f = i / last  # 0 = bass … 1 = treble
            tilt = 0.82 - 0.5 * f
            melody = 0.5 + 0.5 * math.sin(t * (1.3 + 2.1 * f) + i * 0.55) * math.cos(t * 0.7 + f * 5.0)
            value = tilt * (0.3 + 0.45 * melody) + kick * max(0.0, 1.0 - f * 3.0) * 0.5 + rnd() * 0.06
            out.append(min(1.0, max(0.0, value)))
        return out
