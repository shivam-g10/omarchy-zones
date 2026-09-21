# Maintenance

The plugin is a QML service in Omarchy's existing shell. JavaScript handles model
logic; an in-memory bridge to Hyprland's built-in Lua API handles native gestures
and final placement. The editor and overlay load on demand.

## Code map

| File | Responsibility |
| --- | --- |
| `qml/0.5.0/Service.qml` | Gesture state, bounded socket requests, IPC and loaders |
| `qml/0.5.0/Editor.qml` | Definition draft, profile operations and shared-boundary controls |
| `qml/0.5.0/Overlay.qml` | Zones, hover highlight and profile miniatures |
| `qml/0.5.0/Geometry.js` | Validated rectangle movement and shared-edge edits |
| `qml/0.5.0/Profiles.js` | Bounded profile parsing, validation and serialization |
| `qml/0.5.0/Layouts.js` | Picker layout and layout helpers |
| `qml/0.5.0/Store.qml` | FileView persistence, notifications and profile validation |
| `qml/0.5.0/Runtime.js` | Embedded Lua for binding ownership, cancellation and one-time snap handshake |

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

The store uses Quickshell's native `FileView` for reads, writes and file-change
notifications. It spawns no helper processes. Save errors preserve pending edits.
Files follow FileView's standard permissions and symlink semantics; this is a
user-owned configuration path, not a hardened reader for hostile files. The
128 KiB content limit is checked after reading, so it does not cap the initial
file allocation. Atomic writes do not guarantee durability across every
filesystem failure.

The UI imports `qs.Commons` and `qs.Ui` for Omarchy colors, borders, spacing,
controls and fonts. Geometry uses logical monitor pixels and reserved space;
compositor borders extend outside client rectangles.

## Plugin lifecycle

`manifest.json` declares ID `omarchy-zones`, kind `service` and entry point
`qml/0.5.0/Service.qml`. Standard Omarchy add, enable, update and remove commands own
the checkout and enabled state. No setup script, launcher installation or
persistent Hyprland configuration edit is required.

The service loads the Lua bridge into the running compositor and registers only
its own bindings. Disable cancels pending gestures and releases owned bindings.
Hyprland retains a bounded set of inert callback handles until its next normal
configuration reload; re-enable reuses them. The plugin must not force a reload
or overwrite another application's bindings.

Test repeated enable/disable, source update, shell restart, Hyprland reload and
removal with the real Omarchy loader. Confirm that callbacks do not accumulate,
profiles survive, ordinary dragging works, and unrelated files remain unchanged.
Model tests alone cannot establish these lifecycle properties.

See [validation](validation.md) for measured behavior and remaining limits.
