"""Run the visualizer on the GPU the user picked, and prove it.

The setting ``visualizer.gpu`` is integrated | dedicated | plugged_in. A
process can't move to another GPU once it has a graphics context, so a
change means a relaunch: the visualizer quits cleanly (cava stopped, KWin
script unloaded) and ``exec``s itself again, keeping its PID, so systemd
doesn't notice. The flow::

    choose()            before QGuiApplication: read the setting, pick a GPU,
                        set the PRIME offload variables (gpus.apply_env)
    GpuSupervisor       after the window is up:
      ├─ first frame ──▶ read GL_RENDERER: which GPU *really* draws? → gpu.json + log
      ├─ setting changed / AC plugged or unplugged (plugged_in) ──▶ relaunch
      └─ app.exec() returns ──▶ main() calls relaunch_if_requested()

Safety net: the dedicated GPU is never allowed to take the visualizer down.

* Before starting on it we drop a marker (``gpu-attempt``), removed once a
  frame has been drawn, after 15 s alive, or on a clean exit. If the marker
  is still there on the next start, the last attempt crashed (systemd
  restarted us), so this start goes back to integrated.
* If the driver hands us a software rasterizer (llvmpipe) instead, same.
* Either way ``gpu-failed`` records why. It holds until the setting changes
  (= the user asks to retry) or the session ends: both markers live in
  $XDG_RUNTIME_DIR, so a driver update plus a re-login retries by itself.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QOpenGLContext

from .. import config, gpus, paths

log = logging.getLogger("iron_will.visualizer.gpu")

GL_RENDERER = 0x1F01
SETTLE_MS = 15_000          # alive this long on the dGPU = it works, even if no frame came yet
AC_POLL_MS = 2_500          # plugged_in: how often to look at the power supply (a few sysfs reads)
AC_STABLE_POLLS = 2         # same new reading twice in a row (~2.5–5 s) before we relaunch


def _attempt_file():
    return paths.runtime_dir() / "gpu-attempt"


def _failed_file():
    return paths.runtime_dir() / "gpu-failed"


def status_file():
    """What the running visualizer draws on; read by the settings app."""
    return paths.runtime_dir() / "gpu.json"


def _remove(path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@dataclass
class Selection:
    mode: str                       # the setting, as read at startup
    gpus: list[gpus.Gpu]
    target: gpus.Gpu | None         # the GPU we offloaded to; None = the desktop's own
    fallback: str | None = None     # why we're on integrated although the setting says otherwise


def choose() -> Selection:
    """Pick the GPU for this run and set the environment. Call before QGuiApplication."""
    mode = config.load(fallback=True).get("visualizer.gpu", "integrated")
    found = gpus.detect() if mode != "integrated" else []
    dgpu = gpus.dedicated(found)

    if _attempt_file().exists():
        name = _attempt_file().read_text().strip() or "the dedicated GPU"
        _failed_file().write_text(f"The visualizer stopped while starting on {name}.")
        _remove(_attempt_file())
    failed = _failed_file().read_text().strip() if _failed_file().exists() else None

    target = gpus.gpu_for(mode, found, gpus.on_ac_power())
    fallback = None
    if target is not None and failed:
        target, fallback = None, failed
        log.warning("not using %s: %s Using the integrated GPU; pick it again in Settings to retry.",
                    dgpu.name, failed)
    elif mode != "integrated" and dgpu is None:
        fallback = "No dedicated GPU found."

    if target is not None:
        _attempt_file().write_text(target.name)
    gpus.apply_env(target)
    return Selection(mode, found, target, fallback)


class GpuSupervisor(QObject):
    """Verifies the renderer, publishes gpu.json and relaunches when the choice changes."""

    _renderer_found = Signal(str)   # emitted on the render thread, handled on ours

    def __init__(self, selection: Selection, window, store, parent=None):
        super().__init__(parent)
        self._sel = selection
        self._window = window
        self._store = store
        self.renderer: str | None = None
        self.relaunch_requested = False
        self._ac = gpus.on_ac_power()
        self._ac_streak = 0

        self._renderer_found.connect(self._on_renderer)
        # Must run on the render thread, where the GL context is current.
        window.sceneGraphInitialized.connect(self._read_renderer, Qt.ConnectionType.DirectConnection)
        store.changed.connect(self._on_settings_changed)
        QGuiApplication.instance().aboutToQuit.connect(self._on_quit)

        self._ac_timer = QTimer(self, interval=AC_POLL_MS)
        self._ac_timer.timeout.connect(self._poll_ac)
        self._update_ac_polling(selection.mode)
        if selection.target is not None:
            QTimer.singleShot(SETTLE_MS, self, lambda: _remove(_attempt_file()))
        self._write_status()

    # ── which GPU really draws ─────────────────────────────────────────────
    def _read_renderer(self) -> None:
        ctx = QOpenGLContext.currentContext()
        if ctx is not None:
            raw = ctx.functions().glGetString(GL_RENDERER) or "unknown"
        else:   # Vulkan & co. (not used on Linux today, but don't lie)
            raw = f"unknown ({self._window.rendererInterface().graphicsApi().name})"
        self._renderer_found.emit(str(raw))

    def _on_renderer(self, raw: str) -> None:
        self.renderer = raw
        target = self._sel.target
        if target is not None and gpus.is_software(raw):
            reason = f"{target.name} gave the visualizer a software renderer ({gpus.pretty_renderer(raw)})."
            log.warning("%s Falling back to the integrated GPU.", reason)
            _failed_file().write_text(reason)
            self._relaunch()
            return
        _remove(_attempt_file())
        log.info("rendering on %s%s", gpus.pretty_renderer(raw),
                 " (dedicated GPU)" if target is not None else "")
        self._write_status()

    def _write_status(self) -> None:
        status = {
            "pid": os.getpid(),
            "mode": self._sel.mode,
            "dedicated": target.name if (target := self._sel.target) else None,
            "renderer": gpus.pretty_renderer(self.renderer) if self.renderer else None,
            "fallback": self._sel.fallback,
        }
        tmp = status_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(status))
        tmp.replace(status_file())  # atomic: the settings app never reads half a file

    # ── when to move ───────────────────────────────────────────────────────
    def _wanted(self, mode: str, ac: bool) -> gpus.Gpu | None:
        if not self._sel.gpus and mode != "integrated":
            self._sel.gpus = gpus.detect()     # started on integrated, never looked
        return gpus.gpu_for(mode, self._sel.gpus, ac)

    def _on_settings_changed(self, keys: set) -> None:
        if "visualizer.gpu" not in keys:
            return
        mode = self._store.values()["visualizer.gpu"]
        _remove(_failed_file())                # a new choice is a new chance (after a
        self._update_ac_polling(mode)          # failure target is None, so it differs)
        if self._wanted(mode, self._ac) != self._sel.target:
            log.info("GPU setting changed to %s — relaunching", mode)
            self._relaunch()
        else:                                  # e.g. dedicated → plugged_in while plugged in
            self._sel.mode = mode
            self._write_status()

    def _update_ac_polling(self, mode: str) -> None:
        if mode == "plugged_in":
            self._ac = gpus.on_ac_power()
            self._ac_streak = 0
            self._ac_timer.start()
        else:
            self._ac_timer.stop()

    def _poll_ac(self) -> None:
        ac = gpus.on_ac_power()
        if ac == self._ac:
            self._ac_streak = 0
            return
        # Debounce: a loose plug or a dock reconnecting shouldn't relaunch twice.
        self._ac_streak += 1
        if self._ac_streak < AC_STABLE_POLLS:
            return
        self._ac, self._ac_streak = ac, 0
        if _failed_file().exists():
            return                             # the dGPU already failed this session
        if self._wanted("plugged_in", ac) != self._sel.target:
            log.info("%s — relaunching on the %s GPU", "plugged in" if ac else "on battery",
                     "dedicated" if ac else "integrated")
            self._relaunch()

    # ── relaunching ────────────────────────────────────────────────────────
    def _relaunch(self) -> None:
        if not self.relaunch_requested:
            self.relaunch_requested = True
            QGuiApplication.quit()             # aboutToQuit stops cava and the KWin script

    def _on_quit(self) -> None:
        _remove(_attempt_file())               # a clean exit is not a crash
        _remove(status_file())                 # nobody is drawing any more

    def relaunch_if_requested(self, lock_fd: int | None) -> None:
        """Call after app.exec() returns. Replaces this process; same PID."""
        if not self.relaunch_requested:
            return
        _remove(status_file())
        if lock_fd is not None:
            os.close(lock_fd)                  # the new image takes the lock again
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, sys.orig_argv)
