"""Which GPUs does this machine have, and how do we send the visualizer to one? (Qt-free.)

Laptops with a second, *dedicated* GPU (NVIDIA Optimus, AMD hybrid graphics)
run the desktop on the integrated one. An app opts into the other one with a
few environment variables set before it starts (PRIME render offload). The
right set depends on the driver, so we ask the system instead of guessing:

1. **switcheroo-control** (``net.hadess.SwitcherooControl`` on the system
   bus) lists every GPU with its name, whether it's the default, whether it's
   discrete, and exactly the variables that select it. Plasma's own "Run
   using dedicated graphics card" menu entry uses the same service.
2. Without it, ``/sys/class/drm`` tells us the GPUs and their drivers, and we
   fill in the well-known variables ourselves (NVIDIA's proprietary driver,
   or Mesa's ``DRI_PRIME``).

Choosing is ``gpu_for(mode, gpus, on_ac)``; applying is ``apply_env``, which
must run before the process creates its first graphics context.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("iron_will.gpus")

MODES = ("integrated", "dedicated", "plugged_in")
# Remembers which variables *we* added, so a relaunch on another GPU can take
# them back out without touching anything the user set themselves.
APPLIED_ENV = "IRON_WILL_GPU_ENV"

DRM = Path("/sys/class/drm")
POWER_SUPPLY = Path("/sys/class/power_supply")
VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
NVIDIA_OFFLOAD = {
    "__NV_PRIME_RENDER_OFFLOAD": "1",          # EGL/GLX: render on the NVIDIA GPU
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",     # GLX (Xwayland / X11)
    "__VK_LAYER_NV_optimus": "NVIDIA_only",    # Vulkan
    "VK_LOADER_DRIVERS_SELECT": "*nvidia*",
}


@dataclass(frozen=True)
class Gpu:
    name: str
    discrete: bool
    default: bool                 # the one the desktop runs on
    env: dict[str, str] = field(default_factory=dict)


# ── detection ──────────────────────────────────────────────────────────────
def detect() -> list[Gpu]:
    """Every GPU we can find; empty if we can't tell."""
    return _from_switcheroo() or _from_sysfs()


def _from_switcheroo() -> list[Gpu]:
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        reply = bus.call_sync("net.hadess.SwitcherooControl", "/net/hadess/SwitcherooControl",
                              "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", ("net.hadess.SwitcherooControl", "GPUs")),
                              GLib.VariantType("(v)"), Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    except Exception as exc:          # no PyGObject, no system bus, service not running
        log.debug("switcheroo-control unavailable: %s", exc)
        return []
    gpus = []
    for entry in reply.unpack()[0]:
        flat = list(entry.get("Environment", []))
        gpus.append(Gpu(name=pretty_name(entry.get("Name", "GPU")), discrete=bool(entry.get("Discrete")),
                        default=bool(entry.get("Default")), env=dict(zip(flat[::2], flat[1::2]))))
    return gpus


def _from_sysfs() -> list[Gpu]:
    gpus = []
    for card in sorted(DRM.glob("card[0-9]*")):
        if "-" in card.name:          # connectors like card1-eDP-1
            continue
        dev = card / "device"
        try:
            vendor = (dev / "vendor").read_text().strip()
            driver = (dev / "driver").resolve().name
            default = (dev / "boot_vga").read_text().strip() == "1"
        except OSError:
            continue
        slot = dev.resolve().name                         # e.g. 0000:01:00.0
        env = dict(NVIDIA_OFFLOAD) if driver == "nvidia" else {"DRI_PRIME": "pci-" + re.sub(r"[:.]", "_", slot)}
        brand = VENDORS.get(vendor, "")
        gpus.append(Gpu(name=f"{brand} GPU".strip(), discrete=not default and brand != "Intel",
                        default=default, env=env))
    return gpus if len(gpus) > 1 else []


def pretty_name(raw: str) -> str:
    """'NVIDIA Corporation GA107M [GeForce RTX™ 3050 Mobile]' → 'NVIDIA GeForce RTX 3050 Mobile'."""
    raw = raw.replace("™", "").replace("®", "")
    vendor = raw.split()[0] if raw.split() else ""
    marketing = re.search(r"\[([^\]]+)\]", raw)
    if marketing:
        model = marketing.group(1).strip()
        return model if model.lower().startswith(vendor.lower()) else f"{vendor} {model}"
    return raw.replace(" Corporation", "").strip()


def pretty_renderer(raw: str) -> str:
    """GL_RENDERER → something a person reads.

    'NVIDIA GeForce RTX 3050 Laptop GPU/PCIe/SSE2' → 'NVIDIA GeForce RTX 3050 Laptop GPU',
    'Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)' → 'Intel Iris Xe Graphics'.
    """
    name = raw.split("/")[0]
    name = re.sub(r"\((R|TM)\)|[™®]", "", name)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)        # trailing '(TGL GT2)', '(LLVM 19.1.0, 256 bits)'
    name = re.sub(r"^Mesa\s+(?=\S)", "", name)
    return re.sub(r"\s+", " ", name).strip() or raw


def is_software(renderer: str) -> bool:
    """Did the driver give up and hand us a CPU rasterizer?"""
    return any(s in renderer.lower() for s in ("llvmpipe", "softpipe", "swrast", "software"))


def dedicated(gpus: list[Gpu]) -> Gpu | None:
    """The GPU worth offering: discrete, and not the one the desktop already runs on."""
    return next((g for g in gpus if g.discrete and not g.default), None)


def integrated(gpus: list[Gpu]) -> Gpu | None:
    return next((g for g in gpus if g.default), None)


# ── power ──────────────────────────────────────────────────────────────────
def on_ac_power() -> bool:
    """Plugged in? A machine without a battery (a desktop) always is."""
    mains, batteries = [], False
    for supply in POWER_SUPPLY.glob("*"):
        try:
            kind = (supply / "type").read_text().strip()
            if kind == "Mains":
                mains.append((supply / "online").read_text().strip() == "1")
            elif kind == "Battery":
                batteries = True
        except OSError:
            continue
    return any(mains) or not batteries


# ── choosing and applying ──────────────────────────────────────────────────
def wants_dedicated(mode: str, on_ac: bool) -> bool:
    return mode == "dedicated" or (mode == "plugged_in" and on_ac)


def gpu_for(mode: str, gpus: list[Gpu], on_ac: bool) -> Gpu | None:
    """The GPU to offload to, or None for the desktop's default one."""
    return dedicated(gpus) if wants_dedicated(mode, on_ac) else None


def apply_env(gpu: Gpu | None, environ=os.environ) -> None:
    """Point this process (and anything it execs) at *gpu* (None = default).

    Must run before the first graphics context exists; the driver loaders
    read these variables once, when they start.
    """
    for key in filter(None, environ.pop(APPLIED_ENV, "").split(",")):
        environ.pop(key, None)        # whatever a previous run of us added
    if gpu is None:
        return
    added = [k for k in gpu.env if k not in environ]
    environ.update(gpu.env)
    if added:
        environ[APPLIED_ENV] = ",".join(added)
