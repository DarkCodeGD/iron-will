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

    @property
    def icon_path(self) -> Path:
        return ICON_DIR / self.icon


MODES: tuple[RenderMode, ...] = (
    RenderMode("bars", "Bars", "Classic spectrum bars, bass on the left", "bars.svg"),
    RenderMode("mirror", "Mirror", "Spectrum bars mirrored, bass in the middle", "mirror.svg"),
    RenderMode("wave", "Wave", "A smooth line through every band", "wave.svg"),
    RenderMode("fire", "Fire",
               "GPU flames: every hit ignites the fire, guitars feed it, cymbals throw sparks", "fire.svg"),
)

MODE_IDS: tuple[str, ...] = tuple(m.id for m in MODES)
