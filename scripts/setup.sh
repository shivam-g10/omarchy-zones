#!/usr/bin/env bash
# Native setup is an explicit user action, never an Omarchy add/enable hook.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
action="${1:-}"
if [[ $# -ne 1 || ! "$action" =~ ^(build|install|update|remove)$ ]]; then
  printf 'Usage: %s {build|install|update|remove}\n' "$0" >&2
  exit 2
fi

if [[ "$action" == remove ]]; then
  exec python3 "$root/scripts/manage.py" remove
fi

# Omarchy watches plugin checkouts. Keep compiler output and generated symlinks
# outside that tree, so builds neither trigger reloads nor invalidate the folder.
build_dir="${OMARCHY_ZONES_BUILD_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/omarchy-zones/build}"
cmake -S "$root" -B "$build_dir" -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DOMARCHY_ZONES_BUILD_PLUGIN=ON
cmake --build "$build_dir" --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-2}"

if [[ "$action" != build ]]; then
  exec python3 "$root/scripts/manage.py" "$action" --build-dir "$build_dir"
fi
