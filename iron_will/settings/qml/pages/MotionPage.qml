import QtQuick
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Motion"
    subtitle: "Pick a genre preset, or fine-tune the physics and audio analysis yourself."
    resetSections: ["motion", "analysis"]

    readonly property int rev: backend.revision

    PreviewCard {}

    GenrePresets {}

    Card {
        title: "Physics"
        subtitle: "Fast attack + slow decay = punchy hits with smooth falls"
        iconName: "motion"

        SliderRow { key: "motion.attack_ms"; label: "Attack"; unit: " ms"; description: "How fast bars rise — lower is snappier"; stepSize: 5 }
        SliderRow { key: "motion.decay_ms"; label: "Decay"; unit: " ms"; description: "How slowly bars fall — higher is smoother"; stepSize: 10 }
        Divider {}
        SliderRow { key: "motion.peak_hold_ms"; label: "Peak hold"; unit: " ms"; description: "How long caps hang before dropping"; stepSize: 50 }
        SliderRow { key: "motion.peak_gravity"; label: "Peak gravity"; decimals: 1; description: "How hard caps accelerate as they fall" }
        SliderRow { key: "visualizer.fps"; label: "Frame rate"; unit: " fps"; description: "Snaps to an even share of your monitor's refresh rate, so every frame stays up equally long (60 on a 144 Hz screen runs at 72). Higher is smoother but uses more CPU." }
    }

    Card {
        title: "Idle"
        subtitle: "Get out of the way when there is nothing to show"

        ToggleRow { id: idleFade; key: "motion.idle_fade"; label: "Fade out on silence"; description: "Also stops repainting entirely — zero CPU while idle" }
        SliderRow { key: "motion.idle_timeout"; label: "Fade after"; unit: " s"; decimals: 1; stepSize: 0.5; enabled: idleFade.checked }
        ToggleRow { key: "motion.pause_when_covered"; label: "Pause when covered"; description: "Behind fullscreen games and videos or maximized windows: no drawing, no audio capture" }
    }

    Card {
        title: "Audio analysis"
        subtitle: "cava frequency analysis of your default output"

        SegmentedRow {
            key: "analysis.input"; label: "Capture backend"
            labels: ({ auto: "Auto", pipewire: "PipeWire", pulse: "PulseAudio" })
            description: "Auto picks whatever your cava build supports"
        }
        ToggleRow { id: autosens; key: "analysis.autosens"; label: "Auto sensitivity"; description: "Adapts to the current volume so bars never clip or vanish" }
        SliderRow { key: "analysis.sensitivity"; label: autosens.checked ? "Starting sensitivity" : "Sensitivity"; unit: "%"; stepSize: 5 }
        Divider {}
        SliderRow {
            key: "analysis.low_cutoff"; label: "Lowest frequency"; stepSize: 5
            format: function (v) { return Math.round(v) + " Hz" }
        }
        SliderRow {
            key: "analysis.high_cutoff"; label: "Highest frequency"; stepSize: 500
            format: function (v) { return (v / 1000).toFixed(1) + " kHz" }
        }
        SliderRow { key: "analysis.noise_reduction"; label: "cava smoothing"; description: "Pre-smoothing before our physics. Lower = more detail"; stepSize: 1 }
    }
}
