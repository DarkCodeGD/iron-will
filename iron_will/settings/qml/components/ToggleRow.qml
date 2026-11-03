import QtQuick
import QtQuick.Layouts

// Label + description on the left, pill switch on the right, bound to a config key.
RowLayout {
    id: row
    property string key
    property string label
    property string description
    property color accent: Theme.primary
    // Optional custom write (e.g. a backend slot that also adjusts related keys).
    property var setter: null
    readonly property bool checked: sw.checked

    Layout.fillWidth: true
    spacing: 16

    function sync() { sw.checked = backend.get(key) === true }
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
    PillSwitch {
        id: sw
        accent: row.accent
        onToggled: row.setter ? row.setter(checked) : backend.set(row.key, checked)
    }
}
