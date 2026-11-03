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

        // Particle slots for object modes (bubbles): ShaderEffect can't take
        // arrays, so 24 vec4 uniforms. Shaders that don't declare them ignore
        // them, and they only change in modes that have particles.
        readonly property var parts: vis.gpuParticles
        function slot(i) {
            var k = 4 * i
            return parts.length > k + 3 ? Qt.vector4d(parts[k], parts[k + 1], parts[k + 2], parts[k + 3])
                                        : Qt.vector4d(0, 0, 0, 0)
        }
        property vector4d p0: slot(0)
        property vector4d p1: slot(1)
        property vector4d p2: slot(2)
        property vector4d p3: slot(3)
        property vector4d p4: slot(4)
        property vector4d p5: slot(5)
        property vector4d p6: slot(6)
        property vector4d p7: slot(7)
        property vector4d p8: slot(8)
        property vector4d p9: slot(9)
        property vector4d p10: slot(10)
        property vector4d p11: slot(11)
        property vector4d p12: slot(12)
        property vector4d p13: slot(13)
        property vector4d p14: slot(14)
        property vector4d p15: slot(15)
        property vector4d p16: slot(16)
        property vector4d p17: slot(17)
        property vector4d p18: slot(18)
        property vector4d p19: slot(19)
        property vector4d p20: slot(20)
        property vector4d p21: slot(21)
        property vector4d p22: slot(22)
        property vector4d p23: slot(23)
    }
}
