import QtQuick
import Quickshell
import Quickshell.Io
import "Profiles.js" as Profiles

Item {
    id: root

    // The service owns persistence, so closing the editor does not interrupt a
    // save. FileView runs file operations in Quickshell without child processes.
    property var profiles: []
    property bool ready: false
    property bool busy: false
    property string error: ""
    property bool fresh: false
    property string path: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config"))
        + "/omarchy-zones/zones.conf"
    signal loaded()
    signal saved()

    property string operation: ""
    property string operationPath: ""
    property string pendingText: ""
    property var pendingProfiles: []
    property bool reloadQueued: false

    // Validate bytes before decoding: FileView.text() replaces malformed UTF-8.
    // FileView has already allocated the complete file by this point; its API
    // cannot impose a read limit, reject symlinks, or force file permissions.
    function decodeUtf8(buffer) {
        var bytes = new Uint8Array(buffer)
        if (bytes.length > Profiles.maxFileBytes) throw Error("The zone file exceeds 128 KiB.")
        var characters = []
        for (var i = 0; i < bytes.length;) {
            var first = bytes[i++], code = first, count = 0, minimum = 0
            if (first < 0x80) {
                characters.push(String.fromCharCode(first))
                continue
            }
            if (first >= 0xc2 && first <= 0xdf) { code = first & 0x1f; count = 1; minimum = 0x80 }
            else if (first >= 0xe0 && first <= 0xef) { code = first & 0x0f; count = 2; minimum = 0x800 }
            else if (first >= 0xf0 && first <= 0xf4) { code = first & 0x07; count = 3; minimum = 0x10000 }
            else throw Error("The zone file contains invalid UTF-8.")
            if (i + count > bytes.length) throw Error("The zone file contains incomplete UTF-8.")
            for (var end = i + count; i < end; ++i) {
                if ((bytes[i] & 0xc0) !== 0x80) throw Error("The zone file contains invalid UTF-8.")
                code = (code << 6) | (bytes[i] & 0x3f)
            }
            if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff))
                throw Error("The zone file contains invalid UTF-8.")
            if (code <= 0xffff) characters.push(String.fromCharCode(code))
            else {
                code -= 0x10000
                characters.push(String.fromCharCode(0xd800 + (code >> 10), 0xdc00 + (code & 0x3ff)))
            }
        }
        return characters.join("")
    }

    function start(kind, text, definitions) {
        if (busy) return false
        try {
            if (!path.startsWith("/") || path.indexOf("\u0000") >= 0 || Profiles.byteLength(path) > 4096)
                throw Error("The zone configuration path must be an absolute local path.")
        } catch (failure) {
            error = failure.message || String(failure)
            return false
        }
        reloadTimer.stop()
        reloadQueued = false
        error = ""
        operationPath = path
        pendingText = text || ""
        pendingProfiles = definitions || []
        busy = true
        operation = kind
        // Do not start another FileView operation from its completion signal:
        // the underlying asynchronous job finishes clearing its state afterward.
        Qt.callLater(runOperation)
        return true
    }

    function load() { return start("load", "", []) }

    function save(definitions) {
        if (busy) return false
        try {
            return start("save", Profiles.serialize(definitions), Profiles.clone(definitions))
        } catch (failure) {
            error = failure.message || String(failure)
            return false
        }
    }

    function runOperation() {
        if (!busy) return
        if (path !== operationPath) {
            finish("The zone configuration path changed during the operation.")
            return
        }
        if (operation === "save") {
            // FileView skips a write equal to its cached content. Clear that
            // cache so repeated saves still write and always emit completion.
            writer.path = ""
            writer.path = operationPath
            writer.setText(pendingText)
        } else {
            reader.path = ""
            reader.path = operationPath
            reader.data() // Starts an asynchronous read; no cached result is used.
        }
    }

    function verifyWrite() {
        if (operation !== "save") return
        operation = "verify"
        runOperation()
    }

    function readCompleted() {
        if (operation !== "load" && operation !== "verify") return
        try {
            if (path !== operationPath) throw Error("The zone configuration path changed during the operation.")
            var text = decodeUtf8(reader.data())
            if (operation === "verify") {
                // Valid UTF-8 has one encoding for each string. Comparing the
                // strictly decoded text confirms every byte, including any BOM.
                if (text !== pendingText) throw Error("The saved profiles could not be verified. Your edits remain unsaved.")
                profiles = pendingProfiles
                fresh = false
                ready = true
                changes.path = ""
                changes.path = path // A first save may have created the parent.
                finish("", "save")
            } else {
                profiles = Profiles.parse(text)
                fresh = false
                ready = true
                finish("", "load")
            }
        } catch (failure) {
            finish(failure.message || String(failure))
        }
    }

    function readFailed(code) {
        if (operation !== "load" && operation !== "verify") return
        if (operation === "load" && code === FileViewError.FileNotFound && path === operationPath) {
            profiles = []
            fresh = true
            ready = true
            finish("", "load")
        } else finish("Cannot " + (operation === "verify" ? "verify" : "read") + " the zone configuration: " + FileViewError.toString(code) + ".")
    }

    function finish(message, action) {
        error = message || ""
        pendingText = ""
        pendingProfiles = []
        // Completion handlers are deferred until FileView finishes its job.
        // Drop cached file buffers, especially when rejecting an oversized file.
        reader.path = ""
        writer.path = ""
        operation = ""
        busy = false
        if (reloadQueued) {
            reloadQueued = false
            reloadTimer.restart()
        }
        if (!error) {
            if (action === "save") saved()
            else if (action === "load") loaded()
        }
    }

    FileView {
        id: reader
        preload: false
        blockLoading: false
        blockAllReads: false
        printErrors: false
        onLoaded: Qt.callLater(root.readCompleted)
        onLoadFailed: error => Qt.callLater(root.readFailed, error)
    }

    FileView {
        id: writer
        preload: false
        blockWrites: false
        atomicWrites: true
        printErrors: false
        // Quickshell 0.3.1 can signal saved after a failed atomic commit. A
        // separate fresh read must succeed before the store acknowledges it.
        onSaved: Qt.callLater(root.verifyWrite)
        onSaveFailed: error => Qt.callLater(root.finish, "Cannot save the zone configuration: " + FileViewError.toString(error) + ".")
    }

    FileView {
        id: changes
        path: root.path
        preload: false
        watchChanges: true
        printErrors: false
        onFileChanged: {
            if (root.busy) root.reloadQueued = true
            else reloadTimer.restart()
        }
    }
    onPathChanged: changes.path = path

    Timer {
        id: reloadTimer
        interval: 60
        onTriggered: {
            if (root.busy) root.reloadQueued = true
            else root.load()
        }
    }
}
