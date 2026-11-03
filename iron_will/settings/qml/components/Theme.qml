pragma Singleton
import QtQuick

// Design tokens. Flat surfaces, no gradients in the chrome.
// Palette concept: a dark slate base with two complementary accents —
// teal (≈174°) for the visualizer pages and coral (≈6°) for session sounds —
// so each half of the app has its own identity while sharing one system.
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

    // Complementary accents
    readonly property color primary:   "#2EC4B6"      // teal
    readonly property color secondary: "#FF6B5B"      // coral

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

    function tint(c, alpha) { return Qt.rgba(c.r, c.g, c.b, alpha) }
    function hex(c) {
        function h(x) { var s = Math.round(x * 255).toString(16); return s.length < 2 ? "0" + s : s }
        return ("#" + h(c.r) + h(c.g) + h(c.b)).toUpperCase()
    }
}
