"""The single source of truth for every user setting (Qt-free).

All three components read the same TOML file through this module, and the
``FIELDS`` schema below drives *everything*:

* defaults and validation (out-of-range numbers are clamped, junk falls back),
* the explanatory comments written into ``config.toml``,
* the slider ranges / segmented choices shown by the settings GUI.

Add a ``Field`` here and it appears everywhere — no second list to keep in sync.

Values are handled as a flat ``{"section.key": value}`` dict, which keeps diffing
(for hot-reload) and GUI bindings trivial.

CLI::

    python -m iron_will.config --init        # write defaults if missing
    python -m iron_will.config --dump        # print the default file
    python -m iron_will.config --get KEY     # print one (expanded) value
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .visualizer.modes import GPU_MODE_IDS, MODE_IDS

log = logging.getLogger("iron_will.config")

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_COLOR_STOPS = 6


class ConfigError(Exception):
    """The config file exists but is not valid TOML."""


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    default: Any
    help: str
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] | None = None

    @property
    def path(self) -> str:
        return f"{self.section}.{self.key}"

    def coerce(self, value: Any) -> Any:
        """Return a valid value for this field or raise ``ValueError``.

        The field's *default* decides the type, so the schema stays declarative.
        Note: ``bool`` is checked before ``int`` because bool subclasses int.
        """
        default = self.default
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in {"true", "false", "yes", "no", "on", "off", "1", "0"}:
                return value.lower() in {"true", "yes", "on", "1"}
            if isinstance(value, (int, float)):
                return bool(value)
            raise ValueError(f"{self.path}: expected true/false")

        if isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                raise ValueError(f"{self.path}: expected a number")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"{self.path}: expected a finite number")
            if self.min is not None:
                number = max(self.min, number)
            if self.max is not None:
                number = min(self.max, number)
            return int(round(number)) if isinstance(default, int) else round(number, 4)

        if isinstance(default, list):  # list of hex colors (gradient stops)
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"{self.path}: expected a list of colors")
            colors = [str(c).strip().upper() for c in value if HEX_COLOR.match(str(c).strip())]
            if not colors:
                raise ValueError(f"{self.path}: needs at least one #RRGGBB color")
            return colors[:MAX_COLOR_STOPS]

        if isinstance(default, str):
            if not isinstance(value, str):
                raise ValueError(f"{self.path}: expected text")
            if self.choices and value not in self.choices:
                raise ValueError(f"{self.path}: must be one of {', '.join(self.choices)}")
            return value

        raise TypeError(f"unsupported field type for {self.path}")


# ─── Schema ────────────────────────────────────────────────────────────────

SECTIONS: dict[str, str] = {
    "visualizer": "Visualizer · look",
    "motion": "Visualizer · motion & physics",
    "fire": "Visualizer · fire mode",
    "ferro": "Visualizer · ferrofluid mode",
    "bubbles": "Visualizer · bubbles mode",
    "layout": "Visualizer · placement on screen",
    "analysis": "Visualizer · audio analysis (cava)",
    "sounds": "Session sounds",
}

# Keys that moved between sections: new path → old path. Old configs are
# read from the old place until the next save writes the new one.
MOVED: dict[str, str] = {
    "layout.direction": "visualizer.direction",
}

FIELDS: tuple[Field, ...] = (
    # Look
    Field("visualizer", "mode", "bars", "Render style", choices=MODE_IDS),
    Field("visualizer", "bar_count", 64, "Number of bars / wave points", 8, 256),
    Field("visualizer", "spacing", 4, "Gap between bars in pixels", 0, 32),
    Field("visualizer", "roundness", 1.0, "Bar corner rounding: 0 = square, 1 = fully pill-shaped", 0.0, 1.0),
    Field("visualizer", "min_height", 2, "Resting bar height in pixels while audio is playing", 0, 20),
    Field("visualizer", "opacity", 0.9, "Overall opacity", 0.05, 1.0),
    Field("visualizer", "color_source", "accent", "Colors: follow the Plasma accent color, or use the custom list",
          choices=("accent", "custom")),
    Field("visualizer", "colors", ["#2EC4B6", "#3A86FF", "#8338EC"],
          f"Custom gradient stops (1 = solid color, up to {MAX_COLOR_STOPS})"),
    Field("visualizer", "gradient_direction", "vertical", "Gradient axis", choices=("horizontal", "vertical")),
    Field("visualizer", "peaks", True, "Draw falling peak caps above bars"),
    Field("visualizer", "fps", 60, "Frames per second (also cava's analysis rate)", 24, 165),
    # Fire mode
    Field("fire", "height", 0.9, "How tall the flames reach at full blast (share of the visualizer's height)", 0.1, 1.0),
    Field("fire", "intensity", 1.0, "How hard the music drives the fire", 0.3, 2.0),
    Field("fire", "sparks", 0.6, "Spark amount: embers thrown up by snare and cymbal hits (0 = none)", 0.0, 1.0),
    Field("fire", "speed", 1.0, "Flame speed: how fast the flames churn (the music speeds them up further)", 0.3, 2.5),
    Field("fire", "glow", 0.6, "Glow: firelight thrown onto the wallpaper around the flames, and core bloom (0 = none)", 0.0, 1.0),
    Field("fire", "reaction", 0.5, "How fast the fire catches and dies down: 0 = slow, heavy burn, 1 = snappy flare-ups", 0.0, 1.0),
    Field("fire", "translucency", 0.6, "How see-through the flames are: 0 = solid, 1 = ghostly (hot cores stay bright)", 0.0, 1.0),
    Field("fire", "palette", "colors", "Flame colors: your gradient colors, or natural fire",
          choices=("colors", "natural")),
    # Ferrofluid mode
    Field("ferro", "height", 0.85, "How tall the spikes reach at full blast (share of the visualizer's height)", 0.1, 1.0),
    Field("ferro", "intensity", 1.0, "How hard the music pulls on the liquid", 0.3, 2.0),
    Field("ferro", "sharpness", 0.6, "Spike shape: 0 = soft rounded cones, 1 = needle-sharp", 0.0, 1.0),
    Field("ferro", "density", 0.5, "How many spikes stand along the width: 0 = a few big ones, 1 = a dense forest", 0.0, 1.0),
    Field("ferro", "wobble", 0.6, "Liquid jiggle after each hit: 0 = stiff, 1 = very wobbly", 0.0, 1.0),
    Field("ferro", "reaction", 0.5, "How fast the spikes rise and fall: 0 = slow and heavy, 1 = snappy", 0.0, 1.0),
    Field("ferro", "rim", 0.7, "Colored rim light and backlight; keeps the black liquid visible on dark wallpapers", 0.0, 1.0),
    Field("ferro", "gloss", 0.8, "Strength of the studio-light reflections on the liquid", 0.0, 1.0),
    Field("ferro", "palette", "colors", "Rim light colors: your gradient colors, or neutral chrome",
          choices=("colors", "chrome")),
    # Bubbles mode
    Field("bubbles", "amount", 0.6, "How many bubbles float at once, and how fast new ones are blown", 0.0, 1.0),
    Field("bubbles", "size", 0.5, "Bubble size: 0 = tiny, 1 = big and round", 0.0, 1.0),
    Field("bubbles", "float_speed", 1.0, "How fast the bubbles rise (the music speeds them up further)", 0.3, 2.5),
    Field("bubbles", "wobble", 0.6, "How much the bubbles squish and jiggle on each kick: 0 = firm, 1 = jelly", 0.0, 1.0),
    Field("bubbles", "pops", 0.6, "How eagerly snare and cymbal hits pop bubbles (0 = they only pop at the top)", 0.0, 1.0),
    Field("bubbles", "sheen", 0.8, "Rainbow soap-film shimmer on each bubble (0 = clear glass)", 0.0, 1.0),
    Field("bubbles", "fizz", 0.5, "Tiny background bubbles that fizz up with the cymbals (0 = none)", 0.0, 1.0),
    Field("bubbles", "palette", "iridescent", "Bubble colors: rainbow soap film, soft pastels, or your gradient colors",
          choices=("iridescent", "pastel", "colors")),
    Field("bubbles", "pop_shape", "sparkles", "What a popping bubble leaves behind: little sparkles or hearts",
          choices=("sparkles", "hearts")),
    # Motion
    Field("motion", "attack_ms", 35, "Rise time constant in ms (lower = punchier)", 0, 500),
    Field("motion", "decay_ms", 220, "Fall time constant in ms (higher = smoother)", 10, 2000),
    Field("motion", "peak_hold_ms", 400, "How long a peak cap hangs before falling", 0, 3000),
    Field("motion", "peak_gravity", 2.5, "Peak cap fall acceleration (bar-heights per second²)", 0.1, 20.0),
    Field("motion", "idle_fade", True, "Fade the visualizer out when audio goes silent"),
    Field("motion", "idle_timeout", 4.0, "Seconds of silence before fading out", 0.5, 60.0),
    # Layout
    Field("layout", "anchor", "bottom", "Screen edge to attach to", choices=("bottom", "top")),
    Field("layout", "direction", "up", "Which way bars and flames grow", choices=("up", "down")),
    Field("layout", "align", "center", "Horizontal alignment", choices=("left", "center", "right", "stretch")),
    Field("layout", "width", 960, "Width in logical pixels (ignored when align = stretch)", 50, 7680),
    Field("layout", "height", 90, "Height in logical pixels", 16, 2160),
    Field("layout", "full_height", False,
          "Span the whole screen height (minus panels and margin_y), ignoring height. Gives fire mode headroom "
          "so tall flames, glow and embers never hit the window's edge"),
    Field("layout", "margin_x", 0, "Horizontal offset: from the aligned edge, or shift when centered", -4000, 4000),
    Field("layout", "margin_y", 0, "Distance from the anchored edge (or from the panel, see respect_panels)", 0, 4000),
    Field("layout", "layer", "bottom", "Stacking layer: bottom = above wallpaper, below windows",
          choices=("background", "bottom", "top")),
    Field("layout", "respect_panels", True, "Sit above panels instead of behind them (Wayland: exclusive zones)"),
    # Analysis
    Field("analysis", "input", "auto",
          "Audio capture backend; auto tries PipeWire, then PulseAudio (works via pipewire-pulse)",
          choices=("auto", "pipewire", "pulse")),
    Field("analysis", "sensitivity", 100, "Sensitivity in percent", 10, 500),
    Field("analysis", "autosens", True, "Let cava auto-adjust sensitivity to the volume"),
    Field("analysis", "low_cutoff", 50, "Lowest analysed frequency in Hz", 20, 1000),
    Field("analysis", "high_cutoff", 12000, "Highest analysed frequency in Hz", 2000, 20000),
    Field("analysis", "noise_reduction", 20, "cava's own smoothing, 0–100 (our physics does the rest)", 0, 100),
    # Session sounds
    Field("sounds", "directory", "~/Music/login_sounds", "Folder with .mp3 .wav .ogg .flac .opus files (searched recursively)"),
    Field("sounds", "on_login", True, "Play when the session starts"),
    Field("sounds", "on_resume", True, "Play after waking from suspend"),
    Field("sounds", "on_unlock", True, "Play after unlocking the screen"),
    Field("sounds", "login_delay", 3.0, "Seconds to wait after login", 0.0, 30.0),
    Field("sounds", "resume_delay", 2.5, "Seconds to wait after resume (audio devices re-initialising)", 0.0, 30.0),
    Field("sounds", "unlock_delay", 0.5, "Seconds to wait after unlock", 0.0, 30.0),
    Field("sounds", "cooldown", 30, "Minimum seconds between two sounds (stops resume + unlock double-plays)", 0, 600),
    Field("sounds", "volume", 0.8, "Playback volume", 0.0, 1.0),
    Field("sounds", "backend", "auto", "Audio player to use", choices=("auto", "pw-play", "paplay", "ffplay", "mpv")),
    Field("sounds", "avoid_repeat", True, "Never play the same track twice in a row"),
    Field("sounds", "notify", True, "Show a notification with a Stop button while a session sound plays"),
)

FIELD_MAP: dict[str, Field] = {f.path: f for f in FIELDS}


# ─── Load / save ───────────────────────────────────────────────────────────

def defaults() -> dict[str, Any]:
    return {f.path: (list(f.default) if isinstance(f.default, list) else f.default) for f in FIELDS}


def loads(text: str) -> dict[str, Any]:
    """Parse TOML text into a complete, validated flat dict.

    Missing/unknown keys are ignored; invalid values fall back to defaults with
    a warning. Raises ``ConfigError`` only when the TOML itself is malformed.
    """
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(str(exc)) from exc

    values = defaults()
    for field in FIELDS:
        section = data.get(field.section)
        if not isinstance(section, dict) or field.key not in section:
            section = _moved_from(data, field.path)
            if section is None:
                continue
        try:
            values[field.path] = field.coerce(section[field.key])
        except (ValueError, TypeError) as exc:
            log.warning("%s — using default %r", exc, field.default)
    return values


def _moved_from(data: dict, path: str) -> dict | None:
    """The old section still holding a key that has since moved (see MOVED),
    so configs written by older versions keep their setting."""
    old = MOVED.get(path)
    if old is None:
        return None
    sec, key = old.split(".", 1)
    section = data.get(sec)
    return {path.split(".", 1)[1]: section[key]} if isinstance(section, dict) and key in section else None


def load(path: Path | None = None, *, fallback: bool = False) -> dict[str, Any]:
    """Load the config file. A missing file yields defaults.

    With ``fallback=True`` a malformed file also yields defaults (logged)
    instead of raising — what the long-running daemon wants.
    """
    path = Path(path or paths.CONFIG_PATH)
    try:
        return loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defaults()
    except ConfigError as exc:
        if not fallback:
            raise
        log.error("%s is not valid TOML (%s) — using defaults", path, exc)
        return defaults()


def _fmt_number(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else repr(round(float(n), 4))


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(round(value, 4))
        return text if any(c in text for c in ".en") else text + ".0"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(str(v)) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)  # JSON string escapes are valid TOML


def _hint(field: Field) -> str:
    if field.choices:
        return " — " + " | ".join(field.choices)
    if field.min is not None and field.max is not None:
        return f" — {_fmt_number(field.min)} … {_fmt_number(field.max)}"
    return ""


def dumps(values: dict[str, Any]) -> str:
    """Serialise to commented TOML (comments generated from the schema)."""
    out = [
        "# Iron Will — desktop audio toolkit configuration",
        "# Edit by hand or with `iron-will-settings`. Changes apply live.",
        "# Invalid values fall back to their defaults; unknown keys are ignored.",
    ]
    for section, title in SECTIONS.items():
        out += ["", f"# ── {title} " + "─" * max(4, 60 - len(title)), f"[{section}]"]
        for field in FIELDS:
            if field.section == section:
                out.append(f"# {field.help}{_hint(field)}")
                out.append(f"{field.key} = {_toml_value(values.get(field.path, field.default))}")
    return "\n".join(out) + "\n"


def save(values: dict[str, Any], path: Path | None = None) -> str:
    """Atomically write the config (temp file + rename, so readers never see a
    half-written file). Returns the text written."""
    path = Path(path or paths.CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(values)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return text


def ensure_exists(path: Path | None = None) -> Path:
    path = Path(path or paths.CONFIG_PATH)
    if not path.exists():
        save(defaults(), path)
        log.info("wrote default config to %s", path)
    return path


# ─── Derived values shared by several components ───────────────────────────

GPU_ANALYSIS_BANDS = 32  # cava bands in GPU modes (the analyzers fold them into 16 columns)


def cava_bar_count(values: dict[str, Any]) -> int:
    """How many bands cava must compute. Mirror mode shows every band twice
    (low frequencies in the middle), so it only needs half."""
    mode = values["visualizer.mode"]
    if mode in GPU_MODE_IDS:
        return GPU_ANALYSIS_BANDS  # shaders read 16 columns; bar_count doesn't apply
    n = values["visualizer.bar_count"]
    return math.ceil(n / 2) if mode == "mirror" else n


CAVA_KEYS = frozenset({"visualizer.bar_count", "visualizer.mode", "visualizer.fps"}
                      | {f.path for f in FIELDS if f.section == "analysis"})


def _main() -> int:
    parser = argparse.ArgumentParser(prog="python -m iron_will.config", description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="write the default config if missing")
    group.add_argument("--dump", action="store_true", help="print the default config")
    group.add_argument("--path", action="store_true", help="print the config path")
    group.add_argument("--get", metavar="KEY", help="print one value (paths are expanded)")
    args = parser.parse_args()
    if args.init:
        print(ensure_exists())
    elif args.dump:
        print(dumps(defaults()), end="")
    elif args.path:
        print(paths.CONFIG_PATH)
    else:
        if args.get not in FIELD_MAP:
            parser.error(f"unknown key {args.get!r}")
        value = load(fallback=True)[args.get]
        print(paths.expand(value) if args.get == "sounds.directory" else value)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
