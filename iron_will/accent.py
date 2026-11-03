"""Read the Plasma accent color from ``kdeglobals`` (Qt-free).

Plasma stores it as ``[General] AccentColor=r,g,b`` (also when "accent from
wallpaper" is on). Older/default themes may lack it, so we fall back to the
color scheme's selection background, which is what the accent tints anyway.
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from . import paths


def _parse_ini(path: Path) -> dict[str, dict[str, str]]:
    # Hand-rolled on purpose: kdeglobals contains KDE-isms ([$e] suffixes,
    # duplicate keys) that make configparser throw.
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            current[key.split("[", 1)[0].strip()] = value.strip()
    return sections


def _rgb_to_hex(value: str) -> str | None:
    try:
        parts = [int(p) for p in value.split(",")[:3]]
    except ValueError:
        return None
    if len(parts) != 3 or not all(0 <= p <= 255 for p in parts):
        return None
    return "#{:02X}{:02X}{:02X}".format(*parts)


def read_accent(path: Path = paths.KDEGLOBALS) -> str | None:
    """Return the accent as ``#RRGGBB`` or ``None`` if unavailable."""
    try:
        ini = _parse_ini(path)
    except OSError:
        return None
    for section, key in (("General", "AccentColor"), ("Colors:Selection", "BackgroundNormal")):
        value = ini.get(section, {}).get(key)
        if value and (color := _rgb_to_hex(value)):
            return color
    return None


def _adjust_lightness(hex_color: str, delta: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = min(1.0, max(0.0, l + delta))
    return "#{:02X}{:02X}{:02X}".format(*(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s)))


def accent_palette(hex_color: str) -> list[str]:
    """A tasteful 3-stop ramp around the accent: deeper → accent → lighter."""
    return [_adjust_lightness(hex_color, -0.12), hex_color, _adjust_lightness(hex_color, 0.18)]
