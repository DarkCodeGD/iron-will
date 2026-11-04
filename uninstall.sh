#!/usr/bin/env bash
# Iron Will uninstaller. Your sound folder is never touched.
#
#   ./uninstall.sh            remove the app, keep your config
#   ./uninstall.sh --purge    also remove ~/.config/iron-will and saved state
#   ./uninstall.sh --dry-run  show what would be removed
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$CONFIG_HOME/systemd/user"
UNITS=(iron-will-audio.service iron-will-visualizer.service)

DRY_RUN=0 PURGE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --purge) PURGE=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

run() { if (( DRY_RUN )); then printf '  [dry-run]'; printf ' %q' "$@"; echo; else "$@"; fi; }

echo "Removing Iron Will…"
for unit in "${UNITS[@]}"; do
  [[ -f "$UNIT_DIR/$unit" ]] && run systemctl --user disable --now "$unit" 2>/dev/null || true
  run rm -f "$UNIT_DIR/$unit" "$UNIT_DIR/$unit.d/90-fast-stop.conf"
  [[ -d "$UNIT_DIR/$unit.d" ]] && run rmdir --ignore-fail-on-non-empty "$UNIT_DIR/$unit.d" || true
done
run systemctl --user daemon-reload
run rm -f "$BIN_DIR/iron-will-audio" "$BIN_DIR/iron-will-visualizer" "$BIN_DIR/iron-will-settings"
run rm -rf "$DATA_HOME/iron-will"
run rm -f "$DATA_HOME/applications/iron-will-settings.desktop" "$DATA_HOME/icons/hicolor/scalable/apps/iron-will.svg"
if (( PURGE )); then
  run rm -rf "$CONFIG_HOME/iron-will" "$STATE_HOME/iron-will"
  echo "Removed app, config and state."
else
  echo "Removed app. Config kept at $CONFIG_HOME/iron-will (use --purge to remove it)."
fi
