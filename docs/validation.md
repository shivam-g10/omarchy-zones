# Validation

Evidence for Omarchy Zones 0.4.0, recorded on 21 September 2026. Tested software:
Omarchy 4.0.4-1, Hyprland 0.56.2, Quickshell 0.3.1 and Qt 6.11.2.

## Native behavior

The QML implementation passed 27 checks in a private Hyprland desktop with real
Wayland windows. Coverage included numeric and mouse shared boundaries, drawing,
splitting, deletion, profile operations, picker snaps, overlap rejection, one
editor with an unsaved draft, unchanged sentinel windows, ordinary dragging,
modifier cancellation, target closure, disable/reload cleanup and the editor
hotkey. Invalid files, Unicode names and failed save-and-close were also checked.

The measured workload completed 40 normal snaps, 80 additional retention gestures
and five maximum-layout snaps. Maximum layout was 12 profiles × 64 zones.

## Installation and live editor

Live **install → update → remove → reinstall** passed. Removal restored the owned
Hyprland integration block exactly. Four saved profiles remained unchanged, and
Hyprland reload re-enabled Lua gesture handling. Unrelated bindings, shell settings
and Exposé files were unchanged; Exposé remained enabled.

The actual Wayland editor opened as a floating 1160 × 740 window. Repeated launch
retained one instance, the four profile names matched saved definitions, and
pre-existing window geometries stayed unchanged. The editor was closed afterward.

Fourteen sandboxed installer tests, nine actual offscreen storage tests and the
JavaScript model/callback tests passed. Source parsing and official Omarchy
manifest validation passed. A three-second live observation recorded zero idle
cursor queries; it was not a CPU/RAM benchmark.

Physical dragging was not repeated during the final installation checkpoint.
The earlier native checks exercised the same gesture logic. User feedback
reported no noticeable lag on the physical desktop; that is qualitative feedback,
not an instrumented latency measurement.

[Portable verification record](validation-0.4.0.json).

## Measurement methodology

The [README performance table](../README.md#performance) is the single summary of
measured results. [performance.json](performance.json) preserves the
machine-readable values and scope. These values come from the recorded
measurement run, not a new benchmark performed while preparing the release.

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

- Physical presentation around 100 Hz has not been instrumented.
- Native title-bar-only dragging parity remains unverified; use Super+Shift drag.
- Multiple physical monitors, fractional scaling, rotation, XWayland, session
  locking during a drag and long-session retention remain unverified.
- Complete GPU memory, pressure behavior and physical display timestamps were
  unavailable in the measurement run.
- The private fixture is not an entire production desktop benchmark.

Snapping remains one-time. No automatic placement, focus management, stacking
policy or Exposé modification is part of the product.
