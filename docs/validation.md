# Validation

Evidence for Omarchy Zones 0.5.0, recorded on 21 September 2026. Tested software:
Omarchy 4.0.4-1, Hyprland 0.56.2, Quickshell 0.3.1 and Qt 6.11.2.

## Native behavior and lifecycle

The final versioned runtime passed native checks with actual Wayland windows in
a private Hyprland desktop at 2560 × 1440 and its reported 60 Hz refresh rate.
The fixture uses the installed Omarchy shell loader, private configuration and
runtime paths, the active theme, and a dedicated cgroup.

- Standard add and enable alone register hotkeys and load the editor.
- Twenty snaps select the original window and the intended profile and zone.
- Modifier cancellation and target closure remove the overlay and stop queries.
- Ordinary Super+drag retains native behavior.
- Mouse and numeric shared-boundary edits grow one neighbor and shrink the other.
- Reopening preserves one editor; verified saves never move existing windows.
- Twenty disable/enable cycles retain four binds, two rules and one timer;
  active subscriptions are five, disabled subscriptions zero.
- One hundred release/cancellation cycles and disable during dragging clear state.
- A foreign same-chord binding survives disable; re-enabling refuses the conflict.
- Compositor reload, shell restart and abrupt shell termination recover without
  applying a stale snap.
- Standard plugin update executes changed QML from a new versioned directory
  and snaps without restarting the shell. Removal preserves profile/config bytes.

The fixture stopped with no remaining child processes and no changed parent
desktop configuration. The separate model/editor callback tests, 13 real
Quickshell storage tests and 100 mocked runtime lifecycle cycles also pass.

A loader cache issue was found during testing: same-path QML updates can retain
old components on this Omarchy version. Versioned runtime directories give each
release fresh component URLs, including its JavaScript and editor dependencies.
No installer or automatic whole-shell restart is needed.

[Portable verification record](validation-0.5.0.json).

## Live installation

The previous development installation was backed up and its owned configuration
block, launcher and receipt removed. Standard `omarchy plugin add --enable`
then installed 0.5.0. All four profile definitions remained byte-identical;
unrelated desktop settings and Hyprland files were preserved. Hyprland reported
no configuration errors and the runtime was ready with zero cursor queries over
three idle seconds. Existing window geometries were unchanged.

A physical mouse/keyboard check was not repeated: the requested supervised
input interval was not confirmed. The earlier physical feedback remains
qualitative; the new native behavior evidence comes from the private fixture.

## Current idle and resource check

Two reversed 30-second enabled/disabled pairs showed enabled CPU of
0.0146–0.0152% of one core. Disabled runs were 0.0166–0.0348%; no idle CPU
increase was detected. Enabled-minus-disabled PSS endpoints were −0.090 and
+0.324 MiB. Negative differences are noise, not memory savings.

No product helper processes or continuing idle cursor queries were observed.
The fixture includes the shell, compositor, native clients and existing host
helpers, including its plugin watcher. The disabled baseline followed warm use
and retains the fixed Lua slots and shell caches; it is not a pristine compositor.

Editor-visible CPU was 0.0471% of one core over 30 seconds. The 20 rapid native
snaps consumed 15.62% over 2.48 seconds, about 19.39 CPU ms per gesture including
reset/probe-triggered work. This rapid check is not the same workload as the
older benchmark and cannot establish a performance improvement. PSS was about
9.48 MiB above the last disabled endpoint 30 seconds after this activity; no
long-session retention claim follows from this short run.

[Raw resource JSON](performance-0.5.0.json) and [CSV](performance-0.5.0.csv) retain
sparse endpoints. These samples preceded the final error-window cleanup and
versioned-path packaging; normal gesture and storage paths were unchanged.

## Measurement methodology

The [README performance table](../README.md#performance) summarizes the current
idle memory check above. The earlier benchmark's full measurements and scope
remain in [performance.json](performance.json). The methodology below describes
that earlier run, not a new benchmark performed while preparing the release.

The fixture used real Wayland windows at 2560 × 1440 and 60 Hz, an empty bar and
no unrelated first-party services. Cursor sampling was 30 Hz during activated
gestures. Memory ranges cover two resource rounds, each relative to its own
disabled endpoint. Fixture PSS includes compositor, shell, editor, clients and
helpers; it is not the plugin's isolated heap. Shared pages, allocator caches
and workload history affect endpoints. A small negative increment is drift,
not memory savings. CPU percentages use 100% for one core.

Editor opening reports three observed window-map times. Activation, highlight
and release report medians and maxima from five samples each. State changes and
correct geometry are latency proxies, not physical presentation timestamps;
five observations do not support reliable p95 estimates. CPU per editor action
includes inspection probes. CPU per gesture includes reset/setup work, so neither
is a pure UI response-time measurement.

The resource sampler ran outside the measured fixture and consumed about 0.15%
of one core. A separate harness diagnostic measured about 30.4 ms CPU per gesture
for its input/IPC orchestration, accounted separately from fixture CPU. These
observations do not establish a precise instrumentation-overhead bound.

Retention was sampled after editor close and gestures. A continued replay from
20 to 100 gestures flattened during its final 40 gestures. No forced garbage
collection was used. That finite run neither proves long-session boundedness nor
identifies a leak. Closing the UI does not immediately return all shell memory.

## Remaining limits

- The physical display input check was not repeated; the private fixture does
  not establish approximately 100 Hz physical presentation.
- Native title-bar-only dragging parity, multiple monitors, fractional scaling,
  rotation, XWayland and session locking during a drag remain unverified.
- Disabled Lua registrations remain until compositor reload. Abrupt shell death
  can leave registrations until the shell recovers or the compositor reloads;
  release handshakes expire and the dead shell cannot issue cursor queries.
- Quickshell FileView allocates before size validation and follows symlinks with
  platform permissions. It exposes no hard I/O cancellation deadline. A fresh
  read verifies saves before they are acknowledged.
- Complete GPU memory, pressure behavior, physical display timestamps and
  long-session retention were not measured in this release check.

Snapping stores zone definitions only and never maintains window assignments.
