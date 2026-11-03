import QtQuick
import QtQuick.Controls.Basic

// Pill-shaped button.
//   kind: "primary" (solid accent) | "tonal" (tinted accent) | "ghost" (neutral outline)
Button {
    id: control
    property string kind: "primary"
    property color accent: Theme.primary
    property string iconName

    readonly property color fg: kind === "primary" ? Theme.ink
                              : kind === "tonal" ? accent
                              : (hovered ? Theme.text : Theme.textMuted)

    implicitHeight: Theme.controlHeight
    leftPadding: iconName.length && text.length ? 14 : 16
    rightPadding: 16
    hoverEnabled: true
    opacity: enabled ? 1 : 0.4

    contentItem: Row {
        spacing: 8
        Icon {
            visible: control.iconName.length > 0
            anchors.verticalCenter: parent.verticalCenter
            name: control.iconName
            size: 16
            color: control.fg
        }
        Text {
            visible: control.text.length > 0
            anchors.verticalCenter: parent.verticalCenter
            text: control.text
            color: control.fg
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }

    background: Rectangle {
        radius: height / 2
        color: {
            if (control.kind === "primary")
                return control.down ? Qt.darker(control.accent, 1.15)
                     : control.hovered ? Qt.lighter(control.accent, 1.08) : control.accent
            if (control.kind === "tonal")
                return Theme.tint(control.accent, control.down ? 0.28 : control.hovered ? 0.22 : 0.14)
            return control.down ? Theme.surfaceHover : control.hovered ? Theme.surfaceHi : "transparent"
        }
        border.width: control.kind === "ghost" ? 1 : 0
        border.color: Theme.border
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    HoverHandler { cursorShape: Qt.PointingHandCursor }
}
