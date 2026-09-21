#!/usr/bin/env node
// Test the actual QML JavaScript modules without introducing a product runtime.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
const plugin = path.dirname(path.join(root, manifest.entryPoints.service));
function module(name, imports = {}) {
    const source = fs.readFileSync(path.join(plugin, name), "utf8")
        .replace(/^\.(?:pragma|import).*$/gm, "");
    const context = vm.createContext({...imports});
    vm.runInContext(source, context, {filename: name});
    return context;
}
const Geometry = module("Geometry.js");
const Profiles = module("Profiles.js", {Geometry});
const plain = value => JSON.parse(JSON.stringify(value));
const reject = text => assert.throws(() => Profiles.parse(text));

const bounds = {x: 0, y: 0, w: 1000, h: 800};
const halves = [{x: 0, y: 0, w: 500, h: 800}, {x: 500, y: 0, w: 500, h: 800}];
assert.deepEqual(plain(Geometry.moveBoundary(halves, 0, "right", 620, bounds)), [
    {x: 0, y: 0, w: 620, h: 800}, {x: 620, y: 0, w: 380, h: 800},
]);
assert.equal(Geometry.moveBoundary(halves, 0, "right", 990, bounds), null);
assert.equal(Geometry.move(halves, 0, 100, 0, bounds), null);
assert.equal(halves[0].w, 500);
const junction = [halves[0], {x: 500, y: 0, w: 500, h: 400}, {x: 500, y: 400, w: 500, h: 400}];
assert.deepEqual(plain(Geometry.moveBoundary(junction, 1, "left", 600, bounds)), [
    {x: 0, y: 0, w: 600, h: 800}, {x: 600, y: 0, w: 400, h: 400}, {x: 600, y: 400, w: 400, h: 400},
]);
const horizontal = [{x: 0, y: 0, w: 1000, h: 400}, {x: 0, y: 400, w: 1000, h: 400}];
assert.equal(Geometry.moveBoundary(horizontal, 1, "top", 500, bounds)[0].h, 500);
assert.deepEqual(plain(Geometry.moveBoundary([{x: 0, y: 0, w: 1200, h: 800}], 0, "right", 1000, bounds)), [bounds]);
for (const value of [NaN, Infinity, -Infinity, 0.5, 2147483648])
    assert.equal(Geometry.moveBoundary(halves, 0, "right", value, bounds), null);
assert.equal(Geometry.move([null], 0, 0, 0, bounds), null);
assert.equal(Geometry.valid(halves, {...bounds, w: -1}), false);
assert.equal(Geometry.moveBoundary(halves, 0, "unknown", 100, bounds), null);

const definitions = [
    {name: 'Work "wide" \\ layout', layouts: [{monitor: "DP-2", zones: halves}, {monitor: "DISCONNECTED", zones: [{x: 0, y: 0, w: 400, h: 400}]}]},
    {name: "Empty", layouts: []},
    {name: "अध्ययन", layouts: [{monitor: "__proto__", zones: [{x: 0, y: 0, w: 32, h: 32}]}, {monitor: "profile", zones: [{x: 0, y: 0, w: 32, h: 32}]}]},
    {name: "Case", layouts: []},
    {name: "case", layouts: []},
];
const encoded = Profiles.serialize(definitions);
assert.equal(Profiles.serialize(Profiles.parse(encoded)), encoded);
assert.equal(Profiles.zonesFor(Profiles.parse(encoded)[2], "__proto__").length, 1);
const signed = Profiles.parse('omarchy-zones-v2\r\nprofile "Default"\r\n# comment\r\nDP-2 +0 -0 +32 32\r\nDISCONNECTED 32 0 32 32');
assert.equal(signed[0].layouts.length, 2);
assert.equal(Profiles.parse('omarchy-zones-v2\nprofile "a\\n"\n')[0].name, "an");
for (const text of [
    "", "omarchy-zones-v2", "omarchy-zones-v3\n", "omarchy-zones-v2\n",
    'omarchy-zones-v2\nprofile Name\n', 'omarchy-zones-v2\nprofile "Unclosed\n',
    'omarchy-zones-v2\nprofile "Name" junk\n', 'omarchy-zones-v2\nDP-2 0 0 32 32\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 0 0 32 32 # inline\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 0 0 32.0 32\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 +-0 0 32 32\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 0 0 9999999999999999999 32\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 32768 0 32 32\n',
    'omarchy-zones-v2\nprofile "A"\nprofile "A"\n',
    'omarchy-zones-v2\nprofile "Name"\nDP-2 0 0 32 32\nDP-2 1 0 32 32\n',
    "omarchy-zones-v2\n#" + "x".repeat(512) + "\n",
    "omarchy-zones-v2\n" + "# comment\n".repeat(14000),
]) reject(text);
for (const name of ["", " leading", "trailing ", "A\tB", "A\u007f", "\u00a0leading", "trailing\u3000", "a".repeat(65), "अ".repeat(22), "\ud800"])
    assert.throws(() => Profiles.validate([{name, layouts: []}]));
assert.equal(Profiles.byteLength("अध्ययन🙂"), Buffer.byteLength("अध्ययन🙂"));
assert.equal(Profiles.validate([{name: "a".repeat(64), layouts: []}]), true);
const maximum = Array.from({length: 12}, (_, p) => ({name: `Profile ${p}`, layouts: [{monitor: "DP-2", zones:
    Array.from({length: 64}, (_, z) => ({x: z * 32, y: 0, w: 32, h: 32}))}]}));
assert.equal(Profiles.serialize(Profiles.parse(Profiles.serialize(maximum))), Profiles.serialize(maximum));
assert.throws(() => Profiles.validate([...maximum, {name: "Thirteenth", layouts: []}]));
const excess = plain(maximum);
excess[0].layouts.push({monitor: "OTHER", zones: [{x: 0, y: 0, w: 32, h: 32}]});
assert.throws(() => Profiles.validate(excess));
const snapshot = Profiles.clone(definitions);
snapshot[0].layouts[0].zones[0].w = 600;
assert.equal(definitions[0].layouts[0].zones[0].w, 500);
assert.equal(Profiles.defaults([{name: "DP-1", usable: {x: 10, y: 20, w: 101, h: 100}}])[0].layouts[0].zones[1].w, 51);
console.log("QML model: shared boundaries, rollback, profile codec, Unicode, limits and snapshot isolation passed.");
