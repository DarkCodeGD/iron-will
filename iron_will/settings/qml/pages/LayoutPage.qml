import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Layout"
    subtitle: "Where the visualizer sits. On Wayland it lives on the desktop layer — always click-through, never over your windows."
    resetSections: ["layout"]

    readonly property int rev: backend.revision
    function v(key) { rev; return backend.get(key) }

    // ── Miniature screen diagram ────────────────────────────────────────
    Card {
        title: "Placement preview"
        subtitle: backend.screenWidth + " × " + backend.screenHeight + " primary screen · panel drawn at Plasma's default height"
        iconName: "layout"

        // The stage takes the card's full width from the layout; the monitor
        // sizes itself from that. (Binding a Layout.preferredHeight to the
        // item's own layout-assigned width collapses to 0 — chicken and egg.)
        Item {
            id: stage
            Layout.fillWidth: true
            Layout.preferredHeight: monitor.height

            Rectangle {
                id: monitor
                width: Math.min(stage.width, 560)
                height: width * backend.screenHeight / backend.screenWidth
                anchors.horizontalCenter: parent.horizontalCenter
                radius: Theme.radiusInner
                color: Theme.canvas
                border.color: Theme.border
                clip: true

                readonly property real dScale: width / backend.screenWidth
                readonly property int dPanelH: 44
                readonly property bool dTop: page.v("layout.anchor") === "top"
                readonly property string dAlign: page.v("layout.align")
                readonly property int dMx: page.v("layout.margin_x")
                readonly property int dMy: page.v("layout.margin_y")
                readonly property int dReserved: page.v("layout.respect_panels") && !dTop ? dPanelH : 0
                readonly property int dVw: dAlign === "stretch" ? backend.screenWidth - 2 * dMx
                                                                : Math.min(page.v("layout.width"), backend.screenWidth)
                readonly property int dVh: page.v("layout.full_height") ? backend.screenHeight - dReserved - dMy
                                                                    : Math.min(page.v("layout.height"), backend.screenHeight)
                readonly property int dVx: dAlign === "left" ? dMx
                                         : dAlign === "right" ? backend.screenWidth - dVw - dMx
                                         : dAlign === "center" ? (backend.screenWidth - dVw) / 2 + dMx : dMx
                readonly property int dVy: dTop ? dMy : backend.screenHeight - dReserved - dMy - dVh

                // A couple of ghost "windows" to make the layering obvious.
                Rectangle {
                    x: parent.width * 0.08; y: parent.height * 0.1
                    width: parent.width * 0.5; height: parent.height * 0.55
                    radius: 6; color: Theme.surfaceHi; border.color: Theme.border
                    opacity: page.v("layout.layer") === "top" ? 0.55 : 1
                    z: page.v("layout.layer") === "top" ? 1 : 3
                }
                Rectangle {
                    x: parent.width * 0.42; y: parent.height * 0.28
                    width: parent.width * 0.48; height: parent.height * 0.5
                    radius: 6; color: Theme.surface; border.color: Theme.border
                    opacity: page.v("layout.layer") === "top" ? 0.55 : 1
                    z: page.v("layout.layer") === "top" ? 1 : 3
                }
                // Panel
                Rectangle {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                    height: monitor.dPanelH * monitor.dScale
                    color: Theme.sidebar
                    z: 4
                    Row {
                        anchors.centerIn: parent
                        spacing: 4
                        Repeater { model: 5; Rectangle { width: 8; height: 8; radius: 4; color: Theme.surfaceHover } }
                    }
                }
                // The visualizer itself
                Rectangle {
                    x: monitor.dVx * monitor.dScale
                    y: monitor.dVy * monitor.dScale
                    width: Math.max(4, monitor.dVw * monitor.dScale)
                    height: Math.max(3, monitor.dVh * monitor.dScale)
                    radius: Math.min(height / 2, 4)
                    color: Theme.tint(Theme.primary, 0.35)
                    border.color: Theme.primary
                    border.width: 1.5
                    z: 2
                    Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Behavior on y { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                }
            }
        }
    }

    Card {
        title: "Position"
        subtitle: "Anchor to an edge, then nudge with offsets"

        SegmentedRow { key: "layout.anchor"; label: "Screen edge" }
        SegmentedRow { key: "layout.align"; label: "Alignment" }
        Divider {}
        SliderRow {
            key: "layout.width"; label: "Width"; unit: " px"; stepSize: 10
            from: 100; to: backend.screenWidth
            enabled: page.v("layout.align") !== "stretch"
            description: enabled ? "" : "Stretch fills the screen width"
        }
        ToggleRow {
            key: "layout.full_height"; label: "Full screen height"
            description: "Reach all the way to the far edge of the screen. Fire gets room for tall flames, glow and embers (its size stays the same), and it stays click-through."
            setter: function (on) { backend.setFullHeight(on) }
        }
        SliderRow {
            key: "layout.height"; label: "Height"; unit: " px"; from: 16; to: Math.round(backend.screenHeight / 2)
            enabled: !page.v("layout.full_height")
            description: enabled ? "" : "Full screen height is on"
        }
        SliderRow {
            key: "layout.margin_x"; label: "Horizontal offset"; unit: " px"
            from: page.v("layout.align") === "center" ? -Math.round(backend.screenWidth / 2) : 0
            to: Math.round(backend.screenWidth / 2)
            description: page.v("layout.align") === "center" ? "Shift left (−) or right (+) from center" : "Distance from the aligned edge"
        }
        SliderRow {
            key: "layout.margin_y"; label: "Vertical offset"; unit: " px"
            from: 0; to: Math.round(backend.screenHeight / 2)
            description: page.v("layout.respect_panels") ? "Distance from the panel" : "Distance from the screen edge"
        }
    }

    Card {
        title: "Stacking"
        subtitle: "How the visualizer layers with everything else"

        SegmentedRow {
            key: "layout.layer"; label: "Layer"
            description: {
                var l = page.v("layout.layer")
                return l === "top" ? "Floats above windows (still click-through)"
                     : l === "background" ? "Lowest layer — may sit behind desktop widgets"
                     : "Above the wallpaper, below all windows"
            }
        }
        ToggleRow {
            key: "layout.respect_panels"; label: "Sit above panels"
            description: "Keep clear of panels instead of drawing behind them"
        }
    }
}
