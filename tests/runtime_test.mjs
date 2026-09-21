#!/usr/bin/env node
// Exercise the generated compositor code with Lua and a stateful API double.
// Native compositor checks remain necessary for input and rendering behavior.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import {spawnSync} from "node:child_process";

const manifest = JSON.parse(fs.readFileSync(new URL("../manifest.json", import.meta.url), "utf8"));
assert.equal(manifest.entryPoints.service, "qml/" + manifest.version + "/Service.qml");
assert.deepEqual(fs.readdirSync(new URL("../qml/", import.meta.url)), [manifest.version]);
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
const commands = {
    first: runtime.bootstrap("owner-a", []),
    next: runtime.bootstrap("owner-b", []),
    owned: runtime.bootstrap("owner-b", owned),
    conflict: runtime.bootstrap("owner-b", [foreign]),
    staleDisable: runtime.disable("owner-a"),
    disable: runtime.disable("owner-b"),
    cancel: runtime.cancel("owner-b", 1, "syntax-check"),
    apply: runtime.apply("owner-b", 1, {x: 0, y: 0, w: 640, h: 480}),
    quoted: runtime.cancel('owner"\\\n\r\0', 1, 'reason"\\\n\r\0'),
};
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
const checks = String.raw`
local created, events, operations, target, cursor
local function fresh()
  omarchy_zones_runtime = nil
  created = {binds = 0, rules = 0, timers = 0, subscriptions = 0, removed = 0}
  events, operations = {}, {}
  target = {mapped = true, visible = true, fullscreen = 0, at = {x = 0, y = 0},
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
assert(not state.gesture and not state.timer.enabled)
assert(#operations == 4 and operations[2].name == "float" and operations[4].name == "move")
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
print("Runtime: generated Lua syntax, ownership, conflict refusal, failure cleanup, timer reuse and 100 bounded lifecycle cycles passed.")
`;
const result = spawnSync("lua", ["-"], {input: payloads + checks, encoding: "utf8", timeout: 10000});
assert.equal(result.status, 0, result.stderr || String(result.error));
process.stdout.write(result.stdout);
