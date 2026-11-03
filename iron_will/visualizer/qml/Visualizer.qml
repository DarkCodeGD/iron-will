// The visualizer as both the desktop windows and the settings preview use it:
//
//   VisualizerItem — clock, physics, fade, and the CPU painter for bars /
//                    mirror / wave. In a GPU mode (fire, ferrofluid, …) it
//                    paints nothing and publishes the mode's state as gpu*
//                    properties instead.
//   ShaderEffect   — the GPU mode's fragment shader (named by the mode
//                    registry), bound to those properties through one
//                    generic set of uniforms. Hidden — and free — in CPU modes.
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
        // No GPU (software scene graph) means no shaders: GPU modes fall back to bars.
        gpuFallback: GraphicsInfo.api === GraphicsInfo.Software
    }

    ShaderEffect {
        anchors.fill: parent
        visible: vis.visible && vis.gpuActive && vis.gpuShader !== "" && vis.gpuOpacity > 0.003
        opacity: vis.gpuOpacity           // → qt_Opacity
        blending: true
        fragmentShader: vis.gpuShader

        // Generic uniforms (names match every GPU shader's uniform block; each
        // shader documents what the slots mean for it).
        property vector4d colsA: vis.gpuColsA
        property vector4d colsB: vis.gpuColsB
        property vector4d colsC: vis.gpuColsC
        property vector4d colsD: vis.gpuColsD
        property vector4d motion: vis.gpuMotion
        property vector4d extra: vis.gpuExtra
        property vector4d look: Qt.vector4d(vis.gpuLook.x, vis.gpuLook.y, vis.gpuLook.z,
                                            width / Math.max(1, height))
        property vector4d res: Qt.vector4d(width, height, 0, 0)   // item size in pixels
        property color colorA: vis.gpuColorA
        property color colorB: vis.gpuColorB
        property color colorC: vis.gpuColorC
        property real param: vis.gpuParam
    }
}
