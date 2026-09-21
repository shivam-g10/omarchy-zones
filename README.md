# Omarchy Zones

Dedicated window zones for large screens, inspired by Windows PowerToys
FancyZones. Draw a layout, choose a profile while dragging, and snap once.

**Plugin ID: `omarchy-zones` · Version: 0.5.0**

- **Precise layouts:** mouse controls, exact numeric values and shared boundaries.
- **Quick profiles:** choose a saved layout from the picker during a drag.
- **Native theme:** uses Omarchy's existing controls, colors and typography.
- **Quiet idle:** runs in the existing shell, with no idle cursor polling or extra daemon.

## Install

**Ask your Omarchy agent:**

> Install https://github.com/shivam-g10/omarchy-zones using its README.

Requires Omarchy with its Quickshell shell and Lua-based Hyprland. No build,
setup script or additional package installation is needed. See
[validation and compatibility](docs/validation.md).

```sh
omarchy plugin add https://github.com/shivam-g10/omarchy-zones.git --enable
```

Omarchy installs and enables the plugin. Hotkeys register in the running
compositor; the plugin does not edit your Hyprland configuration or install
launcher files. Saved profiles remain separate from the plugin checkout.

## Everyday use

1. Press **Super+Shift+F8** to edit profiles. Draw,
   split, move or resize zones. Shared edges grow one neighbor and shrink the
   other; overlaps are rejected.
2. Hold **Super+Shift before dragging** a window with the left mouse button.
   Hover a profile miniature or a full-size zone, then release to snap.
3. Release Shift before dropping to cancel. Ordinary Super+drag stays native.

Reopening the editor preserves its unsaved draft. Editing profiles never moves
existing windows. Only definitions are saved; there are no window assignments or
persistent links. Snapped windows float, with normal floating-over-tiled stacking.
Native title-bar-only dragging is not yet verified.

## Update or remove

Save and close the editor first. Updating or unloading a shell service discards
its unsaved in-memory draft.

**Update**

```sh
omarchy plugin update omarchy-zones
```

**Remove**

```sh
omarchy plugin remove omarchy-zones
```

Removal disables the plugin and removes its checkout. Profiles stay at
`~/.config/omarchy-zones/zones.conf`, or under `$XDG_CONFIG_HOME` when set.
Existing window positions remain unchanged.

## Performance

Measured 21 September 2026 in two private native-desktop resource rounds at
2560 × 1440, 60 Hz, with 30 Hz cursor sampling during activated gestures.
PSS covers the **whole fixture**, including shell, compositor, clients and
helpers. Phase increments use each round's disabled endpoint; the replay row
compares its stated gesture counts. CPU uses **100% = one core**. These are
observed ranges, not guarantees. They predate the 0.5.0 lifecycle and storage
changes and are not a fresh release benchmark.

| Measurement | Observed result |
| --- | ---: |
| Enabled idle: PSS / average CPU | −0.12 to +2.35 MiB / 0.015% |
| Editor visible: PSS / average CPU | +8.0–22.5 MiB / 0.029–0.031% |
| Stationary activated overlay: PSS / average CPU | +8.1–24.8 MiB / 0.517–0.620% |
| Gesture workload: average / maximum one-second CPU | 3.92–4.78% / 5.42% |
| CPU per gesture, including reset/setup | 28.70–35.17 ms |
| CPU per editor action, including probes | 6.86–7.30 ms |
| Editor window map time, 3 observations | 28.6–38.5 ms |
| Activation state: median / maximum, n=5 | 2.35 / 3.65 ms |
| Highlight state: median / maximum, n=5 | 16.83 / 17.50 ms |
| Release to correct geometry: median / maximum, n=5 | 5.42 / 5.43 ms |
| PSS retained 30 s after editor close | +10.6–26.4 MiB |
| PSS retained 30 s after 20 gestures | +12.8–25.6 MiB |
| Retention replay: growth from gesture 20 to 100 / final 40 | +9.31 MiB / about +0.07 MiB |
| Added resident helpers / continuing idle cursor queries | 0 / 0 observed |

The negative idle endpoint is measurement drift, not free RAM. The shell retains
memory after UI closes. State timings are proxies, not physical presentation
latency; five samples do not establish p95. CPU time per action is not elapsed
response time. [Methodology and limits](docs/validation.md#measurement-methodology)
· [Machine-readable measurements](docs/performance.json).

The 0.5.0 lifecycle check found no detectable idle CPU increase and no added
helper processes. [Current native validation and resource check](docs/validation.md#current-idle-and-resource-check).

## Development and diagnostics

```sh
omarchy-shell omarchy-zones openEditor
omarchy-shell omarchy-zones status
```

See [development](CONTRIBUTING.md), [maintenance](docs/maintenance.md) and
[Omarchy integration](docs/omarchy-integration.md).

The runtime uses QML and JavaScript in Omarchy's existing shell, with a small
in-memory bridge to Hyprland's built-in Lua API.

## License

A project license has not been selected yet. Public availability does not grant
a general reuse license. Licensing must be resolved before marketplace submission.
