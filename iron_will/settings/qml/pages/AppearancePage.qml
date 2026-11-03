import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Appearance"
    subtitle: "Style and colors of the desktop visualizer. Changes apply live to your desktop."
    resetSections: ["visualizer", "fire"]

    readonly property int rev: backend.revision
    readonly property string mode: { rev; return backend.get("visualizer.mode") }
    readonly property bool accentMode: { rev; return backend.get("visualizer.color_source") === "accent" }
    readonly property bool fire: mode === "fire"
    readonly property bool bars: mode === "bars" || mode === "mirror"
    readonly property int windowHeight: { rev; return backend.get("layout.height") }
    readonly property bool naturalFire: { rev; return backend.get("fire.palette") === "natural" }
    readonly property var modeHints: ({
        bars: "Classic spectrum bars, bass on the left",
        mirror: "Mirror puts the bass in the middle",
        wave: "A smooth line through every band",
        fire: "GPU flames: every hit ignites the fire, guitars feed it, cymbals throw sparks"
    })

    PreviewCard {}

    Card {
        title: "Style"
        subtitle: "Shape of the visualization"
        iconName: "bars"

        SegmentedRow { key: "visualizer.mode"; label: "Render mode"; description: page.modeHints[page.mode] || "" }
        SegmentedRow { key: "visualizer.direction"; label: page.fire ? "Flame direction" : "Grow direction" }
        Divider {}
        SliderRow {
            key: "visualizer.bar_count"; label: page.mode === "wave" ? "Wave points" : "Bar count"; stepSize: 1
            visible: !page.fire
        }
        SliderRow {
            key: "visualizer.spacing"; label: "Spacing"; unit: " px"
            visible: page.bars
        }
        SliderRow {
            key: "visualizer.roundness"; label: "Roundness"; decimals: 2
            description: "0 = square corners, 1 = fully pill-shaped"
            visible: page.bars
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "visualizer.min_height"; label: "Resting height"; unit: " px"; description: "Height of a bar at silence while audio plays"
            visible: !page.fire
        }
        SliderRow {
            key: "visualizer.opacity"; label: "Opacity"; decimals: 2
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        ToggleRow {
            key: "visualizer.peaks"; label: "Peak caps"
            description: "Small caps that hang above bars, then fall with gravity"
            visible: page.bars
        }
    }

    Card {
        title: "Fire"
        subtitle: "How the flames burn and react to the music"
        iconName: "flame"
        visible: page.fire

        // Fire needs height to breathe; the default strip is made for bars.
        Rectangle {
            visible: page.windowHeight < 200
            Layout.fillWidth: true
            implicitHeight: hintRow.implicitHeight + 24
            radius: Theme.radiusInner
            color: Theme.tint(Theme.primary, 0.10)
            border.color: Theme.tint(Theme.primary, 0.35)
            RowLayout {
                id: hintRow
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                spacing: 12
                Icon { name: "flame"; size: 18; color: Theme.primary }
                Text {
                    Layout.fillWidth: true
                    text: "Your visualizer is " + page.windowHeight + " px tall. Fire really comes alive at 220–300 px."
                    color: Theme.text; font.pixelSize: Theme.fontSmall; wrapMode: Text.WordWrap
                }
                PillButton {
                    kind: "ghost"; text: "Make it 260 px"
                    onClicked: backend.set("layout.height", 260)
                }
            }
        }

        SegmentedRow {
            key: "fire.palette"; label: "Flame colors"
            description: page.naturalFire ? "Deep red tips, orange body, golden core"
                                          : "Your gradient: first color at the base, last at the tips"
            labels: ({ colors: "Your colors", natural: "Natural fire" })
        }
        Divider {}
        SliderRow {
            key: "fire.height"; label: "Flame height"; decimals: 2
            description: "How much of the visualizer the flames reach at full blast"
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "fire.glow"; label: "Glow"; decimals: 2
            description: "Firelight cast onto the wallpaper around the flames, and the bloom of the hot core"
            format: function (v) { return v < 0.005 ? "Off" : Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "fire.reaction"; label: "Reaction"; decimals: 2
            description: "How the fire catches: low = slow, heavy burn, high = snappy flare-ups. Hits always ignite and die down like real fire."
            format: function (v) { return v < 0.25 ? "Slow burn" : v < 0.75 ? "Natural" : "Explosive" }
        }
        SliderRow {
            key: "fire.translucency"; label: "Translucency"; decimals: 2
            description: "How much the wallpaper shows through, like real fire: wispy tips go first, the hot core stays bright. Lower it on bright wallpapers."
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "fire.intensity"; label: "Intensity"; decimals: 2
            description: "How much fuel each hit throws on the fire: bigger flare-ups, hotter flashes"
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "fire.sparks"; label: "Sparks"; decimals: 2
            description: "Embers thrown up by snare and cymbal hits"
            format: function (v) { return v < 0.005 ? "Off" : Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "fire.speed"; label: "Flame speed"; decimals: 2
            description: "Base churn speed. Fast, dense music speeds it up further."
            format: function (v) { return v.toFixed(1) + "×" }
        }
    }

    Card {
        title: "Color"
        subtitle: page.fire && page.naturalFire ? "Natural fire uses its own colors. Pick \u201cYour colors\u201d in the Fire card to use these."
                                                : "Follow your Plasma accent, or build your own gradient"
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

        SegmentedRow { key: "visualizer.gradient_direction"; label: "Gradient direction"; visible: !page.fire }
    }
}
