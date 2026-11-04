<p align="center">
  <img src="iron_will/assets/iron-will.svg" width="112" alt="Iron Will icon">
</p>

<h1 align="center">Iron Will</h1>

<p align="center">
  <b>A lightweight desktop audio toolkit for KDE Plasma 6</b><br>
  Session sounds on login, resume and unlock, plus a click-through audio visualizer that lives on your desktop.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/KDE_Plasma-6-1D99F3?logo=kde&logoColor=white" alt="KDE Plasma 6">
  <img src="https://img.shields.io/badge/Wayland-layer--shell-FFBC00?logo=wayland&logoColor=black" alt="Wayland layer-shell">
  <img src="https://img.shields.io/badge/Qt-PySide6-41CD52?logo=qt&logoColor=white" alt="PySide6">
  <img src="https://img.shields.io/badge/audio-PipeWire_%2B_cava-2EC4B6" alt="PipeWire + cava">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
</p>

<p align="center">
  <img src="docs/images/visualizer.gif" width="760" alt="Animated visualizer in mirror mode">
</p>

<p align="center">
  <img src="docs/icons/book.svg" width="18" height="18" alt=""> <b><a href="docs/OVERVIEW.md">Read the full overview</a></b>: every mode in depth, all settings, and how it works under the hood.
</p>

## What it does

- <img src="docs/icons/music.svg" width="18" height="18" alt=""> **Session sounds:** plays a random track from your music folder when you log in, wake your laptop, or unlock the screen.
- <img src="docs/icons/bars.svg" width="18" height="18" alt=""> **Desktop visualizer:** music bars that sit on your desktop, right above the panel. They never get in the way of your windows or your clicks.
- <img src="docs/icons/flame.svg" width="18" height="18" alt=""> **Six styles:** bars, wave, mirror, fire, ferrofluid and bubbles.
- <img src="docs/icons/sliders.svg" width="18" height="18" alt=""> **Genre presets:** one click tunes the motion for metal, phonk, electronic, hip-hop, calm music and more.
- <img src="docs/icons/pause.svg" width="18" height="18" alt=""> **Stays out of the way:** the visualizer fades out when the music stops, waits behind the lock screen, and pauses while a fullscreen game, a video or a maximized window covers it.
- <img src="docs/icons/app.svg" width="18" height="18" alt=""> **Settings app:** change anything with sliders and switches, and watch the visualizer update live.

## On the desktop

<p align="center">
  <img src="docs/images/desktop.jpg" alt="Iron Will visualizer running on a KDE Plasma 6 desktop, sitting just above the panel">
</p>

| Bars | Wave | Mirror |
|---|---|---|
| <img src="docs/images/desktop-bars.jpg" alt="Bars mode"> | <img src="docs/images/desktop-wave.jpg" alt="Wave mode"> | <img src="docs/images/desktop-mirror.jpg" alt="Mirror mode"> |
| **Fire** | **Ferrofluid** | **Bubbles** |
| <img src="docs/images/desktop-fire.jpg" alt="Fire mode"> | <img src="docs/images/desktop-ferro.jpg" alt="Ferrofluid mode"> | <img src="docs/images/desktop-bubbles.jpg" alt="Bubbles mode"> |

## Install

You need **KDE Plasma 6** on Linux (Wayland recommended).

```bash
git clone https://github.com/DarkCodeGD/iron-will.git
cd iron-will
./install.sh
```

The installer checks what's missing and asks before installing anything with `sudo`. Everything else stays in your home folder. To see what it would do first, run `./install.sh --dry-run`.

To uninstall, run `./uninstall.sh`. Add `--purge` to also remove your settings. Your music is never touched.

## How to use it

1. Open **Iron Will** from your app menu.
2. Point **Session Sounds** at a folder of music, or keep the chime that comes with it.
3. Pick a style and a genre preset on the **Appearance** and **Motion** pages. Changes save automatically.

**Want a sound to stop?** Press **Stop** on its notification, use Plasma's media controls, or just start your own music.

## Need help?

- **No bars?** Open the **System** page in the settings app: it checks that everything Iron Will needs is installed.
- **Hearing two login sounds?** Turn off Plasma's own login sound in System Settings → Notifications → Plasma Workspace.
- **More fixes, all settings, and how it all works:** see the **[full overview](docs/OVERVIEW.md)**.
