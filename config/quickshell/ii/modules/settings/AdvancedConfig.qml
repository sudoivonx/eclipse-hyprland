import QtQuick
import Quickshell
import Quickshell.Io
import QtQuick.Layouts
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions as CF

ContentPage {
    id: root
    forceWidth: true
    property string sectionFilter: ""
    property var settingsRoot: null
    property string nexusManagerPath: CF.FileUtils.trimFileProtocol(Directories.config) + "/quickshell/ii/modules/settings/nexus-settings.py"
    property bool aegisHyprlandOptionsReady: false
    property bool aegisHyprlandLimitsReady: false
    property bool aegisHyprlandOptionsBusy: false
    property string aegisHyprlandOptionsMessage: Translation.tr("Reading live Hyprland values…")
    property int aegisHyprlandGapsIn: 0
    property int aegisHyprlandGapsOut: 0
    property int aegisHyprlandRounding: 0
    property int aegisHyprlandGapMinimum: 0
    property int aegisHyprlandGapMaximum: 0
    property int aegisHyprlandRoundingMinimum: 0
    property int aegisHyprlandRoundingMaximum: 0

    function refreshHyprlandOptions() {
        if (!aegisHyprlandOptionsReadProc.running)
            aegisHyprlandOptionsReadProc.running = true;
    }

    function applyHyprlandOptions() {
        if (!aegisHyprlandOptionsReady || aegisHyprlandOptionsBusy ||
            (settingsRoot && settingsRoot.nexusActionBusy))
            return;
        const managedIds = [
            "hyprland.general.gaps_in",
            "hyprland.general.gaps_out",
            "hyprland.decoration.rounding"
        ];
        if (settingsRoot && managedIds.some(settingId => !settingsRoot.hasInitialValue({
            sourceKind: "hyprland-options-adapter",
            id: settingId
        }))) {
            aegisHyprlandOptionsBusy = true;
            aegisHyprlandOptionsOperation = "initialize";
            aegisHyprlandOptionsMessage = Translation.tr("Saving the current values as the starting point…");
            settingsRoot.nexusActionBusy = true;
            aegisHyprlandOptionsProcess.command = ["python3", nexusManagerPath, "initialize"];
            aegisHyprlandOptionsProcess.running = true;
            return;
        }
        startHyprlandOptionsApply();
    }

    function startHyprlandOptionsApply() {
        aegisHyprlandOptionsBusy = true;
        aegisHyprlandOptionsOperation = "apply";
        aegisHyprlandOptionsMessage = Translation.tr("Saving and verifying Hyprland values…");
        if (settingsRoot)
            settingsRoot.nexusActionBusy = true;
        const values = {
            "hyprland.general.gaps_in": Number(aegisHyprlandGapsIn),
            "hyprland.general.gaps_out": Number(aegisHyprlandGapsOut),
            "hyprland.decoration.rounding": Number(aegisHyprlandRounding)
        };
        aegisHyprlandOptionsProcess.command = ["python3", nexusManagerPath, "hyprland-options-set", JSON.stringify(values)];
        aegisHyprlandOptionsProcess.running = true;
    }

    property bool aegisGlowReady: false
    property bool aegisGlowEnabled: true
    property real aegisGlowBrightness: 40.784314
    property real aegisGlowSize: 43
    property bool aegisGlowApplyPending: false

    property bool aegisMotionProfileReady: false
    property string aegisMotionProfile: "full"

    function applyAegisMotionProfile(profile) {
        if (!aegisMotionProfileReady || aegisMotionProfileApplyProc.running)
            return;

        // Seçimi, arka plan işlemini beklemeden anında göster.
        root.aegisMotionProfile = profile;

        aegisMotionProfileApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-motion-profile.py" apply "$1"',
            "aegis-motion-profile",
            profile
        ];
        aegisMotionProfileApplyProc.running = true;
    }

    property bool aegisWindowEffectsReady: false
    property real aegisActiveOpacity: 80
    property real aegisInactiveOpacity: 80
    property bool aegisGlassReady: false
    property bool aegisGlassEnabled: true
    property int aegisBlurSize: 12
    property int aegisBlurPasses: 4
    property real aegisAcrylicClarity: 65
    property bool aegisGlassApplyPending: false

    property bool aegisDepthEffectEnabled: false
    property bool aegisWindowEffectsApplyPending: false

    property bool aegisOpacityRulesReady: false
    property bool aegisOpaqueBlender: true
    property bool aegisOpaqueDavinci: true
    property bool aegisOpaqueVlc: true
    property bool aegisOpaquePhotoViewers: true
    property bool aegisOpaqueGames: true
    property bool aegisOpaqueMediaContent: true
    property bool aegisOpaqueFullscreen: true
    property bool aegisOpacityRulesApplyPending: false

    property bool aegisPipFloatReady: false
    property bool aegisPipFloatEnabled: false
    property var aegisCustomWindows: []
    property var aegisCustomEntries: []
    property int aegisCustomSelectedIndex: -1
    property bool aegisCustomReady: false

    function refreshAegisCustomData() {
        if (!aegisCustomWindowsReadProc.running)
            aegisCustomWindowsReadProc.running = true;
        if (!aegisCustomEntriesReadProc.running)
            aegisCustomEntriesReadProc.running = true;
    }

    function addAegisCustomSelection() {
        if (!aegisCustomReady ||
            aegisCustomSelectedIndex < 0 ||
            aegisCustomSelectedIndex >= aegisCustomWindows.length)
            return;

        const win = aegisCustomWindows[aegisCustomSelectedIndex];
        if (!win || !win.class || !win.title)
            return;

        aegisCustomApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-custom-opacity.py" add "$1" "$2"',
            "aegis-custom-opacity",
            String(win.class),
            String(win.title)
        ];
        aegisCustomApplyProc.running = true;
    }

    function removeAegisCustomSelection(index) {
        if (!aegisCustomReady || index < 0 ||
            index >= aegisCustomEntries.length)
            return;

        aegisCustomApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-custom-opacity.py" remove "$1"',
            "aegis-custom-opacity",
            String(index)
        ];
        aegisCustomApplyProc.running = true;
    }


    function queueOpacityRulesApply() {
        if (aegisOpacityRulesReady)
            aegisOpacityRulesApplyDebounce.restart();
    }

    function startOpacityRulesApply() {
        if (!aegisOpacityRulesReady)
            return;

        if (aegisOpacityRulesApplyProc.running) {
            aegisOpacityRulesApplyPending = true;
            return;
        }

        aegisOpacityRulesApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-opacity-rules.py" apply "$1" "$2" "$3" "$4" "$5" "$6" "$7"',
            "aegis-opacity-rules",
            aegisOpaqueBlender ? "true" : "false",
            aegisOpaqueDavinci ? "true" : "false",
            aegisOpaqueVlc ? "true" : "false",
            aegisOpaquePhotoViewers ? "true" : "false",
            aegisOpaqueGames ? "true" : "false",
            aegisOpaqueMediaContent ? "true" : "false",
            aegisOpaqueFullscreen ? "true" : "false"
        ];
        aegisOpacityRulesApplyProc.running = true;
    }

    function queueWindowEffectsApply() {
        if (aegisWindowEffectsReady)
            aegisWindowEffectsApplyDebounce.restart();
    }

    function startWindowEffectsApply() {
        if (!aegisWindowEffectsReady)
            return;
        if (aegisWindowEffectsApplyProc.running) {
            aegisWindowEffectsApplyPending = true;
            return;
        }
        aegisWindowEffectsApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-window-effects.py" apply "$1" "$2" "$3"',
            "aegis-window-effects",
            String(Number(aegisActiveOpacity).toFixed(1)),
            String(Number(aegisInactiveOpacity).toFixed(1)),
            aegisDepthEffectEnabled ? "true" : "false"
        ];
        aegisWindowEffectsApplyProc.running = true;
    }

    function queueGlassApply() {
        if (aegisGlassReady)
            aegisGlassApplyDebounce.restart();
    }

    function applyGlassProfile(profile) {
        if (!aegisGlassReady) {
            console.log("[Aegis Cam] Ayarlar henüz hazır değil.");
            return;
        }

        if (profile === "light") {
            aegisBlurSize = 8;
            aegisBlurPasses = 2;
            aegisAcrylicClarity = 65;
        } else if (profile === "balanced") {
            aegisBlurSize = 14;
            aegisBlurPasses = 4;
            aegisAcrylicClarity = 50;
        } else if (profile === "heavy") {
            aegisBlurSize = 20;
            aegisBlurPasses = 5;
            aegisAcrylicClarity = 25;
        } else {
            console.log("[Aegis Cam] Bilinmeyen profil: " + profile);
            return;
        }

        queueGlassApply();
        console.log("[Aegis Cam] Profil varsayılanları uygulandı: " + profile);
    }

    function startGlassApply() {
        if (!aegisGlassReady)
            return;
        if (aegisGlassApplyProc.running) {
            aegisGlassApplyPending = true;
            return;
        }
        aegisGlassApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-glassctl.py" apply "$1" "$2" "$3" "$4"',
            "aegis-glassctl",
            String(Math.round(aegisBlurSize)),
            String((aegisAcrylicClarity / 100).toFixed(2)),
            aegisGlassEnabled ? "true" : "false",
            String(Math.round(aegisBlurPasses))
        ];
        aegisGlassApplyProc.running = true;
    }

    function queueGlowApply() {
        if (aegisGlowReady)
            aegisGlowApplyDebounce.restart();
    }

    function startGlowApply() {
        if (!aegisGlowReady)
            return;
        if (aegisGlowApplyProc.running) {
            aegisGlowApplyPending = true;
            return;
        }
        aegisGlowApplyProc.command = [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-glowctl.py" apply "$1" "$2" "$3"',
            "aegis-glowctl",
            aegisGlowEnabled ? "true" : "false",
            String(aegisGlowBrightness),
            String(Math.round(aegisGlowSize))
        ];
        aegisGlowApplyProc.running = true;
    }

    Component.onCompleted: {
        if (sectionFilter === "" || sectionFilter === "windows") {
            refreshHyprlandOptions();
            aegisGlowReadProc.running = true;
            aegisWindowEffectsReadProc.running = true;
            aegisGlassReadProc.running = true;
            aegisOpacityRulesReadProc.running = true;
            aegisPipFloatReadProc.running = true;
            refreshAegisCustomData();
        }
        if (sectionFilter === "" || sectionFilter === "motion")
            aegisMotionProfileReadProc.running = true;
    }

    Process {
        id: aegisHyprlandOptionsReadProc
        command: ["python3", root.nexusManagerPath, "hyprland-options-status"]
        stdout: StdioCollector {
            id: aegisHyprlandOptionsReadOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(aegisHyprlandOptionsReadOutput.text);
                const requiredIds = [
                    "hyprland.general.gaps_in",
                    "hyprland.general.gaps_out",
                    "hyprland.decoration.rounding"
                ];
                if (exitCode !== 0 || response.status !== "ok" || response.runtimeVerified !== true || !response.values || !response.limits)
                    throw new Error(response.message || "Hyprland values are not verified.");
                for (const settingId of requiredIds) {
                    const value = Number(response.values[settingId]);
                    const minimum = Number(response.limits[settingId] && response.limits[settingId].minimum);
                    const maximum = Number(response.limits[settingId] && response.limits[settingId].maximum);
                    if (!Number.isFinite(value) || !Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum > maximum)
                        throw new Error("Hyprland returned an incomplete setting value or range.");
                }
                root.aegisHyprlandGapMinimum = Number(response.limits["hyprland.general.gaps_in"].minimum);
                root.aegisHyprlandGapMaximum = Number(response.limits["hyprland.general.gaps_in"].maximum);
                root.aegisHyprlandRoundingMinimum = Number(response.limits["hyprland.decoration.rounding"].minimum);
                root.aegisHyprlandRoundingMaximum = Number(response.limits["hyprland.decoration.rounding"].maximum);
                root.aegisHyprlandLimitsReady = true;
                root.aegisHyprlandGapsIn = Number(response.values["hyprland.general.gaps_in"]);
                root.aegisHyprlandGapsOut = Number(response.values["hyprland.general.gaps_out"]);
                root.aegisHyprlandRounding = Number(response.values["hyprland.decoration.rounding"]);
                root.aegisHyprlandOptionsReady = true;
                root.aegisHyprlandOptionsMessage = Translation.tr("Live values match the saved Hyprland source.");
            } catch (error) {
                root.aegisHyprlandOptionsReady = false;
                root.aegisHyprlandLimitsReady = false;
                root.aegisHyprlandOptionsMessage = error.message || Translation.tr("Hyprland values could not be verified.");
            }
        }
    }

    Process {
        id: aegisHyprlandOptionsProcess
        command: []
        stdout: StdioCollector {
            id: aegisHyprlandOptionsOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            let response = null;
            try {
                response = JSON.parse(aegisHyprlandOptionsOutput.text);
            } catch (error) {
                root.aegisHyprlandOptionsMessage = Translation.tr("NEXUS could not read the result. No success was assumed.");
            }
            root.aegisHyprlandOptionsBusy = false;
            if (root.settingsRoot)
                root.settingsRoot.nexusActionBusy = false;
            if (!response)
                return;
            if (exitCode !== 0 || response.status === "error") {
                root.aegisHyprlandOptionsMessage = response.message || Translation.tr("The Hyprland values could not be updated safely.");
                root.aegisHyprlandOptionsOperation = "";
                root.refreshHyprlandOptions();
                if (root.settingsRoot)
                    root.settingsRoot.refreshHyprlandOptionsStatus();
                return;
            }
            if (root.aegisHyprlandOptionsOperation === "initialize") {
                if (root.settingsRoot)
                    root.settingsRoot.reloadInitialState();
                root.aegisHyprlandOptionsOperation = "";
                root.startHyprlandOptionsApply();
                return;
            }
            root.aegisHyprlandGapsIn = Number(response.values ? response.values["hyprland.general.gaps_in"] : root.aegisHyprlandGapsIn);
            root.aegisHyprlandGapsOut = Number(response.values ? response.values["hyprland.general.gaps_out"] : root.aegisHyprlandGapsOut);
            root.aegisHyprlandRounding = Number(response.values ? response.values["hyprland.decoration.rounding"] : root.aegisHyprlandRounding);
            root.aegisHyprlandOptionsMessage = response.runtimeVerified === true
                ? Translation.tr("Values saved and verified live.")
                : Translation.tr("NEXUS did not verify the live values.");
            root.aegisHyprlandOptionsOperation = "";
            root.refreshHyprlandOptions();
            if (root.settingsRoot) {
                root.settingsRoot.refreshHyprlandOptionsStatus();
                root.settingsRoot.reloadInitialState();
            }
        }
    }

    Connections {
        target: root.settingsRoot
        ignoreUnknownSignals: true
        function onCurrentHyprlandOptionsChanged() {
            if (!root.settingsRoot || !root.settingsRoot.hyprlandOptionsRuntimeVerified || !root.aegisHyprlandLimitsReady)
                return;
            const values = root.settingsRoot.currentHyprlandOptions;
            if (!values || !Number.isFinite(Number(values["hyprland.general.gaps_in"])) ||
                !Number.isFinite(Number(values["hyprland.general.gaps_out"])) ||
                !Number.isFinite(Number(values["hyprland.decoration.rounding"]))) {
                root.aegisHyprlandOptionsReady = false;
                return;
            }
            root.aegisHyprlandGapsIn = Number(values["hyprland.general.gaps_in"]);
            root.aegisHyprlandGapsOut = Number(values["hyprland.general.gaps_out"]);
            root.aegisHyprlandRounding = Number(values["hyprland.decoration.rounding"]);
            root.aegisHyprlandOptionsReady = true;
        }
        function onHyprlandOptionsRuntimeVerifiedChanged() {
            if (!root.settingsRoot || root.settingsRoot.hyprlandOptionsRuntimeVerified)
                return;
            root.aegisHyprlandOptionsReady = false;
            root.aegisHyprlandLimitsReady = false;
        }
    }

    property string aegisHyprlandOptionsOperation: ""

    Timer {
        id: aegisGlowApplyDebounce
        interval: 450
        repeat: false
        onTriggered: root.startGlowApply()
    }

    Process {
        id: aegisGlowReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-glowctl.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisGlowEnabled = state.enabled === true;
                    root.aegisGlowBrightness = Number(state.brightness);
                    root.aegisGlowSize = Number(state.size);
                    root.aegisGlowReady = true;
                } catch (error) {
                    console.log("[Aegis Glow] Ayarlar okunamadı: " + error);
                }
            }
        }
    }

    Process {
        id: aegisGlowApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                const message = text.trim();
                if (message.length > 0)
                    console.log("[Aegis Glow] " + message);
            }
        }
        onRunningChanged: {
            if (!running && root.aegisGlowApplyPending) {
                root.aegisGlowApplyPending = false;
                root.aegisGlowApplyDebounce.restart();
            }
        }
    }


    Timer {
        id: aegisWindowEffectsApplyDebounce
        interval: 500
        repeat: false
        onTriggered: root.startWindowEffectsApply()
    }

    Process {
        id: aegisWindowEffectsReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-window-effects.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisActiveOpacity = Number(state.activeOpacity);
                    root.aegisInactiveOpacity = Number(state.inactiveOpacity);
                    root.aegisDepthEffectEnabled = state.depth === true;
                    root.aegisWindowEffectsReady = true;
                } catch (error) {
                    console.log("[Aegis Window] Ayarlar okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Window] " + text.trim());
            }
        }
    }

    Process {
        id: aegisWindowEffectsApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Window] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Window] HATA: " + text.trim());
            }
        }
        onRunningChanged: {
            if (!running && root.aegisWindowEffectsApplyPending) {
                root.aegisWindowEffectsApplyPending = false;
                root.aegisWindowEffectsApplyDebounce.restart();
            }
        }
    }


    Timer {
        id: aegisOpacityRulesApplyDebounce
        interval: 450
        repeat: false
        onTriggered: root.startOpacityRulesApply()
    }

    Process {
        id: aegisOpacityRulesReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-opacity-rules.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisOpaqueBlender = state.blender === true;
                    root.aegisOpaqueDavinci = state.davinci === true;
                    root.aegisOpaqueVlc = state.vlc === true;
                    root.aegisOpaquePhotoViewers = state.photo_viewers === true;
                    root.aegisOpaqueGames = state.games === true;
                    root.aegisOpaqueMediaContent = state.media_content === true;
                    root.aegisOpaqueFullscreen = state.fullscreen === true;
                    root.aegisOpacityRulesReady = true;
                } catch (error) {
                    console.log("[Aegis Opaklık] Ayarlar okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Opaklık] " + text.trim());
            }
        }
    }

    Process {
        id: aegisOpacityRulesApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Opaklık] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Opaklık] HATA: " + text.trim());
            }
        }
        onRunningChanged: {
            if (!running && root.aegisOpacityRulesApplyPending) {
                root.aegisOpacityRulesApplyPending = false;
                root.aegisOpacityRulesApplyDebounce.restart();
            }
        }
    }

    Process {
        id: aegisCustomWindowsReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-custom-opacity.py" windows'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const result = JSON.parse(text.trim());
                    root.aegisCustomWindows = result;
                    if (root.aegisCustomSelectedIndex >= result.length)
                        root.aegisCustomSelectedIndex = -1;
                } catch (error) {
                    console.log("[Aegis Özel Pencere] Pencere listesi okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Özel Pencere] " + text.trim());
            }
        }
    }

    Process {
        id: aegisCustomEntriesReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-custom-opacity.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    root.aegisCustomEntries = JSON.parse(text.trim());
                    root.aegisCustomReady = true;
                } catch (error) {
                    root.aegisCustomReady = false;
                    console.log("[Aegis Özel Pencere] Kayıtlı seçimler okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Özel Pencere] " + text.trim());
            }
        }
    }

    Process {
        id: aegisCustomApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Özel Pencere] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Özel Pencere] HATA: " + text.trim());
            }
        }
        onRunningChanged: {
            if (!running)
                root.refreshAegisCustomData();
        }
    }

    Process {
        id: aegisPipFloatReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-pip-floatctl.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisPipFloatEnabled = state.enabled === true;
                    root.aegisPipFloatReady = true;
                } catch (error) {
                    console.log("[Aegis PiP] Ayar okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis PiP] " + text.trim());
            }
        }
    }

    Process {
        id: aegisPipFloatApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis PiP] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis PiP] HATA: " + text.trim());
            }
        }
    }

    Process {
        id: aegisMotionProfileReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-motion-profile.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisMotionProfile = state.profile;
                    root.aegisMotionProfileReady = true;
                } catch (error) {
                    console.log("[Aegis Motion] Profil okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Motion] " + text.trim());
            }
        }
    }

    Process {
        id: aegisMotionProfileApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Motion] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Motion] HATA: " + text.trim());
            }
        }
        onRunningChanged: {
            if (!running)
                root.aegisMotionProfileReadProc.running = true;
        }
    }

        Timer {
        id: aegisGlassApplyDebounce
        interval: 450
        repeat: false
        onTriggered: root.startGlassApply()
    }

    Process {
        id: aegisGlassReadProc
        command: [
            "bash", "-lc",
            'python3 "$HOME/.config/hypr/custom/aegis-glassctl.py" get'
        ]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const state = JSON.parse(text.trim());
                    root.aegisBlurSize = Number(state.size);
                    root.aegisBlurPasses = Number(state.passes);
                    root.aegisAcrylicClarity = Number(state.clarity) * 100;
                    root.aegisGlassEnabled = state.enabled !== false;
                    root.aegisGlassReady = true;
                } catch (error) {
                    console.log("[Aegis Cam] Ayarlar okunamadı: " + error);
                }
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Cam] " + text.trim());
            }
        }
    }

    Process {
        id: aegisGlassApplyProc
        command: []
        stdout: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Cam] " + text.trim());
            }
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.log("[Aegis Cam] " + text.trim());
            }
        }
        onRunningChanged: {
            if (!running && root.aegisGlassApplyPending) {
                root.aegisGlassApplyPending = false;
                root.aegisGlassApplyDebounce.restart();
            }
        }
    }

ContentSection {
        icon: "colors"
        title: Translation.tr("Color generation")
        visible: root.sectionFilter === "" || root.sectionFilter === "appearance"

        ConfigRow {
            uniform: true

            RippleButtonWithIcon {
                Layout.fillWidth: true
                materialIcon: "wallpaper"
                mainText: Translation.tr("Wallpaper source")
                toggled: !PulsarColorEngine.manualSource
                enabled: !PulsarColorEngine.busy
                onClicked: PulsarColorEngine.useWallpaperColors()
            }

            RippleButtonWithIcon {
                Layout.fillWidth: true
                materialIcon: "palette"
                mainText: Translation.tr("Pick manual color")
                toggled: PulsarColorEngine.manualSource
                enabled: !PulsarColorEngine.busy
                onClicked: PulsarColorEngine.chooseManualColor()
            }

        }

        StyledText {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: PulsarColorEngine.errorText.length > 0
                ? Appearance.colors.colError
                : Appearance.colors.colSubtext
            text: PulsarColorEngine.errorText.length > 0
                ? PulsarColorEngine.errorText
                : Translation.tr(PulsarColorEngine.manualSource ? "Color source: manual" : "Color source: wallpaper")
        }

        ConfigSwitch {
            buttonIcon: "hardware"
            text: Translation.tr("Shell & utilities")
            checked: Config.options.appearance.wallpaperTheming.enableAppsAndShell
            onCheckedChanged: {
                Config.options.appearance.wallpaperTheming.enableAppsAndShell = checked;
            }
        }
        ConfigSwitch {
            buttonIcon: "palette"
            text: Translation.tr("Tint app window backgrounds")
            checked: Config.options.appearance.wallpaperTheming.tintAppWindowSurfaces
            onCheckedChanged: {
                if (checked === Config.options.appearance.wallpaperTheming.tintAppWindowSurfaces)
                    return;
                Config.options.appearance.wallpaperTheming.tintAppWindowSurfaces = checked;
                PulsarColorEngine.refreshPalette();
            }
            StyledToolTip {
                text: Translation.tr("Tints GTK 3/4 and KDE/Qt app backgrounds with the selected palette. Some apps need restart.")
            }
        }
        ConfigSwitch {
            buttonIcon: "tv_options_input_settings"
            text: Translation.tr("Qt apps")
            checked: Config.options.appearance.wallpaperTheming.enableQtApps
            onCheckedChanged: {
                Config.options.appearance.wallpaperTheming.enableQtApps = checked;
            }
            StyledToolTip {
                text: Translation.tr("Shell & utilities theming must also be enabled")
            }
        }
        ConfigSwitch {
            buttonIcon: "terminal"
            text: Translation.tr("Terminal")
            checked: Config.options.appearance.wallpaperTheming.enableTerminal
            onCheckedChanged: {
                Config.options.appearance.wallpaperTheming.enableTerminal = checked;
            }
            StyledToolTip {
                text: Translation.tr("Shell & utilities theming must also be enabled")
            }
        }
        ConfigRow {
            uniform: true
            ConfigSwitch {
                buttonIcon: "dark_mode"
                text: Translation.tr("Force dark mode in terminal")
                checked: Config.options.appearance.wallpaperTheming.terminalGenerationProps.forceDarkMode
                onCheckedChanged: {
                     Config.options.appearance.wallpaperTheming.terminalGenerationProps.forceDarkMode= checked;
                }
                StyledToolTip {
                    text: Translation.tr("Ignored if terminal theming is not enabled")
                }
            }
        }

        ConfigSpinBox {
            icon: "invert_colors"
            text: Translation.tr("Terminal: Harmony (%)")
            value: Config.options.appearance.wallpaperTheming.terminalGenerationProps.harmony * 100
            from: 0
            to: 100
            stepSize: 10
            onValueChanged: {
                Config.options.appearance.wallpaperTheming.terminalGenerationProps.harmony = value / 100;
            }
        }
        ConfigSpinBox {
            icon: "gradient"
            text: Translation.tr("Terminal: Harmonize threshold")
            value: Config.options.appearance.wallpaperTheming.terminalGenerationProps.harmonizeThreshold
            from: 0
            to: 100
            stepSize: 10
            onValueChanged: {
                Config.options.appearance.wallpaperTheming.terminalGenerationProps.harmonizeThreshold = value;
            }
        }
        ConfigSpinBox {
            icon: "format_color_text"
            text: Translation.tr("Terminal: Foreground boost (%)")
            value: Config.options.appearance.wallpaperTheming.terminalGenerationProps.termFgBoost * 100
            from: 0
            to: 100
            stepSize: 10
            onValueChanged: {
                Config.options.appearance.wallpaperTheming.terminalGenerationProps.termFgBoost = value / 100;
            }
        }
    }

    ContentSection {
        icon: "palette"
        title: Translation.tr("Desktop, Icons & GTK/Qt Appearance")
        visible: root.sectionFilter === "appearance" && desktopAppearanceInlineLoader.hasSettings

        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Unified system icon theme, GTK 3/4, Qt/KDE themes, window buttons, interface font, and sound theme.")
            font.pixelSize: Appearance.font.pixelSize.smaller
            color: Appearance.colors.colSubtext
            wrapMode: Text.WordWrap
        }

        Loader {
            id: desktopAppearanceInlineLoader
            Layout.fillWidth: true
            Layout.preferredHeight: item ? Math.max(0, Number(item.contentHeight || 0)) : 0
            readonly property bool hasSettings: Boolean(
                root.settingsRoot
                && typeof root.settingsRoot.supplementalCountForPage === "function"
                && root.settingsRoot.supplementalCountForPage(findAppearancePage()) > 0
            )
            active: root.sectionFilter === "appearance" && hasSettings
            visible: active
            source: active ? Qt.resolvedUrl("DynamicCategoryConfig.qml") : ""

            function findAppearancePage() {
                if (!root.settingsRoot || !root.settingsRoot.pages)
                    return null;
                const list = root.settingsRoot.pages;
                for (let i = 0; i < list.length; ++i) {
                    if (list[i] && String(list[i].categoryId || "").toLocaleLowerCase() === "appearance")
                        return list[i];
                }
                return null;
            }

            function syncProps() {
                if (!item)
                    return;
                item.settingsRoot = root.settingsRoot;
                item.pageData = findAppearancePage();
                item.supplementalOnly = true;
                item.embedded = true;
            }

            onLoaded: syncProps()

            Connections {
                target: root.settingsRoot
                function onPagesChanged() { desktopAppearanceInlineLoader.syncProps(); }
            }
        }
    }





    ContentSection {
        icon: "animation"
        title: "Animasyon profili"
        visible: root.sectionFilter === "" || root.sectionFilter === "motion"

        ContentSubsection {
            title: "Hareket yoğunluğu"

            ConfigRow {
                uniform: true

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "block"
                    mainText: root.aegisMotionProfile === "off" ? "✓ Kapalı" : "Kapalı"
                    onClicked: root.applyAegisMotionProfile("off")
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "blur_on"
                    mainText: root.aegisMotionProfile === "light" ? "✓ Hafif" : "Hafif"
                    onClicked: root.applyAegisMotionProfile("light")
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "auto_awesome"
                    mainText: root.aegisMotionProfile === "full" ? "✓ Tam" : "Tam"
                    onClicked: root.applyAegisMotionProfile("full")
                }
            }

            StyledToolTip {
                text: "Kapalı: geçişler ve Wobble kapalı. Hafif: daha yumuşak geçişler. Tam: Eclipse'in güçlü animasyon profili."
            }
        }
    }

    ContentSection {
        icon: "space_dashboard"
        title: "Pencere aralıkları ve köşeler"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Genel boşluklar"

            StyledText {
                Layout.fillWidth: true
                text: "Bu değerler Hyprland'ın genel aralıklarıdır. Çalışma alanı kuralları bazı çalışma alanlarında aralıkları geçersiz kılabilir."
                color: Appearance.colors.colSubtext
                wrapMode: Text.WordWrap
            }

            StyledText {
                Layout.fillWidth: true
                text: "Kaydederken Hyprland yapılandırmayı otomatik yenileyebilir. NEXUS canlı sonucu doğrular ve başarısızlıkta geri alır."
                color: Appearance.colors.colSubtext
                wrapMode: Text.WordWrap
            }

            ConfigSpinBox {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                text: "Pencereler arası boşluk"
                icon: "space_dashboard"
                from: root.aegisHyprlandGapMinimum
                to: root.aegisHyprlandGapMaximum
                stepSize: 1
                value: root.aegisHyprlandGapsIn
                visible: root.aegisHyprlandOptionsReady
                enabled: visible && !root.aegisHyprlandOptionsBusy && !aegisHyprlandOptionsReadProc.running && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
                Accessible.name: "Uniform gap between windows in pixels"
                onValueChanged: root.aegisHyprlandGapsIn = value
            }

            ConfigSpinBox {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                text: "Ekran kenarı boşluğu"
                icon: "open_with"
                from: root.aegisHyprlandGapMinimum
                to: root.aegisHyprlandGapMaximum
                stepSize: 1
                value: root.aegisHyprlandGapsOut
                visible: root.aegisHyprlandOptionsReady
                enabled: visible && !root.aegisHyprlandOptionsBusy && !aegisHyprlandOptionsReadProc.running && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
                Accessible.name: "Uniform gap between windows and monitor edges in pixels"
                onValueChanged: root.aegisHyprlandGapsOut = value
            }
        }

        ContentSubsection {
            title: "Köşe görünümü"

            ConfigSpinBox {
                Layout.fillWidth: true
                Layout.preferredHeight: 44
                text: "Pencere köşe yuvarlaklığı"
                icon: "rounded_corner"
                from: root.aegisHyprlandRoundingMinimum
                to: root.aegisHyprlandRoundingMaximum
                stepSize: 1
                value: root.aegisHyprlandRounding
                visible: root.aegisHyprlandOptionsReady
                enabled: visible && !root.aegisHyprlandOptionsBusy && !aegisHyprlandOptionsReadProc.running && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
                Accessible.name: "Window corner rounding in the supported Hyprland range"
                onValueChanged: root.aegisHyprlandRounding = value
            }
        }

        StyledText {
            Layout.fillWidth: true
            text: root.aegisHyprlandOptionsMessage
            color: root.aegisHyprlandOptionsReady || aegisHyprlandOptionsReadProc.running || root.aegisHyprlandOptionsBusy
                   ? Appearance.colors.colSubtext : Appearance.colors.colError
            wrapMode: Text.WordWrap
        }

        RippleButton {
            Layout.fillWidth: true
            Layout.preferredHeight: 46
            buttonRadius: Appearance.rounding.small
            enabled: root.aegisHyprlandOptionsReady && !root.aegisHyprlandOptionsBusy && !aegisHyprlandOptionsReadProc.running && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
            colBackground: Appearance.colors.colPrimary
            colBackgroundHover: Appearance.colors.colPrimaryHover
            Accessible.name: "Apply and verify Hyprland window spacing and rounding"
            onClicked: root.applyHyprlandOptions()
            contentItem: StyledText {
                text: root.aegisHyprlandOptionsBusy ? "Uygulanıyor…" : "Değerleri uygula"
                color: Appearance.colors.colOnPrimary
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.weight: Font.DemiBold
            }
        }
    }

    ContentSection {
        icon: "colors"
        title: "Pencere Glow"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Glow rengi"
            ConfigRow {
                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "colorize"
                    mainText: "Glow rengini ekrandan seç"
                    onClicked: {
                        Quickshell.execDetached([
                            "bash",
                            "-lc",
                            "$HOME/.config/hypr/custom/pick-glow-color.sh"
                        ])
                    }
                }
            }
        }

        ContentSubsection {
            title: "Glow ayarları"

            ConfigSwitch {
                buttonIcon: "blur_on"
                text: "Glow efektini etkinleştir"
                checked: root.aegisGlowEnabled
                onCheckedChanged: {
                    if (root.aegisGlowReady && checked !== root.aegisGlowEnabled) {
                        root.aegisGlowEnabled = checked;
                        root.queueGlowApply();
                    }
                }
            }

            ConfigSlider {
                buttonIcon: "brightness_6"
                text: "Parlaklık (" + Math.round(root.aegisGlowBrightness) + "%)"
                value: root.aegisGlowBrightness
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (root.aegisGlowReady) {
                        root.aegisGlowBrightness = value;
                        root.queueGlowApply();
                    }
                }
            }

            ConfigSlider {
                buttonIcon: "blur_on"
                text: "Boyut (" + Math.round(root.aegisGlowSize) + ")"
                value: root.aegisGlowSize
                from: 10
                to: 80
                usePercentTooltip: false
                onValueChanged: {
                    if (root.aegisGlowReady) {
                        root.aegisGlowSize = value;
                        root.queueGlowApply();
                    }
                }
            }
        }
    }

ContentSection {
        icon: "tune"
        title: "Pencere davranışı"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Aktif ve pasif pencere opaklığı"

            ConfigSlider {
                buttonIcon: "opacity"
                text: "Aktif: " + Math.round(root.aegisActiveOpacity) + "%"
                textWidth: 96
                value: root.aegisActiveOpacity
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (root.aegisWindowEffectsReady &&
                        Math.abs(value - root.aegisActiveOpacity) > 0.05) {
                        root.aegisActiveOpacity = Math.max(75, value);
                        root.queueWindowEffectsApply();
                    }
                }
            }

            ConfigSlider {
                buttonIcon: "opacity"
                text: "Pasif: " + Math.round(root.aegisInactiveOpacity) + "%"
                textWidth: 96
                value: root.aegisInactiveOpacity
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (root.aegisWindowEffectsReady &&
                        Math.abs(value - root.aegisInactiveOpacity) > 0.05) {
                        root.aegisInactiveOpacity = Math.max(75, value);
                        root.queueWindowEffectsApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "layers"
                text: "Pasif pencerede derinlik hissi"
                checked: root.aegisDepthEffectEnabled
                onCheckedChanged: {
                    if (root.aegisWindowEffectsReady &&
                        checked !== root.aegisDepthEffectEnabled) {
                        root.aegisDepthEffectEnabled = checked;
                        root.queueWindowEffectsApply();
                    }
                }
                StyledToolTip {
                    text: "Açıkken pasif pencereler çok hafif karartılır. Boyutları değişmez; bu yerleşik yöntem gerçek ölçekleme yapmaz."
                }
            }
        }
    }

    ContentSection {
        icon: "notifications"
        title: "Bildirim Liquid Glass"
        visible: root.sectionFilter === "" || root.sectionFilter === "effects"

        ContentSubsection {
            title: "Cam görünümü"

            ConfigSlider {
                buttonIcon: "opacity"
                text: "Cam saydamlığı (" + Config.options.notifications.liquidGlass.transparency + "%)"
                textWidth: 190
                value: Config.options.notifications.liquidGlass.transparency
                animateValue: false
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (pressed)
                        Config.options.notifications.liquidGlass.transparency = Math.round(value);
                }
            }

            ConfigSlider {
                buttonIcon: "palette"
                text: "Renk yansıması (" + Config.options.notifications.liquidGlass.colorReflection + "%)"
                textWidth: 190
                value: Config.options.notifications.liquidGlass.colorReflection
                animateValue: false
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (pressed)
                        Config.options.notifications.liquidGlass.colorReflection = Math.round(value);
                }
            }

            ConfigSlider {
                buttonIcon: "flare"
                text: "Neon kenar yoğunluğu (" + Config.options.notifications.liquidGlass.neonIntensity + "%)"
                textWidth: 190
                value: Config.options.notifications.liquidGlass.neonIntensity
                animateValue: false
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (pressed)
                        Config.options.notifications.liquidGlass.neonIntensity = Math.round(value);
                }
            }
        }

        ContentSubsection {
            title: "Renk kaynağı"

            ConfigRow {
                uniform: true

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "wallpaper"
                    mainText: Config.options.notifications.liquidGlass.colorSource === "wallpaper"
                        ? "✓ Duvar kâğıdı" : "Duvar kâğıdı"
                    onClicked: Config.options.notifications.liquidGlass.colorSource = "wallpaper"
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "palette"
                    mainText: Config.options.notifications.liquidGlass.colorSource === "matugen"
                        ? "✓ Matugen" : "Matugen"
                    onClicked: Config.options.notifications.liquidGlass.colorSource = "matugen"
                }
            }
        }

        ContentSubsection {
            title: "Cam profili"

            ConfigRow {
                uniform: true

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "blur_on"
                    mainText: Config.options.notifications.liquidGlass.glassProfile === "light"
                        ? "✓ Hafif" : "Hafif"
                    onClicked: Config.options.notifications.liquidGlass.glassProfile = "light"
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "tune"
                    mainText: Config.options.notifications.liquidGlass.glassProfile === "balanced"
                        ? "✓ Dengeli" : "Dengeli"
                    onClicked: Config.options.notifications.liquidGlass.glassProfile = "balanced"
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "graphic_eq"
                    mainText: Config.options.notifications.liquidGlass.glassProfile === "strong"
                        ? "✓ Yoğun" : "Yoğun"
                    onClicked: Config.options.notifications.liquidGlass.glassProfile = "strong"
                }
            }
        }

        ContentSubsection {
            title: "Animasyon profili"

            ConfigRow {
                uniform: true

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "block"
                    mainText: Config.options.notifications.liquidGlass.animationProfile === "off"
                        ? "✓ Kapalı" : "Kapalı"
                    onClicked: Config.options.notifications.liquidGlass.animationProfile = "off"
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "animation"
                    mainText: Config.options.notifications.liquidGlass.animationProfile === "subtle"
                        ? "✓ Hafif" : "Hafif"
                    onClicked: Config.options.notifications.liquidGlass.animationProfile = "subtle"
                }

                RippleButtonWithIcon {
                    Layout.fillWidth: true
                    materialIcon: "auto_awesome"
                    mainText: Config.options.notifications.liquidGlass.animationProfile === "full"
                        ? "✓ Tam" : "Tam"
                    onClicked: Config.options.notifications.liquidGlass.animationProfile = "full"
                }
            }
        }
    }

    ContentSection {
        icon: "opacity"
        title: "Tam opak pencere istisnaları"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Opaklık uygulanacak pencere türleri"

            ConfigSwitch {
                buttonIcon: "window"
                text: "Blender"
                checked: root.aegisOpaqueBlender
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueBlender) {
                        root.aegisOpaqueBlender = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "movie"
                text: "DaVinci Resolve"
                checked: root.aegisOpaqueDavinci
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueDavinci) {
                        root.aegisOpaqueDavinci = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "play_circle"
                text: "VLC medya oynatıcı"
                checked: root.aegisOpaqueVlc
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueVlc) {
                        root.aegisOpaqueVlc = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "photo"
                text: "Fotoğraf görüntüleyiciler"
                checked: root.aegisOpaquePhotoViewers
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaquePhotoViewers) {
                        root.aegisOpaquePhotoViewers = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "sports_esports"
                text: "Oyunlar"
                checked: root.aegisOpaqueGames
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueGames) {
                        root.aegisOpaqueGames = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "perm_media"
                text: "Video ve fotoğraf içerikleri"
                checked: root.aegisOpaqueMediaContent
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueMediaContent) {
                        root.aegisOpaqueMediaContent = checked;
                        root.queueOpacityRulesApply();
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "fullscreen"
                text: "Tam ekran pencereler"
                checked: root.aegisOpaqueFullscreen
                onCheckedChanged: {
                    if (root.aegisOpacityRulesReady &&
                        checked !== root.aegisOpaqueFullscreen) {
                        root.aegisOpaqueFullscreen = checked;
                        root.queueOpacityRulesApply();
                    }
                }
                StyledToolTip {
                    text: "Açıkken tam ekran pencereler %100 opak olur. Kapalıyken bu özel kural uygulanmaz."
                }
            }
        }
    }

    ContentSection {
        icon: "picture_in_picture"
        title: "Resim içinde resim"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "PiP pencere davranışı"

            ConfigSwitch {
                buttonIcon: "picture_in_picture"
                text: "PiP penceresini yüzer yap"
                checked: root.aegisPipFloatEnabled
                onCheckedChanged: {
                    if (root.aegisPipFloatReady &&
                        checked !== root.aegisPipFloatEnabled) {
                        root.aegisPipFloatEnabled = checked;
                        aegisPipFloatApplyProc.command = [
                            "bash", "-lc",
                            'python3 "$HOME/.config/hypr/custom/aegis-pip-floatctl.py" apply "$1"',
                            "aegis-pip-float",
                            checked ? "true" : "false"
                        ];
                        aegisPipFloatApplyProc.running = true;
                    }
                }
                StyledToolTip {
                    text: "Açıkken yalnızca Zen'in Görüntü içinde görüntü penceresi yüzer pencere kuralı alır. Kapalıyken bu özel kural uygulanmaz."
                }
            }
        }
    }

    ContentSection {
        icon: "tune"
        title: "Özel pencereler"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Açık pencereler"

            DialogButton {
                buttonText: "Pencere listesini yenile"
                Layout.fillWidth: true
                downAction: () => root.refreshAegisCustomData()
            }

            Text {
                Layout.fillWidth: true
                visible: root.aegisCustomWindows.length === 0
                text: "Açık pencere bulunamadı."
                wrapMode: Text.Wrap
                color: Appearance.colors.colSubtext
            }

            Repeater {
                model: root.aegisCustomWindows

                delegate: DialogButton {
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    buttonText: String(modelData.class || "Bilinmeyen uygulama")
                        + " — " + String(modelData.title || "(başlık yok)")

                    downAction: () => {
                        root.aegisCustomSelectedIndex = index;
                        root.addAegisCustomSelection();
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                text: "Bir pencereye basarak o pencere için özel opaklık kuralı ekleyebilirsin."
                wrapMode: Text.Wrap
                color: Appearance.colors.colSubtext
            }
        }

        ContentSubsection {
            title: "Kayıtlı özel kurallar"

            Text {
                Layout.fillWidth: true
                visible: root.aegisCustomReady
                    && root.aegisCustomEntries.length === 0
                text: "Henüz özel pencere kuralı eklenmedi."
                wrapMode: Text.Wrap
                color: Appearance.colors.colSubtext
            }

            Repeater {
                model: root.aegisCustomEntries

                delegate: DialogButton {
                    required property var modelData
                    required property int index

                    Layout.fillWidth: true
                    buttonText: "Kaldır: "
                        + String(modelData.class || "Bilinmeyen uygulama")
                        + " — " + String(modelData.title || "(başlık yok)")

                    downAction: () => root.removeAegisCustomSelection(index)
                }
            }
        }
    }

    ContentSection {
        icon: "blur_on"
        title: "Cam bulanıklığı"
        visible: root.sectionFilter === "" || root.sectionFilter === "windows"

        ContentSubsection {
            title: "Acrylic buzlu cam"

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                DialogButton {
                    buttonText: "Hafif"
                    Layout.fillWidth: true

                    toggled: Math.round(root.aegisBlurSize) === 8
                        && Math.round(root.aegisBlurPasses) === 2
                        && Math.round(root.aegisAcrylicClarity) === 65
                    colEnabled: toggled
                        ? Appearance.colors.colOnPrimary
                        : Appearance.colors.colPrimary

                    downAction: () => {
                        if (!root.aegisGlassReady) {
                            console.log("[Aegis Cam] Ayarlar henüz hazır değil.");
                            return;
                        }
                        root.applyGlassProfile("light");
                        console.log("[Aegis Cam] Hafif profil seçildi.");
                    }
                }

                DialogButton {
                    buttonText: "Dengeli"
                    Layout.fillWidth: true

                    toggled: Math.round(root.aegisBlurSize) === 14
                        && Math.round(root.aegisBlurPasses) === 4
                        && Math.round(root.aegisAcrylicClarity) === 50
                    colEnabled: toggled
                        ? Appearance.colors.colOnPrimary
                        : Appearance.colors.colPrimary

                    downAction: () => {
                        if (!root.aegisGlassReady) {
                            console.log("[Aegis Cam] Ayarlar henüz hazır değil.");
                            return;
                        }
                        root.applyGlassProfile("balanced");
                        console.log("[Aegis Cam] Dengeli profil seçildi.");
                    }
                }

                DialogButton {
                    buttonText: "Yoğun"
                    Layout.fillWidth: true

                    toggled: Math.round(root.aegisBlurSize) === 20
                        && Math.round(root.aegisBlurPasses) === 5
                        && Math.round(root.aegisAcrylicClarity) === 25
                    colEnabled: toggled
                        ? Appearance.colors.colOnPrimary
                        : Appearance.colors.colPrimary

                    downAction: () => {
                        if (!root.aegisGlassReady) {
                            console.log("[Aegis Cam] Ayarlar henüz hazır değil.");
                            return;
                        }
                        root.applyGlassProfile("heavy");
                        console.log("[Aegis Cam] Yoğun profil seçildi.");
                    }
                }
            }

            ConfigSwitch {
                buttonIcon: "blur_on"
                text: "Acrylic cam efektini etkinleştir"
                checked: root.aegisGlassEnabled
                onCheckedChanged: {
                    if (root.aegisGlassReady &&
                        root.aegisGlassEnabled !== checked) {
                        root.aegisGlassEnabled = checked;
                        root.queueGlassApply();
                    }
                }
                StyledToolTip {
                    text: "Kapalıyken bulanıklık devre dışı kalır; boyut ve netlik ayarları korunur."
                }
            }

            ConfigSlider {
                buttonIcon: "blur_on"
                text: "Bulanıklık boyutu (" + Math.round(root.aegisBlurSize) + ")"
                textWidth: 190
                value: root.aegisBlurSize
                animateValue: false
                from: 4
                to: 24
                usePercentTooltip: false
                onValueChanged: {
                    if (pressed && root.aegisGlassReady &&
                        Math.abs(value - root.aegisBlurSize) > 0.05) {
                        root.aegisBlurSize = Math.round(value);
                        root.queueGlassApply();
                    }
                }
            }

            ConfigSlider {
                buttonIcon: "blur_on"
                text: "Bulanıklık geçişi (" + Math.round(root.aegisBlurPasses) + ")"
                textWidth: 190
                value: root.aegisBlurPasses
                animateValue: false
                from: 1
                to: 6
                usePercentTooltip: false
                onValueChanged: {
                    if (pressed && root.aegisGlassReady &&
                        Math.abs(value - root.aegisBlurPasses) > 0.05) {
                        root.aegisBlurPasses = Math.round(value);
                        root.queueGlassApply();
                    }
                }
            }

            ConfigSlider {
                buttonIcon: "tune"
                text: "Arka plan netliği (" + Math.round(root.aegisAcrylicClarity) + "%)"
                textWidth: 190
                value: root.aegisAcrylicClarity
                animateValue: false
                from: 0
                to: 100
                usePercentTooltip: true
                onValueChanged: {
                    if (pressed && root.aegisGlassReady &&
                        Math.abs(value - root.aegisAcrylicClarity) > 0.05) {
                        root.aegisAcrylicClarity = value;
                        root.queueGlassApply();
                    }
                }
            }
        }
    }



    ContentSection {
        icon: "graphic_eq"
        title: Translation.tr("Audio visualizer")
        visible: root.sectionFilter === "" || root.sectionFilter === "audio"

        ConfigSwitch {
            buttonIcon: "graphic_eq"
            text: Translation.tr("Enable audio visualizer")
            checked: Config.options.appearance.pulsarAudioVisualizer.enabled
            onCheckedChanged: Config.options.appearance.pulsarAudioVisualizer.enabled = checked
        }

        ConfigSelectionArray {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            currentValue: Config.options.appearance.pulsarAudioVisualizer.style
            onSelected: newValue => Config.options.appearance.pulsarAudioVisualizer.style = newValue
            options: [
                { displayName: Translation.tr("Wave box"), icon: "waves", value: "wave-box" },
                { displayName: Translation.tr("Levels box"), icon: "equalizer", value: "levels-box" },
                { displayName: Translation.tr("Particles box"), icon: "blur_on", value: "particles-box" },
                { displayName: Translation.tr("Bars box"), icon: "bar_chart", value: "bars-box" },
                { displayName: Translation.tr("Spine box"), icon: "timeline", value: "spine-box" },
                { displayName: Translation.tr("Splitter box"), icon: "vertical_split", value: "splitter-box" },
                { displayName: Translation.tr("Wave circle"), icon: "radio_button_unchecked", value: "wave-circle" },
                { displayName: Translation.tr("Levels circle"), icon: "donut_large", value: "levels-circle" },
                { displayName: Translation.tr("Particles circle"), icon: "blur_circular", value: "particles-circle" },
                { displayName: Translation.tr("Bars circle"), icon: "radio_button_checked", value: "bars-circle" },
                { displayName: Translation.tr("Spine circle"), icon: "track_changes", value: "spine-circle" }
            ]
        }
        ConfigSelectionArray {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            currentValue: Config.options.appearance.pulsarAudioVisualizer.position
            onSelected: newValue => Config.options.appearance.pulsarAudioVisualizer.position = newValue
            options: [
                { displayName: Translation.tr("Top left"), icon: "north_west", value: "top-left" },
                { displayName: Translation.tr("Top center"), icon: "arrow_upward", value: "top-center" },
                { displayName: Translation.tr("Top right"), icon: "north_east", value: "top-right" },
                { displayName: Translation.tr("Left center"), icon: "arrow_back", value: "left-center" },
                { displayName: Translation.tr("Center"), icon: "center_focus_strong", value: "center" },
                { displayName: Translation.tr("Right center"), icon: "arrow_forward", value: "right-center" },
                { displayName: Translation.tr("Bottom left"), icon: "south_west", value: "bottom-left" },
                { displayName: Translation.tr("Bottom center"), icon: "arrow_downward", value: "bottom-center" },
                { displayName: Translation.tr("Bottom right"), icon: "south_east", value: "bottom-right" }
            ]
        }
        ConfigSpinBox {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            icon: "straighten"
            text: Translation.tr("Visualizer length")
            value: Config.options.appearance.pulsarAudioVisualizer.length
            from: 160
            to: 1200
            stepSize: 40
            onValueChanged: Config.options.appearance.pulsarAudioVisualizer.length = value
        }
        ConfigSpinBox {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            icon: "height"
            text: Translation.tr("Visualizer thickness")
            value: Config.options.appearance.pulsarAudioVisualizer.size
            from: 32
            to: 180
            stepSize: 8
            onValueChanged: Config.options.appearance.pulsarAudioVisualizer.size = value
        }
        ConfigSpinBox {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            icon: "graphic_eq"
            text: Translation.tr("Visualizer sensitivity")
            value: Config.options.appearance.pulsarAudioVisualizer.sensitivity
            from: 1
            to: 5
            stepSize: 1
            onValueChanged: Config.options.appearance.pulsarAudioVisualizer.sensitivity = value
        }
        ConfigSpinBox {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            icon: "equalizer"
            text: Translation.tr("Visualizer bars")
            value: Config.options.appearance.pulsarAudioVisualizer.barCount
            from: 8
            to: 64
            stepSize: 8
            onValueChanged: Config.options.appearance.pulsarAudioVisualizer.barCount = value
        }
        ConfigSpinBox {
            enabled: Config.options.appearance.pulsarAudioVisualizer.enabled
            icon: "blur_on"
            text: Translation.tr("Visualizer smoothing")
            value: Config.options.appearance.pulsarAudioVisualizer.smoothing
            from: 0
            to: 10
            stepSize: 1
            onValueChanged: Config.options.appearance.pulsarAudioVisualizer.smoothing = value
        }

        ConfigRow {
            uniform: true
            ConfigSwitch {
                Layout.fillWidth: true
                buttonIcon: "palette"
                text: Translation.tr("Use Pulsar colors")
                checked: !Config.options.appearance.pulsarAudioVisualizer.useCustomColor
                onCheckedChanged: Config.options.appearance.pulsarAudioVisualizer.useCustomColor = !checked
            }
            RippleButtonWithIcon {
                Layout.fillWidth: true
                materialIcon: "colorize"
                mainText: Translation.tr("Pick visualizer color")
                enabled: !PulsarAudioVisualizer.pickingColor
                onClicked: PulsarAudioVisualizer.chooseManualColor()
            }
        }
        StyledText {
            Layout.fillWidth: true
            text: PulsarAudioVisualizer.errorText.length > 0
                ? PulsarAudioVisualizer.errorText
                : PulsarAudioVisualizer.options.useCustomColor
                    ? `${Translation.tr("Custom visualizer color")}: ${PulsarAudioVisualizer.options.customColor}`
                    : Translation.tr("Using the Pulsar color palette")
            color: PulsarAudioVisualizer.errorText.length > 0
                ? Appearance.colors.colError
                : Appearance.colors.colSubtext
        }
    }

    ContentSection {
        icon: "wallpaper_slideshow"
        title: Translation.tr("Wallpaper transitions")
        visible: root.sectionFilter === "" || root.sectionFilter === "motion"

        ConfigSwitch {
            buttonIcon: "animation"
            text: Translation.tr("Enable wallpaper transitions")
            checked: Config.options.background.transitions.enabled
            onCheckedChanged: Config.options.background.transitions.enabled = checked
        }

        ConfigSelectionArray {
            enabled: Config.options.background.transitions.enabled
            currentValue: Config.options.background.transitions.type
            onSelected: newValue => Config.options.background.transitions.type = newValue
            options: [
                { displayName: Translation.tr("Fade through black"), icon: "tonality", value: "fade" },
                { displayName: Translation.tr("Fade through white"), icon: "light_mode", value: "fade-white" },
                { displayName: Translation.tr("Fade through accent"), icon: "palette", value: "fade-color" },
                { displayName: Translation.tr("Crossfade"), icon: "blend", value: "crossfade" },
                { displayName: Translation.tr("Slide left"), icon: "west", value: "slide" },
                { displayName: Translation.tr("Slide right"), icon: "east", value: "slide-right" },
                { displayName: Translation.tr("Slide up"), icon: "north", value: "slide-up" },
                { displayName: Translation.tr("Slide down"), icon: "south", value: "slide-down" },
                { displayName: Translation.tr("Diagonal slide up left"), icon: "north_west", value: "slide-up-left" },
                { displayName: Translation.tr("Diagonal slide up right"), icon: "north_east", value: "slide-up-right" },
                { displayName: Translation.tr("Diagonal slide down left"), icon: "south_west", value: "slide-down-left" },
                { displayName: Translation.tr("Diagonal slide down right"), icon: "south_east", value: "slide-down-right" },
                { displayName: Translation.tr("Wipe left"), icon: "keyboard_double_arrow_left", value: "wipe-left" },
                { displayName: Translation.tr("Wipe right"), icon: "keyboard_double_arrow_right", value: "wipe-right" },
                { displayName: Translation.tr("Wipe up"), icon: "keyboard_double_arrow_up", value: "wipe-up" },
                { displayName: Translation.tr("Wipe down"), icon: "keyboard_double_arrow_down", value: "wipe-down" },
                { displayName: Translation.tr("Center reveal"), icon: "center_focus_strong", value: "center-reveal" },
                { displayName: Translation.tr("Horizontal split"), icon: "horizontal_split", value: "split-horizontal" },
                { displayName: Translation.tr("Vertical split"), icon: "vertical_split", value: "split-vertical" },
                { displayName: Translation.tr("Vertical blinds"), icon: "view_column", value: "vertical-blinds" },
                { displayName: Translation.tr("Horizontal blinds"), icon: "view_day", value: "horizontal-blinds" },
                { displayName: Translation.tr("Zoom in"), icon: "zoom_in", value: "zoom-in" },
                { displayName: Translation.tr("Zoom out"), icon: "zoom_out", value: "zoom-out" },
                { displayName: Translation.tr("Rotate in"), icon: "rotate_right", value: "rotate-in" },
                { displayName: Translation.tr("Instant"), icon: "flash_on", value: "instant" }
            ]
        }

        ConfigSpinBox {
            enabled: Config.options.background.transitions.enabled && Config.options.background.transitions.type !== "instant"
            icon: "timer"
            text: Translation.tr("Transition duration")
            value: Config.options.background.transitions.duration
            from: 200
            to: 1600
            stepSize: 100
            onValueChanged: Config.options.background.transitions.duration = value
        }

        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Animated transitions work with static wallpapers. Dynamic backgrounds switch normally.")
            color: Appearance.colors.colSubtext
            wrapMode: Text.WordWrap
        }
    }


    ContentSection {
        icon: "sports_esports"
        title: Translation.tr("Pulsar Game Mode")
        visible: root.sectionFilter === "" || root.sectionFilter === "gaming"

        ConfigSwitch {
            buttonIcon: "sports_esports"
            text: Translation.tr("Automatically enable game mode")
            checked: Config.options.gameMode.automatic
            onCheckedChanged: Config.options.gameMode.automatic = checked
        }

        StyledText {
            Layout.fillWidth: true
            text: Translation.tr("Detects fullscreen Steam game windows and Gamescope. Browser and video windows are ignored.")
            color: Appearance.colors.colSubtext
            wrapMode: Text.WordWrap
        }
    }

}
