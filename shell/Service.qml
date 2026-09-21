import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "Layouts.js" as Layouts
import "Profiles.js" as Profiles
import "Geometry.js" as Geometry

// This component runs inside the existing Omarchy shell. Only its event
// receiver remains idle; the visual tree and cursor timer exist during a drag.
Item {
    id: root
    property bool enabled: true
    property bool active: false
    readonly property int samplingHz: 30
    property bool traceEnabled: false
    property var trace: []
    property int droppedTrace: 0
    property int token: -1
    readonly property string owner: Date.now().toString() + "-" + Math.random().toString(16).slice(2)
    property var released: null
    property string monitorName: ""
    property var bounds: ({
            x: 0,
            y: 0,
            w: 0,
            h: 0
        })
    property var profiles: []
    property var picker: ({
            cards: []
        })
    property int profileIndex: 0
    property int hoverIndex: -1
    property real cursorX: 0
    property real cursorY: 0
    property bool waiting: false
    property bool sent: false
    property string request: ""
    property string response: ""
    property string purpose: ""
    property int requestToken: -1
    property var pending: null
    property int queries: 0
    property real startedAt: 0
    property alias store: definitions
    property var editorMonitors: []
    property bool wantEditor: false
    property bool editorOpen: false
    property string editorLoadError: ""
    Store {
        id: definitions
    }
    ElapsedTimer {
        id: clock
    }

    function openEditor() {
        if (editorOpen) {
            // Only reactivate our own editor, preserving its unsaved draft.
            Hyprland.dispatch('function() for _, w in ipairs(hl.get_windows()) do if w.title == "Omarchy Zones" then hl.dispatch(hl.dsp.focus({window=w})) end end end');
            return;
        }
        cancel("editor-open");
        editorLoadError = "";
        wantEditor = true;
        definitions.load();
    }
    function failEditor(message) {
        wantEditor = false;
        editorLoadError = message;
    }
    function closeEditor() {
        wantEditor = false;
        editorOpen = false;
    }
    function normalizeMonitors(values) {
        return values.map(function (m) {
            var r = m.reserved || [0, 0, 0, 0], rotated = m.transform % 2 === 1;
            var w = Math.round((rotated ? m.height : m.width) / m.scale);
            var h = Math.round((rotated ? m.width : m.height) / m.scale);
            return {
                name: m.name,
                width: w,
                height: h,
                focused: m.focused,
                usable: {
                    x: r[0],
                    y: r[1],
                    w: w - r[0] - r[2],
                    h: h - r[1] - r[3]
                }
            };
        }).filter(function (m) {
            return m.usable.w >= 64 && m.usable.h >= 32;
        });
    }
    function gestureProfiles(monitor) {
        var source = definitions.profiles.length ? definitions.profiles : Profiles.defaults(normalizeMonitors([monitor]));
        var reserved = monitor.reserved || [0, 0, 0, 0];
        // Gesture owns a value snapshot. Saving or editing cannot change it.
        var usable = normalizeMonitors([monitor])[0].usable;
        return source.map(function (profile) {
            var rectangles = Profiles.zonesFor(profile, monitor.name);
            if (!Geometry.valid(rectangles, usable))
                rectangles = [];
            return {
                name: profile.name,
                width: bounds.w,
                height: bounds.h,
                zones: rectangles.map(function (r) {
                    return {
                        x: r.x - reserved[0],
                        y: r.y - reserved[1],
                        w: r.w,
                        h: r.h
                    };
                })
            };
        });
    }

    function record(type, data) {
        if (!traceEnabled)
            return;
        if (trace.length >= 24000) {
            droppedTrace++;
            return;
        }
        trace.push({
            type: type,
            ms: Number(clock.elapsedNs()) / 1000000,
            wallMs: Date.now(),
            token: token,
            data: data || {}
        });
    }
    function send(command, kind, gestureToken) {
        if (waiting) {
            // Only a final release/control command can supersede a sample.
            if (kind !== "cursor")
                pending = {
                    command: command,
                    kind: kind,
                    token: gestureToken
                };
            return false;
        }
        waiting = true;
        sent = false;
        response = "";
        request = command;
        purpose = kind;
        requestToken = gestureToken;
        socket.connected = true;
        requestTimeout.restart();
        return true;
    }
    function complete() {
        if (!waiting || !sent)
            return;
        requestTimeout.stop();
        var kind = purpose, expected = requestToken, text = response;
        waiting = false;
        sent = false;
        response = "";
        if (kind === "editor-monitors" && wantEditor) {
            try {
                editorMonitors = normalizeMonitors(JSON.parse(text));
                if (editorMonitors.length)
                    editorOpen = true;
                else
                    failEditor("No usable display is available.");
            } catch (error) {
                failEditor("Cannot read display information: " + String(error));
                record("editor_error", {
                    error: String(error)
                });
            }
        } else if ((active || released) && expected === token) {
            try {
                if (kind === "monitors") {
                    var monitors = JSON.parse(text);
                    var monitor = monitors.find(function (m) {
                        return m.name === root.monitorName;
                    });
                    if (!monitor) {
                        cancel("monitor-missing");
                        return;
                    }
                    var reserved = monitor.reserved || [0, 0, 0, 0];
                    var rotated = monitor.transform % 2 === 1;
                    bounds = {
                        x: monitor.x + reserved[0],
                        y: monitor.y + reserved[1],
                        w: Math.round((rotated ? monitor.height : monitor.width) / monitor.scale) - reserved[0] - reserved[2],
                        h: Math.round((rotated ? monitor.width : monitor.height) / monitor.scale) - reserved[1] - reserved[3]
                    };
                    profiles = gestureProfiles(monitor);
                    picker = Layouts.pickerLayout(bounds.w, profiles);
                    profileIndex = Math.min(profileIndex, profiles.length - 1);
                    updateHover(cursorX, cursorY);
                    if (released)
                        finishRelease();
                    else {
                        visuals.active = true;
                        record("activation", {
                            profile: profileIndex,
                            zone: hoverIndex
                        });
                    }
                } else if (kind === "cursor") {
                    var point = JSON.parse(text);
                    updateHover(point.x, point.y);
                    record("sample", {
                        x: point.x,
                        y: point.y,
                        profile: profileIndex,
                        zone: hoverIndex
                    });
                }
            } catch (error) {
                record("bad_response", {
                    error: String(error),
                    text: text
                });
                cancel("response-error");
            }
        }
        if (pending) {
            var next = pending;
            pending = null;
            send(next.command, next.kind, next.token);
        }
    }
    function receive(data) {
        response += data;
        if (response.length > 262144) {
            pending = null;
            waiting = false;
            socket.connected = false;
            record("response_limit", {});
            cancel("response-limit");
            return;
        }
        var ready = false;
        if (purpose === "cursor" || purpose === "monitors" || purpose === "editor-monitors") {
            try {
                JSON.parse(response);
                ready = true;
            } catch (_) {}
        } else
            ready = response.length > 0;
        // Close after the complete response rather than waiting for the peer's
        // normal close, which Quickshell otherwise logs as a socket warning.
        if (ready)
            socket.connected = false;
    }
    function updateHover(x, y) {
        cursorX = x;
        cursorY = y;
        var localX = x - bounds.x, localY = y - bounds.y;
        var hit = Layouts.hitPicker(picker, profiles, localX, localY);
        var previousProfile = profileIndex, previousZone = hoverIndex;
        if (hit) {
            profileIndex = hit.profile;
            hoverIndex = hit.zone;
        } else
            hoverIndex = Layouts.contains(picker, localX, localY) ? -1 : Layouts.hitZone(profiles[profileIndex] ? profiles[profileIndex].zones : [], localX, localY);
        if (previousProfile !== profileIndex || previousZone !== hoverIndex)
            record("highlight", {
                profile: profileIndex,
                zone: hoverIndex,
                x: x,
                y: y
            });
    }
    function clear() {
        active = false;
        visuals.active = false;
        released = null;
        hoverIndex = -1;
        token = -1;
        profiles = [];
        picker = {
            cards: []
        };
    }
    function cancel(reason) {
        record("cancel", {
            reason: reason
        });
        var cancelledToken = token;
        clear();
        if (cancelledToken >= 0)
            send("/eval zones_shell.cancel('shell-cancel'," + cancelledToken + ")", "control", -1);
    }
    function finishRelease() {
        var finishedToken = token;
        updateHover(released.x, released.y);
        var zone = profiles[profileIndex] && profiles[profileIndex].zones[hoverIndex];
        var command = zone ? "/eval zones_shell.apply(" + [token, Math.round(bounds.x + zone.x), Math.round(bounds.y + zone.y), zone.w, zone.h].join(",") + ")" : "/eval zones_shell.cancel('no-zone'," + token + ")";
        record("snap_request", {
            profile: profileIndex,
            zone: hoverIndex,
            rectangle: zone || null
        });
        clear();
        send(command, "snap", finishedToken);
    }
    function handle(event) {
        if (event.name === "configreloaded") {
            // Hyprland replaces its Lua state on reload. Discard old requests
            // before restoring this service's ownership; keep the editor draft.
            requestTimeout.stop();
            waiting = false;
            sent = false;
            pending = null;
            response = "";
            request = "";
            purpose = "";
            requestToken = -1;
            socket.connected = false;
            clear();
            send("/eval if zones_shell then zones_shell.enable(" + (enabled ? "true" : "false") + "," + JSON.stringify(owner) + ") end", "control", -1);
            return;
        }
        if (event.name !== "custom" || !event.data.startsWith("omarchy-zones,"))
            return;
        var fields = event.data.split(","), kind = fields[1], incoming = Number(fields[2]);
        if (kind === "editor" && enabled) {
            openEditor();
            return;
        }
        if (kind === "begin" && enabled && definitions.ready) {
            clear();
            token = incoming;
            monitorName = fields[4];
            cursorX = Number(fields[5]);
            cursorY = Number(fields[6]);
            active = true;
            startedAt = Number(clock.elapsedNs()) / 1000000;
            record("begin", {
                address: fields[3]
            });
            send("j/monitors", "monitors", token);
        } else if (incoming === token && kind === "release") {
            record("release", {
                x: Number(fields[3]),
                y: Number(fields[4])
            });
            released = {
                x: Number(fields[3]),
                y: Number(fields[4])
            };
            active = false;
            visuals.active = false;
            if (profiles.length)
                finishRelease();
            else if (!(waiting && purpose === "monitors" && requestToken === token))
                cancel("no-monitor");
        } else if (incoming === token && kind === "cancel") {
            record("cancel", {
                reason: fields[3]
            });
            clear();
        }
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            root.handle(event);
        }
    }
    Socket {
        id: socket
        path: Hyprland.requestSocketPath
        connected: false
        parser: SplitParser {
            splitMarker: ""
            onRead: data => root.receive(data)
        }
        onConnectionStateChanged: {
            if (connected && root.waiting && !root.sent) {
                root.sent = true;
                write(root.request);
                flush();
            } else if (!connected)
                root.complete();
        }
        onError: error => {
            root.record("socket_error", {
                error: String(error)
            });
        }
    }
    Timer {
        id: requestTimeout
        interval: 250
        onTriggered: {
            if (root.purpose === "editor-monitors" && root.wantEditor)
                root.failEditor("The compositor did not answer the display request.");
            root.pending = null;
            root.waiting = false;
            socket.connected = false;
            root.record("timeout", {
                purpose: root.purpose
            });
            root.cancel("request-timeout");
        }
    }
    Timer {
        interval: 33
        running: root.active && visuals.active
        repeat: true
        onTriggered: {
            if (!root.waiting && root.send("j/cursorpos", "cursor", root.token))
                root.queries++;
        }
    }
    Loader {
        id: visuals
        active: false
        sourceComponent: Overlay {
            controller: root
        }
    }
    Loader {
        id: editorLoader
        active: root.editorOpen
        sourceComponent: Editor {
            controller: root
            monitors: root.editorMonitors
        }
    }
    Loader {
        active: root.editorLoadError !== ""
        sourceComponent: FloatingWindow {
            title: "Omarchy Zones — cannot open"
            implicitWidth: 520
            implicitHeight: 220
            color: Color.background
            visible: true
            onClosed: root.editorLoadError = ""
            Ui.BorderSurface {
                anchors.fill: parent
                color: Color.background
                radius: Style.cornerRadius
                borderSpec: Border.surfaceSpec("popups", "border", Color.accent, 2)
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 24
                    spacing: 16
                    Text {
                        text: "Cannot open zone profiles"
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.heading
                        font.bold: true
                    }
                    Text {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        text: root.editorLoadError
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: Color.foreground
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                    }
                    RowLayout {
                        Item {
                            Layout.fillWidth: true
                        }
                        Ui.Button {
                            text: "Close"
                            bordered: true
                            onClicked: root.editorLoadError = ""
                        }
                        Ui.Button {
                            text: "Retry"
                            bordered: true
                            onClicked: root.openEditor()
                        }
                    }
                }
            }
        }
    }
    Connections {
        target: definitions
        function onLoaded() {
            if (root.wantEditor && !root.editorOpen)
                root.send("j/monitors", "editor-monitors", -1);
        }
        function onErrorChanged() {
            if (definitions.error && root.wantEditor && !root.editorOpen)
                root.failEditor(definitions.error);
        }
    }
    IpcHandler {
        target: "omarchy-zones"
        function setTracing(value: bool): string {
            root.trace = [];
            root.droppedTrace = 0;
            root.traceEnabled = value;
            return "ok";
        }
        function openEditor(): string {
            root.openEditor();
            return "ok";
        }
        function closeEditor(): string {
            if (editorLoader.item)
                editorLoader.item.requestClose();
            return "ok";
        }
        function editorState(): string {
            return JSON.stringify(editorLoader.item ? editorLoader.item.inspect() : null);
        }
        function pickerState(): string {
            return JSON.stringify({
                picker: root.picker,
                profiles: root.profiles,
                bounds: root.bounds
            });
        }
        function enable(value: bool): string {
            root.clear();
            root.enabled = value;
            root.send("/eval zones_shell.enable(" + (value ? "true" : "false") + "," + JSON.stringify(root.owner) + ")", "control", -1);
            return "ok";
        }
        function status(): string {
            return JSON.stringify({
                active: root.active,
                token: root.token,
                queries: root.queries,
                waiting: root.waiting,
                hz: root.samplingHz,
                enabled: root.enabled,
                profile: root.profileIndex,
                zone: root.hoverIndex,
                bounds: root.bounds,
                ready: definitions.ready,
                storeBusy: definitions.busy,
                storeError: definitions.error,
                editorOpen: root.editorOpen,
                editorLoadError: root.editorLoadError,
                savedProfiles: definitions.profiles.length,
                visualsActive: visuals.active,
                profileCount: profiles.length,
                ms: Number(clock.elapsedNs()) / 1000000,
                wallMs: Date.now()
            });
        }
        function takeTrace(): string {
            var result = JSON.stringify({
                events: root.trace,
                dropped: root.droppedTrace
            });
            root.trace = [];
            root.droppedTrace = 0;
            return result;
        }
    }
    Component.onCompleted: {
        clock.restart();
        definitions.load();
        send("/eval zones_shell.enable(true," + JSON.stringify(owner) + ")", "control", -1);
    }
    Component.onDestruction: {
        // Dispatch uses the shell's existing IPC facility during destruction.
        // Lua also expires a released gesture if the whole shell is killed.
        Hyprland.dispatch("function() if zones_shell then zones_shell.enable(false," + JSON.stringify(owner) + ") end end");
    }
}
