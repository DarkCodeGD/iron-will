// X11 (or Wayland without layer-shell): a frameless, click-through tool window
// kept below other windows and positioned from computed x/y.
import QtQuick
import QtQuick.Window
import IronWill 1.0

Window {
    id: root

    title: "Iron Will Visualizer"
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnBottomHint
           | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    x: layoutModel.x
    y: layoutModel.y
    width: layoutModel.width
    height: layoutModel.height
    visible: true

    VisualizerItem {
        id: vis
        objectName: "visualizer"
        anchors.fill: parent
        store: configStore
    }
}
