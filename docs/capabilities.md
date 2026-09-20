# Inspected desktop capabilities

Inspected on 2026-09-20 before implementation:

- Omarchy 4.0.4-1, with Lua Hyprland configuration and a Quickshell desktop shell.
- Hyprland 0.56.2, commit `efb50993780079460b0cbed1363e2166a2de1d9f`.
- The installed GCC version matches Hyprland's build compiler: GCC 16.2.1.
- Qt 6 Widgets and Qt Wayland 6.11.2 are installed.
- One active DP-2 monitor: 2560×1440, scale 1, with a 26-pixel bottom reservation.
- Stock window dragging is Super+left mouse. Super+Shift+left mouse and
  Super+Shift+F8 were unbound. Exposé is independently installed.
- The active Omarchy theme lives under `~/.local/state/omarchy/current/theme`;
  `colors.toml` supplies the editor and overlay colors.

## Why a native plugin

The installed `/usr/share/hypr/stubs/hl.meta.lua` exposes keyboard events but no
pointer movement/button Lua events. The native
`/usr/include/hyprland/src/event/EventBus.hpp` exposes typed pointer, keyboard,
render, monitor, window-close, and config events. The native drag controller
identifies the actual window being moved. This permits event-driven operation
without a separate process polling cursor/window positions.

The plugin observes these events without consuming them. It adds render-pass
rectangles to the existing compositor and schedules only one-shot deferred
callbacks after native input handling. It does not install a compositor function
hook, replace the drag controller, or run a frame timer.

The editor is a separate Qt application. It reads monitor geometry and live
border settings from Hyprland. An explicit relaunch also queries mapped clients
and focuses the existing editor or its modal dialog, restricted to surfaces
owned by that editor process. It has no operation that moves or resizes desktop
windows. An editor-specific floating rule prevents opening the editor from
rearranging tiled windows.

## Version-specific findings

The source for the exact installed commit was inspected alongside the headers:

- `KeybindManager.cpp`: key events call `ensureMouseBindState()`. Modifiers should
  be held before starting the drag. No workaround changes normal compositor input.
- `WindowTarget.cpp` and `DefaultFloatingAlgorithm.cpp`: `setTargetGeom` updates
  client geometry and the compositor's own floating geometry cache. Zone files
  contain client rectangles, so borders extend beyond the rectangle.
- `KeybindManager.cpp` resets the drag-threshold flag after starting a mouse bind.
  With the installed zero threshold, movement does not set that flag again. The
  plugin checks it only when a positive threshold is configured. This was found
  and corrected by native-window testing.
- `LuaBindingsConfigRules.cpp` and `PluginSystem.cpp`: `hl.plugin.load(path)`
  declares the desired plugin on each configuration pass. It must be called
  unconditionally. An early installer incorrectly skipped the declaration when
  already loaded, causing recursive reloads; this was corrected before validation.

The plugin checks the exact Hyprland ABI hash before registering callbacks. It
must be rebuilt against the current compositor after upgrades.

Official references: [Lua events](https://wiki.hypr.land/configuring/core/advanced-configuration/events/),
[mouse bindings](https://wiki.hypr.land/Configuring/Basics/Binds/),
[plugin loading](https://wiki.hypr.land/Plugins/Using-Plugins/), and
[window rules](https://wiki.hypr.land/Configuring/Basics/Window-Rules/).
Current web examples were not substituted for the installed API.
