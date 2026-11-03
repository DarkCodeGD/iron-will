import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Appearance"
    subtitle: "Style and colors of the desktop visualizer. Changes apply live to your desktop."
    resetSections: ["visualizer", "fire", "ferro"]

    readonly property int rev: backend.revision
    readonly property string mode: { rev; return backend.get("visualizer.mode") }
    readonly property bool accentMode: { rev; return backend.get("visualizer.color_source") === "accent" }
    readonly property bool fire: mode === "fire"
    readonly property bool ferro: mode === "ferro"
    readonly property bool gpu: fire || ferro      // drawn by a shader: bar-shape controls don't apply
    readonly property bool bars: mode === "bars" || mode === "mirror"
    readonly property bool fullHeight: { rev; return backend.get("layout.full_height") }
    readonly property bool naturalFire: { rev; return backend.get("fire.palette") === "natural" }
    readonly property bool chromeFerro: { rev; return backend.get("ferro.palette") === "chrome" }

    PreviewCard {}

    Card {
        title: "Style"
        subtitle: "Shape of the visualization"
        iconName: "bars"

        ModePicker {}
        Divider {}
        SliderRow {
            key: "visualizer.bar_count"; label: page.mode === "wave" ? "Wave points" : "Bar count"; stepSize: 1
            visible: !page.gpu
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
            visible: !page.gpu
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

        HeightHint { what: "Fire"; icon: "flame" }

        SegmentedRow {
            key: "fire.palette"; label: "Flame colors"
            description: page.naturalFire ? "Deep red tips, orange body, golden core"
                                          : "Your gradient: first color at the base, last at the tips"
            labels: ({ colors: "Your colors", natural: "Natural fire" })
        }
        Divider {}
        SliderRow {
            key: "fire.height"; label: "Flame height"; decimals: 2
            description: page.fullHeight ? "How much of the screen the flames reach at full blast"
                                         : "How much of the visualizer the flames reach at full blast. Tongues that hit the top fade out; turn on Full screen height in Layout for headroom."
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
        title: "Ferrofluid"
        subtitle: "How the magnetic liquid moves and catches the light"
        iconName: "magnet"
        visible: page.ferro

        HeightHint { what: "Ferrofluid"; icon: "magnet" }

        SegmentedRow {
            key: "ferro.palette"; label: "Rim light"
            description: page.chromeFerro ? "Cool steel rim and a white backlight, like a studio photo"
                                          : "Your gradient: rim from the first color, backlight from the last"
            labels: ({ colors: "Your colors", chrome: "Chrome" })
        }
        Divider {}
        SliderRow {
            key: "ferro.height"; label: "Spike height"; decimals: 2
            description: page.fullHeight ? "How much of the screen the spikes reach at full blast"
                                         : "How much of the visualizer the spikes reach at full blast"
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "ferro.intensity"; label: "Intensity"; decimals: 2
            description: "How hard each hit pulls on the liquid: bigger, sharper spikes"
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "ferro.wobble"; label: "Wobble"; decimals: 2
            description: "How much the liquid jiggles after each hit before it settles"
            format: function (v) { return v < 0.25 ? "Stiff" : v < 0.75 ? "Liquid" : "Jelly" }
        }
        SliderRow {
            key: "ferro.reaction"; label: "Reaction"; decimals: 2
            description: "How fast the spikes rise and slump back: low = slow and heavy, high = snappy"
            format: function (v) { return v < 0.25 ? "Heavy" : v < 0.75 ? "Natural" : "Snappy" }
        }
        SliderRow {
            key: "ferro.sharpness"; label: "Sharpness"; decimals: 2
            description: "Spike shape, from soft rounded cones to needles"
            format: function (v) { return v < 0.3 ? "Soft" : v < 0.7 ? "Sharp" : "Needles" }
        }
        SliderRow {
            key: "ferro.density"; label: "Spike count"; decimals: 2
            description: "A few big spikes, or a dense forest of small ones"
            format: function (v) { return v < 0.3 ? "Few" : v < 0.7 ? "Balanced" : "Dense" }
        }
        SliderRow {
            key: "ferro.gloss"; label: "Gloss"; decimals: 2
            description: "The studio-light reflections that make the liquid look wet"
            format: function (v) { return v < 0.005 ? "Off" : Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "ferro.rim"; label: "Rim & backlight"; decimals: 2
            description: "Colored edge light and the glow behind the spikes, which flashes on kicks. Keeps black liquid visible on dark wallpapers."
            format: function (v) { return v < 0.005 ? "Off" : Math.round(v * 100) + "%" }
        }
    }

    Card {
        title: "Color"
        subtitle: page.fire && page.naturalFire ? "Natural fire uses its own colors. Pick \u201cYour colors\u201d in the Fire card to use these."
                : page.ferro && page.chromeFerro ? "Chrome uses its own colors. Pick \u201cYour colors\u201d in the Ferrofluid card to use these."
                : page.ferro ? "Ferrofluid lights the black liquid with these: rim from the first color, backlight from the last"
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

        SegmentedRow { key: "visualizer.gradient_direction"; label: "Gradient direction"; visible: !page.gpu }
    }
}
