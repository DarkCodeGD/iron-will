import QtQuick
import QtQuick.Controls.Basic

// Pill toggle with a sliding knob.
Switch {
    id: control
    property color accent: Theme.primary

    implicitWidth: 46
    implicitHeight: 26
    padding: 0
    spacing: 0
    hoverEnabled: true

    indicator: Rectangle {
        implicitWidth: 46
        implicitHeight: 26
        radius: height / 2
        color: control.checked ? control.accent : (control.hovered ? Theme.surfaceHover : Theme.surfaceHi)
        border.width: control.checked ? 0 : 1
        border.color: Theme.border
        opacity: control.enabled ? 1 : 0.4
        Behavior on color { ColorAnimation { duration: 160 } }

        Rectangle {
            width: 20; height: 20; radius: 10
            y: 3
            x: control.checked ? parent.width - width - 3 : 3
            color: control.checked ? "#FFFFFF" : Theme.textMuted
            Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Behavior on color { ColorAnimation { duration: 160 } }
        }
    }
    contentItem: Item {}
    background: Item {}

    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
