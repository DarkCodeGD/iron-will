"""Bar physics: asymmetric EMA smoothing + gravity-driven peak caps (Qt-free).

Analogy: each bar is a needle on a VU meter.

* **Attack / decay (asymmetric EMA).** Every frame the bar moves a fraction
  ``alpha`` of the way toward the target. Rising uses a short time constant
  (snappy hits), falling a long one (smooth glide). ``alpha = 1 - e^(-dt/tau)``
  makes it frame-rate independent: 60 fps and 144 fps look identical.
* **Peaks.** A cap is pushed up by its bar, *hangs* for ``hold`` seconds, then
  falls with constant acceleration (velocity grows each frame) — the same
  ``v += g·dt; y -= v·dt`` integration as a dropped ball.

Pure Python lists: ≤256 bars at ≤165 fps is ~40k float ops/s — numpy would
cost more in conversion overhead than it saves.
"""

from __future__ import annotations

import math


class BarPhysics:
    SETTLE_EPS = 0.002

    def __init__(self) -> None:
        self.values: list[float] = []
        self.peaks: list[float] = []
        self._peak_velocity: list[float] = []
        self._peak_hold: list[float] = []
        self.attack_s = 0.035
        self.decay_s = 0.22
        self.hold_s = 0.4
        self.gravity = 2.5

    def configure(self, attack_ms: float, decay_ms: float, hold_ms: float, gravity: float) -> None:
        self.attack_s = attack_ms / 1000
        self.decay_s = max(decay_ms, 1) / 1000
        self.hold_s = hold_ms / 1000
        self.gravity = gravity

    def resize(self, n: int) -> None:
        if n == len(self.values):
            return
        pad = max(0, n - len(self.values))
        self.values = self.values[:n] + [0.0] * pad
        self.peaks = self.peaks[:n] + [0.0] * pad
        self._peak_velocity = self._peak_velocity[:n] + [0.0] * pad
        self._peak_hold = self._peak_hold[:n] + [0.0] * pad

    def reset(self) -> None:
        """Drop every bar and cap to zero (stale state from before a suspend)."""
        n = len(self.values)
        self.values, self.peaks = [0.0] * n, [0.0] * n
        self._peak_velocity, self._peak_hold = [0.0] * n, [0.0] * n

    def step(self, targets: list[float], dt: float) -> None:
        n = len(self.values)
        up = 1.0 if self.attack_s <= 0 else 1.0 - math.exp(-dt / self.attack_s)
        down = 1.0 - math.exp(-dt / self.decay_s)
        values, peaks, vel, hold = self.values, self.peaks, self._peak_velocity, self._peak_hold
        for i in range(n):
            target = targets[i] if i < len(targets) else 0.0
            v = values[i]
            v += (target - v) * (up if target > v else down)
            values[i] = v
            if v >= peaks[i]:
                peaks[i], vel[i], hold[i] = v, 0.0, self.hold_s
            elif hold[i] > 0:
                hold[i] -= dt
            else:
                vel[i] += self.gravity * dt
                peaks[i] = max(v, peaks[i] - vel[i] * dt)

    def settled(self) -> bool:
        eps = self.SETTLE_EPS
        return all(v < eps for v in self.values) and all(p < eps for p in self.peaks)
