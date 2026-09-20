# Validation — 2026-09-20

## Editor rendering and single-instance update (0.3.1)

Version 0.3.1 is built and installed. Controls now use one antialiased outline,
the profile dropdown has rounded corners, and thumbnail height includes its
padding. Reopening settings activates the existing editor or its modal dialog
without reloading or saving pending changes. The snapping implementation did not
change; the plugin's version string was updated with the release.

### Native and automated checks

Ten checks passed with real native Qt Wayland windows in a private Hyprland
0.56.2 compositor at 1280×900, scale 1. The exact distributable was opened in
addition to the instrumented editor. Tests covered:

- Three concurrent relaunches from behind another window: one editor remained,
  with unsaved widths 768/512 intact and the saved file unchanged.
- Relaunch while the New profile dialog was behind another window: the existing
  dialog became focused and accepted typing. After dismissal and an ordinary
  click back into the editor, its unsaved geometry was still intact.
- A 28-pixel profile thumbnail fitting a 30-pixel content area in the actual
  constrained editor layout. The native popup and dialog were captured and
  inspected, including rounded borders and standard button behavior.
- Numeric and mouse shared-boundary edits, private definition-only saves, and
  unchanged sentinel-window geometry throughout edits and relaunches.
- Event-driven theme changes, zero-width borders and zero rounding, and the
  final distributable using the user's Poppins font alias.

All seven CTest targets and 20 manager tests passed. Rendering checks at pixel
ratios 1, 1.25, and 2 found no brighter corner seam: at ratio 1, the sampled
straight border was 110 and the corner peak 109 on the red channel. The layout
regression uses a constrained layout rather than assigning the expected height.
Single-instance coverage includes 13 subprocess test groups and passes ASan,
UBSan, and LeakSanitizer. Review caught a shutdown use-after-free with a connected
IPC client; it was fixed before installation, covered by regression tests, and
independently checked with the original reproducer. The rendering lifecycle
sanitizer checks and Qt/NVIDIA baseline limitation are in [maintenance.md](maintenance.md).

The isolated 0.3.0 → 0.3.1 update preserved seven fixture files and verified six
ownership hashes. The production update changed only the two binaries and their
manifest. All 165 pre-existing desktop configuration files, four saved profiles,
and four windows present immediately before updating were preserved. No desktop
configuration files were added. Installed binaries match the final build and
Hyprland reports no configuration or Zones error. Exposé was not modified or
restarted. The private compositor and test helpers exited after validation.

### Open-editor resource comparison

The old installed editor and new distributable were sampled separately for
20 seconds in the same private compositor with a native sentinel window. Both
used Poppins and the same editor dimensions. Test infrastructure was measured
separately, and before/after helper censuses were retained.

| Editor process | 0.3.0 baseline | 0.3.1 | Difference |
| --- | ---: | ---: | ---: |
| RSS | 109,100 KiB | 114,408 KiB | +5,308 KiB |
| PSS | 37,747 KiB | 39,546 KiB | +1,799 KiB |
| Private memory | 22,588 KiB | 23,548 KiB | +960 KiB |
| CPU, percent of one core | 0.0000% | 0.0500% | One extra 10 ms tick |
| Resident helper processes | 0 | 0 | 0 |

The new editor measured about 38.6 MiB PSS, an observed increase of about 1.8 MiB
while open. Endpoint memory and one CPU tick are noisy measurements, not exact
attribution to the lock or rendering code. No recurring polling or resident helper
was added; closing the editor removes the process and activation listener. Plugin
idle overhead was not remeasured for this editor-only change; the earlier 0.3.0
measurement below remains historical evidence. Peak/GPU memory and long-running
behavior were not measured.

### Limits and evidence

Native tests cover one nested display at scale 1. Fractional pixel-ratio rendering
was checked offscreen, not on a physical scaled monitor. Multiple physical
monitors, moving between different display scales, and exhaustive themes remain
unverified. The user's global theme and desktop input were not changed for tests.

Raw results, screenshots, resource samples, update verification, and a private
backup of the previous installed binaries are under `evidence/editor-fixes/`.
The portable summary is [validation-0.3.1.json](validation-0.3.1.json). Commands
are documented in [tests/README.md](../tests/README.md). Earlier sections record
their original release checkpoints.

## C++ maintenance and theme update (0.3.0)

Version 0.3.0 is built and installed. The production implementation remains C++
with a Qt Widgets editor. Shared theme
parsing, compositor rendering, Qt adaptation, geometry, and installation have
separate responsibilities documented in [maintenance.md](maintenance.md).

### Native checks

The 0.3 checks use real Qt Wayland windows and native move drags inside a private
Hyprland 0.56.2 compositor, at 1280×900 and scale 1. Virtual pointer/keyboard input
is restricted to that compositor's private socket. The production desktop never
receives test input. This is native integration coverage, not a replacement for
physical-monitor testing.

Eighteen plugin checks passed, covering hotkey-only invisibility, full-size zone
and miniature-profile drops, native title-bar movement, ordinary dragging,
modifier-release cancellation, absence of a plugin Escape handler, and unchanged
sentinel-window geometry. Five repeated gestures returned the texture cache,
retained target, and pending callbacks to their empty state. FIFO input and
overlapping profiles were rejected without blocking or snapping, and valid
profiles recovered afterward. Unload/reload cleanup passed.

The native renderer retained the active theme's cyan/gold 45-degree border,
3-pixel width, and 12-pixel radius. A private runtime configuration with three
color stops, mixed alpha values, and a 135-degree angle also passed and was
captured visually.

Seven editor checks passed with native mouse/keyboard input: live theme tokens,
numeric shared-boundary editing, mouse shared-boundary editing, definition-only
saving with unchanged sentinel geometry, event-driven palette/control changes,
runtime zero-width borders and zero rounding, and opening the exact distributable
as a native Wayland client. The numeric edit changed the two widths from
640/640 to 768/512; the mouse edit produced contiguous 873/407 widths. Saved
definitions had mode 0600. The native fixture resolved the user's `monospace`
alias to Poppins and verified that numeric fields did not overlap their help
text before or after a theme refresh. Final screenshots were inspected, including
the exact distributable and zero-border rendering. The sidebar now scrolls when
the font/window dimensions leave insufficient height.

The final release build and all four CTest targets passed, as did all 20 manager
tests. The production update then replaced only two binaries and their ownership
manifest. All 165 pre-existing desktop configuration files retained their hashes;
no configuration files were added. All four saved profiles and existing window
geometries were preserved. Six manifest hashes matched, installed binaries matched
the final build, and Hyprland reported no configuration or Zones errors. Exposé
was not modified or restarted. The private compositor and test clients were
stopped after validation.

### Resource measurements

A warmed unloaded/loaded/unloaded comparison used the same empty native
compositor. Each sample lasted 20 seconds; test windows and input helpers had
exited. A real activated drag was completed before sampling to exercise caches.

| Metric | Unloaded before | Loaded | Unloaded after |
| --- | ---: | ---: | ---: |
| RSS | 265,476 KiB | 265,812 KiB | 265,476 KiB |
| PSS | 179,281 KiB | 179,617 KiB | 179,281 KiB |
| Private memory | 159,952 KiB | 160,288 KiB | 159,952 KiB |
| CPU, percent of one core | 0.0500% | 0.0000% | 0.0000% |
| Product helper processes | 0 | 0 | 0 |

The measured increment was **336 KiB RSS/PSS/private memory** against both
baselines. Resident plugin mappings independently accounted for 336 KiB. This
is an endpoint result, not proof of zero heap allocation: allocator retention,
shared-page accounting, and compositor work can affect small differences. The
first loaded/unloaded pair was noisy (−1,168 KiB RSS and −662 KiB PSS); that raw
result is retained and is not treated as a resource saving.

Loaded idle used zero measurable CPU ticks in this sample, with 10 ms accounting
resolution. There are no resident product helpers and no recurring idle polling.
The editor's theme query process exits after each event-driven refresh. Active
CPU/GPU work, peak memory, and a long-running production-session benchmark were
not measured. On this host Hyprland already loads the same tomlplusplus library;
this measured increment must not be assumed for hosts that do not.

The exact editor distributable, open and idle with Poppins, measured 108,872 KiB
RSS and 38,465 KiB PSS (about 106.3/37.6 MiB). It accumulated zero CPU ticks over
20 seconds. The process census included the editor, test sentinel, and nested
compositor separately; no child helper remained after theme refresh. These editor
figures are process endpoints, not incremental total-system memory. Closing the
editor removes the process entirely. Raw measurements are `editor-idle.json` and
`plugin-idle-aba.json` under the evidence directory.

### Safety checks and remaining limits

Geometry and profile checks passed AddressSanitizer and
UndefinedBehaviorSanitizer. The editor's sanitizer findings and the minimal
Qt/driver comparison are detailed in [maintenance.md](maintenance.md); this is
not a claim that the complete Qt/driver stack is leak-free.

The installer checks exact owned paths, hashes, manifest shape, and compositor
ABI. Its native isolated update test successfully replaced the actual installed
0.2.0 binaries with 0.3.0, preserved seven fixture configuration/definition files,
and verified all six manifest hashes. Failure-path tests cover rollback after a
binary write failure and a rejected/partially acknowledged plugin load. Abrupt
termination and power-loss recovery remain unsupported and untested.

Current native coverage remains one display at scale 1. Multiple physical
monitors, rotation, fractional scaling, XWayland, live session locking during a
drag, and exhaustive theme/component variants remain unverified. Theme checks
include actual palette/control-file changes and runtime border changes; the
user's active theme was not switched globally. Qt editor corners cannot exactly
reproduce Hyprland rounding-power curves, and per-side shell control border
widths are not supported. Window stacking/focus policy remains unchanged.

Repeatable commands are in [tests/README.md](../tests/README.md). Raw native
results, screenshots, helper censuses, and samples are local, Git-ignored files
under `evidence/cpp-hardening/`. The sections below record earlier versions and
must not be read as new 0.3 measurements.

## Profiles update (0.2.0)

The profile picker and editor update is installed. The user's original
`DP-2 300 150 1920 1080` rectangle is preserved as **Default**, alongside Split,
Main + side, and Three columns profiles. The editor can create, duplicate,
rename, and delete profiles. The picker contains no "Esc to cancel" hint.
The existing floating-versus-tiled stacking behavior is unchanged.

Seven checks passed with a real Qt Wayland window and evdev mouse/keyboard input
on a temporary workspace. These checks did not replace compositor dragging with
direct positioning; native dispatches only restored the test's starting position.

| Check | Observed result |
| --- | --- |
| Hotkey without a drag | Picker and overlay stayed hidden; window geometry unchanged. |
| Release over Split's second miniature | Exactly one snap to `[1280, 0, 1280, 1414]`. |
| Hover Main + side, leave tray, drop into the desktop zone | Selected profile persisted through the drag; exact snap to `[1706, 0, 854, 1414]`. |
| Shift + native title-bar drag | Three columns' middle miniature snapped to `[853, 0, 853, 1414]`. |
| Ordinary Super + drag | Window moved normally at its original size; picker and overlay stayed hidden. |
| Release Shift before dropping | Preview closed and the window did not snap. |
| Release in a picker gutter | No snap, even though the gutter overlapped a valid full-size zone. |

All seven cases preserved every other client's geometry. The overlay and picker
closed after release, and the plugin's text texture cache returned to zero.
`evidence/profiles-picker.png` records the actual native picker and target preview.
The repeatable host-specific runner is `tests/native_profiles_check.py`; its raw
results are in `evidence/native-profiles.json`.

The real editor was used to add named profiles, choose a starter layout, save,
switch profiles, and move a shared boundary. Setting Split's first width to 1000
produced `[0,0,1000,1414]` and `[1000,0,1560,1414]`. Dragging that edge with the
mouse produced widths 1172 and 1388, with the adjacent X updated to 1172.
Both operations preserved every existing window. The equal 1280/1280 split was
restored afterward. The Main + side test definition was prepared explicitly after
an input sequence selected the wrong starter; its correct starter geometry was
verified in the editor source.

Geometry, profile-format, and isolated Qt editor integration tests all passed,
along with all ten reversible installer tests. The profile parser also passed
AddressSanitizer and UndefinedBehaviorSanitizer checks. The editor tests cover
legacy migration on explicit save, shared boundaries, unsaved edits across
profile/display switches, duplicate profiles including disconnected displays,
cancel rollback, and save failure recovery. The original v1 file was retained
unchanged until an explicit save from the real editor.

Installation was removed and reinstalled using the existing ownership-checked
manager. All 116 snapshotted pre-existing desktop files, including Hyprland and
independent plugin configuration, retained their hashes. The installed plugin and
editor match the final build. Configuration reload reports no errors. Original
workspace 5, cursor position, and all pre-existing window geometries were restored;
no test window, editor, or input helper remains running.

### Updated idle measurements

Two 20-second samples used the same empty workspace, Hyprland process, and warm
allocator, first unloaded and then loaded. The editor and native test client were
closed before sampling. Only Hyprland was present among the plugin/helper process
names checked; no resident helper was introduced.

| Metric | Unloaded | Loaded | Difference |
| --- | ---: | ---: | ---: |
| RSS | 349,564 KiB | 349,836 KiB | +272 KiB |
| PSS | 258,907 KiB | 259,175 KiB | +268 KiB |
| CPU, percent of one core | 0.0500% | 0.0500% | No measurable increase |
| Resident plugin/helper processes | 0 | 0 | 0 |

These are endpoint samples with 10 ms CPU accounting resolution. They include
unrelated compositor work and allocator noise, and do not measure active drag
CPU/GPU use, peak memory, or prove literally zero idle CPU cost. Raw results,
editor screenshots, saved intermediate definitions, preservation checks, and the
pre-upgrade installation backup are in `evidence/profiles-upgrade/` (Git ignored).

### Temporary test-harness crash

At 14:46:14 IST, PID 79167 (`/tmp/zones-editor-profiles-check`) aborted on an
assertion in an initial offscreen test. The harness called
`QMessageBox::done(QMessageBox::Yes)` instead of clicking the Yes button, so the
product correctly treated deletion as cancelled. Its assertion incorrectly
expected the profile to have been deleted. Clicking the actual dialog button
fixed the harness and the same checks passed. The persisted editor test reports
failures through exceptions and a nonzero exit instead of `assert`/`SIGABRT`.

`coredumpctl` recorded `__assert_fail` followed by `abort`; the captured test output
identified the failed assertion. No matching OOM journal entry was found. Full
core inspection could not resolve additional frames because the temporary binary
had already been rebuilt; no conclusions are drawn from those unresolved frames.
The extracted private core copy was deleted after inspection. This was a test
harness failure, not a crash of the installed editor or Hyprland. The harness did
not write the user's saved zones. No Omarchy upstream report is warranted.

### Remaining profile-specific limits

Native coverage is one DP-2 monitor at scale 1. Multiple monitors, fractional
scaling, rotation, dense 64-zone thumbnails, all 12 profiles visible together,
live session locking during a drag, and live theme switching remain unverified.
The lock guard and bounded tiny-zone badge were reviewed in code. Small miniature
targets can be avoided by continuing from a profile thumbnail into the full-size
desktop zone. The centered Focus starter passed automated checks; it was not
independently exercised in the final native editor build. No change to stacking
or focus behavior was implemented or claimed.

## Original 0.1.0 validation

The proof of concept was built, installed, and tested in the actual installed
Hyprland session. At that checkpoint it was installed with two saved 1280×1414
zones on DP-2. The editor was closed. The original workspace and application geometries
were restored. No commit, push, or remote repository was created.

## Native desktop checks

The test application was a real Qt Wayland client (`xwayland: false`) with a
title bar that calls `QWindow::startSystemMove()`. The helper injected real Linux
input through the user's existing `/dev/uinput` access. It did not simulate
window movement or bypass the compositor drag path. Window geometry was read
from `hyprctl -j clients`. These checks were additional to unit tests.

| Check | Observed result |
| --- | --- |
| Super+Shift+left drag | Overlay appeared; moving from zone 1 to zone 2 changed the highlighted target. |
| Release over zone 2 | Window moved to `[1000, 0]` and resized to `[1560, 1414]`, exactly matching the saved test zone. Overlay closed; snap count increased once. |
| Ordinary Super+left drag | Window moved from `[300, 250]` to `[1476, 360]`; size remained `[600, 400]`. Overlay stayed hidden; snap count did not change. Ordinary dragging also passed before installation. |
| Release Shift before dropping | Overlay closed; native drag geometry remained; no snap. |
| Escape during drag | Overlay closed; no snap. |
| Shift + native title-bar drag | Same exact zone geometry after release; native `startSystemMove` path passed. |
| Drag a tiled window | Dropping floated the dragged window and applied the exact zone geometry once. |
| Mouse shared-edge edit | Moving the divider changed widths from `1280 / 1280` to `1446 / 1114`; the right zone's X became `1446`. |
| Numeric shared-edge edit | Setting the first width to `1000` changed the adjacent X/width to `1000 / 1560`. |
| Numeric overlap attempt | Setting first-zone X to `100` while both zones filled the screen was rejected; saved definitions remained unchanged. |
| Mouse creation and movement | Drew `[1473,156,940,1101]` in free space, then moved it to `[1534,221,940,1101]`. Saved values matched the resulting canvas. |
| Delete and split | Removed the drawn rectangle, expanded the remaining zone, split it, and saved the final equal halves. |
| Existing windows after editing | All pre-existing windows, including the snapped test window, retained identical position, size, and floating state through editor changes and saves. The snapped window remained `[1000,0,1560,1414]` even after zones became equal halves. |
| Reload | Repeated `hyprctl reload` completed; `hyprctl configerrors` was empty. |
| Remove/reinstall | Removal unloaded the plugin and restored all 89 snapshotted existing desktop files byte-for-byte. Definitions survived. Reinstallation succeeded. |
| Exposé and other settings | Hashes unchanged. Only the intended marked block in `hyprland.lua` differs while installed. |

Screenshots and raw measurements are in the local, Git-ignored `evidence/`
directory: `overlay-right.png`, `editor-final.png`, `native-drag.json`,
`editor-check.json`, `editor-final-check.json`, `removal.json`, and
`final-window-preservation.json`. The host-specific reproduction tools are
documented in [tests/README.md](../tests/README.md).

## Incremental idle resources

Measured with the editor and test clients closed, on the same empty test
workspace, with the same Hyprland process. A 30-second unloaded sample was
followed by a 30-second loaded sample. This is a warm unload/reload comparison;
previous allocations can remain in the compositor allocator.

| Metric | Unloaded | Loaded | Difference |
| --- | ---: | ---: | ---: |
| Hyprland RSS | 275,996 KiB | 276,220 KiB | **+224 KiB** |
| Hyprland PSS | 208,803 KiB | 209,027 KiB | **+224 KiB** |
| CPU, percent of one core | 0.0667% | 0.0000% | No measurable increase |
| Resident plugin/helper processes | 0 | 0 | 0 |

The plugin's mapped pages independently accounted for 224 KiB RSS/PSS. Heap
allocations are part of Hyprland and cannot be separated precisely by this
sampling. CPU resolution was 10 ms; unrelated compositor work and short-sample
noise prevent a claim of literally zero CPU cost. These samples measure idle
cost, not drag-time GPU/CPU use or peak memory.

The open editor used 106,556 KiB RSS and 36,308 KiB PSS at one measured endpoint.
That is about 104.1 MiB RSS / 35.5 MiB PSS while editing, with shared Qt pages
included in RSS. It exits completely when closed; no Qt process remains idle.
The test input helper also exited and removed its virtual input device.

Raw files: `idle-unloaded.json`, `idle-loaded.json`, `plugin-mappings.json`, and
`editor-memory.json`. The earlier `idle-before.json` sample was taken on a busy
application workspace and is not used for the incremental comparison.

## Additional checks

- Release CMake/GCC build completed without compiler warnings.
- Geometry tests passed shared boundaries, T junctions, overlap rejection,
  minimum extent, bounds, and atomic rejection of invalid changes.
- Ten installer tests passed rollback, ownership checks, edited-file protection,
  exact configuration restoration, and preservation of later unrelated edits.
- Native testing caught and fixed two version-specific assumptions: plugin
  declarations must repeat on every Lua reload, and the drag-threshold flag is
  not meaningful when the configured threshold is zero.

## Limits and unverified cases

- Native validation covers one DP-2 monitor at scale 1. Multiple monitors,
  fractional scaling, rotated outputs, disconnect/reconnect, special workspaces,
  and suspend/resume were not tested live.
- The generic Qt Wayland client was tested. XWayland applications and a wider
  range of application size constraints were not tested.
- Grouped windows are deliberately excluded. Declared minimum/maximum sizes that
  conflict with a zone reject the snap instead of forcing an incorrect rectangle.
  Those rejection paths were inspected but not exercised with a constrained app.
- Shift must be held before starting the drag on this Hyprland build. Changing
  modifiers can end the native drag; the plugin preserves that native behavior.
- Zone coordinates describe client geometry; compositor borders extend outside.
- Theme colors matched the active Omarchy theme. Switching themes while the
  editor is open was not tested live; the editor uses filesystem events to reload.
- Loading into a fresh login, deliberately mismatched ABI builds, and a Hyprland
  upgrade were not tested. Rebuild after compositor upgrades.
