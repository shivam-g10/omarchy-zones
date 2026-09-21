# Development

Omarchy Zones runs inside the existing Omarchy shell using QML, JavaScript and
Hyprland Lua. Python and shell scripts provide installation and removal.

## Product boundaries

- Snapping is one-time. Editing or switching profiles must never move windows.
- Save definitions only, never window IDs, assignments or persistent links.
- Keep ordinary dragging native and Exposé independent.
- Reuse Omarchy's controls and theme services.
- Do no cursor polling at idle. Measure incremental CPU/RAM including helpers.

## Checks

Work in a development checkout. Editing installed plugin source can reload the
service, so save and close its editor first.

```sh
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint -I /usr/share/omarchy/shell shell/*.qml
node tests/model_test.mjs
node tests/editor_callbacks_test.mjs
python3 tests/store_test.py
python3 tests/install_test.py
```

Node.js runs development tests only. `qmllint` needs the installed Omarchy and
Quickshell imports. Omarchy's manifest validator rejects symlinks anywhere in the
plugin folder, including ignored test artifacts; use a clean checkout if needed.

For drag, geometry or lifecycle changes, also test real native windows. Verify
snapping, cancellation, ordinary dragging, shared-boundary edits, overlap
rejection, one editor with an unsaved draft, and unchanged windows after edits.
Recheck installation, update, disable, reload and removal while preserving
unrelated configuration. Record missing coverage in [validation.md](docs/validation.md).

## Structure

| Path | Responsibility |
| --- | --- |
| `manifest.json` | Stable identity and service entry point |
| `shell/Service.qml` | Gesture state, IPC, Hyprland queries and component loaders |
| `shell/Editor.qml`, `shell/Overlay.qml` | Editor, zones and profile picker |
| `shell/Geometry.js`, `shell/Profiles.js`, `shell/Layouts.js` | Rectangle edits, profile format and layouts |
| `shell/Store.qml` | Bounded reads and atomic saves |
| `shell/bindings.lua` | Native drag integration and one-time release handshake |
| `scripts/setup.sh`, `scripts/manage.py` | Owned installation, update and removal |
| `tests/` | Model, callback, storage and installer regressions |

Keep runtime sockets, personal profiles, desktop captures, raw measurement logs
and generated language-server settings out of Git. Public measurements belong in
`docs/performance.json`, with their scope and limitations in `docs/validation.md`.

## Distribution

Keep the ID `omarchy-zones` and active version metadata consistent. Review and
validate staged files before pushing. Marketplace submission is separate from
Git distribution; recheck its current namespace and licensing requirements
before any listing. Do not add automatic publication workflows without approval.
