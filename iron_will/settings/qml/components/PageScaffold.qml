import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Scrollable page with a title header and a two-step "Reset" pill
// (first click arms it, second click within 3 s confirms).
Item {
    id: page
    property string title
    property string subtitle
    property color accent: Theme.primary
    property var resetSections: []
    default property alias content: column.data

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight + 72
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            id: bar
            policy: ScrollBar.AsNeeded
            contentItem: Rectangle {
                implicitWidth: 6
                radius: 3
                color: bar.pressed ? Theme.textFaint : Theme.surfaceHover
                opacity: bar.active ? 1 : 0.5
            }
        }

        ColumnLayout {
            id: column
            width: Math.min(page.width - 64, 860)
            x: (page.width - width) / 2
            y: 36
            spacing: Theme.gap

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 8
                spacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Text { text: page.title; color: Theme.text; font.pixelSize: Theme.fontTitle; font.weight: Font.DemiBold }
                    Text {
                        text: page.subtitle
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontBody
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
                PillButton {
                    id: resetButton
                    property bool armed: false
                    visible: page.resetSections.length > 0
                    kind: armed ? "tonal" : "ghost"
                    accent: Theme.secondary
                    iconName: "reset"
                    text: armed ? "Click to confirm" : "Reset"
                    onClicked: {
                        if (!armed) { armed = true; disarm.restart(); return }
                        armed = false
                        page.resetSections.forEach(function (s) { backend.resetSection(s) })
                    }
                    Timer { id: disarm; interval: 3000; onTriggered: resetButton.armed = false }
                }
            }
        }
    }
}
