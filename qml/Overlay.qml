pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui

// The controller owns the gesture. This surface only renders its current
// snapshot; an empty input mask keeps the native compositor drag in control.
PanelWindow {
    id: root
    required property var controller

    readonly property var profiles: controller.profiles || []
    readonly property var currentProfile: profiles[controller.profileIndex] || null
    readonly property var zones: currentProfile ? currentProfile.zones : []
    readonly property var picker: controller.picker || ({x: 0, y: 0, w: 0, h: 0, cards: []})
    readonly property real originX: controller.bounds.x - (screen ? screen.x : 0)
    readonly property real originY: controller.bounds.y - (screen ? screen.y : 0)

    readonly property var matchedScreen: Quickshell.screens.find(function(candidate) { return candidate.name === root.controller.monitorName }) || null
    screen: matchedScreen
    visible: controller.active && matchedScreen !== null
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    mask: Region {}
    WlrLayershell.namespace: "omarchy-zones"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Item {
        id: usable
        x: root.originX
        y: root.originY
        width: root.controller.bounds.w
        height: root.controller.bounds.h

        Repeater {
            model: root.zones
            delegate: BorderSurface {
                id: zone
                required property var modelData
                required property int index
                readonly property bool selected: index === root.controller.hoverIndex
                x: modelData.x
                y: modelData.y
                width: modelData.w
                height: modelData.h
                radius: Math.min(Style.cornerRadius, width / 2, height / 2)
                antialiasing: true
                color: selected ? Style.selectionFillFor(Color.foreground, Color.accent)
                                : Style.normalFillFor(Color.foreground, Color.accent)
                borderSpec: selected ? Border.surfaceSpec("popups", "border", Color.accent, 2)
                                     : Border.controlSpec("normal", Color.foreground, Color.accent)

                Rectangle {
                    anchors.centerIn: parent
                    width: Math.min(34, zone.width, zone.height)
                    height: width
                    radius: Math.min(Style.cornerRadius, width / 2)
                    antialiasing: true
                    color: zone.selected ? Color.accent : Color.background
                    Text {
                        anchors.centerIn: parent
                        text: zone.index + 1
                        textFormat: Text.PlainText
                        font.family: Style.font.family
                        font.pixelSize: Style.font.heading
                        color: zone.selected ? Color.background : Color.foreground
                    }
                }
            }
        }

        BorderSurface {
            id: pickerSurface
            x: root.picker.x
            y: root.picker.y
            width: root.picker.w
            height: root.picker.h
            visible: width > 0 && height > 0
            radius: Style.cornerRadius
            antialiasing: true
            color: Color.popups.background
            borderSpec: Border.surfaceSpec("popups", "border", Color.accent, 2)

            Text {
                x: 14; y: 8; width: 70; height: 25
                text: "Zones"
                textFormat: Text.PlainText
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                font.bold: true
                color: Color.popups.text
                verticalAlignment: Text.AlignVCenter
            }
            Text {
                x: parent.width - 120; y: 8; width: 106; height: 25
                text: "Super + Shift"
                textFormat: Text.PlainText
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                color: Color.muted
                horizontalAlignment: Text.AlignRight
                verticalAlignment: Text.AlignVCenter
            }
            Repeater {
                model: root.picker.cards
                delegate: Item {
                    id: card
                    required property var modelData
                    readonly property int profileIndex: modelData.index
                    readonly property bool selected: profileIndex === root.controller.profileIndex
                    x: modelData.x - root.picker.x
                    y: modelData.y - root.picker.y
                    width: modelData.w
                    height: modelData.h

                    BorderSurface {
                        id: preview
                        width: card.modelData.thumbnail.w
                        height: card.modelData.thumbnail.h
                        radius: Style.cornerRadius / 2
                        antialiasing: true
                        color: card.selected ? Style.selectedFillFor(Color.foreground, Color.accent)
                                             : Style.normalFillFor(Color.foreground, Color.accent)
                        borderSpec: Border.controlSpec(card.selected ? "selected" : "normal", Color.foreground, Color.accent)

                        Repeater {
                            model: card.modelData.miniZones
                            delegate: Rectangle {
                                id: mini
                                required property var modelData
                                readonly property bool selected: card.selected && modelData.index === root.controller.hoverIndex
                                x: modelData.x - card.modelData.thumbnail.x
                                y: modelData.y - card.modelData.thumbnail.y
                                width: modelData.w
                                height: modelData.h
                                radius: Math.min(Style.cornerRadius / 4, width / 2, height / 2)
                                antialiasing: true
                                color: selected ? Color.accent : Util.alpha(Color.muted, Style.selectionFillAlpha)
                                Text {
                                    anchors.centerIn: parent
                                    visible: mini.width >= 14 && mini.height >= 16
                                    text: mini.modelData.index + 1
                                    textFormat: Text.PlainText
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.caption
                                    color: mini.selected ? Color.background : Color.foreground
                                }
                            }
                        }
                    }
                    Text {
                        y: preview.height + 3
                        width: parent.width
                        height: 20
                        text: root.profiles[card.profileIndex].name
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        color: Color.popups.text
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
            Text {
                x: 14; y: parent.height - 25
                width: parent.width - 28; height: 20
                text: parent.width < 300 ? "Release to snap" : "Hover a zone · Release to snap"
                textFormat: Text.PlainText
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                color: Color.popups.text
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
}
