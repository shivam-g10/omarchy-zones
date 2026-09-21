# QML product tests

Run from the repository root:

```sh
node tests/model_test.mjs
node tests/editor_callbacks_test.mjs
node tests/runtime_test.mjs
python tests/store_test.py
```

These tests read the active implementation in `qml/0.5.0/`. Node and Python are
development test tools; neither is added to the product runtime by these tests.
The persistence integration tests use the Quickshell already supplied by
Omarchy, with an offscreen software renderer and temporary runtime/config files.
They do not inject desktop input or alter the installed plugin.

- `model_test.mjs` verifies shared-boundary growth/shrinkage, overlap rejection,
  rollback, v1/v2 definition compatibility, Unicode and size limits, and isolated
  layout snapshots.
- `editor_callbacks_test.mjs` runs the actual editor callbacks against focused
  fixtures. It covers Unicode profile duplication, failed Save-and-close,
  cancellation, and preserving edits made while a save is in progress.
- `runtime_test.mjs` parses the generated Lua and exercises ownership, conflicts,
  partial failure cleanup and bounded repeated activation with a stateful Lua
  API double. Real compositor checks remain necessary.
- `store_test.py` exercises the actual `FileView` persistence path with private
  fixtures: profile reads and saves, failure handling, external replacement,
  component teardown and absence of helper processes. Standard filesystem
  permissions and symlink behavior are part of this contract.

Passing model and offscreen tests does not establish native drag behavior or
physical display latency. Native checks must still verify the intended window
and zone, unchanged sentinel windows, editor changes without window movement,
ordinary dragging, cancellation, and teardown.

## Private native validation

These opt-in checks run real Wayland windows through the actual Omarchy plugin
loader in a private nested desktop. They require the installed Omarchy shell,
Lua-based Hyprland, a user systemd session, and Qt/Wayland development headers.
Build the test-only window and input helpers first:

```sh
bash tests/build-native-tools.sh
bash tests/isolated/build-input.sh
```

Run the stages in order from a terminal. The cleanup trap stops the private
compositor even if a check fails; `lifecycle` removes the fixture plugin.

```sh
(
  set -e
  python3 tests/isolated/lab.py start --mode 2560x1440@60
  trap 'python3 tests/isolated/lab.py stop' EXIT
  python3 tests/isolated/check.py install
  python3 tests/isolated/check.py correctness
  python3 tests/isolated/check.py resources
  python3 tests/isolated/check.py lifecycle
)
```

`lab.py` owns a private HOME, runtime directory, theme copy, D-Bus session and
process cgroup. It creates a nested compositor window on a silent workspace.
`check.py install` commits a test-only snapshot and calls the real
`omarchy plugin add --enable --yes`; no setup script or parent configuration
edit is involved. `gestures.py` verifies the private socket and compositor
ownership before sending virtual input. It never targets the physical seat.

Correctness checks exercise snapping, profile selection, cancellation, ordinary
dragging, shared boundaries, numeric edits, saving and editor reuse. Lifecycle
checks cover binding conflicts, repeated enable/disable, reloads, shell restarts
and removal. Resource checks sample the private cgroup. Results live under
`evidence/lifecycle-0.5.0/`; fixture and cleanup details live in `build/native-lab/`.
These generated files stay out of Git. Inspect the results before claiming a
check passed; state timings are not physical presentation measurements.

## Input fixtures

`native_window.cpp` creates a real Qt Wayland test window, including native
title-bar movement. `isolated/wayland-input.c` sends virtual pointer/keyboard
events to a specified private Wayland socket. Its build script fetches pinned
protocol XML with verified checksums. The compiled helpers are test-only; they
are never installed or required by the QML product. Building them requires the
corresponding compiler and Qt/Wayland development headers.

The optional `native_input.cpp` and `native_driver.py` target the physical seat
through `/dev/uinput`; use them only during an explicitly agreed desktop-control
interval. They are not part of unattended unit tests. Their acceleration and
fixed-pause behavior make them unsuitable for latency benchmarks.

Run only one input controller at a time. If a run is interrupted before its
cleanup trap is installed, inspect `python3 tests/isolated/lab.py status` and stop
the lab explicitly. The stop command checks the fixture cgroup and compares
parent configuration hashes captured at startup.

## Continuous integration

CI runs model, editor-callback, runtime and offscreen FileView tests, then checks
QML and generated Lua syntax. Its Arch container installs Quickshell for the
storage tests. Syntax checks do not instantiate Omarchy controls or verify their
rendering; native checks remain necessary.
