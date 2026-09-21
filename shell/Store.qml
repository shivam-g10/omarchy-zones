import QtQuick
import Quickshell
import Quickshell.Io
import "Profiles.js" as Profiles

Item {
    id: root

    // The root service owns this small store. The visual editor can unload
    // without interrupting a save or keeping an extra process resident.
    property var profiles: []
    property bool ready: false
    property bool busy: false
    property string error: ""
    property bool fresh: false
    property bool legacy: false
    property string path: (Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config"))
        + "/omarchy-zones/zones.conf"
    signal loaded()
    signal saved()

    property string operation: ""
    property string pendingText: ""
    property var pendingProfiles: []
    property bool reloadQueued: false

    // Values such as paths and content never become shell source. The outer
    // shell owns no file operation: its timeout child supervises the complete
    // pipeline even if Quickshell kills the outer process during plugin unload.
    readonly property string superviseScript: [
        'trap \'kill -TERM "$child" 2>/dev/null; wait "$child"; exit 143\' HUP INT TERM',
        '/usr/bin/timeout --signal=TERM --kill-after=1s 4s "$@" <&0 &',
        'child=$!',
        'wait "$child"',
        'exit $?'
    ].join("\n")

    readonly property string readScript: [
        'set -o pipefail',
        'path=$1',
        '[ ! -L "$path" ] || { echo "The zone file must not be a symbolic link." >&2; exit 2; }',
        '[ -e "$path" ] || exit 4',
        '[ -f "$path" ] || { echo "The zone configuration must be a regular file." >&2; exit 2; }',
        'dd if="$path" iflag=nonblock,nofollow,count_bytes count=131073 status=none | iconv -f UTF-8 -t UTF-8'
    ].join("\n")

    readonly property string writeScript: [
        'set -eu',
        'umask 077',
        'path=$1',
        'expected=$2',
        'directory=${path%/*}',
        '[ ! -L "$directory" ] || { echo "The zone directory must not be a symbolic link." >&2; exit 2; }',
        'mkdir -p -m 700 -- "$directory"',
        '[ ! -L "$path" ] && { [ ! -e "$path" ] || [ -f "$path" ]; } || { echo "The zone file must be regular and not a symbolic link." >&2; exit 2; }',
        'temporary=$(mktemp -- "$directory/.zones-save.XXXXXXXX")',
        'trap \'rm -f -- "$temporary"\' EXIT',
        'trap \'exit 143\' HUP INT TERM',
        'dd of="$temporary" iflag=count_bytes count=131073 conv=fsync status=none',
        'actual=$(wc -c < "$temporary")',
        '[ "$actual" -eq "$expected" ] && [ "$actual" -le 131072 ] || { echo "Profile content was incomplete or too large." >&2; exit 2; }',
        '[ ! -L "$path" ] && { [ ! -e "$path" ] || [ -f "$path" ]; } || { echo "The zone file changed type while saving." >&2; exit 2; }',
        'mv -fT -- "$temporary" "$path"',
        'printf "saved\\n"'
    ].join("\n")

    function start(kind, text, definitions) {
        if (busy || worker.running) return false
        if (!path.startsWith("/") || path.indexOf("\u0000") >= 0 || Profiles.byteLength(path) > 4096) {
            error = "The zone configuration path must be an absolute local path."
            return false
        }
        error = ""
        operation = kind
        pendingText = text || ""
        pendingProfiles = definitions || []
        busy = true
        worker.stdinEnabled = kind === "save"
        worker.command = ["/usr/bin/bash", "--noprofile", "--norc", "-c", superviseScript, "zones-store",
            "/usr/bin/bash", "--noprofile", "--norc", "-c", kind === "save" ? writeScript : readScript,
            "zones-file", path, String(Profiles.byteLength(pendingText))]
        worker.running = true
        watchdog.restart()
        return true
    }

    function load() { return start("load", "", []) }

    function save(definitions) {
        if (busy || worker.running) return false
        try {
            var text = Profiles.serialize(definitions)
            return start("save", text, Profiles.clone(definitions))
        } catch (failure) {
            error = failure.message || String(failure)
            return false
        }
    }

    function complete(code, status) {
        watchdog.stop()
        var action = operation
        try {
            if (error) return
            if (action === "load" && code === 4 && status === 0) {
                profiles = []
                ready = true
                fresh = true
                legacy = false
            } else if (code !== 0 || status !== 0) {
                throw new Error(code === 124 || code === 137 ? "Profile file operation timed out."
                    : String(stderr.text || "Cannot " + action + " the zone configuration.").trim().slice(0, 400))
            } else if (action === "load") {
                var parsed = Profiles.parse(stdout.text)
                profiles = parsed.profiles
                legacy = parsed.legacy
                fresh = false
                ready = true
            } else if (action === "save") {
                if (stdout.text !== "saved\n") throw new Error("The profile write was not acknowledged.")
                profiles = pendingProfiles
                legacy = false
                fresh = false
                ready = true
            }
        } catch (failure) {
            error = failure.message || String(failure)
        } finally {
            pendingText = ""
            pendingProfiles = []
            operation = ""
            busy = false
            if (reloadQueued) {
                reloadQueued = false
                reloadTimer.restart()
            }
        }
        if (!error) {
            if (action === "load") loaded()
            else if (action === "save") {
                // A first save may have created the previously absent parent.
                changes.path = ""
                changes.path = root.path
                saved()
            }
        }
    }

    // This object only watches metadata. Never call text(), data() or reload():
    // FileView's reader allocates before the profile size limit can be applied.
    FileView {
        id: changes
        path: root.path
        preload: false
        watchChanges: true
        printErrors: false
        onFileChanged: reloadTimer.restart()
    }
    onPathChanged: changes.path = path

    Timer {
        id: reloadTimer
        interval: 60
        onTriggered: {
            if (root.busy || worker.running) root.reloadQueued = true
            else root.load()
        }
    }

    Process {
        id: worker
        environment: ({LC_ALL: "C", BASH_ENV: "", ENV: "", PATH: "/usr/bin:/bin"})
        stdout: StdioCollector { id: stdout; waitForEnd: true }
        stderr: StdioCollector { id: stderr; waitForEnd: true }
        onStarted: {
            if (root.operation === "save") {
                write(root.pendingText)
                stdinEnabled = false
            }
        }
        onExited: (code, status) => root.complete(code, status)
    }

    Timer {
        id: watchdog
        interval: 6500
        onTriggered: {
            root.error = "Profile file operation timed out."
            worker.signal(15)
            // The command's timeout supervises its own process group. This
            // timer also clears the UI if the executable could not be started.
            if (!worker.running) root.complete(-1, 1)
        }
    }

    Component.onDestruction: if (worker.running) worker.signal(15)
}
