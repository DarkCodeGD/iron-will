"""Synthesise a soft two-note chime so a fresh install works out of the box.

    python -m iron_will.dispatcher.chime OUT.wav

Additive synthesis: each note is a sine plus two quiet harmonics, shaped by a
fast attack / exponential decay envelope (like a struck bell), then the notes
are overlapped a perfect fifth apart. Pure stdlib — no numpy needed.
"""

from __future__ import annotations

import math
import struct
import sys
import wave

RATE = 44_100


def _note(freq: float, length: float, gain: float) -> list[float]:
    samples = []
    for i in range(int(RATE * length)):
        t = i / RATE
        envelope = min(1.0, t / 0.008) * math.exp(-t * 3.2)
        tone = (math.sin(2 * math.pi * freq * t)
                + 0.30 * math.sin(2 * math.pi * freq * 2 * t)
                + 0.08 * math.sin(2 * math.pi * freq * 3 * t))
        samples.append(gain * envelope * tone)
    return samples


def render(path: str) -> None:
    length = 1.6
    mix = [0.0] * int(RATE * length)
    for start, freq in ((0.0, 659.25), (0.16, 987.77)):  # E5 then B5
        offset = int(start * RATE)
        for i, s in enumerate(_note(freq, length - start, 0.32)):
            mix[offset + i] += s
    fade = int(0.05 * RATE)  # tail fade so it never clicks
    for i in range(fade):
        mix[-1 - i] *= i / fade
    frames = b"".join(struct.pack("<hh", v, v) for v in (int(max(-1.0, min(1.0, s)) * 32000) for s in mix))
    with wave.open(path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m iron_will.dispatcher.chime OUT.wav")
    render(sys.argv[1])
