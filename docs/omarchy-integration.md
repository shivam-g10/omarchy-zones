# Omarchy integration

The root manifest uses schema version 1, ID `omarchy-zones`, kind `service` and
entry point `qml/0.5.0/Service.qml`. The service runs inside the existing
`omarchy-shell`; editor and overlay components load on demand.

## Installation contract

Omarchy's Git installer clones and validates a repository, then optionally enables
its plugin. It executes no repository hooks or privileged commands. Updates
fast-forward source; removal disables and removes the shell checkout.

The standard lifecycle is sufficient:

```sh
omarchy plugin add https://github.com/shivam-g10/omarchy-zones.git --enable
omarchy plugin update omarchy-zones
omarchy plugin remove omarchy-zones
```

The plugin registers its hotkeys through Hyprland's built-in Lua API at runtime.
It does not write Hyprland configuration, install launcher files or run a setup
script. Omarchy owns its normal plugin checkout and enabled-state changes.
Profiles live outside the checkout, under `$XDG_CONFIG_HOME/omarchy-zones` or
`~/.config/omarchy-zones`, and survive removal.

## Runtime access

```sh
omarchy-shell omarchy-zones openEditor
omarchy-shell omarchy-zones status
```

Press **Super+Shift+F8** to open the editor. The optional IPC commands above call
the same loaded service; no separate application launcher is installed.

Enabling the service registers gesture handling. Disabling it cancels pending
work, releases owned bindings and unloads its UI. Save and close the editor
before disabling, updating, removing or reloading.

Hyprland retains a bounded set of inert callback handles until its next normal
configuration reload. Re-enabling reuses those handles; the plugin does not
force a compositor reload. This bridge is needed because Quickshell's global
shortcut API registers named endpoints, not physical key combinations or native
window-drag observers.

## Identifier and marketplace

The ID is **`omarchy-zones`**. The installed CLI validator accepts it; the reserved
prefix is `omarchy.` with a dot, not `omarchy-`.

Git distribution and marketplace listing are separate. The publishing guides
recommend namespaced IDs, and the registry inspected on 20 September 2026
required a publisher/plugin namespace. Recheck that rule and select a project
license before a listing. Local validation does not establish marketplace
acceptance. No marketplace submission workflow is configured.

## Official references

- [Development guide](https://plugins.omarchy.org/develop.html)
- [Publishing guide](https://plugins.omarchy.org/publish.html)
- [Shell plugins manual](https://omarchy.org/manual/shell-plugins/)
- [Runtime and manifest reference](https://github.com/omacom/omarchy/blob/quattro/shell/README.md)
- [CLI validator](https://github.com/omacom/omarchy/blob/quattro/bin/omarchy-plugin-validate)
- [Registry namespace validation](https://github.com/omacom/omarchy-plugin-registry/blob/main/app/services/registry/manifest_validator.rb)

The installed shell loader and command sources were inspected alongside these
references.
