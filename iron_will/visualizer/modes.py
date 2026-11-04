"""The render-mode registry: every visualizer Iron Will can draw.

One entry per mode. Everything else is derived from this list: the config
schema's ``visualizer.mode`` choices, the mode tiles in the settings app
(name, icon, tagline) and their order. Adding a visualizer means adding an
entry here, an SVG in ``assets/modes/`` and its renderer.

Kept free of Qt imports so ``config`` can use it in plain-Python contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "modes"


@dataclass(frozen=True)
class RenderMode:
    id: str          # config value (``visualizer.mode``)
    name: str        # tile label
    tagline: str     # one line shown under the tiles when selected
    icon: str        # SVG file in assets/modes/
    noun: str = "bars"   # what grows ("Which way the … grow")
    shader: str = ""     # analyzer modes: their own compiled fragment shader in visualizer/shaders/
                         # (the spectrum modes share SPECTRUM_SHADER instead, see below)

    @property
    def icon_path(self) -> Path:
        return ICON_DIR / self.icon


MODES: tuple[RenderMode, ...] = (
    RenderMode("bars", "Bars", "Classic spectrum bars, bass on the left", "bars.svg"),
    RenderMode("mirror", "Mirror", "Spectrum bars mirrored, bass in the middle", "mirror.svg"),
    RenderMode("wave", "Wave", "A smooth line through every band", "wave.svg", noun="wave"),
    RenderMode("fire", "Fire",
               "GPU flames: every hit ignites the fire, guitars feed it, cymbals throw sparks", "fire.svg",
               noun="flames", shader="fire.frag.qsb"),
    RenderMode("ferro", "Ferrofluid",
               "Glossy black magnetic liquid: the bass pulls it up into spikes that wobble back down",
               "ferro.svg", noun="spikes", shader="ferro.frag.qsb"),
    RenderMode("bubbles", "Bubbles",
               "Rainbow soap bubbles: kicks blow big ones, guitars keep them coming, snares pop them",
               "bubbles.svg", noun="bubbles", shader="bubbles.frag.qsb"),
    RenderMode("tendrils", "Void Tendrils",
               "Shadowy tendrils writhe with the music, whip on every kick and bleed void essence",
               "tendrils.svg", noun="tendrils", shader="tendrils.frag.qsb"),
)

MODE_IDS: tuple[str, ...] = tuple(m.id for m in MODES)
# Modes driven by their own analyzer and shader, fed 16 analysis bands.
GPU_MODE_IDS: frozenset[str] = frozenset(m.id for m in MODES if m.shader)
# Modes that draw the classic spectrum (one value per bar, bar_count bars).
# They render on the GPU too, all through one shader fed a data texture
# (visualizer/datatex.py); only a software scene graph paints them on the CPU.
SPECTRUM_MODE_IDS: frozenset[str] = frozenset(MODE_IDS) - GPU_MODE_IDS
SPECTRUM_SHADER = "spectrum.frag.qsb"
BY_ID: dict[str, RenderMode] = {m.id: m for m in MODES}
