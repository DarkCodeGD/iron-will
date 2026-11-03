"""A synthetic, music-like spectrum for the settings preview (no cava needed).

A tiny "drum machine + band" in spectrum space. A beat clock fires drum
envelopes; each one paints energy into the part of the spectrum where that
instrument lives:

    kick   ─ low bins, punchy      sub (808) ─ lowest bins, long boom
    snare  ─ mid bins, beats 2 & 4 hats/cymbals ─ high bins, off-beats
    melody ─ slow wandering bumps everywhere (riffs, pads, vocals)

A ``DemoStyle`` sets the tempo and how loud each part is, so every genre
preset previews with a fitting groove.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoStyle:
    bpm: float = 125.0          # 0 = no drums at all
    kicks_per_beat: int = 1     # 4 = sixteenth-note double bass
    kick: float = 0.5
    kick_decay: float = 0.12    # seconds
    sub: float = 0.0            # 808 / sub-bass weight
    sub_decay: float = 0.4
    snare: float = 0.2
    hats: float = 0.15
    melody: float = 0.45
    melody_speed: float = 1.0
    noise: float = 0.06


class DemoSignal:
    def __init__(self, style: DemoStyle | None = None) -> None:
        self.style = style or DemoStyle()
        self._t = 0.0
        self._beats = 0.0
        self._kick = self._sub = self._snare = self._hat = 0.0
        self._rng = random.Random(7)

    def _advance_drums(self, dt: float) -> None:
        s = self.style
        if s.bpm > 0:
            prev, self._beats = self._beats, self._beats + dt * s.bpm / 60.0

            def crossed(per_beat: float, offset: float = 0.0) -> bool:
                return math.floor((self._beats - offset) * per_beat) != math.floor((prev - offset) * per_beat)

            if crossed(s.kicks_per_beat):
                self._kick = 1.0
            if crossed(1):
                self._sub = 1.0
                if math.floor(self._beats) % 2 == 1:   # beats 2 and 4
                    self._snare = 1.0
            if crossed(1, offset=0.5):                  # off-beat eighths
                self._hat = 1.0
        self._kick *= math.exp(-dt / s.kick_decay)
        self._sub *= math.exp(-dt / s.sub_decay)
        self._snare *= math.exp(-dt / 0.09)
        self._hat *= math.exp(-dt / 0.05)

    def sample(self, n: int, dt: float) -> list[float]:
        s = self.style
        self._t += dt
        self._advance_drums(dt)
        t = self._t * s.melody_speed
        kick, sub, snare, hat = s.kick * self._kick, s.sub * self._sub, s.snare * self._snare, s.hats * self._hat
        rnd = self._rng.random
        out = []
        last = max(n - 1, 1)
        for i in range(n):
            f = i / last  # 0 = bass … 1 = treble
            melody = 0.5 + 0.5 * math.sin(t * (1.3 + 2.1 * f) + i * 0.55) * math.cos(t * 0.7 + f * 5.0)
            value = ((0.82 - 0.5 * f) * (0.22 + s.melody * melody)
                     + kick * max(0.0, 1.0 - f * 3.0)
                     + sub * max(0.0, 1.0 - f * 6.0)
                     + snare * math.exp(-((f - 0.42) / 0.15) ** 2)
                     + hat * max(0.0, (f - 0.55) / 0.45)
                     + rnd() * s.noise)
            out.append(min(1.0, max(0.0, value)))
        return out
