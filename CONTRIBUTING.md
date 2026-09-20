# Development

Keep changes small and preserve one-time snapping: profile editing must never
move existing windows, and saved definitions must never contain window links.
Keep Exposé and unrelated desktop settings separate.

## Build and test

Use a normal development checkout, not the directory watched by Omarchy's shell:

```sh
git clone https://github.com/shivam-g10/omarchy-zones.git
cd omarchy-zones
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python tests/manage_test.py
python tests/packaging_test.py
```

The full build needs the running Hyprland's exact headers. To work on the editor
and core without compositor headers, use a separate build directory:

```sh
cmake -S . -B build-editor -DOMARCHY_ZONES_BUILD_PLUGIN=OFF
cmake --build build-editor --parallel 2
ctest --test-dir build-editor --output-on-failure
```

An editor-only build cannot be installed as a complete plugin. CI runs that
portable subset plus installer/packaging checks. CI does not prove native drag,
shell lifecycle, physical monitor, or compositor ABI behavior.

Validate a clean publication checkout with Omarchy and the installed QML tools:

```sh
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint shell/Launcher.qml
```

Omarchy's validator rejects symlinks even in ignored build directories. Validate
a clean clone or staged publication snapshot, not a checkout containing native
lab files. Native tools and controlled desktop procedures are documented in
[tests/README.md](tests/README.md). Test helpers are never installed as services.

## Structure

| Path | Responsibility |
| --- | --- |
| `manifest.json`, `shell/` | Omarchy ID, metadata, and on-demand QML launcher |
| `src/` | Native snapping, editor, geometry, profiles, theme and instance handling |
| `scripts/setup.sh` | Explicit build and native lifecycle entry point |
| `scripts/manage.py` | ABI/ownership checks, installation, update rollback and removal |
| `tests/` | Core, renderer, process, installer, packaging and native checks |
| `docs/` | Architecture, evidence summaries, compatibility and development decisions |
| `poc/rust-evaluation/` | Historical experiments; not production build inputs |

Do not commit compiler output, runtime sockets, raw desktop captures, personal
configuration, local measurement logs, or generated language-server settings.
Public validation summaries must distinguish measured results from untested
cases. Measure incremental idle CPU/RAM, including helpers, for runtime changes.

## Publishing boundary

The permanent Git-install ID is `omarchy-zones`. Keep CMake, editor, native plugin
and manifest versions consistent. Validate, build, test and inspect staged files
before pushing. Marketplace submission is a separate action; no workflow here
submits or releases automatically. Review the current official publishing rules
again before any future listing, including license and namespace requirements.
