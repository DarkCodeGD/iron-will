import QtQuick

// Small status / info pill.
Rectangle {
    id: chip
    property string text
    property string iconName
    property color accent: Theme.textMuted
    property bool filled: false

    implicitHeight: 26
    // Natural size from the label's *implicit* width (Row measures actual
    // widths, and the label shrinks to elide, so using the Row would loop).
    readonly property real iconSpace: chipIcon.visible ? chipIcon.width + row.spacing : 0
    implicitWidth: iconSpace + label.implicitWidth + 20
    radius: height / 2
    color: filled ? Theme.tint(accent, 0.15) : Theme.surfaceHi
    border.width: filled ? 0 : 1
    border.color: Theme.border

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Icon {
            id: chipIcon
            visible: chip.iconName.length > 0
            anchors.verticalCenter: parent.verticalCenter
            name: chip.iconName; size: 14
            color: chip.filled ? chip.accent : Theme.textMuted
        }
        Text {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            // Natural width, but elide when a layout squeezes the chip.
            width: Math.max(0, Math.min(implicitWidth, chip.width - 20 - chip.iconSpace))
            elide: Text.ElideRight
            text: chip.text
            color: chip.filled ? chip.accent : Theme.textMuted
            font.pixelSize: Theme.fontSmall
            font.weight: Font.Medium
        }
    }
}
