import QtQuick

// Small status / info pill.
Rectangle {
    id: chip
    property string text
    property string iconName
    property color accent: Theme.textMuted
    property bool filled: false

    implicitHeight: 26
    implicitWidth: row.implicitWidth + 20
    radius: height / 2
    color: filled ? Theme.tint(accent, 0.15) : Theme.surfaceHi
    border.width: filled ? 0 : 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon {
            visible: chip.iconName.length > 0
            anchors.verticalCenter: parent.verticalCenter
            name: chip.iconName; size: 14
            color: chip.filled ? chip.accent : Theme.textMuted
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: chip.text
            color: chip.filled ? chip.accent : Theme.textMuted
            font.pixelSize: Theme.fontSmall
            font.weight: Font.Medium
        }
    }
}
