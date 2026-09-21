# Maintenance

The plugin is a QML service in Omarchy's existing shell. JavaScript handles model
logic; Hyprland Lua handles the native gesture and final placement. The editor
and overlay load on demand.

## Code map

| File | Responsibility |
| --- | --- |
| `shell/Service.qml` | Gesture state, bounded socket requests, IPC and loaders |
| `shell/Editor.qml` | Definition draft, profile operations and shared-boundary controls |
| `shell/Overlay.qml` | Zones, hover highlight and profile miniatures |
| `shell/Geometry.js` | Validated rectangle movement and shared-edge edits |
| `shell/Profiles.js` | Bounded profile parsing, validation and serialization |
| `shell/Layouts.js` | Picker layout and layout helpers |
| `shell/Store.qml` | File notifications, bounded reads and atomic saves |
| `shell/bindings.lua` | Activated drag, cancellation and one-time snap handshake |
| `scripts/manage.py` | Owned plugin files, Hyprland integration and lifecycle |

## Gesture lifecycle

An activated mouse press captures the current window for that gesture only.
Lua emits a begin event; the service reads usable monitor geometry and snapshots
the saved definitions. Cursor sampling runs at 30 Hz while active, through the
compositor socket. Only one request is in flight; release/control requests take
priority over another sample. No cursor helper process is spawned.

Release supplies the final cursor position. The service resolves a zone and
requests one placement. Lua validates the token and window, clears its transient
reference before changing geometry, and expires unanswered releases. Modifier
release, target closure, desktop changes and teardown cancel pending work.
The timer stops and overlay unloads when the gesture ends.

No snapped-window registry exists. Editor actions change definitions only, and
saving cannot modify an active gesture's snapshot. Floating-window stacking
remains the compositor's normal behavior.

## Editor, storage and theme

One editor is loaded on demand. Relaunching activates its existing draft. Save
and close before updating, disabling or reloading the service: unloading also
destroys that draft. Shell caches can remain after UI components unload; use
measurements rather than visibility to assess memory release.

Profiles live at `$XDG_CONFIG_HOME/omarchy-zones/zones.conf`, defaulting to
`~/.config/omarchy-zones/zones.conf`. Both v1 and v2 files are accepted; v1 converts
only on successful save. Limits are 12 profiles, 64 zones per profile, a 128 KiB
file and a minimum zone extent of 32 logical pixels. Invalid edits leave the
previous layout intact.

The store watches file notifications. Short-lived bounded commands validate
regular files and UTF-8, then save through a private temporary file and atomic
replacement. Paths and content use arguments/stdin, not shell-source interpolation.
Save errors preserve pending edits. Atomic replacement is not a guarantee of
crash durability across every filesystem failure.

The UI imports `qs.Commons` and `qs.Ui` for Omarchy colors, borders, spacing,
controls and fonts. Geometry uses logical monitor pixels and reserved space;
compositor borders extend outside client rectangles.

## Installation and ownership

`manifest.json` declares ID `omarchy-zones`, kind `service` and entry point
`shell/Service.qml`. Setup adds the Lua integration and launcher, then enables
the service. Omarchy add/update/remove commands do not execute repository hooks.

The manager preserves unrelated configuration and rejects modified owned files.
Setup removal disables the service and removes owned desktop integration while
keeping profiles and plugin source. The official remove command can then delete
or back up the remaining source directory. Test these properties when packaging
changes; geometry tests cannot establish installer safety.

See [validation](validation.md) for measured behavior and remaining limits.
