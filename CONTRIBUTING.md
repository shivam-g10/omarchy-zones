# Development

Omarchy Zones runs inside the existing Omarchy shell using QML and JavaScript.
A small in-memory bridge uses Hyprland's built-in Lua API for native gestures.
The official Omarchy plugin commands handle installation and removal.

## Product boundaries

- Snapping is one-time. Editing or switching profiles must never move windows.
- Save definitions only, never window IDs, assignments or persistent links.
- Keep ordinary dragging native and preserve unrelated desktop behavior.
- Reuse Omarchy's controls and theme services.
- Do no cursor polling at idle. Measure incremental CPU/RAM including helpers.

## Checks

Work in a development checkout. Editing installed plugin source can reload the
service, so save and close its editor first.

```sh
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint -I /usr/share/omarchy/shell qml/0.5.0/*.qml
node tests/model_test.mjs
node tests/editor_callbacks_test.mjs
node tests/runtime_test.mjs
python3 tests/store_test.py
```

Node.js and Python run development tests only. `qmllint` needs the installed
Omarchy and Quickshell imports. Omarchy's manifest validator rejects symlinks
anywhere in the plugin folder, including ignored test artifacts; use a clean
checkout if needed.

For drag, geometry or lifecycle changes, also test real native windows. Verify
snapping, cancellation, ordinary dragging, shared-boundary edits, overlap
rejection, one editor with an unsaved draft, and unchanged windows after edits.
Recheck installation, update, disable, reload and removal while preserving
unrelated configuration. Record missing coverage in [validation.md](docs/validation.md).

## Structure

| Path | Responsibility |
| --- | --- |
| `manifest.json` | Stable identity and service entry point |
| `qml/0.5.0/Service.qml` | Gesture state, IPC, Hyprland queries and component loaders |
| `qml/0.5.0/Editor.qml`, `qml/0.5.0/Overlay.qml` | Editor, zones and profile picker |
| `qml/0.5.0/Geometry.js`, `qml/0.5.0/Profiles.js`, `qml/0.5.0/Layouts.js` | Rectangle edits, profile format and layouts |
| `qml/0.5.0/Store.qml` | FileView persistence and profile validation |
| `qml/0.5.0/Runtime.js` | Embedded Lua for runtime bindings and one-time release handshake |
| `tests/` | Model, callback, storage and native lifecycle checks |

Keep runtime sockets, personal profiles, desktop captures, raw measurement logs
and generated language-server settings out of Git. Public measurements belong in
`docs/performance.json`, with their scope and limitations in `docs/validation.md`.

## Distribution

Use a separate Git checkout for development. Install a committed local checkout
with `omarchy plugin add /absolute/path/to/checkout --enable`, or use the GitHub
URL in the README. Omarchy owns the installed checkout and enabled state; do not
add setup hooks, desktop launchers or persistent Hyprland configuration edits.

Keep the ID `omarchy-zones` and active version metadata consistent. Review and
validate staged files before pushing. Marketplace submission is separate from
Git distribution; recheck its current namespace and licensing requirements
before any listing. Do not add automatic publication workflows without approval.

Every release must move the complete runtime to `qml/<new-version>/` and update
the manifest version and service entry point together. Remove the previous
runtime directory in the same release. The installed loader can retain QML code
at an unchanged URL after a source update; a new versioned path gives the whole
runtime fresh URLs so standard plugin updates need no manual shell restart.
The native lifecycle check must verify that an actual source update executes
the new code.
