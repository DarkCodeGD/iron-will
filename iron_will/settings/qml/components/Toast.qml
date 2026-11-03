import QtQuick

// Transient pill notification that slides up from the bottom edge.
Rectangle {
    id: toast
    property string message
    property string kind: "info"     // "info" | "error"
    readonly property color accent: kind === "error" ? Theme.secondary : Theme.primary

    function show(msg, k) { message = msg; kind = k || "info"; shown = true; hideTimer.restart() }
    property bool shown: false

    anchors.horizontalCenter: parent.horizontalCenter
    y: shown ? parent.height - height - 28 : parent.height + 12
    opacity: shown ? 1 : 0
    implicitHeight: 42
    implicitWidth: row.implicitWidth + 36
    radius: height / 2
    color: Theme.surfaceHi
    border.color: Theme.tint(accent, 0.5)
    border.width: 1
    z: 100

    Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 10
        Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: toast.accent }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: toast.message
            color: Theme.text
            font.pixelSize: 13
            font.weight: Font.Medium
        }
    }

    Timer { id: hideTimer; interval: 2800; onTriggered: toast.shown = false }
}
