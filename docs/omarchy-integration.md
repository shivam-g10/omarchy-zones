# Omarchy integration

The root manifest uses schema version 1, ID `omarchy-zones`, kind `service` and
entry point `shell/Service.qml`. The service runs inside the existing
`omarchy-shell`; editor and overlay components load on demand.

## Installation contract

Omarchy's Git installer clones and validates a repository, then optionally enables
its plugin. It executes no repository hooks or privileged commands. Updates
fast-forward source; removal disables and removes the shell checkout.

`scripts/setup.sh`, backed by `scripts/manage.py`, explicitly installs the
additional desktop integration: a marked `dofile` block for `shell/bindings.lua`,
a command launcher and an application entry. It then enables the service.
Local-checkout installation copies runtime files into the user plugin directory;
same-directory Git installation preserves the checkout.

Run setup removal before `omarchy plugin remove omarchy-zones`. Setup removes
owned integration and keeps profiles and plugin source; Omarchy can then remove
the source directory. Profiles remain outside that directory. Setup honors XDG
configuration/data paths, while Omarchy's Git installer uses its home-directory
plugin path.

## Runtime access

```sh
omarchy-zones
omarchy-shell omarchy-zones openEditor
omarchy-shell omarchy-zones status
```

Enabling the service enables gesture handling. Disabling it cancels pending work
and unloads its UI. Save and close the editor before disabling, updating,
removing or reloading. Ordinary dragging and Exposé remain independent.

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
