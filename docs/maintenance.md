# Maintenance

The product remains C++ with a Qt Widgets editor. The Rust experiments under
`poc/rust-evaluation/` are separate research artifacts and are not built or
installed by the production CMake project.

## Code map

| File | Responsibility |
| --- | --- |
| `src/plugin.cpp` | Native Hyprland drag events, profile picker, rendering, one-time snap, and transient state cleanup. |
| `src/editor.cpp` | Qt Widgets editor, monitor validation, profile operations, shared-boundary input, and atomic profile saves. |
| `src/geometry.hpp` | Rectangle validation and transactional movement/shared-boundary changes, independent of Qt and Hyprland. |
| `src/profiles.hpp` | Bounded profile format parsing, name/coordinate validation, and serialization. |
| `src/theme.hpp` | Bounded TOML input and shared palette, gradient, control-state, and font values. Contains no Qt/compositor objects. |
| `src/editor_theme.hpp` | Qt palette/style adaptation and event-driven theme refresh while the editor is open. |
| `src/editor_instance.hpp` | Configuration locking and bounded, same-user local activation requests. |
| `src/editor_activation.hpp` | Revealing the existing editor or modal dialog on an explicit relaunch. |
| `scripts/manage.py` | Ownership-checked installation, binary updates with rollback, and reversible removal. |

The editor never dispatches window movement. The plugin holds a weak reference
only during the current drag and its deferred drop callback. Saved data contains
zone definitions, not window identities or assignments. Preserve these boundaries
when adding features.

## Theme behavior

The reader uses `$XDG_STATE_HOME/omarchy/current/theme`, falling back to
`~/.local/state/omarchy/current/theme`. `colors.toml` supplies palette colors;
`shell.toml` supplies normal, hover, focus, selected, pressed, and text-selection
control tokens plus the base font size. Validated values are converted into Qt
styles or compositor render values; raw theme text is never inserted into a style
sheet. Invalid or missing values use bounded defaults.

The compositor's current border settings take precedence over file defaults.
Gradients retain their color stops, alpha, and angle. The editor follows the live
border width and corner radius; the native overlay also uses Hyprland's rounding
power. Labels use the same `monospace` fontconfig alias as the Omarchy shell.
Small preview elements scale their geometry to remain usable. Numeric fields and
dropdowns use a locally owned Qt base style and draw themed arrow glyphs over
Qt's own subcontrol rectangles. Qt retains stepping, repeat, keyboard, wheel,
accessibility, and popup behavior. Numeric rows use their current font metrics and intrinsic layout sizes. The
sidebar scrolls when a short window or larger font leaves insufficient room,
rather than compressing controls into each other.

Control outlines use one antialiased closed path. Qt's stylesheet border reserves
layout space but remains transparent, avoiding the brighter seams caused by
overlapping translucent corner segments. Parent-owned, input-transparent outline
widgets preserve standard Qt control classes, dialog roles, and input handling.
Profile miniatures use the display pixel ratio; combo height includes the icon
and padding. The popup uses a public QListView with a rounded themed surface.

The open editor watches theme files and their parents, local Hyprland files,
fontconfig, and the Omarchy window-gap toggle. Notifications start a single-shot
200 ms debounce, then a short-lived asynchronous `hyprctl` query with a 1.5 second
deadline. Watches are reattached after atomic replacements or a changed theme
symlink. There is no recurring polling timer or resident query process. The
native plugin refreshes theme values on an activated drag and configuration
reload, without a background theme watcher.

This is a targeted theme adapter, not an implementation of every Omarchy shell
component. Control border widths are uniform; per-side border-width overrides
are not supported. Qt uses circular rounded corners rather than Hyprland's
rounding-power shape inside the editor. Arbitrary theme-specific shell surface
layouts and component overrides are outside this adapter.

## Single editor lifecycle

Before reading profiles, the editor acquires a kernel `flock` on the empty,
owner-only `.editor.lock` beside `zones.conf`. The stable inode survives atomic
profile saves and is never unlinked on exit. Kernel cleanup releases a crashed
process's lock. A later launch can then remove the stale application socket.

The activation socket lives in a private directory under `XDG_RUNTIME_DIR`.
Its identity includes the canonical configuration path and desktop session.
Peer credentials restrict requests to the same user. Input length, client count,
connection lifetime, and startup waits are bounded. A busy or inaccessible owner
causes an error rather than opening a competing editor. Different desktop sessions
cannot edit the same configuration simultaneously.

An activation request reveals the existing editor, preferring an open modal
dialog. On Hyprland, a bounded, short-lived `hyprctl` query finds a mapped surface
belonging to this editor process, then focuses its validated address. This runs
only on an explicit relaunch and never moves or resizes other windows. The socket
adds no recurring timer or helper process. It carries an activation command only;
it does not transfer profiles, window assignments, or unsaved changes.

Shutdown disconnects and destroys server-owned sockets before destroying their
callback state, including sockets already queued for deferred deletion. Thirteen
subprocess test groups pass under ASan, UBSan, and LeakSanitizer. They cover live
connections during shutdown, startup races, crash recovery, stalled owners,
malformed clients, and unsafe paths. A nonempty pre-existing lock file is rejected
without changing its contents or permissions.

## Safety and lifetime changes in 0.3

- Rectangle edges and boundary arithmetic use 64-bit intermediates. Resized
  extents are checked before narrowing. Invalid proposals leave layouts intact.
- The editor validates logical monitor dimensions and reserved space before
  converting coordinates. An oversized saved zone on a smaller display can be
  resized or deleted; dragging it no longer passes an inverted range to
  `std::clamp`. Canvas selections are checked before indexing.
- Profile and theme reads open nonblocking descriptors, require regular files,
  and enforce size limits while reading. A FIFO cannot stall the compositor or
  editor, and file growth cannot bypass a prior size check.
- Editor saves use atomic replacement with direct-write fallback disabled and
  owner-only permissions. A symbolic-link destination is rejected. A failed
  save preserves pending edits. Dynamic profile names and error text are shown
  as plain text.
- Canvas access now checks selection bounds; the existing stable display buffer
  remains independent of profile-vector reallocations. Theme callbacks use a
  guarded Qt pointer so they cannot call an editor that has already been destroyed.
- Deferred compositor callbacks are tracked and cancelled during unload and
  interrupted gestures. Snap callbacks use a weak target and recheck window,
  monitor, lock, and drag state before touching geometry. Plugin event callbacks
  catch C++ exceptions, cancel transient work, and report a bounded error.
- Picker textures are bounded and released after the gesture. Resetting theme
  state clears cached text textures so old colors cannot remain in the picker.
- The installer validates the exact manifest shape, owned path set, and hashes;
  a forged manifest cannot name arbitrary files for removal. Symlink and modified
  file checks protect later user edits. The `update` command replaces binaries
  without removing and recreating the desktop integration.

These changes address concrete unsafe paths and make their boundaries easier to
review. They are not a security audit or a guarantee that a C++ plugin cannot
crash its host compositor. Hyprland's exact plugin ABI remains a requirement.

The updater rolls back handled errors, including a rejected new plugin or a
failed binary write. Its rollback snapshots live in process memory: abrupt
termination or power loss between replacements is not a crash-durable
transaction and can require manual recovery. It does not silently overwrite
owned files that another process changes during the update.

## Checks and limits

The Qt integration test covers profile switching and editing, shared boundaries,
legacy preservation, failed-save recovery, symlink rejection, private saves,
FIFO rejection, invalid monitor geometry, oversized zones, and stale selections.
Geometry/profile tests also exercise invalid and extreme input. Theme tests
cover parsing and token fallback separately from rendering. Native-window
results and resource measurements are recorded in [validation.md](validation.md).

AddressSanitizer and UndefinedBehaviorSanitizer passed the editor test with
leak detection disabled. LeakSanitizer was also run separately: the host's
GTK platform theme reported fontconfig/Pango allocations at exit. Using the
Fusion style and generic platform theme reduced the report to 183 bytes in four
allocations from `libnvidia-glcore`. A minimal QApplication/QLabel-only program
reproduced exactly the same 183-byte report. This does not establish a leak-free
Qt/driver stack or prove the absence of every editor leak.

The local comparison logs are `build/editor-profiles-sanitized.log` and
`build/qt-sanitizer-baseline.log`; build artifacts are intentionally ignored by
Git. Sanitizer tests use the offscreen Qt platform and complement, rather than
replace, real native-window checks. Test input and measurement helpers are never
installed as product services.

The 0.3.1 outline and popup changes also passed 32 repeated create/show/theme
refresh/input/destroy cycles under ASan and UBSan. A fresh minimal Qt label
program reproduced the same 183-byte NVIDIA leak report when leak detection was
enabled. Logs are under `build/render-fixed/`; these checks do not establish
long-running or platform-wide leak freedom.
