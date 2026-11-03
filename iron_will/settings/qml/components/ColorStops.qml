import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts

// Editor for the custom gradient stops: swatch pills (click to edit, × to
// remove), an "Add" pill, and one-click presets. Presets are previewed as flat
// color segments rather than gradients, to keep the chrome itself flat.
ColumnLayout {
    id: editor
    property string key: "visualizer.colors"
    property color accent: Theme.primary
    property var colors: []
    readonly property int maxStops: 6

    readonly property var presets: [
        { name: "Aurora",     colors: ["#2EC4B6", "#3A86FF", "#8338EC"] },
        { name: "Reef",       colors: ["#2EC4B6", "#FF6B5B"] },
        { name: "Ember",      colors: ["#FFBE0B", "#FB5607", "#FF006E"] },
        { name: "Synthwave",  colors: ["#F72585", "#7209B7", "#4CC9F0"] },
        { name: "Lagoon",     colors: ["#90E0EF", "#00B4D8", "#0077B6"] },
        { name: "Forest",     colors: ["#B7E4C7", "#52B788", "#2D6A4F"] },
        { name: "Mono",       colors: ["#E8EDF2"] }
    ]

    spacing: 14
    Layout.fillWidth: true

    function sync() { colors = backend.get(key) }
    Component.onCompleted: sync()
    Connections { target: backend; function onRevisionChanged() { editor.sync() } }

    function commit(list) { backend.set(key, list) }
    function sameColors(a, b) {
        if (a.length !== b.length) return false
        for (var i = 0; i < a.length; i++) if (a[i].toUpperCase() !== b[i].toUpperCase()) return false
        return true
    }

    Flow {
        Layout.fillWidth: true
        spacing: 10

        Repeater {
            model: editor.colors
            delegate: Rectangle {
                id: swatch
                required property string modelData
                required property int index
                width: swatchRow.implicitWidth + 16
                height: 36
                radius: 18
                color: swatchMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceHi
                border.color: Theme.border

                MouseArea {
                    id: swatchMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { dialog.editIndex = swatch.index; dialog.selectedColor = swatch.modelData; dialog.open() }
                }
                Row {
                    id: swatchRow
                    anchors.verticalCenter: parent.verticalCenter
                    x: 6
                    spacing: 8
                    Rectangle {
                        width: 24; height: 24; radius: 12
                        color: swatch.modelData
                        border.color: Qt.rgba(1, 1, 1, 0.12)
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: swatch.modelData
                        color: Theme.text
                        font.pixelSize: Theme.fontSmall
                        font.family: "monospace"
                    }
                    Item {
                        visible: editor.colors.length > 1
                        width: 20; height: 20
                        anchors.verticalCenter: parent.verticalCenter
                        Rectangle {
                            anchors.fill: parent; radius: 10
                            color: removeMouse.containsMouse ? Theme.tint(Theme.secondary, 0.2) : "transparent"
                        }
                        Icon {
                            anchors.centerIn: parent
                            name: "close"; size: 14
                            color: removeMouse.containsMouse ? Theme.secondary : Theme.textMuted
                        }
                        MouseArea {
                            id: removeMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: { var c = editor.colors.slice(); c.splice(swatch.index, 1); editor.commit(c) }
                        }
                    }
                }
            }
        }

        PillButton {
            visible: editor.colors.length < editor.maxStops
            kind: "tonal"
            accent: editor.accent
            iconName: "add"
            text: "Add stop"
            onClicked: {
                var c = editor.colors.slice()
                c.push(c.length ? c[c.length - 1] : "#2EC4B6")
                editor.commit(c)
                dialog.editIndex = c.length - 1
                dialog.selectedColor = c[c.length - 1]
                dialog.open()
            }
        }
    }

    Text {
        text: "Presets"
        color: Theme.textMuted
        font.pixelSize: Theme.fontSmall
        font.weight: Font.Medium
    }

    Flow {
        Layout.fillWidth: true
        spacing: 8
        Repeater {
            model: editor.presets
            delegate: Rectangle {
                id: preset
                required property var modelData
                readonly property bool active: editor.sameColors(editor.colors, modelData.colors)
                width: presetRow.implicitWidth + 24
                height: 34
                radius: 17
                color: active ? Theme.tint(editor.accent, 0.14) : (presetMouse.containsMouse ? Theme.surfaceHover : Theme.surfaceHi)
                border.color: active ? editor.accent : Theme.border
                Behavior on color { ColorAnimation { duration: 120 } }

                Row {
                    id: presetRow
                    anchors.centerIn: parent
                    spacing: 8
                    Row {   // overlapping flat dots, not a gradient
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: -5
                        Repeater {
                            model: preset.modelData.colors
                            delegate: Rectangle {
                                required property string modelData
                                width: 16; height: 16; radius: 8
                                color: modelData
                                border.width: 2
                                border.color: preset.color
                            }
                        }
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: preset.modelData.name
                        color: preset.active ? Theme.text : Theme.textMuted
                        font.pixelSize: Theme.fontSmall
                        font.weight: Font.Medium
                    }
                }
                MouseArea {
                    id: presetMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: editor.commit(preset.modelData.colors)
                }
            }
        }
    }

    ColorDialog {
        id: dialog
        property int editIndex: 0
        title: "Choose a color"
        onAccepted: {
            var c = editor.colors.slice()
            c[editIndex] = Theme.hex(selectedColor)
            editor.commit(c)
        }
    }
}
