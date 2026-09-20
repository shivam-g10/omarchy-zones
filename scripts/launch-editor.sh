#!/usr/bin/env bash
set -euo pipefail

editor="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-zones/omarchy-zones-editor"
if [[ ! -x "$editor" ]]; then
  message='Build and install the native component first. See the Omarchy Zones README.'
  printf '%s\n' "$message" >&2
  if command -v notify-send >/dev/null 2>&1; then
    notify-send --app-name='Omarchy Zones' 'Native setup required' "$message" || true
  fi
  exit 1
fi
exec "$editor"
