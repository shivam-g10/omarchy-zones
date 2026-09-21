-- Native movement must be registered before the non-consuming gesture observer.
-- These rules apply only to the zone editor and its startup error window.
o.window({ class = "^org.quickshell$", title = "^Omarchy Zones$" }, { float = true, center = true })
o.window({ class = "^org.quickshell$", title = "^Omarchy Zones — cannot open$" }, { float = true, center = true })
o.bind("SUPER + SHIFT + mouse:272", "Move window with zones", hl.dsp.window.drag(), { mouse = true })

-- A captured weak window reference exists only for a gesture and its bounded
-- release handshake. There are no assignments or ongoing window management.
zones_shell = { enabled = false, serial = 0, gesture = nil, expiry = nil }
local state = zones_shell

local function emit(kind, extra)
  hl.dispatch(hl.dsp.event("omarchy-zones," .. kind .. "," .. (extra or "")))
end

function state.cancel(reason, token)
  if token and (not state.gesture or state.gesture.token ~= token) then return end
  if state.expiry then state.expiry:set_enabled(false); state.expiry = nil end
  local gesture = state.gesture
  state.gesture = nil
  if gesture then emit("cancel", gesture.token .. "," .. (reason or "cancel")) end
end

function state.enable(value, owner)
  if value ~= true and owner and owner ~= state.owner then return end
  state.cancel("disabled")
  state.enabled = value == true
  state.owner = value == true and owner or nil
end

local function begin()
  state.cancel("replaced")
  if not state.enabled then return end
  local window = hl.get_active_window()
  local monitor = hl.get_monitor_at_cursor()
  if not window or not monitor or not window.mapped or window.group or window.fullscreen ~= 0 then return end
  local cursor = hl.get_cursor_pos()
  if not cursor then return end
  local at, size = window.at, window.size
  if not window.visible or cursor.x < at.x or cursor.y < at.y
      or cursor.x >= at.x + size.x or cursor.y >= at.y + size.y then return end
  -- Monitor names are protocol identifiers. Reject delimiters rather than
  -- allowing an unexpected device name to alter this small event protocol.
  if not monitor.name:match("^[%w_.%-]+$") then return end
  state.serial = state.serial + 1
  state.gesture = {token = state.serial, window = window, released = false}
  emit("begin", table.concat({state.serial, window.address, monitor.name,
    cursor.x, cursor.y}, ","))
end

local function release()
  local gesture = state.gesture
  if not gesture or gesture.released then return end
  local cursor = hl.get_cursor_pos()
  if not cursor then state.cancel("cursor"); return end
  gesture.released = true
  emit("release", table.concat({gesture.token, cursor.x, cursor.y}, ","))
  -- A killed/reloading shell cannot leave a stale target available indefinitely.
  state.expiry = hl.timer(function() state.cancel("release-timeout") end,
    {timeout = 500, type = "oneshot"})
end

function state.apply(token, x, y, width, height)
  local gesture = state.gesture
  if not gesture or gesture.token ~= token or not gesture.released then return end
  local window = gesture.window
  state.cancel("finished") -- Clear before dispatching any compositor mutation.
  for _, value in ipairs({x, y, width, height}) do
    if type(value) ~= "number" or value ~= value or value % 1 ~= 0 or math.abs(value) > 65536 then return end
  end
  if width < 1 or height < 1 or width > 32768 or height > 32768 then return end
  local ok = pcall(function()
    if not window.mapped or window.group or window.fullscreen ~= 0 then return end
    hl.dispatch(hl.dsp.window.float({action = "enable", window = window}))
    hl.dispatch(hl.dsp.window.resize({x = width, y = height, window = window}))
    hl.dispatch(hl.dsp.window.move({x = x, y = y, window = window}))
    emit("snapped", tostring(token))
  end)
  if not ok then emit("error", tostring(token)) end
end

hl.bind("SUPER + SHIFT + mouse:272", begin, {non_consuming = true})
hl.bind("SUPER + SHIFT + F8", function() emit("editor", "0") end)
hl.bind("mouse:272", release, {release = true, ignore_mods = true, non_consuming = true})
hl.on("input.keyboard.key", function(key, _, pressed)
  -- Event keycodes use xkb (+8), and arrive before modifier state is updated.
  if pressed == 0 and (key == 50 or key == 62 or key == 133 or key == 134) then
    if state.gesture and not state.gesture.released then state.cancel("modifier") end
  end
end)
hl.on("window.close", function(window)
  if state.gesture and state.gesture.window == window then state.cancel("target-closed") end
end)
for _, name in ipairs({"monitor.layout_changed", "workspace.active", "keybinds.submap"}) do
  hl.on(name, function() state.cancel(name) end)
end
