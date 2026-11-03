// Wayland: a wlr-layer-shell surface (via LayerShellQt), exactly how Plasma's
// own panels are placed. Lives on the "bottom" layer by default — above the
// wallpaper, below every application window. Never takes keyboard focus and
// is click-through (empty input region), so it can't get in your way.
import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell
import IronWill 1.0

Window {
    id: root

    title: "Iron Will Visualizer"
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    width: layoutModel.width
    height: layoutModel.height
    visible: true

    // KWin derives the window *type* from the scope: unknown scopes become
    // "normal" windows, which this one never activates — so effects like Dim
    // Inactive and Translucency would permanently wash it out. "desktop" makes
    // KWin treat it as part of the desktop, which those effects skip.
    LayerShell.Window.scope: "desktop"
    LayerShell.Window.layer: layoutModel.layer
    LayerShell.Window.anchors: layoutModel.anchorFlags
    LayerShell.Window.margins: layoutModel.margins
    LayerShell.Window.exclusionZone: layoutModel.exclusionZone
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.activateOnShow: false

    Visualizer {
        anchors.fill: parent
        store: configStore
    }
}
