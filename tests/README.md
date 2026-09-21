# QML product tests

Run from the repository root:

```sh
node tests/model_test.mjs
node tests/editor_callbacks_test.mjs
python tests/store_test.py
python tests/install_test.py
```

These tests read the active implementation in `shell/`. Node and Python are
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
- `store_test.py` exercises actual QML persistence: atomic private writes,
  literal command arguments, invalid or oversized input, unsafe file types,
  external file replacement, and cleanup after component destruction.
- `install_test.py` covers installation/removal in a sandbox. It does not install
  into the current desktop.

Passing model and offscreen tests does not establish native drag behavior or
physical display latency. Native checks must still verify the intended window
and zone, unchanged sentinel windows, editor changes without window movement,
ordinary dragging, cancellation, and teardown.

## Native test fixtures

Generic native fixtures remain available for private compositor validation:

```sh
bash tests/build-native-tools.sh
bash tests/isolated/build-input.sh
```

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

Native validation must use the `omarchy-zones` IPC target, private
configuration/runtime paths, and the actual Omarchy plugin loader. Run only one
input controller at a time and stop the private compositor and its helpers
afterward. The fixtures provide windows and input; they are not a complete
automated native test runner.

## Continuous integration

CI runs the model, editor-callback, and sandboxed installer tests, then checks
QML, Lua, and shell-script syntax. The persistence tests require Quickshell and
run separately on Omarchy. Syntax checks do not instantiate Omarchy controls or
verify their rendering; native checks remain necessary.
