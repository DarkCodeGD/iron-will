pragma Singleton
import QtQuick

// Design tokens. Flat surfaces, no gradients in the chrome.
// Palette concept: the logo's "fire" on a blue-slate base. Blue is orange's
// complement, so the warm accents pop instead of sitting flat. Orange (≈28°)
// marks the visualizer pages, crimson-rose (≈352°) marks session sounds;
// together they're the two ends of the logo's gradient.
QtObject {
    // Surfaces (darkest → lightest)
    readonly property color bg:           "#0F1419"
    readonly property color sidebar:      "#131A21"
    readonly property color surface:      "#18212A"
    readonly property color surfaceHi:    "#202A35"
    readonly property color surfaceHover: "#283441"
    readonly property color border:       "#25303C"
    readonly property color canvas:       "#0A0E12"   // preview "desktop"

    // Text
    readonly property color text:      "#E8EDF2"
    readonly property color textMuted: "#8D99A8"
    readonly property color textFaint: "#5D6A79"
    readonly property color ink:       "#0B1418"      // text on accent fills

    // Accents (the logo's gradient ends)
    readonly property color primary:   "#FF8A1F"      // orange
    readonly property color secondary: "#FF4D63"      // crimson-rose
    // Status: semantic, independent of the brand accents, so "installed" and
    // "missing" never depend on telling orange from crimson.
    readonly property color success:   "#3DD68C"      // mint: ok / running / saved
    readonly property color danger:    "#FF4D63"      // missing / failed / unsaved / error
    // What faded warm accents turn into (see tint())
    readonly property color warmTint:  Qt.hsla(352 / 360, 1.0, 0.60, 1.0)

    // Shape & rhythm
    readonly property int radiusCard: 18
    readonly property int radiusInner: 12
    readonly property int controlHeight: 36
    readonly property int gap: 16

    // Type scale (px)
    readonly property int fontTitle: 24
    readonly property int fontSection: 15
    readonly property int fontBody: 14
    readonly property int fontSmall: 12
    readonly property int fontCaption: 11

    // A faded accent for fills: selected nav items, chips, tonal buttons,
    // icon circles. Orange faded onto dark slate is *brown* (#FF8A1F at 15%
    // over the surface is #3B3128), because dark orange is what brown is.
    // So warm orange/amber accents fade through crimson instead, which
    // darkens into a warm wine tone. Bright uses (text, icons, solid buttons,
    // sliders, switches) keep the true orange.
    function tint(c, alpha) {
        var hue = c.hslHue * 360
        if (c.hslSaturation > 0.3 && hue >= 12 && hue <= 60)
            return Qt.rgba(warmTint.r, warmTint.g, warmTint.b, alpha)
        return Qt.rgba(c.r, c.g, c.b, alpha)
    }
    function hex(c) {
        function h(x) { var s = Math.round(x * 255).toString(16); return s.length < 2 ? "0" + s : s }
        return ("#" + h(c.r) + h(c.g) + h(c.b)).toUpperCase()
    }
}
