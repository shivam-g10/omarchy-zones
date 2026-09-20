# Qt Bridges Rust editor evaluation

This is a standalone comparison PoC, not a replacement for Omarchy Zones.
It uses the official `qtbridge` **0.2.0** Rust crate and Qt Quick/QML. The
application contains no handwritten C++ or manual FFI. The dependency builds
C++ internally and still requires a C++ compiler.

The native editor has two adjacent zones, one draggable shared boundary, an
exact numeric width, reset, and an optional test-file save. Rust clamps the
boundary to 320–2240 within a 2560×1414 logical-pixel demonstration layout.
This is intentionally a small editing slice, not full profile/editor parity.
It contains no window placement calls, overlay plugin, or window assignments.

## Requirements and build

Verified host: Arch/Omarchy, Rust 1.98.0, Cargo 1.98.0, Qt 6.11.2. The published
crate declares Rust >=1.87 and Qt >=6.10. Qt base/private development headers,
Qt declarative/Quick/Quick Controls/Quick Shapes/QuickTest, qmake6, and a C++
compiler are needed. The installed host already had these dependencies.

From the repository root:

```sh
cd poc/rust-evaluation/qtbridge
cargo build --release --locked -j2
cargo test --release --locked -j2
```

`.cargo/config.toml` selects `QMAKE=qmake6` and limits Cargo to two jobs.
`Cargo.lock` pins the complete resolved dependency graph. `qtbridge=0.2.0`
and the stable `notify=8.2.0` watcher are explicitly pinned.

## Run in a test compositor

```sh
./target/release/zones-qtbridge-poc --output /existing/test-directory/qtbridge-layout.conf
```

Window title: **Omarchy Zones · Qt Bridges PoC**. Application name:
`omarchy-zones-qtbridge-poc`. Initial size is 900×620. F12 prints measured
window-local coordinates for the boundary, numeric control, and Save button.
Startup prints the same `AUTOMATION` JSON record. Actual Wayland app ID must
be checked in the compositor under test.

Without `--output`, Save reports that saving is disabled. Output parents must
already exist. The app refuses symlink outputs and the current/home production
`omarchy-zones/zones.conf`. It writes only one explicitly selected test file,
using a same-directory temporary file and atomic rename. The file uses the v2
profile format with connector name `POC-DISPLAY`, not a live desktop connector.
There is no installation or desktop configuration change.

Read-only and offscreen checks:

```sh
./target/release/zones-qtbridge-poc --probe
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
  ./target/release/zones-qtbridge-poc --smoke --output /existing/test-directory/smoke.conf
```

`--probe` creates no Qt window. `--smoke` creates a hidden QML window, exercises
the Rust/QML bridge and clamping, optionally saves the test file, and exits.
These checks do not replace real native mouse/keyboard validation.

## Theme and background behavior

Startup reads the active Omarchy `colors.toml` and `shell.toml` through
`XDG_STATE_HOME` (or `~/.local/state`). It also reads the live Hyprland active
border gradient, rounding, and border width with three `hyprctl -j getoption`
queries. There are no dispatcher calls. Qt supplies the system font family;
the shell's font size and colors are used by QML.

A Qt Quick Shape/LinearGradient draws the preview border using the live colors,
angle, border width, and rounding. The compositor still supplies the real
outer window border. Theme file changes use an inotify-backed filesystem
watcher and queue a Qt event; there is no periodic polling or resident helper
process. A watcher thread exists while the editor is open. Refresh theme
rereads live options on demand. Arbitrary live Hyprland option changes without
a theme-file event do not trigger an automatic refresh.

## Evidence and limits

Original build timings and logs are retained locally under the Git-ignored
`evidence/` directory. The first dependency build took
83.84 s, then exposed a missing TOML `serde` feature in this PoC. Enabling that
feature produced a successful release build in 2.82 s; subsequent source-only
builds took about 0.65 s. The first figure includes crate download and dependency
compilation and is not a clean successful cold-build measurement. Two Rust core
tests and a hidden offscreen QML bridge/clamp/atomic-save probe passed.
Native interaction, idle CPU/RAM,
GPU use, and compositor-specific appearance must be measured separately.
No claim of lower memory or CPU cost follows merely from using Rust.

Qt Bridges was announced as public beta on 1 July 2026. The API/tooling remains
less mature than established Qt C++ APIs. QML/Rust type information is not yet
fully shared by language-server tooling. This PoC targets Linux x86_64 only;
other platforms, large profile sets, editor parity, accessibility completeness,
and production packaging are unvalidated.

Primary sources:

- [Qt's Rust public-beta announcement](https://www.qt.io/blog/qt-bridges-public-beta-for-rust)
- [Official Qt Bridges Rust 0.2.0 documentation](https://doc-snapshots.qt.io/qtbridge-rust/qtbridge/index.html)
- [Official Rust bridge repository](https://code.qt.io/cgit/qt/qtbridge-rust.git/)
- [Published qtbridge 0.2.0 crate](https://crates.io/crates/qtbridge/0.2.0)
