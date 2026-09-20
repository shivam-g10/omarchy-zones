#!/usr/bin/env bash
# Build the isolated-lab input client; this script never connects to a desktop.
set -euo pipefail

tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
generated_dir="$tools_dir/generated"
for tool in curl sha256sum wayland-scanner pkg-config "${CC:-cc}"; do
    command -v "$tool" >/dev/null || { printf 'Required build tool missing: %s\n' "$tool" >&2; exit 1; }
done
pkg-config --exists wayland-client xkbcommon
mkdir -p -- "$generated_dir"
build_dir=$(mktemp -d "$generated_dir/.build-input.XXXXXX")
trap 'rm -rf -- "$build_dir"' EXIT
mkdir -- "$build_dir/generated"

# These upstream revisions match the protocols used for native validation.
# Exact SHA-256 checks also protect the cached XML files from unnoticed changes.
pointer_url='https://raw.githubusercontent.com/swaywm/wlr-protocols/c11408942e2fb54d41dadb84cdf844331076ae11/unstable/wlr-virtual-pointer-unstable-v1.xml'
pointer_sha='3ff6d540be0bc5228195bf072bde42117ea17945a5c2061add5d3cf97d6bb524'
keyboard_url='https://raw.githubusercontent.com/swaywm/wlroots/5334ee8bfd93b2bfdc077f422b87c2509f04d5d4/protocol/virtual-keyboard-unstable-v1.xml'
keyboard_sha='7ad7870003ecd592cae47dc19d277a609b7f18fd7b7be012623cf3225a7294f5'

fetch_protocol() {
    local name=$1 url=$2 digest=$3
    local cached="$generated_dir/$name.xml" staged="$build_dir/generated/$name.xml"
    if [[ -f "$cached" ]] && printf '%s  %s\n' "$digest" "$cached" | sha256sum --check --status; then
        cp -- "$cached" "$staged"
    else
        curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
            --connect-timeout 10 --max-time 60 --retry 2 --output "$staged" "$url"
    fi
    printf '%s  %s\n' "$digest" "$staged" | sha256sum --check --status || {
        printf 'Protocol checksum failed: %s\n' "$name" >&2; exit 1;
    }
    wayland-scanner client-header "$staged" "$build_dir/generated/$name.h"
    wayland-scanner private-code "$staged" "$build_dir/generated/$name.c"
}
fetch_protocol pointer "$pointer_url" "$pointer_sha"
fetch_protocol keyboard "$keyboard_url" "$keyboard_sha"

# Compile against the staged headers, and replace the executable only on success.
# Renaming also permits rebuilding while an earlier helper process is running.
cp -- "$tools_dir/wayland-input.c" "$build_dir/wayland-input.c"
read -r -a compiler_flags <<< "$(pkg-config --cflags wayland-client xkbcommon)"
read -r -a linker_flags <<< "$(pkg-config --libs wayland-client xkbcommon)"
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra "${compiler_flags[@]}" \
    "$build_dir/wayland-input.c" "$build_dir/generated/pointer.c" "$build_dir/generated/keyboard.c" \
    -o "$build_dir/generated/wayland-input" "${linker_flags[@]}"
for file in pointer.xml pointer.h pointer.c keyboard.xml keyboard.h keyboard.c wayland-input; do
    mv -- "$build_dir/generated/$file" "$generated_dir/$file"
done
printf 'Built %s\n' "$generated_dir/wayland-input"
