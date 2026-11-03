import QtQuick
import QtQuick.Layouts

// Rounded, flat surface with an optional header (title, subtitle, actions).
Rectangle {
    id: card
    property string title
    property string subtitle
    property string iconName
    property color accent: Theme.primary
    default property alias content: body.data
    property alias actions: actionRow.data

    Layout.fillWidth: true
    implicitHeight: column.implicitHeight + 48
    radius: Theme.radiusCard
    color: Theme.surface
    border.color: Theme.border
    border.width: 1

    ColumnLayout {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
        spacing: 20

        RowLayout {
            visible: card.title.length > 0
            Layout.fillWidth: true
            spacing: 12

            Rectangle {
                visible: card.iconName.length > 0
                implicitWidth: 34; implicitHeight: 34; radius: 17
                color: Theme.tint(card.accent, 0.14)
                Icon { anchors.centerIn: parent; name: card.iconName; size: 18; color: card.accent }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text { text: card.title; color: Theme.text; font.pixelSize: Theme.fontSection; font.weight: Font.DemiBold }
                Text {
                    visible: text.length > 0
                    text: card.subtitle
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
            Row { id: actionRow; spacing: 8; Layout.alignment: Qt.AlignVCenter }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: 20
        }
    }
}
