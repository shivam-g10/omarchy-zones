#!/usr/bin/env node
// Execute the actual editor callbacks to cover Unicode and asynchronous-save
// regressions. Native interaction correctness is tested separately in the lab.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
const plugin = path.dirname(path.join(root, manifest.entryPoints.service));
function module(name, imports = {}) {
    const context = vm.createContext({...imports});
    vm.runInContext(fs.readFileSync(path.join(plugin, name), "utf8").replace(/^\.(?:pragma|import).*$/gm, ""), context);
    return context;
}
const Geometry = module("Geometry.js");
const Profiles = module("Profiles.js", {Geometry});
const source = fs.readFileSync(path.join(plugin, "Editor.qml"), "utf8");
function callback(name, context) {
    const match = new RegExp(`^([ \\t]*)function ${name}\\([^\\n]*\\{`, "m").exec(source);
    assert.ok(match, `Missing editor callback ${name}`);
    const end = source.indexOf(`\n${match[1]}}`, match.index);
    assert.ok(end > match.index, `Unterminated editor callback ${name}`);
    vm.runInContext(source.slice(match.index, end + match[1].length + 2), context, {filename: `Editor.qml:${name}`});
    return context[name];
}

const nameContext = vm.createContext({Profiles, draft: []});
const availableName = callback("availableName", nameContext);
for (const name of ["😀".repeat(15), "अ".repeat(20), "a".repeat(64), "mixed🙂".repeat(6)]) {
    assert.ok(Profiles.validName(name, false));
    const duplicate = availableName(name + " copy");
    assert.ok(Profiles.validName(duplicate, false));
    assert.ok(Profiles.byteLength(duplicate) <= 48);
    nameContext.draft = [{name: duplicate}];
    assert.equal(availableName(name + " copy"), duplicate + " 2");
    nameContext.draft = [];
}

const saved = [{name: "Default", layouts: []}];
let closes = 0, modalCloses = 0;
const editor = {draft: structuredClone(saved), closeAfterSave: true, savedSnapshot: "", message: ""};
const controller = {store: {profiles: saved, error: ""}, closeEditor() { closes++; }};
const context = vm.createContext({editor, controller});
const onSaved = callback("onSaved", context);
const onErrorChanged = callback("onErrorChanged", context);
editor.draft[0].name = "New unsaved edit";
onSaved();
assert.equal(closes, 0, "An acknowledged older save must not close a newer draft");
assert.equal(editor.closeAfterSave, false);
assert.equal(editor.savedSnapshot, JSON.stringify(saved));
editor.closeAfterSave = true;
controller.store.error = "Disk full";
onErrorChanged();
assert.equal(editor.closeAfterSave, false, "A failed close-save must clear its close request");
controller.store.error = "";
controller.store.profiles = structuredClone(editor.draft);
onSaved();
assert.equal(closes, 0, "A later ordinary save must not inherit a failed close request");
editor.closeAfterSave = true;
onSaved();
assert.equal(closes, 1, "An unchanged acknowledged draft should still close when requested");

const saveContext = vm.createContext({Profiles, Geometry, draft: structuredClone(saved), monitors: [],
    closeAfterSave: true, message: "", controller: {store: {error: "Busy", save() { return false; }}},
    modal: {close() { modalCloses++; }}});
const saveDefinitions = callback("saveDefinitions", saveContext);
assert.equal(saveDefinitions(), false);
assert.equal(saveContext.closeAfterSave, false);
saveContext.closeAfterSave = true;
saveContext.draft[0].name = "";
assert.equal(saveDefinitions(), false);
assert.equal(saveContext.closeAfterSave, false, "Validation failure must also clear the close request");
saveContext.closeAfterSave = true;
callback("cancelDialog", saveContext)();
assert.equal(saveContext.closeAfterSave, false);
assert.equal(modalCloses, 1);
console.log("Editor callbacks: Unicode duplication, save failure, cancellation, and newer-draft protection passed.");
