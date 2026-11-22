pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.modules.common
import qs.modules.common.functions

/**
 * Shared entry point for Pulsar palette selection and regeneration.
 * Matugen and the existing terminal generator remain the color producers;
 * this service coordinates them and exposes the live Material palette.
 */
Singleton {
    id: root

    readonly property bool manualSource: {
        const color = Config.options.appearance.palette.accentColor || "";
        return /^#?[0-9a-fA-F]{6}$/.test(color);
    }
    readonly property var palette: Appearance.m3colors
    readonly property color primary: Appearance.m3colors.m3primary
    readonly property color primaryFixed: Appearance.m3colors.m3primaryFixed
    readonly property color surface: Appearance.m3colors.m3surface
    readonly property color surfaceContainer: Appearance.m3colors.m3surfaceContainer
    readonly property color launcherSurface: ColorUtils.mix(surfaceContainer, primary, 0.76)
    readonly property color onSurface: Appearance.m3colors.m3onSurface
    readonly property bool busy: wallpaperColorProcess.running || pickerProcess.running
    property string errorText: ""

    function runColorScript(args) {
        if (root.busy) return;
        root.errorText = "";
        const tintWindows = Config.options.appearance.wallpaperTheming.tintAppWindowSurfaces ? "true" : "false";
        wallpaperColorProcess.command = [Directories.wallpaperSwitchScriptPath, ...args, "--tint-app-window-surfaces", tintWindows];
        wallpaperColorProcess.running = true;
    }

    function useWallpaperColors() {
        runColorScript(["--noswitch", "--color", "clear"]);
    }

    function refreshPalette() {
        paletteRefreshTimer.restart();
    }

    Timer {
        id: paletteRefreshTimer
        interval: 150
        repeat: false
        onTriggered: {
            if (root.manualSource) {
                const color = Config.options.appearance.palette.accentColor || "";
                root.runColorScript(["--noswitch", "--color", color]);
            } else {
                root.useWallpaperColors();
            }
        }
    }

    function chooseManualColor() {
        if (root.busy) return;
        root.errorText = "";
        pickerProcess.pickedColor = "";
        pickerProcess.outputComplete = false;
        pickerProcess.resultExitCode = -1;
        pickerProcess.running = true;
    }

    Process {
        id: pickerProcess
        property string pickedColor: ""
        property bool outputComplete: false
        property int resultExitCode: -1
        command: ["hyprpicker", "--no-fancy"]
        stdout: StdioCollector {
            onStreamFinished: {
                pickerProcess.pickedColor = text.trim();
                pickerProcess.outputComplete = true;
            }
        }
        onExited: (exitCode, exitStatus) => {
            pickerProcess.resultExitCode = exitCode;
            pickerCompletionTimer.start();
        }
    }

    Timer {
        id: pickerCompletionTimer
        interval: 50
        repeat: true
        onTriggered: {
            if (pickerProcess.running || !pickerProcess.outputComplete || pickerProcess.resultExitCode < 0)
                return;
            stop();
            if (pickerProcess.resultExitCode !== 0) {
                root.errorText = "Color picker failed or was cancelled.";
                return;
            }
            if (!/^#?[0-9a-fA-F]{6}$/.test(pickerProcess.pickedColor)) {
                root.errorText = "Color picker did not return a valid color.";
                return;
            }
            // Wait for the picker process and its stdout collector to finish
            // before passing the color through the shared busy guard.
            root.runColorScript(["--noswitch", "--color", pickerProcess.pickedColor]);
        }
    }

    Process {
        id: wallpaperColorProcess
        command: []
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    root.errorText = text.trim();
            }
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0 && root.errorText.length === 0)
                root.errorText = `Color generation failed (exit ${exitCode}).`;
        }
    }
}
