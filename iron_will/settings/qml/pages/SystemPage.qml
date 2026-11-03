import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "System"
    subtitle: "Background services, dependencies and configuration."

    property var deps: backend.dependencies()
    onVisibleChanged: if (visible) { deps = backend.dependencies(); backend.refreshServices() }

    Card {
        title: "Background services"
        subtitle: "systemd user services — switching one on also starts it at every login"
        iconName: "system"

        Repeater {
            model: backend.services
            delegate: ColumnLayout {
                required property var modelData
                required property int index
                Layout.fillWidth: true
                spacing: 16

                Divider { visible: index > 0 }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 16
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        RowLayout {
                            spacing: 10
                            Text { text: modelData.label; color: Theme.text; font.pixelSize: Theme.fontBody; font.weight: Font.Medium }
                            Chip {
                                filled: true
                                accent: !modelData.installed ? Theme.textMuted
                                      : modelData.active ? Theme.success
                                      : modelData.state === "failed" ? Theme.danger : Theme.textMuted
                                text: !modelData.installed ? "Not installed"
                                    : modelData.active ? "Running"
                                    : modelData.state === "failed" ? "Failed" : "Stopped"
                            }
                        }
                        Text {
                            text: modelData.installed ? modelData.description : "Run ./install.sh to set up " + modelData.unit
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSmall
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                    PillSwitch {
                        enabled: modelData.installed
                        checked: modelData.active && modelData.enabled
                        onToggled: backend.setServiceRunning(modelData.unit, checked)
                    }
                }
            }
        }
    }

    Card {
        title: "Dependencies"
        subtitle: "What Iron Will needs on this machine"

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 12
            rowSpacing: 12

            Repeater {
                model: page.deps
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 58
                    radius: 29
                    color: Theme.surfaceHi
                    border.color: Theme.border

                    RowLayout {
                        anchors { fill: parent; leftMargin: 12; rightMargin: 18 }
                        spacing: 12
                        Rectangle {
                            implicitWidth: 34; implicitHeight: 34; radius: 17
                            color: Theme.tint(modelData.ok ? Theme.success : Theme.danger, 0.16)
                            Icon {
                                anchors.centerIn: parent
                                name: modelData.ok ? "check" : "close"; size: 18
                                color: modelData.ok ? Theme.success : Theme.danger
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text { text: modelData.name; color: Theme.text; font.pixelSize: 13; font.weight: Font.DemiBold }
                            Text {
                                text: modelData.ok ? modelData.detail : "Missing — install " + modelData.package
                                color: modelData.ok ? Theme.textMuted : Theme.danger
                                font.pixelSize: Theme.fontCaption
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }
    }

    Card {
        title: "Configuration"
        subtitle: "Everything lives in one commented TOML file. Edits here save automatically; hand edits are picked up live."
        iconName: "file"

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                radius: height / 2
                color: Theme.surfaceHi
                border.color: Theme.border
                Text {
                    anchors { left: parent.left; right: parent.right; margins: 16; verticalCenter: parent.verticalCenter }
                    text: backend.configPath
                    elide: Text.ElideMiddle
                    color: Theme.text
                    font.pixelSize: 13
                    font.family: "monospace"
                }
            }
            PillButton { kind: "tonal"; iconName: "open"; text: "Open file"; onClicked: backend.openPath(backend.configPath) }
        }
    }

    Text {
        Layout.fillWidth: true
        Layout.topMargin: 4
        horizontalAlignment: Text.AlignHCenter
        text: "Iron Will " + backend.version + " · desktop audio toolkit for KDE Plasma"
        color: Theme.textFaint
        font.pixelSize: Theme.fontCaption
    }
}
