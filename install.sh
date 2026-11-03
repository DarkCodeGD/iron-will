#!/usr/bin/env bash
# Iron Will installer — everything goes into your home directory (~/.local,
# ~/.config). Root is only used, after asking, to install missing packages.
#
#   ./install.sh               install / upgrade
#   ./install.sh --dry-run     show what would happen, change nothing
#   ./install.sh --no-deps     skip the package check
#   ./install.sh --no-services install files but don't enable the services
#   ./install.sh --yes         don't prompt
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_DIR="$DATA_HOME/iron-will"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$CONFIG_HOME/systemd/user"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
UNITS=(iron-will-audio.service iron-will-visualizer.service)

DRY_RUN=0 SKIP_DEPS=0 SKIP_SERVICES=0 ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --no-deps) SKIP_DEPS=1 ;;
    --no-services) SKIP_SERVICES=1 ;;
    -y|--yes) ASSUME_YES=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

# ── output helpers ─────────────────────────────────────────────────────────
if [[ -t 1 ]]; then B=$'\e[1m' TEAL=$'\e[38;2;46;196;182m' CORAL=$'\e[38;2;255;107;91m' DIM=$'\e[2m' R=$'\e[0m'
else B="" TEAL="" CORAL="" DIM="" R=""; fi
step() { printf '\n%s▸ %s%s\n' "$B$TEAL" "$*" "$R"; }
ok()   { printf '  %s✓%s %s\n' "$TEAL" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$CORAL" "$R" "$*"; }
info() { printf '  %s%s%s\n' "$DIM" "$*" "$R"; }

run() {  # run a command, or just print it in dry-run mode
  if (( DRY_RUN )); then printf '  %s[dry-run]%s' "$DIM" "$R"; printf ' %q' "$@"; echo; else "$@"; fi
}
render() {  # render <template> <dest>: substitute @BIN_DIR@ / @APP_DIR@
  if (( DRY_RUN )); then info "[dry-run] render $(basename "$1") → $2"; return; fi
  mkdir -p "$(dirname "$2")"
  sed -e "s|@BIN_DIR@|$BIN_DIR|g" -e "s|@APP_DIR@|$APP_DIR|g" "$1" > "$2"
}
confirm() {
  (( ASSUME_YES )) && return 0
  [[ -t 0 ]] || return 1
  read -r -p "  $1 [Y/n] " reply; [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

printf '%s\n' "${B}Iron Will${R} ${DIM}— desktop audio toolkit for KDE Plasma${R}"
(( DRY_RUN )) && warn "dry run: nothing will be changed"

# ── 1. dependencies ────────────────────────────────────────────────────────
step "Checking dependencies"
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  warn "Python 3.11+ is required (for tomllib)"; exit 1
fi
ok "python3 $(python3 -c 'import platform; print(platform.python_version())')"

PM=""
for candidate in dnf pacman zypper apt-get; do command -v "$candidate" >/dev/null && { PM=$candidate; break; }; done

# name | check kind | target | dnf pkg | pacman pkg | zypper pkg | apt pkg
DEPS=(
  "cava|cmd|cava|cava|cava|cava|cava"
  "pw-play|cmd|pw-play|pipewire-utils|pipewire|pipewire-tools|pipewire-bin"
  "wpctl|cmd|wpctl|wireplumber|wireplumber|wireplumber|wireplumber"
  "PySide6|py|PySide6|python3-pyside6|pyside6|python3-PySide6|python3-pyside6.qtquick"
  "PyGObject|py|gi|python3-gobject|python-gobject|python3-gobject|python3-gi"
  "LayerShellQt|qml|org/kde/layershell|layer-shell-qt|layer-shell-qt|layer-shell-qt6|qml6-module-org-kde-layershell"
)
qml_import_dir() { python3 -c 'from PySide6.QtCore import QLibraryInfo as L; print(L.path(L.LibraryPath.QmlImportsPath))' 2>/dev/null; }

missing=()
if (( ! SKIP_DEPS )); then
  for entry in "${DEPS[@]}"; do
    IFS='|' read -r name kind target p_dnf p_pacman p_zypper p_apt <<<"$entry"
    case "$kind" in
      cmd) command -v "$target" >/dev/null && found=1 || found=0 ;;
      py)  python3 -c "import $target" 2>/dev/null && found=1 || found=0 ;;
      qml) dir="$(qml_import_dir)"; [[ -n "$dir" && -f "$dir/$target/qmldir" ]] && found=1 || found=0 ;;
    esac
    if (( found )); then ok "$name"; else
      warn "$name is missing"
      case "$PM" in dnf) missing+=("$p_dnf") ;; pacman) missing+=("$p_pacman") ;;
                    zypper) missing+=("$p_zypper") ;; apt-get) missing+=("$p_apt") ;; esac
    fi
  done
  if (( ${#missing[@]} )); then
    case "$PM" in
      dnf|zypper) cmd=(sudo "$PM" install -y "${missing[@]}") ;;
      pacman)     cmd=(sudo pacman -S --needed --noconfirm "${missing[@]}") ;;
      apt-get)    cmd=(sudo apt-get install -y "${missing[@]}") ;;
      *)          cmd=() ;;
    esac
    if (( ${#cmd[@]} )) && confirm "Install missing packages with: ${cmd[*]} ?"; then
      run "${cmd[@]}"
    else
      warn "continuing without: ${missing[*]:-(unknown package manager)} — some features stay disabled"
    fi
  fi
else
  info "skipped (--no-deps)"
fi

# ── 2. files ───────────────────────────────────────────────────────────────
step "Installing files"
run mkdir -p "$APP_DIR" "$BIN_DIR"
run rm -rf "$APP_DIR/iron_will"                       # clean upgrade of our own package dir
run cp -r "$SRC/iron_will" "$APP_DIR/iron_will"
run find "$APP_DIR/iron_will" -name __pycache__ -type d -prune -exec rm -rf {} +
run cp "$SRC/README.md" "$APP_DIR/README.md"
ok "package → $APP_DIR"

for pair in "iron-will-audio:iron_will.dispatcher" "iron-will-visualizer:iron_will.visualizer" "iron-will-settings:iron_will.settings"; do
  name="${pair%%:*}" module="${pair#*:}"
  if (( DRY_RUN )); then info "[dry-run] write launcher $BIN_DIR/$name"; continue; fi
  cat > "$BIN_DIR/$name" <<EOF
#!/bin/sh
# Iron Will launcher (generated by install.sh)
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m $module "\$@"
EOF
  chmod +x "$BIN_DIR/$name"
done
ok "launchers → $BIN_DIR/iron-will-{settings,visualizer,audio}"

for unit in "${UNITS[@]}"; do render "$SRC/systemd/$unit" "$UNIT_DIR/$unit"; done
ok "systemd user units → $UNIT_DIR"

render "$SRC/desktop/iron-will-settings.desktop" "$APPS_DIR/iron-will-settings.desktop"
run mkdir -p "$ICON_DIR"
run cp "$SRC/iron_will/assets/iron-will.svg" "$ICON_DIR/iron-will.svg"
command -v update-desktop-database >/dev/null && run update-desktop-database -q "$APPS_DIR" || true
# Refresh KDE's menu cache so Plasma picks up the entry (and its icon) right away.
command -v kbuildsycoca6 >/dev/null && run kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
ok "app launcher → Iron Will (application menu)"

# ── 3. config + sound folder ───────────────────────────────────────────────
step "Configuration"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"
if (( DRY_RUN )); then
  info "[dry-run] write default config if missing: $(python3 -m iron_will.config --path)"
else
  ok "config: $(python3 -m iron_will.config --init)"
fi
SOUND_DIR="$(python3 -m iron_will.config --get sounds.directory)"
run mkdir -p "$SOUND_DIR"
if [[ -z "$(find "$SOUND_DIR" -maxdepth 3 -type f \( -iname '*.mp3' -o -iname '*.wav' -o -iname '*.ogg' -o -iname '*.oga' -o -iname '*.flac' -o -iname '*.opus' \) 2>/dev/null | head -1)" ]]; then
  run python3 -m iron_will.dispatcher.chime "$SOUND_DIR/iron-will-chime.wav"
  ok "sound folder was empty — added a generated chime: $SOUND_DIR/iron-will-chime.wav"
else
  ok "sound folder: $SOUND_DIR"
fi

# ── 4. services ────────────────────────────────────────────────────────────
step "Services"
run systemctl --user daemon-reload
if (( SKIP_SERVICES )); then
  info "not enabling services (--no-services). Turn them on from Iron Will → System."
else
  # restart (not just start) so an upgrade picks up the new code
  run systemctl --user enable "${UNITS[@]}"
  run systemctl --user restart "${UNITS[@]}"
  ok "enabled and started: ${UNITS[*]}"
fi

# ── 5. hints ───────────────────────────────────────────────────────────────
step "Done"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR is not in your PATH — the app menu entry still works." ;; esac
info "Open ${B}Iron Will${R}${DIM} from the application menu (or run iron-will-settings)."
info "Logs: journalctl --user -u iron-will-visualizer -u iron-will-audio -f"
info "Tip: Plasma has its own login sound (System Settings → Notifications →"
info "     Plasma Workspace → Login). Disable it if you hear two sounds."
