import QtQuick
import QtQuick.Layouts

// Label on the left, segmented choices on the right — choices come from the schema.
RowLayout {
    id: row
    property string key
    property string label
    property string description
    property var labels: ({})        // value → display label (defaults to Capitalised value)
    property color accent: Theme.primary
    readonly property string value: seg.current

    Layout.fillWidth: true
    spacing: 16

    function sync() { seg.current = backend.get(key) }
    Component.onCompleted: sync()
    Connections { target: backend; function onRevisionChanged() { row.sync() } }

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
    Segmented {
        id: seg
        accent: row.accent
        options: backend.field(row.key).choices.map(function (v) {
            return { value: v, label: row.labels[v] || (v.charAt(0).toUpperCase() + v.slice(1)) }
        })
        onPicked: function (value) { seg.current = value; backend.set(row.key, value) }
    }
}
