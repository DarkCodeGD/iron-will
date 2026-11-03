"""XDG-aware filesystem locations shared by every component (Qt-free)."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


CONFIG_HOME = _xdg("XDG_CONFIG_HOME", ".config")
CONFIG_DIR = CONFIG_HOME / "iron-will"
CONFIG_PATH = CONFIG_DIR / "config.toml"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "iron-will"
KDEGLOBALS = CONFIG_HOME / "kdeglobals"

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"


def runtime_dir() -> Path:
    """Per-user tmpfs directory (``$XDG_RUNTIME_DIR/iron-will``), created on demand.

    Lives in RAM, is private to the user (0700) and is wiped on logout — the
    right home for lock files, the generated cava config and logs.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/iron-will-{os.getuid()}"
    path = Path(base) / "iron-will"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def expand(path: str) -> Path:
    """Expand ``~`` and ``$VARS`` in a user-supplied path."""
    return Path(os.path.expandvars(os.path.expanduser(path)))
