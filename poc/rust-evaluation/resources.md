# Resource measurements

These are observations from the isolated native Wayland PoCs on 20 September
2026, not predictions for a finished migration. The same Hyprland process ran
at 1280 × 900, scale 1, without animations, shadow, or blur. Test windows and
inputs used only the private compositor. All experiments and their compositor
were stopped afterward.

## Incremental native plugin cost

The plugin first completed an actual snap. Its test window and virtual-input
helper then exited. Two 20-second idle samples used the same warmed compositor,
first with the plugin loaded, then unloaded.

| Compositor state | RSS | PSS | Private memory | CPU, one core |
| --- | ---: | ---: | ---: | ---: |
| Warm plugin loaded | 261,820 KiB | 173,464 KiB | 153,216 KiB | 0.05% |
| Plugin unloaded | 261,612 KiB | 173,256 KiB | 153,008 KiB | 0.00% |
| Loaded minus unloaded | **208 KiB** | **208 KiB** | **208 KiB** | **0.05 percentage points** |

The loaded interval recorded one 10 ms accounting tick; the unloaded interval
recorded none. This is too small a difference to confidently attribute to the
plugin rather than ordinary compositor activity. It is not evidence of an idle
timer or a guarantee of zero CPU. Source inspection found event callbacks and
deferred event-loop work, with no polling or periodic timer. Descendant censuses
before and after both samples found no resident helper process. The measurement
controller slept during sampling; no virtual-input process was present.

An earlier pre-gesture pair measured +160 KiB RSS and +226 KiB PSS with zero CPU
ticks in either interval. The warm result above is the more relevant figure.
Loading/unloading does not necessarily return all allocator or renderer caches;
the order and retained state limit how precisely either delta represents a
fresh-session installation.

## Editor open and idle

Each editor had completed numeric and mouse editing, saving, and an event-driven
theme refresh before its 20-second idle sample. Neither editor remains running
after closing. There is no separate editor service.

| Editor | RSS | PSS | Private memory | CPU, one core | Threads | Resident helpers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qt Bridges 0.2.0 | 180.3 MiB | **75.5 MiB** | 53.4 MiB | 0.00% | 11 | 0 |
| CXX-Qt 0.10.0 | 182.7 MiB | **77.6 MiB** | 55.4 MiB | 0.00% | 11 | 0 |

RSS counts shared mapped pages in full. PSS apportions them among processes, so
it is more useful when discussing cumulative application memory. These rows are
editor-process costs, not a measured whole-desktop increase. Qt renderer and
filesystem-watcher threads are included in the process measurements. Endpoint
censuses found no editor child process. Startup or theme refresh launches three
short-lived read-only `hyprctl getoption` processes; none persists at idle.

The sampled compositor consumed approximately 163.3 MiB PSS while either editor
was open. The native sentinel window used approximately 30.4 MiB PSS. Those are
test infrastructure and whole-compositor values, not additional permanent
plugin services. All three sampled processes recorded zero idle CPU ticks.

There was no controlled comparison against an equivalent C++ implementation of
this QML interface. These results do not establish that Rust, Qt Bridges, or
CXX-Qt is inherently faster or lighter. The small difference between editor
samples is not a basis for selecting a framework.

## Active work

Boundary dragging sent approximately 25 pointer moves per second for 10 seconds.
Both editors used the same interface, control geometry, and input pattern.

| Sample | Editor CPU | Nested compositor CPU | Input-helper CPU | Sentinel CPU |
| --- | ---: | ---: | ---: | ---: |
| Qt Bridges boundary drag, 249 moves | 1.90% | 0.60% | 0.00% | 0.00% |
| CXX-Qt boundary drag, 250 moves | 1.99% | 0.30% | 0.00% | 0.00% |

The test-only input helper used 636–638 KiB PSS during these samples and exited
after input. The editors' active PSS was 75.6 and 77.6 MiB respectively. The
Python stimulus controller is not included in this editor table; it is test
infrastructure, not a product dependency.

A separate native drag comparison used the same window and trajectory, again
for 10 seconds at approximately 25 moves per second:

| Native drag | Nested compositor CPU | Native window CPU | Input-helper CPU | Test controller CPU |
| --- | ---: | ---: | ---: | ---: |
| Ordinary Super drag | 0.50% | 0.10% | 0.00% | 0.10% |
| Super+Shift zones drag | 0.50% | 0.20% | 0.00% | 0.20% |

The zones sample ended with a real snap to 640,0,640,900. Ordinary dragging
retained the original 600 × 400 size. These figures include native rendering and
the nested compositor, and are not a microbenchmark of Rust or the geometry
functions. The small differences fall within the limits of these short samples.

## Evidence and limits

The original local `evidence/validation-summary.json` retains native checks,
process measurements, helper censuses, cleanup, and desktop integrity. It is
excluded from the public repository along with raw machine-specific data.
Reproduction writes `native-resources.json`, `qtbridge-idle.json`,
`qtbridge-active.json`, `cxxqt-idle.json`, and `cxxqt-active.json` under
`artifacts/`.

CPU came from `/proc/PID/stat` at 100 ticks/second. A single tick over 20 seconds
equals 0.05% of one core. Memory came from `/proc/PID/smaps_rollup` at endpoints.
Samples are not peaks and exclude GPU memory. Process censuses are snapshots;
they do not trace every short-lived process between endpoints. Source inspection
and the process snapshots support the absence of persistent product helpers.

Native nested rendering differs from the physical multi-monitor desktop.
Allocator retention, shared-library sharing, and other machine activity can
affect results. No statistical confidence interval or sustained-load claim is
made. The practical design result is that the editor can remain entirely
on-demand, while the native Rust/C++ plugin needs no extra resident process.
