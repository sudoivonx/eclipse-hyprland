pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.modules.common
import qs.modules.common.functions
import qs.services

Singleton {
    id: root

    readonly property bool automaticEnabled: Config.options.gameMode.automatic
    readonly property string helperPath: `${Directories.scriptPath}/game-mode/pulsar_game_mode.py`
    readonly property string detectorPath: `${Directories.scriptPath}/game-mode/pulsar_game_detector.py`
    readonly property string stateFilePath: `${FileUtils.trimFileProtocol(Directories.state)}/pulsar/game-mode.json`
    readonly property string detectorInput: {
        const clients = HyprlandData.windowList || [];
        const candidates = clients
            .filter(client => client && Number(client.pid) > 1 && client.address)
            .map(client => ({
                address: String(client.address),
                pid: Number(client.pid),
                class: String(client.class || ""),
                initialClass: String(client.initialClass || ""),
                contentType: String(client.contentType || "")
            }));
        candidates.sort((a, b) => a.address.localeCompare(b.address));
        return JSON.stringify(candidates);
    }
    readonly property bool gameDetected: {
        const clients = HyprlandData.windowList || [];
        return clients.some(client => root.isGameWindow(client)
            || (client && root.steamGameAddresses.includes(String(client.address))));
    }
    readonly property bool active: manualActive || autoActive

    property bool manualActive: false
    property bool manualSuppressed: false
    property bool autoActive: false
    property bool recoveryReady: false
    property bool profileApplied: false
    property bool profileRequestPending: false
    property bool desiredProfileActive: false
    property bool lastAttemptFailed: false
    property bool lastAttemptTarget: false
    property string profileAction: ""
    property string errorText: ""
    property var steamGameAddresses: []
    property string detectorScanInput: ""
    property bool detectorScanPending: false
    property bool detectorReady: false

    function isGameWindow(client): bool {
        if (!client)
            return false;

        const classes = [client.class, client.initialClass]
            .map(value => String(value || "").toLowerCase());
        const excludedClasses = ["steam", "steamwebhelper", "steam_app_228980", "steam_app_1493710", "steam_app_4183110"];
        if (classes.some(appClass => excludedClasses.includes(appClass)))
            return false;

        if (String(client.contentType || "").toLowerCase() === "game")
            return true;

        return classes.some(appClass => /^steam_app_[0-9]+$/.test(appClass)
            || appClass === "gamescope"
            || /^combatmaster(?:\.x86_64)?$/.test(appClass));
    }

    function refreshGameDetection(): void {
        if (detectorProcess.running) {
            detectorScanPending = true;
            return;
        }
        detectorScanPending = false;
        detectorScanInput = detectorInput;
        detectorProcess.command = ["python3", detectorPath, detectorScanInput];
        detectorProcess.running = true;
    }

    // Called by shell.qml so automatic detection is always active.
    function load(): void {}

    function toggleManual(): void {
        if (manualActive) {
            manualActive = false;
        } else if (autoActive) {
            autoActive = false;
            manualSuppressed = true;
        } else {
            manualActive = true;
            manualSuppressed = false;
        }
    }

    function requestProfile(targetActive: bool): void {
        desiredProfileActive = targetActive;
        if (!recoveryReady)
            return;
        if (profileProcess.running) {
            profileRequestPending = true;
            return;
        }
        if (profileApplied === targetActive)
            return;
        if (lastAttemptFailed && lastAttemptTarget === targetActive)
            return;
        profileAction = targetActive ? "enter" : "restore";
        lastAttemptTarget = targetActive;
        lastAttemptFailed = false;
        profileProcess.command = ["python3", helperPath, profileAction, stateFilePath];
        profileProcess.running = true;
    }

    onDetectorInputChanged: {
        if (detectorReady)
            refreshGameDetection();
    }
    onActiveChanged: requestProfile(active)

    onGameDetectedChanged: {
        if (gameDetected) {
            gameExitTimer.stop();
            if (automaticEnabled && !autoActive && !manualSuppressed)
                gameEnterTimer.restart();
        } else {
            gameEnterTimer.stop();
            if (autoActive)
                gameExitTimer.restart();
            manualSuppressed = false;
        }
    }

    onAutomaticEnabledChanged: {
        if (!automaticEnabled) {
            gameEnterTimer.stop();
            autoActive = false;
        } else if (gameDetected && !manualSuppressed && !autoActive) {
            gameEnterTimer.restart();
        }
    }

    Component.onCompleted: {
        detectorReady = true;
        recoveryProcess.command = ["python3", helperPath, "restore", stateFilePath];
        recoveryProcess.running = true;
        refreshGameDetection();
        if (gameDetected && automaticEnabled)
            gameEnterTimer.restart();
    }

    Component.onDestruction: {
        if (profileApplied)
            Quickshell.execDetached(["python3", helperPath, "restore", stateFilePath]);
    }

    Timer {
        id: gameEnterTimer
        interval: 1200
        repeat: false
        onTriggered: {
            if (root.gameDetected && root.automaticEnabled && !root.manualSuppressed)
                root.autoActive = true;
        }
    }

    Timer {
        id: gameExitTimer
        interval: 2500
        repeat: false
        onTriggered: {
            if (!root.gameDetected)
                root.autoActive = false;
        }
    }

    Process {
        id: detectorProcess
        command: []
        stdout: StdioCollector {
            id: detectorStdout
            onStreamFinished: {
                if (root.detectorScanInput !== root.detectorInput)
                    return;
                try {
                    const addresses = JSON.parse(detectorStdout.text);
                    if (Array.isArray(addresses))
                        root.steamGameAddresses = addresses.map(address => String(address));
                } catch (error) {
                    root.errorText = `Pulsar game detection: ${error}`;
                }
            }
        }
        stderr: StdioCollector {
            id: detectorStderr
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0 && root.detectorScanInput === root.detectorInput) {
                root.steamGameAddresses = [];
                root.errorText = detectorStderr.text.trim() || "Pulsar game detection helper failed";
            }
            if (root.detectorScanPending || root.detectorScanInput !== root.detectorInput) {
                root.detectorScanPending = false;
                root.refreshGameDetection();
            }
        }
    }

    Process {
        id: recoveryProcess
        command: []
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length)
                    root.errorText = text.trim();
            }
        }
        onExited: (exitCode, exitStatus) => {
            root.recoveryReady = true;
            if (exitCode !== 0) {
                root.lastAttemptFailed = true;
                root.lastAttemptTarget = false;
            }
            root.requestProfile(root.active);
        }
    }

    Process {
        id: profileProcess
        command: []
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length)
                    root.errorText = text.trim();
            }
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode === 0) {
                root.profileApplied = root.profileAction === "enter";
                root.lastAttemptFailed = false;
                root.errorText = "";
            } else {
                root.lastAttemptFailed = true;
                root.lastAttemptTarget = root.profileAction === "enter";
            }
            if (root.profileRequestPending) {
                root.profileRequestPending = false;
                root.requestProfile(root.desiredProfileActive);
            } else if (root.profileApplied !== root.desiredProfileActive) {
                root.requestProfile(root.desiredProfileActive);
            }
        }
    }
}
