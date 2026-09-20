# Omarchy integration research

Checked on 20 September 2026 against Omarchy 4.0.4-1's installed commands and
the official sources linked below.

## Supported contract

Omarchy discovers a root `manifest.json` containing schema version 1, ID, name,
version, kinds, and QML entry points. Supported kinds are shell components;
there is no native Hyprland build/install kind. Panels load on demand inside
the existing Quickshell process. This repository declares a `panel` entry that
opens the separately installed native editor and then releases its own loader.

The local validator accepts `omarchy-zones`. The reserved prefix is `omarchy.`
with a dot, not `omarchy-`. The requested exact ID is retained. The general guides
recommend namespaced IDs, and the newer registry server has a stricter
publisher/plugin namespace rule. Direct Git compatibility does not establish
future marketplace acceptance; resolve that contract before submitting.

Git installation clones and validates files, then optionally enables the shell
plugin. It executes no build scripts, installation hooks, or privileged commands.
Updates fast-forward source; they do not rebuild native dependencies. Removal
disables/deletes the shell checkout without invoking native uninstall hooks.

Accordingly, `scripts/setup.sh` is an explicit user command. It builds in the
user's cache, then delegates to the existing native ownership/ABI manager.
Removal runs that manager before removing the shell checkout. Enabling or
disabling the shell launcher does not change native snapping or close unsaved
editor windows. This distinction is intentional and stated in the README.

## Why not hyprpm as well

Hyprland documents `hyprpm.toml` for native plugin builds and loading, but that
does not install the editor, hotkeys, or Omarchy integration. Adding a second
owner for the same `.so` would complicate update/removal. This PoC retains one
native manager. A later packaging change should replace ownership coherently,
not mix managers for an already-installed backend.

## Official sources

- [Omarchy development guide](https://plugins.omarchy.org/develop.html)
- [Omarchy publishing guide](https://plugins.omarchy.org/publish.html)
- [Omarchy shell plugins manual](https://omarchy.org/manual/shell-plugins/)
- [Shell runtime and manifest reference](https://github.com/omacom/omarchy/blob/quattro/shell/README.md)
- [CLI validator](https://github.com/omacom/omarchy/blob/quattro/bin/omarchy-plugin-validate)
- [Registry namespace validation](https://github.com/omacom/omarchy-plugin-registry/blob/main/app/services/registry/manifest_validator.rb)
- [Official plugin with an explicit external CLI dependency](https://github.com/basecamp/omarchy-basecamp-plugin)
- [Hyprland native plugin guidelines](https://wiki.hypr.land/hyprland-plugins/development/plugin-guidelines/)

The installed validator/add/update/remove scripts were inspected as well as the
web documentation. No registry account, marketplace submission, automatic
publishing workflow, or new resident process is part of this repository setup.
