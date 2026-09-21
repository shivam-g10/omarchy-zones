.pragma library

// The compositor bridge is evaluated in memory through Hyprland's existing
// socket. It never changes desktop configuration or launches another process.
// Dynamic values are Lua literals, never fragments of executable source.
function quote(value) {
    return '"' + String(value).replace(/[\\"\x00-\x1f\x7f]/g, function (character) {
        if (character === '"' || character === "\\")
            return "\\" + character;
        return "\\" + ("000" + character.charCodeAt(0)).slice(-3);
    }) + '"';
}
function literal(value) {
    if (Array.isArray(value))
        return "{" + value.map(literal).join(",") + "}";
    if (value && typeof value === "object")
        return "{" + Object.keys(value).map(function (key) {
            return "[" + quote(key) + "]=" + literal(value[key]);
        }).join(",") + "}";
    if (typeof value === "boolean")
        return value ? "true" : "false";
    if (typeof value === "number" && Number.isFinite(value))
        return String(value);
    return quote(value === null || value === undefined ? "" : value);
}
function conflicts(binds) {
    if (!Array.isArray(binds))
        throw new Error("The compositor returned an invalid binding list.");
    var relevant = binds.filter(function (binding) {
        if (binding.enabled === false)
            return false;
        var key = String(binding.key || "").toLowerCase();
        return (binding.modmask === 65 && (key === "mouse:272" || key === "f8" || binding.keycode === 74 || binding.catch_all))
            || (key === "mouse:272" && binding.modmask === 0 && binding.release);
    }).map(function (binding) {
        return {
            key: binding.key || "",
            keycode: binding.keycode || 0,
            modmask: binding.modmask,
            submap: binding.submap || "",
            release: !!binding.release,
            dispatcher: binding.dispatcher || "",
            arg: String(binding.arg || ""),
            label: binding.modmask === 0 ? "left-button release" : "Super+Shift+" + (binding.key || "keycode " + binding.keycode)
        };
    });
    if (relevant.length > 64)
        throw new Error("Too many conflicting compositor bindings.");
    return relevant;
}
function bootstrap(owner, binds) {
    return `/eval 
local owner = ${quote(owner)}
local known_binds = ${literal(conflicts(binds))}
local registry = "omarchy_zones_runtime"
local state = rawget(_G, registry)
local function report(kind, message)
  hl.dispatch(hl.dsp.event("omarchy-zones," .. kind .. "," .. message .. "," .. owner))
end
if state and (type(state) ~= "table" or state.schema ~= 1) then
  report("runtime-error", "An incompatible Omarchy Zones runtime is already registered; reload Hyprland")
  return
end
if not state then
  state = {schema = 1, binds = {}, rules = {}, subscriptions = {}, handlers = {}, serial = 0, enabled = false}
  rawset(_G, registry, state)
end
local function count(values)
  local result = 0
  for _ in pairs(values) do result = result + 1 end
  return result
end
local function emit(kind, extra)
  hl.dispatch(hl.dsp.event("omarchy-zones," .. kind .. "," .. (extra or "") .. "," .. (state.owner or "")))
end
local function cancel(reason, token)
  if token and (not state.gesture or state.gesture.token ~= token) then return end
  if state.timer then state.timer:set_enabled(false) end
  local gesture = state.gesture
  state.gesture = nil
  if gesture then emit("cancel", gesture.token .. "," .. (reason or "cancel")) end
end
local function stop()
  state.enabled = false
  cancel("disabled")
  for _, handle in pairs(state.binds) do handle:set_enabled(false) end
  for _, handle in pairs(state.rules) do handle:set_enabled(false) end
  for _, handle in pairs(state.subscriptions) do handle:remove() end
  state.subscriptions = {}
  state.handlers = {}
  state.owner = nil
end
local function owns(binding)
  for _, handle in pairs(state.binds) do
    if handle:is_enabled() ~= nil and binding.dispatcher == handle.handler
        and binding.arg == handle.arg and binding.modmask == handle.modmask
        and binding.key == handle.key and binding.keycode == handle.keycode
        and binding.submap == handle.submap and binding.release == handle.release then
      return true
    end
  end
  return false
end
local ok, failure = pcall(function()
  -- Existing exact handles remain disabled between plugin loads. Hyprland 0.56
  -- removes bindings by key tuple, so remove/unbind would affect other owners.
  for _, binding in ipairs(known_binds) do
    if not owns(binding) then
      error("A binding already uses " .. binding.label .. "; resolve it before enabling Omarchy Zones")
    end
  end
  for _, handles in ipairs({state.binds, state.rules}) do
    for _, handle in pairs(handles) do
      if handle:is_enabled() == nil then
        error("An Omarchy Zones runtime handle expired; reload Hyprland before enabling it")
      end
    end
  end
  if state.timer and state.timer:is_enabled() == nil then
    error("The Omarchy Zones timer expired; reload Hyprland before enabling it")
  end
  stop()
  state.owner = owner
  state.cancel = function(caller, reason, token)
    if caller == state.owner then cancel(reason, token) end
  end
  state.disable = function(caller)
    if caller == state.owner then
      stop()
      report("runtime", "0")
    end
  end
  state.handlers.move = function()
    -- The dispatcher must run synchronously in this native button callback.
    hl.dispatch(hl.dsp.window.drag())
  end
  state.handlers.begin = function()
    cancel("replaced")
    local window, monitor = hl.get_active_window(), hl.get_monitor_at_cursor()
    if not window or not monitor or not window.mapped or window.group or window.fullscreen ~= 0 then return end
    local cursor = hl.get_cursor_pos()
    if not cursor then return end
    local at, size = window.at, window.size
    if not window.visible or cursor.x < at.x or cursor.y < at.y
        or cursor.x >= at.x + size.x or cursor.y >= at.y + size.y then return end
    if not monitor.name:match("^[%w_.%-]+$") then return end
    state.serial = state.serial + 1
    state.gesture = {token = state.serial, window = window, released = false}
    emit("begin", table.concat({state.serial, window.address, monitor.name, cursor.x, cursor.y}, ","))
  end
  state.handlers.release = function()
    local gesture = state.gesture
    if not gesture or gesture.released then return end
    local cursor = hl.get_cursor_pos()
    if not cursor then cancel("cursor"); return end
    gesture.released = true
    emit("release", table.concat({gesture.token, cursor.x, cursor.y}, ","))
    state.timer:set_timeout(500)
    state.timer:set_enabled(true)
  end
  state.handlers.editor = function() emit("editor", "0") end
  state.handlers.expire = function() cancel("release-timeout") end
  state.apply = function(caller, token, x, y, width, height)
    if caller ~= state.owner then return end
    local gesture = state.gesture
    if not gesture or gesture.token ~= token or not gesture.released then return end
    local window = gesture.window
    cancel("finished")
    for _, value in ipairs({x, y, width, height}) do
      if type(value) ~= "number" or value ~= value or value % 1 ~= 0 or math.abs(value) > 65536 then return end
    end
    if width < 1 or height < 1 or width > 32768 or height > 32768 then return end
    pcall(function()
      if not window.mapped or window.group or window.fullscreen ~= 0 then return end
      hl.dispatch(hl.dsp.window.float({action = "enable", window = window}))
      hl.dispatch(hl.dsp.window.resize({x = width, y = height, window = window}))
      hl.dispatch(hl.dsp.window.move({x = x, y = y, window = window}))
    end)
  end
  local function invoke(name)
    return function(...)
      local handler = state.enabled and state.handlers[name]
      if handler then handler(...) end
    end
  end
  -- Registration order preserves native drag followed by its non-consuming
  -- observer. A temporary definition context leaves other submaps unchanged.
  hl.define_submap("", function()
    if not state.binds[1] then
      state.binds[1] = hl.bind("SUPER + SHIFT + mouse:272", invoke("move"), {mouse = true, description = "Omarchy Zones: move window"})
    end
    if not state.binds[2] then
      state.binds[2] = hl.bind("SUPER + SHIFT + mouse:272", invoke("begin"), {non_consuming = true, description = "Omarchy Zones: show zones"})
    end
    if not state.binds[3] then
      state.binds[3] = hl.bind("SUPER + SHIFT + F8", invoke("editor"), {description = "Omarchy Zones: edit profiles"})
    end
    if not state.binds[4] then
      state.binds[4] = hl.bind("mouse:272", invoke("release"), {release = true, ignore_mods = true, non_consuming = true, description = "Omarchy Zones: finish drag"})
    end
  end)
  if count(state.binds) ~= 4 then error("The compositor did not register all Omarchy Zones bindings") end
  if not state.rules[1] then
    state.rules[1] = hl.window_rule({match = {class = "^org.quickshell$", title = "^Omarchy Zones$"}, float = true, center = true})
  end
  if not state.rules[2] then
    state.rules[2] = hl.window_rule({match = {class = "^org.quickshell$", title = "^Omarchy Zones — cannot open$"}, float = true, center = true})
  end
  -- One reusable, self-disarming repeat timer avoids retaining one Lua callback
  -- for every canceled one-shot timer on the supported Hyprland version.
  if not state.timer then
    state.timer = hl.timer(function()
      state.timer:set_enabled(false)
      local handler = state.enabled and state.handlers.expire
      if handler then handler() end
    end, {timeout = 500, type = "repeat"})
    state.timer:set_enabled(false)
  end
  state.handlers.keyboard = function(key, _, pressed)
    if pressed == 0 and (key == 50 or key == 62 or key == 133 or key == 134) then
      if state.gesture and not state.gesture.released then cancel("modifier") end
    end
  end
  state.handlers.closed = function(window)
    if state.gesture and state.gesture.window == window then cancel("target-closed") end
  end
  state.subscriptions[1] = hl.on("input.keyboard.key", invoke("keyboard"))
  state.subscriptions[2] = hl.on("window.close", invoke("closed"))
  for index, name in ipairs({"monitor.layout_changed", "workspace.active", "keybinds.submap"}) do
    state.handlers[name] = function() cancel(name) end
    state.subscriptions[index + 2] = hl.on(name, invoke(name))
  end
  for _, handle in pairs(state.rules) do handle:set_enabled(true) end
  for _, handle in pairs(state.binds) do handle:set_enabled(true) end
  state.enabled = true
  report("runtime", "1")
end)
if not ok then
  -- A failed registration never leaves active partial bindings or a timer.
  -- Retained handles remain available for a later successful enable attempt.
  stop()
  report("runtime", "0")
  local message = tostring(failure):gsub("[\\r\\n,]", " "):sub(1, 240)
  report("runtime-error", message)
end
`;
}
function call(owner, method, arguments_) {
    var member = "runtime[" + quote(method) + "]";
    return "local runtime=rawget(_G,\"omarchy_zones_runtime\"); if type(runtime)==\"table\" and runtime.schema==1 and type("
        + member + ")==\"function\" then " + member + "(" + [quote(owner)].concat((arguments_ || []).map(literal)).join(",") + ") end";
}
function disable(owner) {
    return call(owner, "disable", []);
}
function cancel(owner, token, reason) {
    return "/eval " + call(owner, "cancel", [reason || "shell-cancel", token]);
}
function apply(owner, token, rectangle) {
    return "/eval " + call(owner, "apply", [token, rectangle.x, rectangle.y, rectangle.w, rectangle.h]);
}
