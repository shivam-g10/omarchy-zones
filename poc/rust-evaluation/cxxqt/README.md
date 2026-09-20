# CXX-Qt editor evaluation

This standalone Cargo project evaluates CXX-Qt 0.10.0 with the host's Qt 6.11.2 and Rust 1.98.0. It does not replace the production editor or load a Hyprland plugin. Its QML interface is the same as the sibling Qt Bridges evaluation except for its module name and identifying labels.

The 900 × 620 window contains two adjacent zones in a 2560 × 1414 logical-pixel model. A Rust-owned boundary can be moved with the mouse or changed numerically. The boundary is read-only to QML and clamps to 320–2240, so growing one zone shrinks its neighbor without overlap. The interface reads the active Omarchy colors, shell controls, border gradient, and rounding. A filesystem watcher queues theme changes onto the Qt event loop; it does not poll. The read-only `hyprctl getoption` helpers run on initial theme loading or a theme refresh and then exit.

Saving is disabled unless an explicit `--output TEST_FILE` is provided. Save writes only the two test zone definitions in v2 format, using an atomic rename. The production `omarchy-zones/zones.conf` location and symlink outputs are rejected. It does not query, track, move, or resize other windows, install desktop bindings, or create a background service.

## Build and use

From this directory:

```sh
cargo build --release --locked --jobs 2
cargo test --release --locked --jobs 2
./target/release/zones-cxxqt-evaluation --probe
./target/release/zones-cxxqt-evaluation --output /tmp/cxxqt-test-layout.conf
```

The executable is `target/release/zones-cxxqt-evaluation`; the window title is `Omarchy Zones · CXX-Qt PoC`. QML and the application module are embedded as Qt resources, so there is no external application QML directory to install. The system Qt libraries, Qt Quick modules, and platform plugins remain runtime dependencies. This is not a fully static binary.

Required local tooling is Cargo/Rust, a C++ compiler, Qt Core/Gui/Qml/Quick/QuickControls2 headers and tools, and `qmake6` (or an explicit `QMAKE` path). The available host tools were used without installing packages. `.cargo/config.toml` limits builds to two jobs. The final project has no linker override. Although Rust 1.98 includes LLD internally, CXX-Qt's `qt-build-utils` 0.10 checks the shell PATH and automatically selects the already-installed GNU gold on this host. The successful build emits Rust's gold-deprecation warning. An exploratory minimal build specified gold explicitly; that redundant override was removed. No replacement linker was installed. The selection behavior is visible in the [0.10.0 platform build helper](https://github.com/KDAB/cxx-qt/blob/v0.10.0/crates/qt-build-utils/src/platform.rs).

For a QML/Rust integration smoke check without showing a window:

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software timeout 15s \
  ./target/release/zones-cxxqt-evaluation --smoke --output /tmp/cxxqt-smoke-layout.conf
```

Smoke mode checks both boundary clamps, sets the boundary to 1600, saves to the supplied test path, prints a `PROBE` JSON record, and exits. It is not a substitute for native mouse/keyboard validation. F12 prints an `AUTOMATION` JSON record with current control positions, boundary value, and theme values for the separate native test runner.

## What this route proves

The implementation uses Rust for the QObject state, callable methods, geometry constraint, save path, and theme watcher. Qt Quick supplies the scene and controls. `build.rs` generates and compiles the bridge and QML module through Cargo. There is no handwritten C++ in this project, but C++ generation and compilation remain part of the build. This follows KDAB's [Cargo-only guide](https://kdab.github.io/cxx-qt/book/getting-started/4-cargo-executable.html) and [Rust QObject module guide](https://kdab.github.io/cxx-qt/book/getting-started/2-our-first-cxx-qt-module.html).

CXX-Qt is not a comprehensive Rust QtWidgets API. Its [0.10.0 README](https://github.com/KDAB/cxx-qt/blob/v0.10.0/README.md) describes limited widget support through Rust-backed QObjects used from C++ widgets. Reimplementing the existing QWidget editor entirely in Rust is therefore a different project: it would need custom bindings or retain C++ widgets. This PoC evaluates the supported Rust plus Qt Quick path, not a direct conversion of every QWidget call. The [published Qt type bindings](https://github.com/KDAB/cxx-qt/blob/v0.10.0/crates/cxx-qt-lib/src/lib.rs) and [type integration guide](https://kdab.github.io/cxx-qt/book/concepts/types.html) define that boundary.

The generated CXX-Qt object supplies a guarded thread queue for filesystem notifications. This uses the [CXX-Qt Threading API](https://docs.rs/cxx-qt/0.10.0/cxx_qt/trait.Threading.html) instead of accessing a QObject from the watcher thread. The watcher exists only while the editor is open.

## Evidence and limits

Original build measurements and validation output are retained locally under the Git-ignored `evidence/` directory. The first minimal release build took 146.308 seconds. Recompiling the full interface and dependencies after changing linker flags took 146.863 seconds and exposed one missing TOML `serde` feature; enabling that feature produced a successful build in 6.939 seconds. The largest child compiler RSS in the full attempt was 900,880 KiB. These stages are kept separately rather than presenting the final incremental time as a clean build. The remaining GCC 16 warning originates in Qt `QChar` headers (`-Wsfinae-incomplete`); no warning suppression was added. Build times include this host's concurrent activity and cache state; they are observations, not general framework benchmarks. Compiler maximum RSS records the largest observed child-process RSS, not a sum or peak of the whole build tree.

Local validation passed two Rust tests and the offscreen QML-to-Rust smoke flow, including writing a test-only v2 file with a 1600/960 split. `--probe` successfully reported the active theme. The release executable is 3,165,312 bytes on this build; that does not include its shared Qt dependencies. The lockfile resolves 86 packages including the application and target-specific packages; it is not a count of runtime processes.

The project contains only a two-zone editor comparison. It does not implement production profiles, multiple displays, snapping overlays, installation, or compositor integration. Native interaction and idle CPU/RAM measurement are performed by the parent evaluation harness separately. Unit tests or an offscreen smoke result alone must not be reported as native validation.
