#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$root/build/tests"
g++ -std=c++20 -O2 -Wall -Wextra "$root/tests/native_input.cpp" -o "$root/build/tests/native-input"
g++ -std=c++20 -O2 -fPIC -Wall -Wextra "$root/tests/native_window.cpp" -o "$root/build/tests/native-window" $(pkg-config --cflags --libs Qt6Widgets)
