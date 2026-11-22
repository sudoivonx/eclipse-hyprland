pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.modules.common
import qs.services

Singleton {
    id: root

    readonly property var options: Config.options.appearance.pulsarAudioVisualizer
    readonly property bool enabled: options.enabled
    readonly property bool effectiveEnabled: enabled
    readonly property bool pickingColor: colorPicker.running
    readonly property color activeColor: options.useCustomColor
        ? options.customColor
        : PulsarColorEngine.primary
    property var levels: Array(options.barCount).fill(0)
    property var targetLevels: Array(options.barCount).fill(0)
    property string errorText: ""
    property bool restartPending: false
    property bool stopRequested: false

    function resetAppearanceDefaults() {
        options.position = "bottom-center";
        options.style = "bars-box";
        options.length = 640;
        options.size = 80;
        options.sensitivity = 2;
        options.barCount = 32;
        options.smoothing = 6;
    }

    function resetLevels() {
        const count = options.barCount;
        root.levels = Array(count).fill(0);
        root.targetLevels = Array(count).fill(0);
    }

    function startMeter() {
        if (!root.effectiveEnabled)
            return;
        // A stop request is asynchronous. If game mode ends before Process.onExited,
        // retain the start request and relaunch once the old capture has exited.
        if (root.stopRequested) {
            root.restartPending = true;
            meterRestartTimer.start();
            return;
        }
        if (meterProcess.running)
            return;
        const sink = Audio.sink;
        if (!sink || sink.id === undefined || sink.id < 0) {
            root.errorText = "No output audio device is available.";
            return;
        }
        root.errorText = "";
        root.resetLevels();
        meterProcess.command = [
            "python3",
            `${Directories.scriptPath}/audio/pulsar_audio_meter.py`,
            "--target", String(sink.id),
            "--bars", String(options.barCount)
        ];
        root.stopRequested = false;
        meterProcess.running = true;
    }

    function stopMeter() {
        root.restartPending = false;
        if (meterProcess.running) {
            root.stopRequested = true;
            meterProcess.running = false;
        } else {
            root.stopRequested = false;
        }
        root.resetLevels();
    }

    function restartMeter() {
        if (!root.effectiveEnabled)
            return;
        if (meterProcess.running) {
            root.restartPending = true;
            root.stopRequested = true;
            meterProcess.running = false;
        } else {
            root.startMeter();
        }
    }

    function chooseManualColor() {
        if (colorPicker.running)
            return;
        root.errorText = "";
        colorPicker.pickedColor = "";
        colorPicker.outputComplete = false;
        colorPicker.resultExitCode = -1;
        colorPicker.running = true;
    }

    Connections {
        target: Config.options.appearance.pulsarAudioVisualizer
        function onEnabledChanged() {
            if (root.enabled) {
                root.resetAppearanceDefaults();
                if (root.effectiveEnabled) root.startMeter();
            } else {
                root.stopMeter();
                root.resetAppearanceDefaults();
            }
        }
        function onBarCountChanged() {
            root.resetLevels();
            root.restartMeter();
        }
    }

    Connections {
        target: Audio
        function onSinkChanged() {
            root.restartMeter();
        }
    }

    Component.onCompleted: {
        root.resetLevels();
        if (root.effectiveEnabled)
            root.startMeter();
    }

    Timer {
        id: animationTimer
        interval: 33
        repeat: true
        running: root.effectiveEnabled
        onTriggered: {
            const opts = root.options;
            const raw = root.targetLevels;
            const previous = root.levels;
            const count = opts.barCount;
            const sensitivity = Math.max(1, Math.min(5, Number(opts.sensitivity)));
            const smoothing = Math.max(0, Math.min(10, Number(opts.smoothing))) / 10;
            const next = [];
            for (let i = 0; i < count; ++i) {
                const goal = Math.max(0, Math.min(1, Number(raw[i] || 0) * sensitivity));
                const current = Number(previous[i] || 0);
                const factor = goal > current ? 0.58 - smoothing * 0.36 : 0.3 - smoothing * 0.23;
                next.push(Math.abs(goal - current) < 0.004 ? goal : current + (goal - current) * factor);
            }
            root.levels = next;
        }
    }

    Process {
        id: meterProcess
        command: []
        stdout: SplitParser {
            onRead: data => {
                const line = data.trim();
                if (!line.length)
                    return;
                try {
                    const value = JSON.parse(line);
                    if (value && value.error) {
                        root.errorText = String(value.error);
                        root.stopRequested = true;
                        meterProcess.running = false;
                        return;
                    }
                    if (Array.isArray(value))
                        root.targetLevels = value;
                } catch (error) {
                    root.errorText = `Audio meter returned invalid data: ${error}`;
                }
            }
        }
        stderr: SplitParser {
            onRead: data => {
                if (data.trim().length)
                    root.errorText = data.trim();
            }
        }
        onExited: (exitCode, exitStatus) => {
            if (root.restartPending) {
                meterRestartTimer.start();
            } else if (root.stopRequested) {
                root.stopRequested = false;
                if (root.effectiveEnabled) {
                    root.restartPending = true;
                    meterRestartTimer.start();
                }
            } else if (root.effectiveEnabled) {
                if (exitCode !== 0)
                    root.errorText = `PipeWire meter stopped (exit ${exitCode}).`;
                root.restartPending = true;
                meterRestartTimer.start();
            }
        }
    }

    Timer {
        id: meterRestartTimer
        interval: 250
        repeat: true
        onTriggered: {
            if (meterProcess.running)
                return;
            stop();
            root.restartPending = false;
            root.stopRequested = false;
            root.startMeter();
        }
    }

    // Recover if the meter exits normally or a stop/start notification is missed.
    // This timer is active only while the visualizer should be running and the
    // capture process is absent.
    Timer {
        id: meterRecoveryTimer
        interval: 1000
        repeat: true
        running: root.effectiveEnabled && !meterProcess.running
        onTriggered: {
            if (root.stopRequested) {
                root.restartPending = true;
                meterRestartTimer.start();
            } else {
                root.startMeter();
            }
        }
    }

    Process {
        id: colorPicker
        property string pickedColor: ""
        property bool outputComplete: false
        property int resultExitCode: -1
        command: ["hyprpicker", "--no-fancy"]
        stdout: StdioCollector {
            onStreamFinished: {
                colorPicker.pickedColor = text.trim();
                colorPicker.outputComplete = true;
            }
        }
        onExited: (exitCode, exitStatus) => {
            colorPicker.resultExitCode = exitCode;
            colorPickerCompletionTimer.start();
        }
    }

    Timer {
        id: colorPickerCompletionTimer
        interval: 50
        repeat: true
        onTriggered: {
            if (colorPicker.running || !colorPicker.outputComplete || colorPicker.resultExitCode < 0)
                return;
            stop();
            if (colorPicker.resultExitCode !== 0) {
                root.errorText = "Color picker failed or was cancelled.";
                return;
            }
            if (!/^#?[0-9a-fA-F]{6}$/.test(colorPicker.pickedColor)) {
                root.errorText = "Color picker did not return a valid color.";
                return;
            }
            root.options.customColor = colorPicker.pickedColor.startsWith("#")
                ? colorPicker.pickedColor
                : `#${colorPicker.pickedColor}`;
            root.options.useCustomColor = true;
        }
    }
}
