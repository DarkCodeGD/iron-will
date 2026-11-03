import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Label + value pill + pill slider, bound to a config key.
// Range defaults to the schema's min/max (DRY); override from/to when a
// friendlier UI range makes sense.
ColumnLayout {
    id: row
    property string key
    property string label
    property string description
    property string unit
    property int decimals: 0
    property real stepSize: 0
    property color accent: Theme.primary
    property var format: null              // optional function(value) → string
    readonly property var meta: backend.field(key)
    property real from: meta.min
    property real to: meta.max

    Layout.fillWidth: true
    spacing: 10
    opacity: enabled ? 1 : 0.4

    function display(v) {
        if (row.format) return row.format(v)
        return Number(v).toFixed(row.decimals) + row.unit
    }
    function sync() { if (!slider.pressed) slider.value = backend.get(key) }
    Component.onCompleted: sync()
    Connections { target: backend; function onRevisionChanged() { row.sync() } }

    RowLayout {
        Layout.fillWidth: true
        spacing: 12
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3
            Text { text: row.label; color: Theme.text; font.pixelSize: Theme.fontBody; font.weight: Font.Medium; Layout.fillWidth: true }
            Text {
                visible: text.length > 0
                text: row.description
                color: Theme.textMuted
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
        Rectangle {
            implicitWidth: Math.max(52, valueText.implicitWidth + 22)
            implicitHeight: 26
            radius: height / 2
            color: Theme.tint(row.accent, 0.14)
            Text {
                id: valueText
                anchors.centerIn: parent
                text: row.display(slider.value)
                color: row.accent
                font.pixelSize: Theme.fontSmall
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
        }
    }

    Slider {
        id: slider
        Layout.fillWidth: true
        from: row.from
        to: row.to
        stepSize: row.stepSize > 0 ? row.stepSize : Math.pow(10, -row.decimals)
        snapMode: Slider.SnapAlways
        padding: 0
        implicitHeight: 22
        hoverEnabled: true
        onMoved: backend.set(row.key, value)

        background: Rectangle {
            x: slider.leftPadding
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth
            height: 6
            radius: 3
            color: Theme.surfaceHover
            Rectangle {
                width: slider.visualPosition * parent.width
                height: parent.height
                radius: 3
                color: row.accent
            }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: 20; height: 20; radius: 10
            color: "#FFFFFF"
            border.width: 5
            border.color: row.accent
            scale: slider.pressed ? 1.12 : (slider.hovered ? 1.05 : 1.0)
            Behavior on scale { NumberAnimation { duration: 120 } }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
    }
}
