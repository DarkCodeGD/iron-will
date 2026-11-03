import QtQuick

// Pill segmented control with a highlight pill that glides between options.
//   options: [{ value: "bars", label: "Bars" }, …]
Rectangle {
    id: seg
    property var options: []
    property string current
    property color accent: Theme.primary
    signal picked(string value)

    readonly property int index: {
        for (var i = 0; i < options.length; i++)
            if (options[i].value === current) return i
        return -1
    }

    implicitHeight: Theme.controlHeight
    implicitWidth: row.implicitWidth + 8
    radius: height / 2
    color: Theme.surfaceHi
    border.color: Theme.border
    border.width: 1
    opacity: enabled ? 1 : 0.4

    Rectangle {
        id: highlight
        readonly property Item target: { rep.count; return seg.index >= 0 ? rep.itemAt(seg.index) : null }
        visible: target !== null
        y: 4
        height: parent.height - 8
        x: target ? row.x + target.x : 4
        width: target ? target.width : 0
        radius: height / 2
        color: seg.accent
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }

    Row {
        id: row
        x: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Repeater {
            id: rep
            model: seg.options
            delegate: Item {
                required property var modelData
                required property int index
                width: label.implicitWidth + 30
                height: seg.height - 8
                Text {
                    id: label
                    anchors.centerIn: parent
                    text: modelData.label
                    font.pixelSize: 13
                    font.weight: Font.Medium
                    color: index === seg.index ? Theme.ink : (mouse.containsMouse ? Theme.text : Theme.textMuted)
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                MouseArea {
                    id: mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: seg.picked(modelData.value)
                }
            }
        }
    }
}
