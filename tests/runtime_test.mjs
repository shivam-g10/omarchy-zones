#!/usr/bin/env node
// Exercise the generated compositor code with Lua and a stateful API double.
// Native compositor checks remain necessary for input and rendering behavior.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {spawnSync} from "node:child_process";

const manifest = JSON.parse(fs.readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
assert.equal(manifest.entryPoints.service, "qml/Service.qml");
const entry = new URL("../" + manifest.entryPoints.service, import.meta.url);
const runtime = vm.createContext({});
vm.runInContext(fs.readFileSync(new URL("Runtime.js", entry), "utf8")
    .replace(/^\.pragma.*$/gm, ""), runtime, {filename: "Runtime.js"});
const lua = command => command.replace(/^\/eval\s*/, "");
const owned = [
    {key: "mouse:272", modmask: 65, arg: "1"},
    {key: "mouse:272", modmask: 65, arg: "2"},
    {key: "F8", modmask: 65, arg: "3"},
    {key: "mouse:272", modmask: 0, arg: "4", release: true},
].map(binding => ({keycode: 0, submap: "", release: false, dispatcher: "__lua", ...binding}));
const foreign = {...owned[2], submap: "foreign", arg: "999"};
const hostile = '\"; __zones_injected = true; --\\\n\r\0';
const commands = {
    first: runtime.bootstrap("owner-a", []),
    next: runtime.bootstrap("owner-b", []),
    owned: runtime.bootstrap("owner-b", owned),
    conflict: runtime.bootstrap("owner-b", [foreign]),
    staleDisable: runtime.disable("owner-a"),
    disable: runtime.disable("owner-b"),
    cancel: runtime.cancel("owner-b", 1, "syntax-check"),
    apply: runtime.apply("owner-b", 1, {x: 0, y: 0, w: 640, h: 480}),
    finish: runtime.finish("owner-b", 1),
    quoted: runtime.cancel('owner"\\\n\r\0', 1, 'reason"\\\n\r\0'),
    hostileOwner: runtime.bootstrap(hostile, []),
    hostileBinding: runtime.bootstrap("owner-b", [{...foreign, key: hostile, keycode: 74,
        submap: hostile, dispatcher: hostile, arg: hostile}]),
    hostileReason: runtime.cancel("owner-b", 1, hostile),
    hostileMember: runtime.call("owner-b", "disable) then __zones_injected=true end --", []),
    hostileToken: runtime.apply("owner-b", hostile, {x: 0, y: 0, w: 640, h: 480}),
};
// Malformed numeric fields must be rejected by Lua before window operations.
const invalidRectangles = [
    {x: hostile}, {x: NaN}, {x: Infinity}, {x: 0.5}, {x: 65537},
    {w: hostile}, {w: 0}, {w: 32769}, {h: null},
];
invalidRectangles.forEach((rectangle, index) => {
    commands["invalidRectangle" + index] = runtime.apply("owner-b", 1, {x: 0, y: 0, w: 640, h: 480, ...rectangle});
});
for (const command of Object.values(commands)) {
    const result = spawnSync("luac", ["-p", "-"], {input: lua(command), encoding: "utf8"});
    assert.equal(result.status, 0, result.stderr || String(result.error));
}
assert.equal(runtime.conflicts([{...foreign, enabled: false}]).length, 0);
assert.equal(runtime.conflicts([{key: "mouse:272", modmask: 64}]).length, 0);
assert.equal(runtime.conflicts([{key: "", keycode: 74, modmask: 65}]).length, 1);
assert.throws(() => runtime.conflicts({}), /invalid binding list/);
assert.throws(() => runtime.conflicts(Array(65).fill(foreign)), /Too many/);

const payloads = "local payloads = " + runtime.literal(Object.fromEntries(
    Object.entries(commands).map(([key, command]) => [key, lua(command)]))) + "\n";
// Compare against independently encoded UTF-8 bytes, not the quoting helper.
const byteString = value => "string.char(" + [...Buffer.from(value)].join(",") + ")";
const strings = [hostile, "backslash\\9", "अध्ययन 🪟", '[[\"]]; __zones_injected=true; --',
    Array.from({length: 32}, (_, i) => String.fromCharCode(i)).join("") + "\x7f123"];
const literalChecks = strings.map(value => "assert(" + runtime.quote(value) + " == " + byteString(value) + ")").join("\n")
    + "\nlocal escaped = " + runtime.literal({[hostile]: [hostile, true, 23]})
    + "\nassert(escaped[" + byteString(hostile) + "][1] == " + byteString(hostile) + ")\n";
const checks = String.raw`
local created, events, operations, target, cursor
local function fresh()
  omarchy_zones_runtime = nil
  created = {binds = 0, rules = 0, timers = 0, subscriptions = 0, removed = 0}
  events, operations = {}, {}
  target = {mapped = true, visible = true, floating = false, fullscreen = 0, at = {x = 0, y = 0},
    size = {x = 800, y = 600}, address = "0xab"}
  cursor = {x = 400, y = 400}
end
local function handle()
  return {
    enabled = true,
    set_enabled = function(self, value) self.enabled = value end,
    is_enabled = function(self) return self.enabled end,
    remove = function() error("Broad handle removal is forbidden") end,
    set_timeout = function(self, value) self.timeout = value end,
  }
end
hl = {
  bind = function(key, callback, options)
    created.binds = created.binds + 1
    local result = handle()
    result.callback, result.handler, result.arg = callback, "__lua", tostring(created.binds)
    result.modmask = key:find("SUPER") and 65 or 0
    result.key = key:find("F8") and "F8" or "mouse:272"
    result.keycode, result.submap, result.release = 0, "", options.release or false
    return result
  end,
  unbind = function() error("Broad unbind is forbidden") end,
  define_submap = function(name, callback) assert(name == ""); callback() end,
  window_rule = function(rule)
    assert(rule.match.class == "^org.quickshell$")
    assert(rule.match.title == "^Omarchy Zones$" or rule.match.title == "^Omarchy Zones — cannot open$")
    created.rules = created.rules + 1
    return handle()
  end,
  timer = function(callback, options)
    assert(options.type == "repeat" and options.timeout == 500)
    created.timers = created.timers + 1
    local result = handle(); result.callback = callback; return result
  end,
  on = function(name, callback)
    created.subscriptions = created.subscriptions + 1
    return {name = name, callback = callback, remove = function(self)
      assert(not self.removed); self.removed = true; created.removed = created.removed + 1
    end}
  end,
  get_active_window = function() return target end,
  get_monitor_at_cursor = function() return {name = "DP-2"} end,
  get_cursor_pos = function() return cursor end,
  dispatch = function(action)
    local list = type(action) == "string" and events or operations
    list[#list + 1] = action
    if type(action) == "table" and action.name == "float" then action.options.window.floating = true end
  end,
  dsp = {event = function(value) return value end, window = {}},
}
for _, name in ipairs({"drag", "float", "resize", "move"}) do
  hl.dsp.window[name] = function(options) return {name = name, options = options} end
end
local function run(name) assert(load(payloads[name], name))() end
local function bounded()
  assert(created.binds == 4 and created.rules == 2 and created.timers == 1)
  assert(created.subscriptions - created.removed == 5)
end
local function disabled(state)
  assert(not state.enabled and not state.gesture and #state.subscriptions == 0)
  assert(not state.timer or not state.timer.enabled)
  assert(next(state.handlers) == nil)
  for _, item in pairs(state.binds) do assert(not item.enabled) end
  for _, item in pairs(state.rules) do assert(not item.enabled) end
  assert(created.subscriptions == created.removed)
end
fresh()
run("first"); bounded()
local state = omarchy_zones_runtime
assert(state.enabled and not state.timer.enabled)
state.binds[1].callback(); assert(operations[1].name == "drag")
state.binds[2].callback(); assert(state.gesture.token == 1)
state.binds[4].callback(); assert(state.gesture.released and state.timer.enabled)
state.apply("wrong-owner", 1, 0, 0, 500, 600); assert(state.gesture)
state.apply("owner-a", 1, 0, 0, 500, 600)
assert(state.gesture.rectangle.w == 500 and state.timer.enabled and #operations == 2)
state.finish("wrong-owner", 1); state.finish("owner-a", 2)
assert(#operations == 2)
state.apply("owner-a", 1, 0, 0, 999, 999)
assert(state.gesture.rectangle.w == 500 and #operations == 2)
state.finish("owner-a", 1)
assert(not state.gesture and not state.timer.enabled)
assert(#operations == 4 and operations[2].name == "float" and operations[4].name == "move")
state.finish("owner-a", 1); assert(#operations == 4)
state.binds[2].callback()
state.cancel("owner-a", "stale-token", state.gesture.token - 1); assert(state.gesture)
state.subscriptions[1].callback(50, 0, 0); assert(not state.gesture)
state.binds[2].callback(); state.binds[4].callback(); state.timer.callback()
assert(not state.gesture and not state.timer.enabled)
run("next"); bounded()
assert(omarchy_zones_runtime == state and state.owner == "owner-b")
run("staleDisable"); assert(state.enabled)
run("owned"); bounded(); assert(state.enabled)
for index = 1, 100 do
  run("disable"); disabled(state)
  -- Even accidentally invoked callbacks are inert while the runtime is disabled.
  local before = #operations
  state.binds[1].callback(); state.binds[2].callback()
  assert(#operations == before and not state.gesture)
  run("next"); bounded()
end
-- A foreign registration added after activation is never toggled or removed.
local foreign = handle()
foreign.set_enabled = function() error("Foreign registration was modified") end
state.binds[2].callback(); run("disable"); disabled(state); assert(foreign.enabled)
run("conflict"); disabled(state); assert(foreign.enabled)
assert(events[#events]:match("runtime%-error") and events[#events]:match("Super%+Shift%+F8"))
run("next"); bounded()
-- Listener failure cleans up a partially activated runtime and reuses all slots.
local register = hl.on
hl.on = function(name, callback)
  if name == "window.close" then error("injected listener failure") end
  return register(name, callback)
end
run("next"); disabled(state)
assert(events[#events]:match("runtime%-error") and events[#events]:match("injected listener failure"))
hl.on = register; run("next"); bounded(); run("disable"); disabled(state)
-- First-load failure preserves disabled partial slots; retry does not duplicate them.
fresh()
local rule = hl.window_rule
hl.window_rule = function(options)
  if created.rules == 1 then error("injected rule failure") end
  return rule(options)
end
run("first"); state = omarchy_zones_runtime; disabled(state)
assert(created.binds == 4 and created.rules == 1 and created.timers == 0)
hl.window_rule = rule; run("next"); bounded(); run("disable"); disabled(state)
-- Attack-like input is data across every interpolation boundary.
fresh(); run("hostileOwner"); assert(omarchy_zones_runtime.enabled)
fresh(); run("hostileBinding"); disabled(omarchy_zones_runtime)
fresh(); run("next"); state = omarchy_zones_runtime
run("hostileMember"); assert(state.enabled)
state.binds[2].callback(); state.binds[4].callback()
run("hostileToken"); assert(state.gesture and #operations == 0)
run("hostileReason"); assert(not state.gesture and #operations == 0)
for index = 0, 8 do
  fresh(); run("next"); state = omarchy_zones_runtime
  state.binds[2].callback(); state.binds[4].callback()
  run("invalidRectangle" .. index)
  assert(not state.gesture and not state.timer.enabled and #operations == 0)
end
-- The extra socket round trip must not retain or resize a canceled/replaced target.
for _, reason in ipairs({"timeout", "closed", "cancel", "disabled", "replaced", "unmapped", "tiled", "grouped", "fullscreen"}) do
  fresh(); run("next"); state = omarchy_zones_runtime
  state.binds[2].callback(); state.binds[4].callback(); run("apply")
  assert(state.gesture.rectangle and #operations == 1 and state.timer.enabled)
  if reason == "timeout" then state.timer.callback()
  elseif reason == "closed" then state.subscriptions[2].callback(target)
  elseif reason == "cancel" then run("cancel")
  elseif reason == "disabled" then run("disable")
  elseif reason == "replaced" then state.binds[2].callback()
  elseif reason == "unmapped" then target.mapped = false
  elseif reason == "tiled" then target.floating = false
  elseif reason == "grouped" then target.group = {}
  elseif reason == "fullscreen" then target.fullscreen = 1 end
  run("finish")
  assert(#operations == 1, reason .. " resized a canceled target")
  if reason == "replaced" then
    assert(state.gesture.token == 2 and not state.gesture.rectangle)
  else assert(not state.gesture and not state.timer.enabled) end
end
-- Focus changes cannot redirect the second phase to a different window.
fresh(); run("next"); state = omarchy_zones_runtime
state.binds[2].callback(); state.binds[4].callback(); run("apply")
local captured = target
target = {mapped = true, floating = true, fullscreen = 0}
run("finish")
assert(#operations == 3 and operations[2].options.window == captured and operations[3].options.window == captured)
assert(__zones_injected == nil)
print("Runtime: Lua input isolation, ownership, conflict refusal, failure cleanup, timer reuse and 100 bounded lifecycle cycles passed.")
`;
const result = spawnSync("lua", ["-"], {input: literalChecks + payloads + checks, encoding: "utf8", timeout: 10000});
assert.equal(result.status, 0, result.stderr || String(result.error));
process.stdout.write(result.stdout);
