import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Appearance"
    subtitle: "Style and colors of the desktop visualizer. Changes apply live to your desktop."
    resetSections: ["visualizer"]

    readonly property int rev: backend.revision
    readonly property string mode: { rev; return backend.get("visualizer.mode") }
    readonly property bool accentMode: { rev; return backend.get("visualizer.color_source") === "accent" }

    PreviewCard {}

    Card {
        title: "Style"
        subtitle: "Shape of the visualization"
        iconName: "bars"

        SegmentedRow { key: "visualizer.mode"; label: "Render mode"; description: "Mirror puts the bass in the middle" }
        SegmentedRow { key: "visualizer.direction"; label: "Grow direction" }
        Divider {}
        SliderRow { key: "visualizer.bar_count"; label: page.mode === "wave" ? "Wave points" : "Bar count"; stepSize: 1 }
        SliderRow {
            key: "visualizer.spacing"; label: "Spacing"; unit: " px"
            visible: page.mode !== "wave"
        }
        SliderRow {
            key: "visualizer.roundness"; label: "Roundness"; decimals: 2
            description: "0 = square corners, 1 = fully pill-shaped"
            visible: page.mode !== "wave"
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow { key: "visualizer.min_height"; label: "Resting height"; unit: " px"; description: "Height of a bar at silence while audio plays" }
        SliderRow {
            key: "visualizer.opacity"; label: "Opacity"; decimals: 2
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        ToggleRow {
            key: "visualizer.peaks"; label: "Peak caps"
            description: "Small caps that hang above bars, then fall with gravity"
            visible: page.mode !== "wave"
        }
    }

    Card {
        title: "Color"
        subtitle: "Follow your Plasma accent, or build your own gradient"
        iconName: "palette"

        SegmentedRow {
            key: "visualizer.color_source"; label: "Color source"
            labels: ({ accent: "Plasma accent", custom: "Custom" })
        }

        RowLayout {   // accent preview
            visible: page.accentMode
            Layout.fillWidth: true
            spacing: 14
            Rectangle {
                implicitWidth: 40; implicitHeight: 40; radius: 20
                color: backend.accentColor || Theme.textFaint
                border.color: Qt.rgba(1, 1, 1, 0.12)
            }
            ColumnLayout {
                spacing: 2
                Text {
                    text: backend.accentColor ? "Following " + backend.accentColor : "No accent color found"
                    color: Theme.text; font.pixelSize: Theme.fontBody; font.weight: Font.Medium
                }
                Text {
                    text: backend.accentColor ? "Updates automatically when you change it in System Settings"
                                              : "Falling back to the custom colors below"
                    color: Theme.textMuted; font.pixelSize: Theme.fontSmall
                }
            }
        }

        ColorStops { visible: !page.accentMode || !backend.accentColor }

        SegmentedRow { key: "visualizer.gradient_direction"; label: "Gradient direction" }
    }
}
