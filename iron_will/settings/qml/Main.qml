import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "components"

ApplicationWindow {
    id: win
    width: 1140
    height: 800
    minimumWidth: 940
    minimumHeight: 620
    visible: true
    title: "Iron Will"
    color: Theme.bg

    property int current: 0
    readonly property var pages: [
        { group: "Visualizer", label: "Appearance",     icon: "bars",   source: "pages/AppearancePage.qml", accent: Theme.primary },
        { group: "",           label: "Layout",         icon: "layout", source: "pages/LayoutPage.qml",     accent: Theme.primary },
        { group: "",           label: "Motion",         icon: "motion", source: "pages/MotionPage.qml",     accent: Theme.primary },
        { group: "Session",    label: "Session Sounds", icon: "volume", source: "pages/SoundsPage.qml",     accent: Theme.secondary },
        { group: "",           label: "System",         icon: "system", source: "pages/SystemPage.qml",     accent: Theme.primary }
    ]

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── Sidebar ───────────────────────────────────────────────────────
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 256
            color: Theme.sidebar

            Rectangle { anchors { top: parent.top; bottom: parent.bottom; right: parent.right } width: 1; color: Theme.border }

            ColumnLayout {
                anchors { fill: parent; margins: 16; topMargin: 24 }
                spacing: 4

                // Brand
                RowLayout {
                    Layout.leftMargin: 6
                    Layout.bottomMargin: 22
                    spacing: 12
                    Image {       // the app logo (same SVG as the app menu and notifications)
                        source: Qt.resolvedUrl("../../assets/iron-will.svg")
                        Layout.preferredWidth: 42; Layout.preferredHeight: 42
                        sourceSize: Qt.size(84, 84)      // 2× for crisp HiDPI rendering
                        fillMode: Image.PreserveAspectFit
                        smooth: true; mipmap: true
                    }
                    ColumnLayout {
                        spacing: 1
                        Text { text: "Iron Will"; color: Theme.text; font.pixelSize: 17; font.weight: Font.Bold }
                        Text { text: "Desktop audio toolkit"; color: Theme.textMuted; font.pixelSize: Theme.fontCaption }
                    }
                }

                Repeater {
                    model: win.pages
                    delegate: ColumnLayout {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 4
                        Text {
                            visible: modelData.group.length > 0
                            Layout.leftMargin: 16
                            Layout.topMargin: index === 0 ? 0 : 18
                            Layout.bottomMargin: 4
                            text: modelData.group.toUpperCase()
                            color: Theme.textFaint
                            font.pixelSize: 10
                            font.weight: Font.Bold
                            font.letterSpacing: 1.2
                        }
                        NavItem {
                            label: modelData.label
                            iconName: modelData.icon
                            accent: modelData.accent
                            active: win.current === index
                            onClicked: win.current = index
                        }
                    }
                }

                Item { Layout.fillHeight: true }

                // Autosave status
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 38
                    radius: 19
                    color: Theme.surface
                    border.color: Theme.border
                    Row {
                        anchors.centerIn: parent
                        spacing: 8
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 8; height: 8; radius: 4
                            color: backend.dirty ? Theme.danger : Theme.success
                            Behavior on color { ColorAnimation { duration: 200 } }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: backend.dirty ? "Saving…" : "All changes saved"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSmall
                        }
                    }
                }
            }
        }

        // ── Pages ─────────────────────────────────────────────────────────
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: win.current
            Repeater {
                model: win.pages
                delegate: Loader {
                    required property var modelData
                    source: modelData.source
                }
            }
        }
    }

    Toast { id: toast }
    Connections {
        target: backend
        function onToast(message, kind) { toast.show(message, kind) }
    }
}
