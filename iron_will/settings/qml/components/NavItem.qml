import QtQuick
import QtQuick.Layouts

// Sidebar navigation pill.
Rectangle {
    id: nav
    property string label
    property string iconName
    property bool active
    property color accent: Theme.primary
    signal clicked

    Layout.fillWidth: true
    implicitHeight: 42
    radius: height / 2
    color: active ? Theme.tint(accent, 0.15) : (mouse.containsMouse ? Theme.surfaceHi : "transparent")
    Behavior on color { ColorAnimation { duration: 140 } }

    Row {
        anchors.verticalCenter: parent.verticalCenter
        x: 16
        spacing: 12
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: nav.iconName
            size: 18
            color: nav.active ? nav.accent : Theme.textMuted
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: nav.label
            color: nav.active ? Theme.text : Theme.textMuted
            font.pixelSize: Theme.fontBody
            font.weight: nav.active ? Font.DemiBold : Font.Medium
        }
    }

    // Small accent dot marks the active page.
    Rectangle {
        visible: nav.active
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        width: 6; height: 6; radius: 3
        color: nav.accent
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: nav.clicked()
    }
}
