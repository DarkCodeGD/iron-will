// The visualizer as both the desktop windows and the settings preview use it:
//
//   VisualizerItem — clock, physics, fade, and the CPU painter for bars /
//                    mirror / wave. In fire mode it paints nothing and
//                    publishes the flame state as fire* properties instead.
//   ShaderEffect   — the GPU fire (shaders/fire.frag), bound to those
//                    properties. Hidden — and free — in every other mode.
import QtQuick
import IronWill 1.0

Item {
    id: root
    property alias store: vis.store
    property alias demo: vis.demo

    VisualizerItem {
        id: vis
        objectName: "visualizer"   // app.py finds the item by this name
        anchors.fill: parent
        // No GPU (software scene graph) means no shaders: fire falls back to bars.
        fireFallback: GraphicsInfo.api === GraphicsInfo.Software
    }

    ShaderEffect {
        anchors.fill: parent
        visible: vis.visible && vis.fireActive && vis.fireOpacity > 0.003
        opacity: vis.fireOpacity          // → qt_Opacity
        blending: true
        fragmentShader: Qt.resolvedUrl("../shaders/fire.frag.qsb")

        // Uniforms (names match the shader's uniform block).
        property vector4d colsA: vis.fireColsA
        property vector4d colsB: vis.fireColsB
        property vector4d colsC: vis.fireColsC
        property vector4d colsD: vis.fireColsD
        property vector4d motion: vis.fireMotion
        property vector4d look: Qt.vector4d(vis.fireLook.x, vis.fireLook.y, vis.fireLook.z,
                                            width / Math.max(1, height))
        property color tipColor: vis.fireTip
        property color midColor: vis.fireMid
        property color bodyColor: vis.fireBody
    }
}
