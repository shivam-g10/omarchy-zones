#!/bin/sh
set -eu
poc_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cargo build --release --jobs 2 --manifest-path "$poc_dir/Cargo.toml" --target-dir "$poc_dir/target"
# Cargo compiles Rust and the C++ adapter. This final link retains the C++ ABI
# entry points; rustc's cdylib export filtering would otherwise hide them.
plugin_tmp=$(mktemp "$poc_dir/target/release/.zones-rust-poc.XXXXXX.so")
trap 'rm -f -- "$plugin_tmp"' EXIT HUP INT TERM
c++ -shared -o "$plugin_tmp" \
    -Wl,--undefined=pluginInit -Wl,--undefined=pluginExit -Wl,--undefined=pluginAPIVersion \
    "$poc_dir/target/release/libzones_rust_native_core.a" \
    $(pkg-config --libs hyprland) -ldl -lpthread
mv -f -- "$plugin_tmp" "$poc_dir/target/release/zones-rust-poc.so"
printf '%s\n' "$poc_dir/target/release/zones-rust-poc.so"
