import QtQuick
import QtQuick.Layouts
import IronWill 1.0

// Live preview: the *same* Visualizer the desktop uses, fed by a synthetic
// music-like signal, so what you see here is exactly what you get.
Rectangle {
    id: card
    Layout.fillWidth: true
    implicitHeight: 196
    radius: Theme.radiusCard
    color: Theme.surface
    border.color: Theme.border

    property int rev: backend.revision
    readonly property bool topAnchor: { rev; return backend.get("layout.anchor") === "top" }
    readonly property int configuredHeight: { rev; return backend.get("layout.height") }

    RowLayout {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
        Text { text: "Live preview"; color: Theme.text; font.pixelSize: Theme.fontSection; font.weight: Font.DemiBold }
        Item { Layout.fillWidth: true }
        Rectangle {   // "LIVE" pill with a pulsing coral dot
            implicitHeight: 24
            implicitWidth: liveRow.implicitWidth + 20
            radius: 12
            color: Theme.tint(Theme.secondary, 0.14)
            Row {
                id: liveRow
                anchors.centerIn: parent
                spacing: 6
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 7; height: 7; radius: 3.5
                    color: Theme.secondary
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: card.visible
                        NumberAnimation { to: 0.3; duration: 700; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
                    }
                }
                Text { text: "DEMO SIGNAL"; color: Theme.secondary; font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 0.8 }
            }
        }
    }

    Rectangle {
        id: stage
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; top: header.bottom; margins: 20; topMargin: 14 }
        radius: Theme.radiusInner
        color: Theme.canvas
        clip: true

        Visualizer {
            store: configStore
            demo: true
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 32
            height: Math.min(parent.height - 24, Math.max(24, card.configuredHeight))
            y: card.topAnchor ? 12 : parent.height - height - 12
        }
    }
}
