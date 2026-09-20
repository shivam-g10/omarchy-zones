# Rust native-plugin feasibility experiment

This standalone experiment tests a Rust geometry core inside a real Hyprland
plugin. It does not modify, install, or replace Omarchy Zones. Do not load this
experimental plugin into the everyday desktop; use the isolated compositor
described in the parent evaluation notes.

## Build and checks

```sh
cargo test --jobs 2
cargo clippy --all-targets --jobs 2 -- -D warnings
sh build-plugin.sh
```

The last command runs `cargo build --release --jobs 2`. Cargo's `cc` build
dependency compiles the C++ adapter, and Rust produces a static library containing
both parts. A final `c++ -shared` invocation creates
`target/release/zones-rust-poc.so` while retaining Hyprland's C++ ABI entry points.
The final library replaces its previous path atomically, so rebuilding does not
truncate a library already mapped by an isolated compositor. This avoids
pretending that Cargo's default `cdylib` export filtering preserves
C++ plugin entry points automatically. The whole build is one script, but it
still uses both compilers and matching Hyprland headers. `Cargo.lock` pins the
build dependencies. There are no third-party Rust runtime dependencies.

The experiment was built against this machine's Hyprland 0.56.2 headers with
Rust 1.98.0. The plugin checks Hyprland's API hash before registering callbacks.
It still needs a rebuild after an incompatible compositor update.

## Division of responsibilities

| Rust core | C++ adapter |
| --- | --- |
| Creates two adjacent equal-width zones from the monitor's usable rectangle | Reads monitor work areas and the real native drag target |
| Validates minimum sizes, extent overflow, and adjacency | Owns Hyprland smart pointers, signal listeners, and renderer objects |
| Rejects nonfinite pointer positions and performs hit testing | Receives mouse, keyboard, render, monitor, close, and lock events |
| Computes a one-shot drop rectangle | Renders the two zones and performs the deferred move/resize |
| Moves a shared boundary while preserving outer bounds | Enforces live window size limits, session lock, and compositor lifecycle |

The boundary uses four plain C-compatible value types/functions, with no owning
pointers, C++ containers, or window identities crossing into Rust. Rust panics
are caught before returning to C++; invalid input produces an invalid result.
C++ event callbacks catch exceptions and disable the experiment on failure.
Hyprland's normal initialization exception mechanism handles an ABI mismatch.

The C++ adapter remains substantial because this test preserves native dragging,
compositor rendering, and lifecycle checks. It is not a Rust-only implementation.
There are no timers, file watchers, polling loops, or resident helper processes.
A weak target reference exists during the current drag and its one-shot deferred
drop only; it is cleared afterward. The plugin stores no window assignments.

## Native interface

The isolated compositor needs its own native move binding for
`Super+Shift+left mouse`; the plugin does not register or modify bindings.
Shift plus a native title-bar move uses the same path. An ordinary move without
Shift leaves the overlay hidden. Holding Shift without moving a window does not
show the overlay. Releasing Shift cancels snapping. The overlay uses a deliberate
fixed cyan test color; theme fidelity belongs to the separate editor experiment.

With `hyprctl` explicitly targeting the isolated compositor, `zones-rust-poc`
returns diagnostic text:

```text
zones-rust-poc: 0.1.0
overlay: hidden
hovered-zone: -1
snaps: 0
rust-calls: 0
callback-failure: no
retained-target: no
pending-snap: 0
monitor:
zone-0: 0 0 0 0
zone-1: 0 0 0 0
```

Zone coordinates are monitor-local logical pixels. `hovered-zone` is zero-based.
`rust-calls` increments only when an activated gesture invokes the core; the
diagnostic command itself does not execute geometry work. The final drop invokes
Rust again and captures its returned rectangle by value.

## What this experiment establishes

Six Rust tests cover odd-width/negative-origin work areas, overflow and minimum
sizes, shared-boundary geometry, malformed layouts and nonfinite pointer input,
activation-gated drop decisions, and panic containment. The build and strict
Clippy check passed. Dynamic symbol inspection verified `pluginInit`,
`pluginExit`, `pluginAPIVersion`, and all four Rust functions in the resulting
shared library.

Native runtime results are recorded separately by the parent evaluation after
loading this artifact in an isolated compositor. A successful build and these
tests alone do not establish native snapping, memory cost, or visual correctness.

This is a fixed two-zone experiment. It has no profile file, selector, persistence,
or editor. Shared-boundary logic is tested in Rust but has no native editing UI in
this plugin. It does not establish parity with the installed product or prove
that migrating the entire product is worthwhile.

For scale, the source contains 151 Rust core lines, 146 Rust test lines, 240 C++
adapter lines, a 14-line C ABI header, and 41 build-script lines. These are raw
line counts, not a measure of complexity. The unstripped debug-enabled release
artifact is approximately 4.4 MiB on disk; this is not its incremental RAM cost.
