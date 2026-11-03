import QtQuick
import QtQuick.Layouts

// Genre preset picker: one tap retunes the motion physics + frequency range.
// The active tile is derived from the live config (no stored "preset" key),
// so touching any slider afterwards naturally shows "Custom tuning".
Card {
    id: card
    title: "Genre presets"
    subtitle: "Tuned bounce and frequency range for what you listen to. Colors and layout stay yours."
    iconName: "music"

    readonly property string active: backend.activePreset
    readonly property var activeInfo: {
        for (var i = 0; i < backend.genrePresets.length; i++)
            if (backend.genrePresets[i].id === active) return backend.genrePresets[i]
        return null
    }

    actions: Chip {
        filled: true
        accent: card.activeInfo ? Theme.primary : Theme.secondary
        iconName: card.activeInfo ? "check" : "tune"
        text: card.activeInfo ? card.activeInfo.name : "Custom tuning"
    }

    GridLayout {
        Layout.fillWidth: true
        columns: width > 620 ? 2 : 1
        columnSpacing: 12
        rowSpacing: 12

        Repeater {
            model: backend.genrePresets
            delegate: Rectangle {
                id: tile
                required property var modelData
                readonly property bool selected: modelData.id === card.active

                Layout.fillWidth: true
                Layout.fillHeight: true          // equal heights across a row
                implicitHeight: content.implicitHeight + 32
                radius: 20
                color: selected ? Theme.tint(Theme.primary, 0.10) : (mouse.containsMouse ? Theme.surfaceHover : Theme.surfaceHi)
                border.width: selected ? 1.5 : 1
                border.color: selected ? Theme.primary : Theme.border
                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on border.color { ColorAnimation { duration: 140 } }

                RowLayout {
                    id: content
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 16; rightMargin: 16 }
                    spacing: 14

                    Rectangle {
                        Layout.alignment: Qt.AlignTop
                        implicitWidth: 42; implicitHeight: 42; radius: 21
                        color: tile.selected ? Theme.primary : Theme.tint(Theme.primary, 0.14)
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Icon {
                            anchors.centerIn: parent
                            name: tile.modelData.icon; size: 20
                            color: tile.selected ? Theme.ink : Theme.primary
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            Layout.fillWidth: true
                            text: tile.modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                        }
                        Text {
                            Layout.fillWidth: true
                            text: tile.modelData.tagline
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSmall
                            wrapMode: Text.WordWrap
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.topMargin: 2
                            text: tile.modelData.details
                            color: tile.selected ? Theme.primary : Theme.textFaint
                            font.pixelSize: Theme.fontCaption
                            font.features: { "tnum": 1 }
                        }
                    }
                }

                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: backend.applyPreset(tile.modelData.id)
                }
            }
        }
    }
}
