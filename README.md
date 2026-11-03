# Iron Will

A lightweight, modular desktop audio toolkit for **KDE Plasma 6** (Wayland first, X11 fallback):

- **Session sounds:** plays a random track from your library on **login**, **resume from suspend**, and **screen unlock**.
- **Desktop visualizer:** a click-through spectrum visualizer on the desktop layer, sitting right above your panel. It never steals focus and never covers windows.
- **Settings app:** a GUI for every setting. Changes auto-save, and the visualizer **updates live** as you drag sliders.

## Install

```bash
./install.sh --dry-run   # preview every step
./install.sh             # install (asks before using sudo for missing packages)
```

Everything goes into your home directory: `~/.local/share/iron-will`, `~/.local/bin`, `~/.config/iron-will`, and systemd **user** units. Root is only used, after asking, to install packages. If your sound folder is empty, the installer generates a soft chime so it works right away.

Uninstall with `./uninstall.sh` (keeps config) or `./uninstall.sh --purge`. Your sound folder is never touched.

### Dependency checklist

| Need | Fedora | Arch | Used for |
|---|---|---|---|
| Python ≥ 3.11 | `python3` | `python` | everything (`tomllib`) |
| PySide6 | `python3-pyside6` | `pyside6` | visualizer + settings GUI |
| LayerShellQt | `layer-shell-qt` | `layer-shell-qt` | Wayland desktop-layer placement |
| cava | `cava` | `cava` | real-time frequency analysis |
| pw-play | `pipewire-utils` | `pipewire` | session sound playback |
| wpctl | `wireplumber` | `wireplumber` | waiting for audio devices after resume |
| PyGObject | `python3-gobject` | `python-gobject` | D-Bus listener |
| setpriv *(optional)* | `util-linux` | `util-linux` | makes sure cava dies with the visualizer |
| paplay / ffplay / mpv *(optional)* | | | playback fallbacks |

The **System** page in the settings app shows this checklist live.

## Usage

| Command | What it does |
|---|---|
| `iron-will-settings` | open the settings app (also in the app menu as *Iron Will*) |
| `iron-will-audio --play` | play one random track now |
| `iron-will-audio --list` | list the tracks the daemon would use |
| `systemctl --user restart iron-will-visualizer` | restart the visualizer |
| `journalctl --user -u iron-will-visualizer -u iron-will-audio -f` | follow the logs |

Set `IRON_WILL_DEBUG=1` for verbose logs.

## Configuration

Everything is stored in one commented file, `~/.config/iron-will/config.toml` (see [`config/config.example.toml`](config/config.example.toml)). You can edit it by hand or in the GUI. Both components pick up changes live. Invalid values fall back to their defaults and never crash anything.

Main groups: `[visualizer]` (mode, bars, spacing, roundness, colors, opacity, fps), `[motion]` (attack/decay, peak physics, idle fade), `[layout]` (edge, alignment, size, offsets, layer), `[analysis]` (cava sensitivity, frequency range) and `[sounds]` (folder, events, delays, cooldown, volume, player).

## Architecture

```
                       ┌──────────── ~/.config/iron-will/config.toml ────────────┐
                       │      (one schema: iron_will/config.py → FIELDS)          │
                       ▼                         ▲ autosave            ▼ re-read per event
 ┌──────── visualizer ─────────┐    ┌──── settings GUI ────┐    ┌──── dispatcher ────┐
 │ ConfigStore (file watcher)  │    │ ConfigStore+autosave │    │ GLib main loop     │
 │   ├─ LayoutModel ─▶ layer-  │    │ SettingsBackend ─▶QML│    │ logind PrepareFor- │
 │   │    shell anchors/margins│    │ live preview uses the│    │   Sleep → resume   │
 │   └─ VisualizerItem ◀─frame─┤    │ same VisualizerItem  │    │ ScreenSaver Active-│
 │ CavaProcess (stdout pipe)   │    │ with a demo signal   │    │   Changed → unlock │
 │   └─ cava ◀── PipeWire      │    └──────────────────────┘    │ Player (flock,     │
 └─────────────────────────────┘                                │  backend fallback) │
                                                                └────────────────────┘
```

Key design decisions:

- **Layer-shell instead of window hints.** On Wayland, `WindowStaysOnBottomHint` and absolute positioning are ignored. A layer-shell surface on the *bottom* layer is placed by the compositor, the same way Plasma places panels. With `exclusionZone = 0` it automatically sits above the panel.
- **cava over a stdout pipe, not a FIFO.** No stale `/tmp` files and no blocking open handshake, and EOF tells us immediately if cava dies (it's restarted with backoff). cava runs under `setpriv --pdeathsig`, so even a SIGKILL'd visualizer can't leave an orphan.
- **Asymmetric EMA physics.** Bars rise with a short time constant and fall with a long one, using `alpha = 1 − e^(−dt/τ)`, so motion looks the same at any frame rate. Peak caps hang, then fall with gravity.
- **Zero cost when idle.** After the configured silence, the visualizer fades out and stops its render timer completely.
- **User daemon, not `system-sleep` hooks.** Root sleep hooks can't reach your PipeWire session. The daemon listens on D-Bus as you, uses `CLOCK_BOOTTIME` for the cooldown (time spent suspended counts), waits for an audio sink with `wpctl` after resume, and holds a kernel `flock` so sounds never overlap across processes.

## Project layout

```
iron_will/
  config.py  paths.py  accent.py  util.py  qtcommon.py
  dispatcher/   player.py  daemon.py  chime.py
  visualizer/   cava.py  physics.py  demo.py  renderer.py  layout.py  app.py  qml/
  settings/     backend.py  app.py  qml/{Main.qml, components/, pages/}
  assets/iron-will.svg
systemd/  desktop/  config/config.example.toml  install.sh  uninstall.sh
```

## Troubleshooting

- **No bars?** Check `cava` is installed (System page), then look at `$XDG_RUNTIME_DIR/iron-will/cava.log`.
- **Visualizer is a normal window on Wayland?** The LayerShellQt QML module is missing. Install `layer-shell-qt`.
- **Two login sounds?** Turn off Plasma's own login sound in System Settings → Notifications → Plasma Workspace.
- **No sound after resume?** Raise *Resume delay* in Session Sounds. The daemon also waits up to 10 s for the audio device.
