import QtQuick
import QtQuick.Layouts

// "Your visualizer is too short for this mode" hint with one-click fixes.
// GPU modes (fire, ferrofluid, …) need height to breathe; the default strip
// is made for bars. Hidden once the strip is tall enough or full height.
Rectangle {
    id: hint
    property string what: "This mode"     // e.g. "Fire"
    property string icon: "flame"
    readonly property int windowHeight: { backend.revision; return backend.get("layout.height") }
    readonly property bool fullHeight: { backend.revision; return backend.get("layout.full_height") }

    visible: windowHeight < 200 && !fullHeight
    Layout.fillWidth: true
    implicitHeight: hintRow.implicitHeight + 24
    radius: Theme.radiusInner
    color: Theme.tint(Theme.primary, 0.10)
    border.color: Theme.tint(Theme.primary, 0.35)

    RowLayout {
        id: hintRow
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
        spacing: 12
        Icon { name: hint.icon; size: 18; color: Theme.primary }
        Text {
            Layout.fillWidth: true
            text: "Your visualizer is " + hint.windowHeight + " px tall. " + hint.what + " really comes alive at 220–300 px."
            color: Theme.text; font.pixelSize: Theme.fontSmall; wrapMode: Text.WordWrap
        }
        PillButton {
            kind: "ghost"; text: "Make it 260 px"
            onClicked: backend.set("layout.height", 260)
        }
        PillButton {
            kind: "ghost"; text: "Full screen"
            onClicked: backend.setFullHeight(true)
        }
    }
}
