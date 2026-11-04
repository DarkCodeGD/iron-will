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

    // Only on machines with a second, dedicated GPU (most gaming laptops).
    Card {
        id: gpuCard
        readonly property var info: backend.gpu
        visible: info.available === true
        title: "Graphics card"
        subtitle: "This computer has two GPUs. Pick the one that draws the visualizer."
        iconName: "bolt"

        SegmentedRow {
            key: "visualizer.gpu"
            label: "Draw the visualizer on"
            description: "Integrated (" + gpuCard.info.integrated + ") saves battery. Dedicated ("
                       + gpuCard.info.dedicated + ") is faster, but stays awake and uses more power while "
                       + "the visualizer runs. When plugged in uses it on AC power only. "
                       + "The visualizer restarts itself to switch."
            labels: ({ integrated: "Integrated", dedicated: "Dedicated", plugged_in: "When plugged in" })
        }

        Divider {}

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Chip {
                filled: true
                // Mint when healthy, either GPU (an orange tint reads brown on this surface).
                accent: !gpuCard.info.running ? Theme.textMuted
                      : gpuCard.info.fallback !== "" ? Theme.danger : Theme.success
                text: !gpuCard.info.running ? "Not running"
                    : gpuCard.info.renderer === "" ? "Starting"
                    : gpuCard.info.onDedicated ? "Dedicated" : "Integrated"
            }
            Text {
                Layout.fillWidth: true
                text: !gpuCard.info.running ? "Start the visualizer to see which GPU it draws on."
                    : gpuCard.info.renderer === "" ? "Waiting for the first frame…"
                    : "Drawing on " + gpuCard.info.renderer
                color: Theme.text
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
            }
        }
        Text {
            visible: gpuCard.info.fallback !== ""
            Layout.fillWidth: true
            text: gpuCard.info.fallback + " Using the integrated GPU for now; pick an option above to try again."
            color: Theme.danger
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.WordWrap
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
