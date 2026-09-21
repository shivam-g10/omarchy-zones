#!/usr/bin/env bash
# Desktop integration is explicit; enabling a plugin never modifies user files.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$root/scripts/manage.py" "$@"
