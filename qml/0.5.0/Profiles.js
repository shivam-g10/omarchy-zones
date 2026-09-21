.pragma library
.import "Geometry.js" as Geometry

var maxProfiles = 12
var maxZonesPerProfile = 64
var maxProfileNameBytes = 64
var maxMonitorNameBytes = 128
var maxFileBytes = 131072
var maxLineBytes = 512
var coordinateLimit = 32768

function fail(message) { throw new Error(message) }

// QML strings are UTF-16; the disk format's limits count UTF-8 bytes.
function byteLength(text) {
    if (typeof text !== "string") fail("Expected text.")
    var bytes = 0
    for (var i = 0; i < text.length; i++) {
        var c = text.charCodeAt(i)
        if (c >= 0xd800 && c <= 0xdbff) {
            var next = text.charCodeAt(++i)
            if (!(next >= 0xdc00 && next <= 0xdfff)) fail("Invalid Unicode text.")
            bytes += 4
        } else if (c >= 0xdc00 && c <= 0xdfff) fail("Invalid Unicode text.")
        else bytes += c < 0x80 ? 1 : c < 0x800 ? 2 : 3
    }
    return bytes
}

function unicodeSpace(c) {
    return (c >= 9 && c <= 13) || c === 32 || c === 0x85 || c === 0xa0 || c === 0x1680
        || (c >= 0x2000 && c <= 0x200a) || c === 0x2028 || c === 0x2029
        || c === 0x202f || c === 0x205f || c === 0x3000
}

function control(c) { return c < 32 || (c >= 0x7f && c <= 0x9f) || c === 0x2028 || c === 0x2029 }

function validName(name, monitor) {
    if (typeof name !== "string" || !name.length) return false
    var size = byteLength(name)
    if (size > (monitor ? maxMonitorNameBytes : maxProfileNameBytes)) return false
    if (monitor ? name.charAt(0) === "#"
                : unicodeSpace(name.charCodeAt(0)) || unicodeSpace(name.charCodeAt(name.length - 1))) return false
    for (var i = 0; i < name.length; i++) {
        var c = name.charCodeAt(i)
        if (control(c) || (monitor && unicodeSpace(c))) return false
    }
    return true
}

function clone(profiles) {
    return profiles.map(function(profile) {
        return {name: profile.name, layouts: profile.layouts.map(function(layout) {
            return {monitor: layout.monitor, zones: Geometry.clone(layout.zones)}
        })}
    })
}

function zonesFor(profile, monitor) {
    if (!profile || !Array.isArray(profile.layouts)) return []
    for (var i = 0; i < profile.layouts.length; i++)
        if (profile.layouts[i].monitor === monitor) return profile.layouts[i].zones
    return []
}

function validate(profiles) {
    if (!Array.isArray(profiles) || profiles.length < 1 || profiles.length > maxProfiles)
        fail("Keep between 1 and 12 profiles.")
    var names = []
    for (var p = 0; p < profiles.length; p++) {
        var profile = profiles[p]
        if (!profile || !validName(profile.name, false))
            fail("Profile names must be trimmed, nonempty, at most 64 UTF-8 bytes, and contain no control characters.")
        if (names.indexOf(profile.name) >= 0) fail("Profile names must be unique: " + profile.name + ".")
        names.push(profile.name)
        if (!Array.isArray(profile.layouts)) fail("Invalid profile layouts.")
        var monitors = [], count = 0
        for (var m = 0; m < profile.layouts.length; m++) {
            var layout = profile.layouts[m]
            if (!layout || !validName(layout.monitor, true) || monitors.indexOf(layout.monitor) >= 0)
                fail("Invalid or repeated monitor name in profile " + profile.name + ".")
            monitors.push(layout.monitor)
            if (!Array.isArray(layout.zones)) fail("Invalid zone list.")
            count += layout.zones.length
            if (count > maxZonesPerProfile) fail("At most 64 zones are allowed in each profile.")
            if (!Geometry.valid(layout.zones, {x: 0, y: 0, w: coordinateLimit, h: coordinateLimit}))
                fail("Zones must not overlap and must be at least 32 by 32 pixels within 0 to 32768 on " + layout.monitor + ".")
        }
    }
    return true
}

function asciiTrim(text) { return text.replace(/^[ \t\r\v\f]+|[ \t\r\v\f]+$/g, "") }

function number(token) {
    if (!/^[+-]?[0-9]+$/.test(token)) fail("Invalid zone integer.")
    var result = Number(token)
    if (!Geometry.integer(result)) fail("Zone integer is out of range.")
    return result
}

// std::quoted escapes the next character literally. JSON.parse would interpret
// sequences such as backslash+n differently and is not a compatible parser.
function quoted(text) {
    var value = ""
    for (var i = 1; i < text.length; i++) {
        var c = text.charAt(i)
        if (c === "\\") {
            if (++i >= text.length) fail("Malformed profile name.")
            value += text.charAt(i)
        } else if (c === '"') {
            if (asciiTrim(text.slice(i + 1))) fail("Malformed profile name.")
            return value
        } else value += c
    }
    fail("Malformed profile name.")
}

function parse(text) {
    if (byteLength(text) > maxFileBytes) fail("The zone file exceeds 128 KiB.")
    if (text.indexOf("\n") < 0) fail("Unknown zone file format.")
    var lines = text.split("\n")
    var header = lines[0].replace(/\r$/, "")
    var legacy = header === "omarchy-zones-v1"
    if (!legacy && header !== "omarchy-zones-v2") fail("Unknown zone file format.")
    var profiles = legacy ? [{name: "Default", layouts: []}] : []
    for (var n = 0; n < lines.length; n++) {
        if (byteLength(lines[n]) > maxLineBytes) fail("A zone file line exceeds 512 bytes.")
        if (n === 0) continue
        var line = asciiTrim(lines[n])
        if (!line || line.charAt(0) === "#") continue
        try {
            var match = /^([^ \t\r\v\f]+)(?:[ \t\r\v\f]+(.*))?$/.exec(line)
            var first = match[1], rest = match[2] || ""
            if (!legacy && first === "profile" && rest.charAt(0) === '"') {
                if (profiles.length >= maxProfiles) fail("At most 12 profiles are allowed.")
                profiles.push({name: quoted(rest), layouts: []})
                continue
            }
            if (!profiles.length) fail("Define a profile before its zones.")
            var fields = line.split(/[ \t\r\v\f]+/)
            if (fields.length !== 5) fail("Invalid zone.")
            var current = profiles[profiles.length - 1]
            var layout = null, count = 0
            for (var m = 0; m < current.layouts.length; m++) {
                count += current.layouts[m].zones.length
                if (current.layouts[m].monitor === first) layout = current.layouts[m]
            }
            if (count >= maxZonesPerProfile) fail("At most 64 zones are allowed in each profile.")
            if (!layout) {
                layout = {monitor: first, zones: []}
                current.layouts.push(layout)
            }
            layout.zones.push({x: number(fields[1]), y: number(fields[2]), w: number(fields[3]), h: number(fields[4])})
        } catch (error) { fail(error.message + " At line " + (n + 1) + ".") }
    }
    validate(profiles)
    return {profiles: profiles, legacy: legacy}
}

function serialize(profiles) {
    validate(profiles)
    var lines = ["omarchy-zones-v2"]
    profiles.forEach(function(profile) {
        lines.push('profile "' + profile.name.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"')
        // Names are identifiers, never object property keys or shell syntax.
        profile.layouts.slice().sort(function(a, b) { return a.monitor < b.monitor ? -1 : a.monitor > b.monitor ? 1 : 0 })
            .forEach(function(layout) {
                layout.zones.forEach(function(zone) {
                    lines.push([layout.monitor, zone.x, zone.y, zone.w, zone.h].join(" "))
                })
            })
    })
    var text = lines.join("\n") + "\n"
    if (byteLength(text) > maxFileBytes) fail("The zone file exceeds 128 KiB.")
    return text
}

function defaults(monitors) {
    var layouts = []
    monitors.forEach(function(monitor) {
        var bounds = monitor.usable
        if (!bounds || bounds.w < 64 || bounds.h < 32) return
        var half = Math.floor(bounds.w / 2)
        layouts.push({monitor: monitor.name, zones: [
            {x: bounds.x, y: bounds.y, w: half, h: bounds.h},
            {x: bounds.x + half, y: bounds.y, w: bounds.w - half, h: bounds.h}
        ]})
    })
    var result = [{name: "Default", layouts: layouts}]
    validate(result)
    return result
}
