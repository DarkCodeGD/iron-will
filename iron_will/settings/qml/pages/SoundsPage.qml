import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"

PageScaffold {
    id: page
    title: "Session Sounds"
    subtitle: "Play a random track from your library when the session starts, wakes up or unlocks."
    accent: Theme.secondary
    resetSections: ["sounds"]

    readonly property color tone: Theme.secondary
    property var info: ({ path: "", exists: false, count: 0, tracks: [] })
    property string scannedDir: ""

    function refresh() {
        var dir = backend.get("sounds.directory")
        if (dir === scannedDir) return
        scannedDir = dir
        info = backend.soundInfo()
    }
    Component.onCompleted: refresh()
    Connections { target: backend; function onRevisionChanged() { page.refresh() } }
    onVisibleChanged: if (visible) { scannedDir = ""; refresh() }   // rescan when revisiting

    Card {
        title: "Sound library"
        subtitle: "mp3 · wav · ogg · flac · opus — subfolders included"
        iconName: "music"
        accent: page.tone

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Theme.controlHeight
                radius: height / 2
                color: Theme.surfaceHi
                border.color: Theme.border
                Row {
                    anchors { left: parent.left; leftMargin: 14; right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                    spacing: 10
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "folder"; size: 16; color: Theme.textMuted }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 26
                        text: page.info.path
                        elide: Text.ElideMiddle
                        color: Theme.text
                        font.pixelSize: 13
                    }
                }
            }
            PillButton { kind: "tonal"; accent: page.tone; text: "Browse"; onClicked: folderDialog.open() }
            PillButton { kind: "ghost"; iconName: "open"; text: "Open"; enabled: page.info.exists; onClicked: backend.openPath(page.info.path) }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Chip {
                filled: true
                accent: page.info.count > 0 ? page.tone : Theme.textMuted
                iconName: page.info.count > 0 ? "music" : "close"
                text: !page.info.exists ? "Folder not found"
                      : page.info.count === 0 ? "No audio files yet"
                      : page.info.count + (page.info.count === 1 ? " track" : " tracks")
            }
            Text {
                visible: page.info.count === 0
                text: "Drop some audio files into the folder, then come back."
                color: Theme.textMuted
                font.pixelSize: Theme.fontSmall
            }
            Item { Layout.fillWidth: true }
            PillButton {
                kind: "primary"
                accent: page.tone
                iconName: "play"
                text: "Play random track"
                enabled: page.info.count > 0
                onClicked: backend.playTest()
            }
        }

        Flow {
            visible: page.info.count > 0
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: page.info.tracks.slice(0, 12)
                delegate: Chip { required property string modelData; text: modelData }
            }
            Chip { visible: page.info.count > 12; text: "+" + (page.info.count - 12) + " more" }
        }
    }

    Card {
        title: "Play on"
        subtitle: "Pick the moments, and how long to wait for audio devices to wake up"
        iconName: "volume"
        accent: page.tone

        ToggleRow { id: onLogin; key: "sounds.on_login"; accent: page.tone; label: "Login"; description: "When your Plasma session starts" }
        SliderRow { key: "sounds.login_delay"; accent: page.tone; label: "Delay"; unit: " s"; decimals: 1; stepSize: 0.5; enabled: onLogin.checked }
        Divider {}
        ToggleRow { id: onResume; key: "sounds.on_resume"; accent: page.tone; label: "Resume from suspend"; description: "After waking up — also waits for the audio device to come back" }
        SliderRow { key: "sounds.resume_delay"; accent: page.tone; label: "Delay"; unit: " s"; decimals: 1; stepSize: 0.5; enabled: onResume.checked }
        Divider {}
        ToggleRow { id: onUnlock; key: "sounds.on_unlock"; accent: page.tone; label: "Screen unlock"; description: "After you unlock the lock screen" }
        SliderRow { key: "sounds.unlock_delay"; accent: page.tone; label: "Delay"; unit: " s"; decimals: 1; stepSize: 0.1; enabled: onUnlock.checked }
    }

    Card {
        title: "Playback"
        subtitle: "Volume, player and repetition"
        accent: page.tone

        SliderRow {
            key: "sounds.volume"; accent: page.tone; label: "Volume"; decimals: 2
            format: function (v) { return Math.round(v * 100) + "%" }
        }
        SliderRow {
            key: "sounds.cooldown"; accent: page.tone; label: "Cooldown"; unit: " s"; stepSize: 5
            from: 0; to: 300
            description: "Minimum gap between sounds — stops resume and unlock from both playing"
        }
        SegmentedRow {
            key: "sounds.backend"; accent: page.tone; label: "Player"
            labels: ({ auto: "Auto", "pw-play": "pw-play", paplay: "paplay", ffplay: "ffplay", mpv: "mpv" })
            description: "Auto tries each installed player until one works"
        }
        ToggleRow { key: "sounds.avoid_repeat"; accent: page.tone; label: "Avoid repeats"; description: "Never play the same track twice in a row" }
    }

    FolderDialog {
        id: folderDialog
        title: "Choose your session sound folder"
        currentFolder: page.info.exists ? "file://" + page.info.path : ""
        onAccepted: backend.setSoundDirectory(selectedFolder.toString())
    }
}
