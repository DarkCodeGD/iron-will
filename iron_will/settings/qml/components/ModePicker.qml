import QtQuick
import QtQuick.Layouts

// Render-mode picker: one compact tile per visualizer (custom SVG icon + name),
// wrapping onto new rows as more visualizers are added. The tiles come from
// the Python mode registry (backend.renderModes, see visualizer/modes.py), so
// a new visualizer shows up here without touching this file.
// The selected mode's tagline is shown under the tiles.
ColumnLayout {
    id: picker
    property string key: "visualizer.mode"
    readonly property string current: { backend.revision; return backend.get(key) }
    readonly property var currentInfo: {
        var all = backend.renderModes
        for (var i = 0; i < all.length; i++)
            if (all[i].id === current) return all[i]
        return null
    }

    Layout.fillWidth: true
    spacing: 12

    Text {
        text: "Render mode"
        color: Theme.text
        font.pixelSize: Theme.fontBody
        font.weight: Font.Medium
    }

    Flow {
        Layout.fillWidth: true
        spacing: 10

        Repeater {
            model: backend.renderModes
            delegate: Rectangle {
                id: tile
                required property var modelData
                readonly property bool selected: modelData.id === picker.current
                readonly property bool lit: selected || mouse.containsMouse

                width: 112; height: 108
                radius: Theme.radiusInner + 4
                color: selected ? Theme.tint(Theme.primary, 0.10) : (mouse.containsMouse ? Theme.surfaceHover : Theme.surfaceHi)
                border.width: selected ? 1.5 : 1
                border.color: selected ? Theme.primary : Theme.border
                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on border.color { ColorAnimation { duration: 140 } }

                Accessible.role: Accessible.RadioButton
                Accessible.name: modelData.name
                Accessible.checked: selected

                // Unselected icons sit back in neutral grey (half-desaturated
                // orange reads as brown) so the active one pops; hovering
                // brings them to full color. Two images crossfade: the grey
                // one comes from the icon provider, not a shader, so this also
                // works on the software renderer.
                Item {
                    id: art
                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 16 }
                    width: 48; height: 48
                    scale: mouse.pressed ? 0.94 : 1.0
                    Behavior on scale { NumberAnimation { duration: 90 } }

                    Image {
                        anchors.fill: parent
                        source: tile.modelData.icon + "/grey"
                        sourceSize: Qt.size(96, 96)    // 2× for crisp HiDPI
                        smooth: true
                        opacity: tile.lit ? 0.0 : 0.55
                        Behavior on opacity { NumberAnimation { duration: 160 } }
                    }
                    Image {
                        anchors.fill: parent
                        source: tile.modelData.icon
                        sourceSize: Qt.size(96, 96)
                        smooth: true
                        opacity: tile.lit ? 1.0 : 0.0
                        Behavior on opacity { NumberAnimation { duration: 160 } }
                    }
                }

                Text {
                    anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 14 }
                    width: parent.width - 12
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: tile.modelData.name
                    color: tile.selected ? Theme.text : Theme.textMuted
                    font.pixelSize: 13
                    font.weight: tile.selected ? Font.DemiBold : Font.Medium
                }

                // Check badge on the active tile.
                Rectangle {
                    visible: tile.selected
                    anchors { top: parent.top; right: parent.right; margins: 8 }
                    width: 18; height: 18; radius: 9
                    color: Theme.primary
                    Icon { anchors.centerIn: parent; name: "check"; size: 13; color: Theme.ink }
                }

                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: if (!tile.selected) backend.set(picker.key, tile.modelData.id)
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        visible: text.length > 0
        text: picker.currentInfo ? picker.currentInfo.tagline : ""
        color: Theme.textMuted
        font.pixelSize: Theme.fontSmall
        wrapMode: Text.WordWrap
    }
}
