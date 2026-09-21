import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import Quickshell
import qs.Commons
import qs.Ui as Ui
import "Geometry.js" as Geometry
import "Profiles.js" as Profiles

// On-demand native editor. Only definition drafts live here; there are no
// window references or movement dispatchers in this component.
FloatingWindow {
    id: editor
    required property var controller
    required property var monitors
    title: "Omarchy Zones"
    implicitWidth: 1160
    implicitHeight: 740
    minimumSize: Qt.size(1000, 660)
    color: Color.background
    visible: true

    property var draft: []
    property string savedSnapshot: ""
    property int profileIndex: 0
    property int monitorIndex: 0
    property int selected: 0
    property bool drawing: false
    property string message: ""
    property string dialogKind: ""
    property string dialogError: ""
    property bool closeAfterSave: false
    readonly property var monitor: monitors[monitorIndex]
    readonly property var bounds: monitor ? monitor.usable : ({
            x: 0,
            y: 0,
            w: 0,
            h: 0
        })
    readonly property var zones: draft[profileIndex] && monitor ? Profiles.zonesFor(draft[profileIndex], monitor.name) : []
    readonly property var selection: zones[selected] || null
    readonly property bool dirty: JSON.stringify(draft) !== savedSnapshot || controller.store.fresh

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }
    function zoneCount() {
        return draft[profileIndex].layouts.reduce(function (n, layout) {
            return n + layout.zones.length;
        }, 0);
    }
    function replaceZones(value) {
        if (!value || !Geometry.valid(value, bounds)) {
            message = "Value rejected: zones cannot overlap, exceed the screen, or be smaller than 32 × 32.";
            return false;
        }
        var next = clone(draft), layouts = next[profileIndex].layouts;
        var index = layouts.findIndex(function (layout) {
            return layout.monitor === monitor.name;
        });
        if (index < 0)
            layouts.push({
                monitor: monitor.name,
                zones: value
            });
        else if (!value.length)
            layouts.splice(index, 1);
        else
            layouts[index].zones = value;
        try {
            Profiles.validate(next);
        } catch (error) {
            message = String(error);
            return false;
        }
        draft = next;
        selected = value.length ? Math.max(0, Math.min(selected, value.length - 1)) : -1;
        message = "Unsaved changes";
        return true;
    }
    function editField(field, value) {
        if (!selection || !Number.isInteger(value))
            return false;
        var result;
        if (field === "x" || field === "y") {
            var x = field === "x" ? value : selection.x;
            var y = field === "y" ? value : selection.y;
            result = Geometry.move(zones, selected, x, y, bounds);
        } else if (field === "w" || field === "h") {
            var edge = field === "w" ? "right" : "bottom";
            var origin = field === "w" ? selection.x : selection.y;
            result = Geometry.moveBoundary(zones, selected, edge, origin + value, bounds);
        } else {
            return false;
        }
        return replaceZones(result);
    }
    function starter(kind) {
        var b = bounds;
        if (kind === 0)
            return [];
        if (kind === 1) {
            var w = Math.max(Geometry.minimumExtent, Math.floor(b.w * .75));
            var h = Math.max(Geometry.minimumExtent, Math.floor(b.h * .78));
            return [
                {
                    x: b.x + Math.floor((b.w - w) / 2),
                    y: b.y + Math.floor((b.h - h) / 2),
                    w: w,
                    h: h
                }
            ];
        }
        var count = kind === 4 ? 3 : 2, result = [];
        for (var i = 0; i < count; ++i) {
            var left = kind === 3 ? (i === 0 ? 0 : Math.floor(b.w * 2 / 3)) : Math.floor(b.w * i / count);
            var right = kind === 3 ? (i === 0 ? Math.floor(b.w * 2 / 3) : b.w) : Math.floor(b.w * (i + 1) / count);
            result.push({
                x: b.x + left,
                y: b.y,
                w: right - left,
                h: b.h
            });
        }
        return result;
    }
    function availableName(base) {
        while (Profiles.byteLength(base) > 48) {
            // Remove one Unicode code point, preserving a supplementary
            // character's UTF-16 surrogate pair while enforcing the byte cap.
            var end = base.length - 1;
            var last = base.charCodeAt(end);
            if (last >= 0xdc00 && last <= 0xdfff)
                end--;
            base = base.slice(0, end);
        }
        var name = base, index = 2;
        while (draft.some(function (profile) {
            return profile.name === name;
        }))
            name = base + " " + index++;
        return name;
    }
    function chooseProfile(index) {
        drawing = false;
        canvas.resetDrag();
        profileIndex = index;
        selected = zones.length ? 0 : -1;
    }
    function split(vertical) {
        if (!selection || zoneCount() >= Profiles.maxZonesPerProfile)
            return;
        var next = clone(zones), first = clone(selection), second = clone(selection);
        if (vertical) {
            first.w = Math.floor(first.w / 2);
            second.x += first.w;
            second.w -= first.w;
        } else {
            first.h = Math.floor(first.h / 2);
            second.y += first.h;
            second.h -= first.h;
        }
        next[selected] = first;
        next.push(second);
        replaceZones(next);
    }
    function deleteZone() {
        if (!selection)
            return;
        var next = clone(zones);
        next.splice(selected, 1);
        replaceZones(next);
    }
    function showDialog(kind) {
        closeAfterSave = false;
        drawing = false;
        canvas.resetDrag();
        dialogKind = kind;
        dialogError = "";
        nameInput.text = kind === "new" ? availableName("Profile") : kind === "duplicate" ? availableName(draft[profileIndex].name + " copy") : draft[profileIndex].name;
        starterChoice.value = "2";
        modal.open();
        if (kind === "new" || kind === "duplicate" || kind === "rename")
            Qt.callLater(function () {
                nameInput.forceActiveFocus();
                nameInput.selectAll();
            });
    }
    function acceptDialog() {
        var next = clone(draft), index = profileIndex;
        if (dialogKind === "close") {
            modal.close();
            controller.closeEditor();
            return;
        }
        if (dialogKind === "delete") {
            if (next.length <= 1)
                return;
            next.splice(index, 1);
            index = Math.min(index, next.length - 1);
        } else {
            var name = nameInput.text.trim();
            if (dialogKind === "rename")
                next[index].name = name;
            else {
                var profile = dialogKind === "duplicate" ? clone(next[index]) : {
                    name: name,
                    layouts: []
                };
                profile.name = name;
                if (dialogKind === "new") {
                    var rectangles = starter(Number(starterChoice.value));
                    if (!Geometry.valid(rectangles, bounds)) {
                        dialogError = "Display too small for this layout.";
                        return;
                    }
                    if (rectangles.length)
                        profile.layouts = [
                            {
                                monitor: monitor.name,
                                zones: rectangles
                            }
                        ];
                }
                next.push(profile);
                index = next.length - 1;
            }
        }
        try {
            Profiles.validate(next);
        } catch (error) {
            dialogError = String(error);
            return;
        }
        draft = next;
        chooseProfile(index);
        message = "Unsaved changes";
        modal.close();
    }
    function saveDefinitions() {
        try {
            Profiles.validate(draft);
            for (var p = 0; p < draft.length; ++p)
                for (var m = 0; m < monitors.length; ++m)
                    if (!Geometry.valid(Profiles.zonesFor(draft[p], monitors[m].name), monitors[m].usable))
                        throw Error("A zone exceeds the usable display.");
            if (!controller.store.save(draft)) {
                closeAfterSave = false;
                message = controller.store.error || "A profile file operation is already in progress.";
                return false;
            }
            return true;
        } catch (error) {
            closeAfterSave = false;
            message = String(error);
            return false;
        }
    }
    function cancelDialog() {
        closeAfterSave = false;
        modal.close();
    }
    function requestClose() {
        if (controller.store.busy)
            return;
        if (dirty)
            showDialog("close");
        else
            controller.closeEditor();
    }
    function center(item) {
        var p = item.mapToItem(content, item.width / 2, item.height / 2);
        return {
            x: p.x,
            y: p.y
        };
    }
    // Read-only diagnostics for native interaction checks.
    function inspect() {
        var controls = {
            profileChoice: center(profileChoice),
            addProfile: center(addProfile),
            duplicateProfile: center(duplicateProfile),
            renameProfile: center(renameProfile),
            deleteProfile: center(deleteProfile),
            drawZone: center(drawZone),
            splitVertical: center(splitVertical),
            splitHorizontal: center(splitHorizontal),
            deleteZone: center(deleteZoneButton),
            saveZones: center(saveButton),
            close: center(closeButton)
        };
        for (var i = 0; i < 4; ++i)
            controls[["xValue", "yValue", "widthValue", "heightValue"][i]] = center(numericFields.itemAt(i).input);
        var first = zones[0] || {
            x: 0,
            y: 0,
            w: 0,
            h: 0
        };
        var origin = canvas.mapToItem(content, canvas.originX, canvas.originY);
        var inputs = [];
        for (var field = 0; field < 4; ++field) {
            var widget = numericFields.itemAt(field).input;
            inputs.push({text: widget.text, focus: widget.activeFocus, enabled: widget.enabled, pressFocus: widget.activeFocusOnPress});
        }
        return {
            editorWidth: width,
            editorHeight: height,
            controls: controls,
            inputs: inputs,
            profileNames: draft.map(function (p) {
                return p.name;
            }),
            profileIndex: profileIndex,
            profilePopupOpen: profileChoice.popupOpen,
            rectangles: zones.map(function (r) {
                return [r.x, r.y, r.w, r.h];
            }),
            selectedZone: selected,
            boundaryValue: selection ? selection.w : 0,
            boundary: {
                x: origin.x + (first.x + first.w) * canvas.scaleFactor,
                y: origin.y + (first.y + first.h / 2) * canvas.scaleFactor
            },
            canvas: {
                x: canvas.x,
                y: canvas.y,
                w: canvas.width,
                h: canvas.height,
                scale: canvas.scaleFactor,
                originX: origin.x,
                originY: origin.y
            },
            saveEnabled: saveButton.enabled,
            dirty: dirty,
            message: message,
            theme: {
                accent: String(Color.accent),
                fontSize: Style.font.body
            },
            modal: modal.opened ? {
                kind: dialogKind,
                name: center(nameInput),
                accept: center(acceptButton),
                cancel: center(cancelButton),
                save: center(modalSaveButton),
                error: dialogError
            } : null
        };
    }
    Connections {
        target: controller.store
        function onSaved() {
            editor.savedSnapshot = JSON.stringify(controller.store.profiles);
            var unchanged = JSON.stringify(editor.draft) === editor.savedSnapshot;
            var requestedClose = editor.closeAfterSave;
            editor.closeAfterSave = false;
            editor.message = unchanged ? "Profiles saved" : "Profiles saved. Newer changes remain unsaved.";
            if (requestedClose && unchanged)
                controller.closeEditor();
        }
        function onErrorChanged() {
            if (controller.store.error) {
                editor.closeAfterSave = false;
                editor.message = controller.store.error;
            }
        }
    }
    onClosed: {
        if (dirty) {
            visible = true;
            showDialog("close");
        } else
            controller.closeEditor();
    }
    Component.onCompleted: {
        draft = controller.store.profiles.length ? clone(controller.store.profiles) : Profiles.defaults(monitors);
        savedSnapshot = JSON.stringify(draft);
        monitorIndex = Math.max(0, monitors.findIndex(function (m) {
            return m.focused;
        }));
        selected = zones.length ? 0 : -1;
    }

    Item {
        id: content
        anchors.fill: parent
        focus: true
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Zones"
                    color: Color.foreground
                    font.family: Style.font.family
                    font.pixelSize: 26
                    font.bold: true
                }
                Item {
                    Layout.fillWidth: true
                }
                Ui.Dropdown {
                    Layout.preferredWidth: 190
                    label: "Display"
                    showLabel: false
                    value: editor.monitor ? editor.monitor.name : ""
                    options: editor.monitors.map(function (m) {
                        return m.name;
                    })
                    onChanged: value => {
                        editor.monitorIndex = editor.monitors.findIndex(function (m) {
                            return m.name === value;
                        });
                        editor.selected = editor.zones.length ? 0 : -1;
                        editor.drawing = false;
                        canvas.resetDrag();
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                Text {
                    text: "Profile"
                    color: Color.foreground
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                }
                Ui.Dropdown {
                    id: profileChoice
                    Layout.fillWidth: true
                    showLabel: false
                    options: editor.draft.map(function (p, i) {
                        return {
                            value: String(i),
                            label: p.name
                        };
                    })
                    value: String(editor.profileIndex)
                    onChanged: value => editor.chooseProfile(Number(value))
                }
                Ui.Button {
                    id: addProfile
                    text: "New profile"
                    bordered: true
                    enabled: editor.draft.length < Profiles.maxProfiles
                    onClicked: editor.showDialog("new")
                }
                Ui.Button {
                    id: duplicateProfile
                    text: "Duplicate"
                    bordered: true
                    enabled: editor.draft.length < Profiles.maxProfiles
                    onClicked: editor.showDialog("duplicate")
                }
                Ui.Button {
                    id: renameProfile
                    text: "Rename"
                    bordered: true
                    onClicked: editor.showDialog("rename")
                }
                Ui.Button {
                    id: deleteProfile
                    text: "Delete profile"
                    bordered: true
                    enabled: editor.draft.length > 1
                    onClicked: editor.showDialog("delete")
                }
            }
            Text {
                text: "Save different layouts. Choose one from the picker when dragging a window."
                color: Color.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.body
            }
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 32
                Item {
                    id: canvas
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumWidth: 500
                    readonly property real scaleFactor: editor.monitor ? Math.min((width - 48) / editor.monitor.width, (height - 78) / editor.monitor.height) : 1
                    readonly property real originX: editor.monitor ? (width - editor.monitor.width * scaleFactor) / 2 : 0
                    readonly property real originY: editor.monitor ? (height - 30 - editor.monitor.height * scaleFactor) / 2 : 0
                    property string dragKind: ""
                    property var before: []
                    property int dragZone: -1
                    property real startX: 0
                    property real startY: 0
                    property var preview: null
                    function resetDrag() {
                        dragKind = "";
                        before = [];
                        preview = null;
                    }
                    function point(mouse) {
                        return {
                            x: Math.round((mouse.x - originX) / scaleFactor),
                            y: Math.round((mouse.y - originY) / scaleFactor)
                        };
                    }
                    Rectangle {
                        x: canvas.originX
                        y: canvas.originY
                        width: editor.monitor ? editor.monitor.width * canvas.scaleFactor : 0
                        height: editor.monitor ? editor.monitor.height * canvas.scaleFactor : 0
                        color: Qt.darker(Color.background, 1.12)
                        border.color: Color.muted
                        border.width: 1
                        radius: 8
                        antialiasing: true
                    }
                    Repeater {
                        model: editor.zones
                        delegate: Ui.BorderSurface {
                            required property var modelData
                            required property int index
                            x: canvas.originX + modelData.x * canvas.scaleFactor
                            y: canvas.originY + modelData.y * canvas.scaleFactor
                            width: modelData.w * canvas.scaleFactor
                            height: modelData.h * canvas.scaleFactor
                            radius: Style.cornerRadius
                            antialiasing: true
                            color: Qt.alpha(Color.accent, index === editor.selected ? .19 : .08)
                            borderSpec: Border.controlSpec(index === editor.selected ? "focus" : "normal", Color.foreground, Color.accent)
                            Column {
                                anchors.centerIn: parent
                                spacing: 4
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: index + 1
                                    color: Color.foreground
                                    font.bold: true
                                    font.pixelSize: Style.font.body
                                }
                                Text {
                                    text: modelData.w + " × " + modelData.h
                                    color: Color.muted
                                    font.pixelSize: Style.font.body
                                    visible: parent.parent.width > 100
                                }
                            }
                        }
                    }
                    Rectangle {
                        visible: canvas.preview !== null
                        x: canvas.originX + (canvas.preview ? canvas.preview.x : 0) * canvas.scaleFactor
                        y: canvas.originY + (canvas.preview ? canvas.preview.y : 0) * canvas.scaleFactor
                        width: (canvas.preview ? canvas.preview.w : 0) * canvas.scaleFactor
                        height: (canvas.preview ? canvas.preview.h : 0) * canvas.scaleFactor
                        color: Qt.alpha(Color.accent, .15)
                        border.color: Color.accent
                        border.width: 2
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: editor.drawing ? Qt.CrossCursor : Qt.ArrowCursor
                        onPressed: mouse => {
                            var p = canvas.point(mouse);
                            canvas.startX = p.x;
                            canvas.startY = p.y;
                            canvas.before = editor.clone(editor.zones);
                            if (editor.drawing) {
                                canvas.dragKind = "draw";
                                canvas.preview = {
                                    x: p.x,
                                    y: p.y,
                                    w: 0,
                                    h: 0
                                };
                                return;
                            }
                            var tolerance = 7 / canvas.scaleFactor;
                            for (var i = editor.zones.length - 1; i >= 0; --i) {
                                var r = editor.zones[i];
                                if (p.x < r.x - tolerance || p.x > r.x + r.w + tolerance || p.y < r.y - tolerance || p.y > r.y + r.h + tolerance)
                                    continue;
                                editor.selected = i;
                                canvas.dragZone = i;
                                canvas.dragKind = Math.abs(p.x - r.x) < tolerance ? "left" : Math.abs(p.x - r.x - r.w) < tolerance ? "right" : Math.abs(p.y - r.y) < tolerance ? "top" : Math.abs(p.y - r.y - r.h) < tolerance ? "bottom" : "move";
                                return;
                            }
                            editor.selected = -1;
                        }
                        onPositionChanged: mouse => {
                            if (!pressed || !canvas.dragKind)
                                return;
                            var p = canvas.point(mouse);
                            if (canvas.dragKind === "draw") {
                                canvas.preview = {
                                    x: Math.min(p.x, canvas.startX),
                                    y: Math.min(p.y, canvas.startY),
                                    w: Math.abs(p.x - canvas.startX),
                                    h: Math.abs(p.y - canvas.startY)
                                };
                                return;
                            }
                            var r = canvas.before[canvas.dragZone];
                            var next = canvas.dragKind === "move" ? Geometry.move(canvas.before, canvas.dragZone, r.x + p.x - canvas.startX, r.y + p.y - canvas.startY, editor.bounds) : Geometry.moveBoundary(canvas.before, canvas.dragZone, canvas.dragKind, (canvas.dragKind === "left" || canvas.dragKind === "right") ? p.x : p.y, editor.bounds);
                            if (next)
                                editor.replaceZones(next);
                        }
                        onReleased: {
                            if (canvas.dragKind === "draw" && canvas.preview && editor.zoneCount() < Profiles.maxZonesPerProfile) {
                                var next = editor.clone(canvas.before);
                                next.push(canvas.preview);
                                if (editor.replaceZones(next))
                                    editor.selected = next.length - 1;
                                editor.drawing = false;
                            }
                            canvas.resetDrag();
                        }
                        onCanceled: canvas.resetDrag()
                    }
                    Text {
                        anchors.bottom: parent.bottom
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: editor.monitor ? editor.monitor.name + " · " + editor.monitor.width + " × " + editor.monitor.height + " logical pixels" : ""
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 234
                    Layout.minimumWidth: 234
                    Layout.maximumWidth: 234
                    Layout.alignment: Qt.AlignTop
                    spacing: 12
                    Text {
                        text: editor.selection ? "Zone " + (editor.selected + 1) : "Select a zone"
                        color: Color.foreground
                        font.bold: true
                        font.pixelSize: Style.font.body
                    }
                    Repeater {
                        id: numericFields
                        model: [
                            {
                                label: "X",
                                field: "x"
                            },
                            {
                                label: "Y",
                                field: "y"
                            },
                            {
                                label: "Width",
                                field: "w"
                            },
                            {
                                label: "Height",
                                field: "h"
                            }
                        ]
                        delegate: RowLayout {
                            required property var modelData
                            property alias input: fieldInput
                            Layout.fillWidth: true
                            Text {
                                text: modelData.label
                                color: Color.foreground
                                font.pixelSize: Style.font.body
                                Layout.fillWidth: true
                            }
                            Ui.TextField {
                                id: fieldInput
                                Layout.preferredWidth: 136
                                enabled: editor.selection !== null
                                activeFocusOnPress: true
                                selectByMouse: true
                                text: editor.selection ? String(editor.selection[modelData.field]) : ""
                                validator: IntValidator {
                                    bottom: 0
                                    top: 32768
                                }
                                onEditingFinished: {
                                    if (editor.selection)
                                        editor.editField(modelData.field, Number(text));
                                    text = editor.selection ? String(editor.selection[modelData.field]) : "";
                                }
                                Connections {
                                    target: editor
                                    function onZonesChanged() {
                                        fieldInput.text = editor.selection ? String(editor.selection[modelData.field]) : "";
                                    }
                                    function onSelectedChanged() {
                                        fieldInput.text = editor.selection ? String(editor.selection[modelData.field]) : "";
                                    }
                                }
                            }
                        }
                    }
                    Text {
                        text: "X / Y move a zone.\nWidth / Height move shared edges."
                        color: Color.muted
                        font.pixelSize: Style.font.body
                    }
                    Ui.Button {
                        id: drawZone
                        text: "Draw zone"
                        selected: editor.drawing
                        bordered: true
                        Layout.fillWidth: true
                        enabled: editor.draft.length > 0 && editor.zoneCount() < Profiles.maxZonesPerProfile
                        onClicked: editor.drawing = !editor.drawing
                    }
                    Ui.Button {
                        id: splitVertical
                        text: "Split left / right"
                        bordered: true
                        Layout.fillWidth: true
                        enabled: editor.selection !== null
                        onClicked: editor.split(true)
                    }
                    Ui.Button {
                        id: splitHorizontal
                        text: "Split top / bottom"
                        bordered: true
                        Layout.fillWidth: true
                        enabled: editor.selection !== null
                        onClicked: editor.split(false)
                    }
                    Ui.Button {
                        id: deleteZoneButton
                        text: "Delete zone"
                        bordered: true
                        Layout.fillWidth: true
                        enabled: editor.selection !== null
                        onClicked: editor.deleteZone()
                    }
                    Text {
                        text: "Edits only change zone definitions."
                        color: Color.muted
                        font.pixelSize: Style.font.body
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }
            Text {
                text: editor.message || "Drag shared edges to resize. Use Draw zone or Split to add zones."
                color: Color.foreground
                font.pixelSize: Style.font.body
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: editor.draft.length + " profiles" + (editor.dirty ? " · Unsaved" : "")
                    color: Color.foreground
                    font.pixelSize: Style.font.body
                }
                Item {
                    Layout.fillWidth: true
                }
                Ui.Button {
                    id: closeButton
                    text: "Close"
                    bordered: true
                    enabled: !controller.store.busy
                    onClicked: editor.requestClose()
                }
                Ui.Button {
                    id: saveButton
                    text: controller.store.busy ? "Saving…" : "Save profiles"
                    bordered: true
                    enabled: editor.dirty && !controller.store.busy
                    onClicked: editor.saveDefinitions()
                }
            }
        }
        Controls.Dialog {
            id: modal
            anchors.centerIn: parent
            width: 440
            modal: true
            focus: true
            closePolicy: Controls.Popup.NoAutoClose
            background: Ui.BorderSurface {
                color: Color.popups.background
                radius: Style.cornerRadius
                borderSpec: Border.controlSpec("focus", Color.foreground, Color.accent)
            }
            contentItem: ColumnLayout {
                spacing: 16
                Text {
                    text: editor.dialogKind === "close" ? "Unsaved changes" : editor.dialogKind === "delete" ? "Delete profile" : editor.dialogKind === "new" ? "New profile" : editor.dialogKind === "duplicate" ? "Duplicate profile" : "Rename profile"
                    color: Color.foreground
                    font.bold: true
                    font.pixelSize: 20
                }
                Text {
                    visible: editor.dialogKind === "close" || editor.dialogKind === "delete"
                    text: editor.dialogKind === "close" ? "Save changes before closing?" : "Delete this profile and its zone definitions?"
                    color: Color.foreground
                    font.pixelSize: Style.font.body
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
                Ui.TextField {
                    id: nameInput
                    Layout.fillWidth: true
                    visible: editor.dialogKind !== "close" && editor.dialogKind !== "delete"
                    onAccepted: editor.acceptDialog()
                }
                Ui.Dropdown {
                    id: starterChoice
                    Layout.fillWidth: true
                    visible: editor.dialogKind === "new"
                    label: "Start with"
                    options: [
                        {
                            value: "0",
                            label: "Empty"
                        },
                        {
                            value: "1",
                            label: "Focus"
                        },
                        {
                            value: "2",
                            label: "Split"
                        },
                        {
                            value: "3",
                            label: "Main + side"
                        },
                        {
                            value: "4",
                            label: "Three columns"
                        }
                    ]
                }
                Text {
                    text: editor.dialogError
                    visible: text !== ""
                    color: Color.accent
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                    font.pixelSize: Style.font.body
                }
                RowLayout {
                    Item {
                        Layout.fillWidth: true
                    }
                    Ui.Button {
                        id: cancelButton
                        text: "Cancel"
                        bordered: true
                        onClicked: editor.cancelDialog()
                    }
                    Ui.Button {
                        id: acceptButton
                        text: editor.dialogKind === "close" ? "Discard" : editor.dialogKind === "delete" ? "Delete" : "OK"
                        bordered: true
                        onClicked: editor.acceptDialog()
                    }
                    Ui.Button {
                        id: modalSaveButton
                        text: "Save"
                        bordered: true
                        visible: editor.dialogKind === "close"
                        onClicked: {
                            editor.closeAfterSave = true;
                            modal.close();
                            editor.saveDefinitions();
                        }
                    }
                }
            }
        }
    }
}
