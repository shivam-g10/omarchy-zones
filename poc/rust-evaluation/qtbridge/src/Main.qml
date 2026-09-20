import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import zones_qtbridge_poc

ApplicationWindow {
    id: window
    property bool probeMode: false
    visible: !probeMode
    width: 900
    height: 620
    minimumWidth: 800
    minimumHeight: 560
    title: "Omarchy Zones · Qt Bridges PoC"
    color: theme.background
    readonly property var theme: JSON.parse(backend.themeJson)
    font.pixelSize: theme.fontSize
    palette.window: theme.background
    palette.base: theme.surface
    palette.button: theme.raised
    palette.buttonText: theme.foreground
    palette.text: theme.foreground
    palette.windowText: theme.foreground
    palette.highlight: theme.accent
    palette.highlightedText: theme.background

    Backend { id: backend }

    component BorderCard: Item {
        id: card
        property color fill: window.theme.surface
        property real lineWidth: window.theme.borderWidth
        property real corner: window.theme.rounding
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeWidth: -1
                fillGradient: LinearGradient {
                    x1: card.width * (0.5 - 0.5 * Math.cos(window.theme.borderAngle * Math.PI / 180))
                    y1: card.height * (0.5 - 0.5 * Math.sin(window.theme.borderAngle * Math.PI / 180))
                    x2: card.width - x1
                    y2: card.height - y1
                    GradientStop { position: 0; color: window.theme.borderStart }
                    GradientStop { position: 1; color: window.theme.borderEnd }
                }
                PathRectangle { x: 0; y: 0; width: card.width; height: card.height; radius: card.corner }
            }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: card.lineWidth
            radius: Math.max(0, card.corner - card.lineWidth)
            color: card.fill
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 26
        spacing: 18
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 5
                Label { text: "Zones"; font.pixelSize: 26; font.weight: Font.DemiBold; color: theme.foreground }
                Label { text: "Rust backend · Qt Quick interface"; color: theme.muted }
            }
            Item { Layout.fillWidth: true }
            Rectangle {
                implicitWidth: 148; implicitHeight: 28; radius: 14; color: theme.raised
                Label { anchors.centerIn: parent; text: "Qt Bridges 0.2.0"; color: theme.accent }
            }
        }
        Label { text: "Move one boundary. Both zones update together."; color: theme.foreground }
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 22
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 10
                BorderCard {
                    id: preview
                    objectName: "zonePreview"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Item {
                        id: screen
                        width: parent.width - 36
                        height: width * 1414 / 2560
                        anchors.centerIn: parent
                        Rectangle {
                            width: screen.width * backend.boundary / 2560
                            height: screen.height
                            color: Qt.alpha(theme.accent, 0.13)
                            border.color: theme.accent
                            border.width: 1
                            Label { anchors.centerIn: parent; text: "1\n" + backend.boundary + " × 1414"; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.5; color: theme.foreground }
                        }
                        Rectangle {
                            x: screen.width * backend.boundary / 2560
                            width: screen.width - x
                            height: screen.height
                            color: Qt.alpha(theme.foreground, 0.05)
                            border.color: Qt.alpha(theme.foreground, 0.45)
                            border.width: 1
                            Label { anchors.centerIn: parent; text: "2\n" + (2560 - backend.boundary) + " × 1414"; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.5; color: theme.foreground }
                        }
                        Rectangle {
                            id: boundaryHandle
                            objectName: "sharedBoundary"
                            x: screen.width * backend.boundary / 2560 - width / 2
                            width: 16; height: parent.height
                            color: handleArea.containsMouse || handleArea.pressed ? Qt.alpha(theme.accent, 0.18) : "transparent"
                            Rectangle { anchors.centerIn: parent; width: 4; height: 38; radius: 2; color: theme.accent }
                            MouseArea {
                                id: handleArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.SizeHorCursor
                                onPositionChanged: mouse => {
                                    if (pressed) backend.set_boundary(Math.round(mapToItem(screen, mouse.x, mouse.y).x / screen.width * 2560))
                                }
                            }
                        }
                    }
                }
                Label { Layout.alignment: Qt.AlignHCenter; text: "2560 × 1414 logical pixels · two adjacent zones"; color: theme.muted }
            }
            ColumnLayout {
                Layout.preferredWidth: 188
                Layout.alignment: Qt.AlignTop
                spacing: 12
                Label { text: "Shared boundary"; font.weight: Font.DemiBold; color: theme.foreground }
                Label { text: "Left zone width"; color: theme.muted }
                SpinBox {
                    id: widthInput
                    objectName: "widthInput"
                    Layout.fillWidth: true
                    from: 320; to: 2240; stepSize: 1
                    value: backend.boundary
                    editable: true
                    onValueModified: backend.set_boundary(value)
                }
                Label { text: "Right zone: " + (2560 - backend.boundary) + " px"; color: theme.foreground }
                Label { Layout.fillWidth: true; text: "Minimum 320 px per zone.\nOverlap is prevented in Rust."; wrapMode: Text.WordWrap; color: theme.muted }
                Button { Layout.fillWidth: true; text: "Reset equal split"; onClicked: backend.reset() }
                Button { Layout.fillWidth: true; text: "Refresh theme"; onClicked: backend.refresh_theme() }
                Item { Layout.preferredHeight: 6 }
                Label { Layout.fillWidth: true; text: "Active desktop colors, border gradient and rounding."; wrapMode: Text.WordWrap; color: theme.muted }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { Layout.fillWidth: true; text: backend.status; wrapMode: Text.WrapAnywhere; color: theme.muted }
            Button { id: saveButton; objectName: "saveTestLayout"; text: "Save test layout"; onClicked: backend.save() }
        }
        Label { text: "Isolated proof of concept. Existing desktop windows are never changed."; color: theme.muted; font.pixelSize: Math.max(10, theme.fontSize - 1) }
    }
    function reportLayout() {
        let shared = boundaryHandle.mapToItem(window.contentItem, boundaryHandle.width / 2, boundaryHandle.height / 2)
        let field = widthInput.mapToItem(window.contentItem, widthInput.width / 2, widthInput.height / 2)
        let save = saveButton.mapToItem(window.contentItem, saveButton.width / 2, saveButton.height / 2)
        backend.report("AUTOMATION " + JSON.stringify({width: window.width, height: window.height, boundary: shared, input: field, save: save, boundaryValue: backend.boundary, theme: theme}))
    }
    Shortcut { sequence: "F12"; onActivated: window.reportLayout() }
    Component.onCompleted: {
        backend.watch_theme()
        Qt.callLater(() => {
            if (probeMode) {
                backend.set_boundary(0)
                if (backend.boundary !== 320) { console.error("PROBE clamp lower failed"); Qt.exit(1); return }
                backend.set_boundary(99999)
                if (backend.boundary !== 2240) { console.error("PROBE clamp upper failed"); Qt.exit(1); return }
                backend.set_boundary(1600)
                backend.save()
                backend.report("PROBE " + JSON.stringify({boundary: backend.boundary, status: backend.status, theme: theme}))
                Qt.exit(0)
            } else reportLayout()
        })
    }
}
