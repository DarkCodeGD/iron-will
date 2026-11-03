"""Genre presets: motion physics + audio analysis tuned per music style (Qt-free).

Presets only touch the *feel* keys (how bars rise/fall and which frequencies
are analysed) — never colors or layout, which stay the user's own. Every
preset defines the same keys, so "which preset is active?" is a simple exact
match; tweak any slider afterwards and the UI shows "Custom".

Rough tuning logic
------------------
* attack  — how fast a bar jumps to a hit. Drums want ~10 ms.
* decay   — how fast it falls. Short for fast drumming (each kick stays
  distinct), long for sustained 808s or ambient swells.
* peak hold / gravity — how long caps hang and how hard they drop.
* cutoffs — the analysed band. Bars are spread over this range, so a
  narrow low range (phonk) gives the bass more bars.
* noise_reduction — cava's pre-smoothing: low = more detail, high = calmer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config
from .visualizer.demo import DemoStyle


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    tagline: str
    icon: str
    tuning: tuple[int, int, int, float, int, int, int, int]
    demo: DemoStyle = field(default_factory=DemoStyle)

    # tuning order ↓ (kept compact so the table below reads like a mixing desk)
    KEYS = ("motion.attack_ms", "motion.decay_ms", "motion.peak_hold_ms", "motion.peak_gravity",
            "analysis.sensitivity", "analysis.low_cutoff", "analysis.high_cutoff", "analysis.noise_reduction")

    @property
    def values(self) -> dict[str, Any]:
        """Schema-coerced values, so comparisons with the live config are exact."""
        return {k: config.FIELD_MAP[k].coerce(v) for k, v in zip(self.KEYS, self.tuning)}

    @property
    def details(self) -> str:
        v = self.values
        high = v["analysis.high_cutoff"] / 1000
        return (f"↑ {v['motion.attack_ms']} ms · ↓ {v['motion.decay_ms']} ms · "
                f"{v['analysis.low_cutoff']} Hz – {high:g} kHz")


_DEFAULTS = config.defaults()

PRESETS: tuple[Preset, ...] = (
    #                                                       attack decay hold grav  sens low  high  nr
    Preset("balanced", "Balanced", "A versatile all-rounder for any playlist", "tune",
           tuple(_DEFAULTS[k] for k in Preset.KEYS), DemoStyle()),
    Preset("metal", "Metal & Rock", "Fast drums and double bass: every hit lands, cymbals and riffs shine", "bolt",
           (8, 110, 150, 7.0, 100, 40, 16000, 10),
           DemoStyle(bpm=170, kicks_per_beat=4, kick=0.45, kick_decay=0.05, snare=0.55, hats=0.6,
                     melody=0.5, melody_speed=1.6, noise=0.1)),
    Preset("phonk", "Phonk & Bass", "Heavy 808s that boom and linger, with extra bars for the low end", "speaker",
           (15, 320, 350, 2.5, 110, 25, 6000, 25),
           DemoStyle(bpm=130, kick=0.45, sub=0.9, sub_decay=0.55, snare=0.3, hats=0.25, melody=0.25, noise=0.04)),
    Preset("electronic", "Electronic", "Four-on-the-floor punch and crisp hi-hats", "equalizer",
           (18, 200, 300, 4.0, 100, 35, 14000, 18),
           DemoStyle(bpm=128, kick=0.6, sub=0.35, snare=0.25, hats=0.45, melody=0.35)),
    Preset("hiphop", "Hip-Hop & R&B", "Laid-back kicks and snares, sub-bass, vocal mids", "mic",
           (25, 260, 400, 3.0, 105, 30, 9000, 22),
           DemoStyle(bpm=90, kick=0.55, sub=0.5, snare=0.5, hats=0.3, melody=0.3)),
    Preset("calm", "Calm & Ambient", "Gentle, floating motion for lo-fi, ambient and classical", "moon",
           (90, 650, 900, 1.0, 140, 50, 10000, 45),
           DemoStyle(bpm=0, melody=0.55, melody_speed=0.4, noise=0.02)),
    Preset("jazz", "Jazz & Acoustic", "Natural instruments with soft dynamics and detailed highs", "music",
           (40, 380, 550, 1.8, 120, 60, 14000, 30),
           DemoStyle(bpm=120, kick=0.2, snare=0.2, hats=0.35, melody=0.55, melody_speed=0.8, noise=0.05)),
)

BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}


def match(values: dict[str, Any]) -> Preset | None:
    """The preset whose feel keys all equal the current values, if any."""
    for preset in PRESETS:
        if all(values.get(k) == v for k, v in preset.values.items()):
            return preset
    return None


def demo_style_for(values: dict[str, Any]) -> DemoStyle:
    preset = match(values)
    return preset.demo if preset else DemoStyle()
