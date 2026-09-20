# Native integration tooling

## Isolated native checks for 0.3

The preferred current runners create real Qt Wayland windows inside a private
Hyprland compositor. Virtual pointer/keyboard input targets only its private
`/tmp/ozr-*` socket. The editor and plugin use the production code, and the
editor runner also opens the exact distributable. These are native compositor
checks, not geometry simulations. They do not test physical-monitor behavior.

Run from the repository root in a compatible Omarchy/Hyprland session with
Omarchy Zones already installed and loaded. The lab records the parent plugin's
status through `hyprctl zones`; the update check also needs the installed
binaries as its baseline. Follow the root README's installation instructions
first. These prerequisites apply to the native lab, not to CTest or the manager
unit tests.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
ctest --test-dir build --output-on-failure
python tests/manage_test.py
bash tests/build-native-tools.sh
bash tests/isolated/build-input.sh
python tests/isolated/lab.py start
python tests/isolated/check_plugin.py
python tests/isolated/check_editor.py --measure
python tests/isolated/check_update.py
python tests/isolated/measure_idle_plugin.py
python tests/isolated/lab.py stop
```

Run these sequentially: each runner requires an empty private compositor and
restores its private fixtures. `build-input.sh` fetches pinned protocol XML files
and verifies their checksums. The lab records hashes of the existing desktop
configuration before starting and checks them when stopped. Only temporary
window rules are used to place the nested compositor on a silent workspace;
the user's desktop configuration is not edited. Always stop the lab afterward,
including after a failed check. Test helpers are not installed with the product.

Plugin results and screenshots are written under `evidence/cpp-hardening/`;
the current editor and update checks use `evidence/editor-fixes/`. The idle
runner performs a warmed unloaded/loaded/unloaded comparison and records helper
process censuses; it does not measure peak or GPU memory. The optional editor
measurement includes the editor, sentinel window, and private compositor as
separate processes so test infrastructure is not mistaken for product overhead.

`check_update.py` additionally checks an installed-binary update in a private
installation, using the currently installed binaries as its starting fixture.
Repeating it after a production update verifies a same-version replacement.

The editor runner exercises concurrent relaunches with unsaved changes, refocus
from another native window, and relaunch while a profile dialog is open. It also
captures the native profile popup and verifies that its thumbnail fits the actual
editor layout. All input stays inside the private compositor.

The `editor-instance` CTest uses separate processes to check startup races,
crash recovery, busy owners, session isolation, malformed requests, and unsafe
filesystem entries. The `editor-render` checks inspect pixels and standard Qt
control interactions offscreen; `editor-render-hidpi` repeats them at scale 2.
These supplement native validation rather than substituting for it.

## Omarchy shell publication checks

With the lab stopped, run:

```sh
python tests/isolated/check_shell.py --build-dir build --measure-seconds 20
```

This runner starts and stops its own private native compositor. It copies the
installed official shell QML unchanged, exposes only an empty built-in bar,
and uses private HOME/XDG paths plus D-Bus without service activation. The real
Omarchy CLI adds a temporary Git snapshot, enables and summons the launcher,
disables/re-enables it, and removes it. The actual native editor is pre-staged
as an external dependency; this test does not install the native backend.
It verifies one editor window, definition preservation, idle helper census,
and cleanup without touching the running production shell.

Results remain local under `evidence/publishing/`. To check a native update from
an alternate build directory in an already-running empty private lab:

```sh
python tests/isolated/check_update.py --build-dir build-publish-native
```

## Original physical-desktop checks

These tools operate on the real Hyprland session. They are test-only and are not
installed with the plugin. They do not modify desktop configuration.

`native_profiles_check.py` validates the profile picker with real native input.
It requires workspace `zones-profiles-test`, a native test window titled
`Zones profiles A`, and the four-profile fixture printed by:

```sh
python tests/native_profiles_check.py --print-fixture
```

The runner never writes that configuration itself. Back up the user's definitions
and intentionally prepare the fixture before running it; restore definitions and
the original desktop afterward. It checks hotkey-only visibility, miniature and
full-size drops, native title-bar dragging, ordinary dragging, cancellation, tray
gutters, unchanged other clients, and text texture cleanup. It writes a screenshot
and `native-profiles.json` under `evidence/`. The monitor assumptions are checked
before input starts. Run it only during an agreed desktop-control interval:

```sh
python tests/native_profiles_check.py
```

The `editor-profiles` CTest uses Qt offscreen with a temporary XDG configuration
directory. It complements native testing and never injects input into the desktop.

The original `native_drag_check.py` runs the six v1 drag scenarios recorded in the validation
report. It requires the dedicated `zones-poc` workspace, a native test window
titled `Zones validation A`, and two saved DP-2 zones that cover the test path.
Close the editor first and leave the mouse/keyboard idle during the run. It moves
and resizes the test window. It refuses to start with another layout and stops
input if the active workspace changes. Run it only when you intend to give it
temporary control of the desktop:

```sh
python tests/native_drag_check.py
```

## Build and launch

```sh
./tests/build-native-tools.sh
QT_QPA_PLATFORM=wayland ./build/tests/native-window 'Zones test A'
```

`native-window` is a real Qt Wayland client with a draggable title bar. Its title
bar calls `QWindow::startSystemMove`, so tests exercise native compositor dragging.
Check `hyprctl -j clients` for its address, geometry, and `xwayland: false`.
The application prints `platform wayland` and reports accepted/rejected system
move requests. Use a dedicated temporary workspace for integration tests.

## Real input

The input helper requires existing write access to `/dev/uinput`. On the inspected
machine, the logged-in user already has this ACL. No new daemon, package, ACL,
udev rule, or elevated permission is required. The process creates a temporary
virtual keyboard/mouse and removes it on exit. EOF, SIGINT, and SIGTERM release
held keys before removal.

For low-level commands:

```sh
./build/tests/native-input <<'INPUT'
key KEY_LEFTCTRL down
button BTN_LEFT down
move 300 0 30 16
button BTN_LEFT up
key KEY_LEFTCTRL up
quit
INPUT
```

Run this only after placing the pointer over the intended test window. This
example uses Control as the plugin trigger; substitute the actual configured
modifier. Relative motion uses the desktop's normal pointer acceleration.

For accurate positions without changing pointer settings, use the Python helper
from the repository root:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path('tests').resolve()))
from native_driver import NativeInput, hyprctl_json

# Obtain this rectangle from hyprctl clients immediately before the drag.
x, y, width, height = 100, 100, 600, 400
with NativeInput() as pointer:
    pointer.move_to(x + width // 2, y + 30)
    pointer.key('KEY_LEFTCTRL', True)  # Use the actual configured trigger.
    pointer.button(down=True)
    pointer.move_to(400, 700)
    # Take an overlay screenshot here before releasing the button.
    pointer.button(down=False)
    pointer.key('KEY_LEFTCTRL', False)
print(hyprctl_json('clients'))
```

`move_to` reads the actual cursor position and compensates for acceleration.
This feedback loop belongs to the explicit integration test, not the product.
`NativeInput` closes its helper and releases all keys when the context exits,
including after assertion failures. The input helper accepts numeric Linux key
codes for keys not included in its named aliases.

A complete native validation should capture:

1. Client geometry before and after a trigger-held drag into a zone.
2. A screenshot while the pointer is over a zone, showing overlay and target.
3. Adjacent zone rectangles before and after moving their shared boundary in
   the editor, including an exact numeric edit.
4. All existing client geometries before and after saving editor changes.
5. A title-bar drag without the plugin trigger: normal movement, no snapping.
6. A drag with the trigger released before mouse release: no snapping.
7. Geometry after unload and after reinstall, with existing desktop settings
   and independently installed plugins preserved.

## Idle measurement

Close the editor and test windows, settle the desktop, and keep the same visible
applications in both runs. Load/unload the plugin outside this script.

```sh
./tests/measure_idle.py --label unloaded --duration 30 --output /tmp/zones-unloaded.json
# Load the plugin, then allow the desktop to settle.
./tests/measure_idle.py --label loaded --duration 30 \
  --baseline /tmp/zones-unloaded.json --output /tmp/zones-loaded.json
```

The sampler measures Hyprland and named plugin helpers. Pass `--pid` or `--name`
for any other helper processes. It records process identity, CPU tick deltas,
RSS, and proportional set size (PSS) at both endpoints. CPU is a percentage of
one CPU core. PSS is preferable to summed RSS because it apportions shared pages.
The measurement does not capture memory peaks or helpers that start and stop
between endpoints. CPU includes unrelated compositor rendering, and small
loaded/unloaded differences include allocator and workload noise. Repeat paired
runs when small deltas would otherwise lead to an unsupported conclusion.
