pragma ComponentBehavior: Bound

import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.widgets.widgetCanvas
import qs.modules.common.functions as CF
import QtQuick
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

import qs.modules.ii.background.widgets
import qs.modules.ii.background.widgets.clock
import qs.modules.ii.background.widgets.weather

Variants {
    id: root
    model: Quickshell.screens

    PanelWindow {
        id: bgRoot

        required property var modelData

        // Hide when fullscreen
        property list<HyprlandWorkspace> workspacesForMonitor: {
            if (!monitor || !Hyprland.workspaces?.values) return [];
            return Hyprland.workspaces.values.filter(workspace => workspace?.monitor && workspace.monitor.name === monitor.name);
        }
        property var activeWorkspaceWithFullscreen: workspacesForMonitor.find(workspace => workspace?.active && (workspace.toplevels?.values ?? []).some(window => window?.wayland?.fullscreen)) ?? null
        visible: GlobalStates.screenLocked || (!(activeWorkspaceWithFullscreen != undefined)) || !Config?.options.background.hideWhenFullscreen

        // Workspaces
        property HyprlandMonitor monitor: Hyprland.monitorFor(modelData)
        property list<var> relevantWindows: HyprlandData.windowList.filter(win => win?.workspace && monitor && win.monitor == monitor.id && win.workspace.id >= 0).sort((a, b) => a.workspace.id - b.workspace.id)
        property int firstWorkspaceId: relevantWindows[0]?.workspace?.id || 1
        property int lastWorkspaceId: relevantWindows[relevantWindows.length - 1]?.workspace?.id || 10
        property int workspaceChunkSize: Config?.options.bar.workspaces.shown ?? 10
        property int totalWorkspaces: Math.ceil(lastWorkspaceId / workspaceChunkSize) * workspaceChunkSize
        // Wallpaper
        property bool wallpaperIsVideo: Config.options.background.wallpaperPath.endsWith(".mp4") || Config.options.background.wallpaperPath.endsWith(".webm") || Config.options.background.wallpaperPath.endsWith(".mkv") || Config.options.background.wallpaperPath.endsWith(".avi") || Config.options.background.wallpaperPath.endsWith(".mov")
        property string wallpaperPath: wallpaperIsVideo ? Config.options.background.thumbnailPath : Config.options.background.wallpaperPath
        property string thumbnailPath: Config.options.background.thumbnailPath
        readonly property bool wallpaperUsesExternalProvider: pathUsesExternalProvider(Config.options.background.wallpaperPath)
        readonly property int wallpaperTransitionDuration: Math.max(200, Math.min(1600, Number(Config.options.background.transitions.duration) || 500))
        property string lastWallpaperPath: ""
        property string lastThumbnailPath: ""
        property bool lastWallpaperUsesExternalProvider: false
        property bool externalWallpaperProviderRunning: false
        property bool wallpaperChangeAwaitingProviderCheck: false
        property string transitionPreviousPath: ""
        property string transitionNextPath: ""
        property string transitionType: ""
        property real transitionProgress: 1
        property bool transitionLayerActive: false
        property bool transitionPending: false

        function pathUsesExternalProvider(path) {
            const value = (path || "").toLowerCase();
            const supportedImage = /\.(jpg|jpeg|png|webp|avif|bmp|svg)$/.test(value);
            const video = /\.(mp4|webm|mkv|avi|mov)$/.test(value);
            return value.length > 0 && (video || !supportedImage);
        }

        function cancelWallpaperTransition() {
            transitionStartTimeout.stop();
            wallpaperProgressAnimation.stop();
            wallpaperFadeAnimation.stop();
            transitionPending = false;
            transitionLayerActive = false;
            transitionPreviousPath = "";
            transitionNextPath = "";
            transitionProgress = 1;
            fadeCurtain.opacity = 0;
        }

        function finishWallpaperTransition() {
            transitionStartTimeout.stop();
            transitionPending = false;
            transitionLayerActive = false;
            transitionPreviousPath = "";
            transitionNextPath = "";
            transitionProgress = 1;
            fadeCurtain.opacity = 0;
        }

        function tryStartWallpaperTransition() {
            if (!transitionPending)
                return;
            if (previousTransitionImage.status === Image.Error || nextTransitionImage.status === Image.Error) {
                cancelWallpaperTransition();
                return;
            }
            if (previousTransitionImage.status !== Image.Ready || nextTransitionImage.status !== Image.Ready)
                return;

            transitionPending = false;
            transitionStartTimeout.stop();
            if (["fade", "fade-white", "fade-color"].includes(transitionType))
                wallpaperFadeAnimation.restart();
            else
                wallpaperProgressAnimation.restart();
        }

        function handleWallpaperPathChange(providerRunning) {
            const oldPath = lastWallpaperPath;
            const oldUsesExternalProvider = lastWallpaperUsesExternalProvider;
            const newPath = Config.options.background.wallpaperPath;
            const newUsesExternalProvider = pathUsesExternalProvider(newPath);
            const transitions = Config.options.background.transitions;
            const selectedType = transitions.type;

            lastWallpaperPath = newPath;
            lastThumbnailPath = Config.options.background.thumbnailPath;
            lastWallpaperUsesExternalProvider = newUsesExternalProvider;
            cancelWallpaperTransition();

            // External video providers do not expose frames for a reliable QML transition.
            if (!transitions.enabled || GlobalStates.screenLocked || PulsarGameMode.active || providerRunning || oldUsesExternalProvider || newUsesExternalProvider ||
                selectedType === "instant" || !oldPath || oldPath === newPath)
                return;

            const supportedTransitionTypes = [
                "fade", "fade-white", "fade-color", "crossfade", "slide", "slide-right", "slide-up", "slide-down",
                "slide-up-left", "slide-up-right", "slide-down-left", "slide-down-right",
                "wipe-left", "wipe-right", "wipe-up", "wipe-down", "center-reveal", "split-horizontal", "split-vertical",
                "vertical-blinds", "horizontal-blinds", "zoom-in", "zoom-out", "rotate-in"
            ];
            transitionType = supportedTransitionTypes.includes(selectedType) ? selectedType : "crossfade";
            transitionPreviousPath = oldPath;
            transitionNextPath = newPath;
            transitionProgress = 1;
            transitionLayerActive = true;
            transitionPending = true;
            transitionStartTimeout.restart();
            Qt.callLater(() => bgRoot.tryStartWallpaperTransition());
        }

        Component.onCompleted: {
            lastWallpaperPath = Config.options.background.wallpaperPath;
            lastThumbnailPath = Config.options.background.thumbnailPath;
            lastWallpaperUsesExternalProvider = pathUsesExternalProvider(lastWallpaperPath);
            externalWallpaperProviderCheck.running = true;
        }
        property bool wallpaperSafetyTriggered: {
            const enabled = Config.options.workSafety.enable.wallpaper;
            const sensitiveWallpaper = (CF.StringUtils.stringListContainsSubstring(wallpaperPath.toLowerCase(), Config.options.workSafety.triggerCondition.fileKeywords));
            const sensitiveNetwork = (CF.StringUtils.stringListContainsSubstring(Network.networkName.toLowerCase(), Config.options.workSafety.triggerCondition.networkNameKeywords));
            return enabled && sensitiveWallpaper && sensitiveNetwork;
        }
        readonly property real parallaxRation: Config.options.background.parallax.workspaceZoom
        property real minSuitableScale: 1 // Some reasonable init, to be updated
        property real effectiveWallpaperScale: minSuitableScale * parallaxRation
        property int wallpaperWidth: modelData.width // Some reasonable init value, to be updated
        property int wallpaperHeight: modelData.height // Some reasonable init value, to be updated
        property real scaledWallpaperWidth: wallpaperWidth * effectiveWallpaperScale
        property real scaledWallpaperHeight: wallpaperHeight * effectiveWallpaperScale
        property real parallaxTotalPixelsX: Math.max(0, scaledWallpaperWidth - screen.width)
        property real parallaxTotalPixelsY: Math.max(0, scaledWallpaperHeight - screen.height)
        readonly property bool verticalParallax: (Config.options.background.parallax.autoVertical && wallpaperHeight > wallpaperWidth) || Config.options.background.parallax.vertical
        // Colors
        property bool shouldBlur: (GlobalStates.screenLocked && Config.options.lock.blur.enable)
        property color dominantColor: Appearance.colors.colPrimary // Default, to be changed
        property bool dominantColorIsDark: dominantColor.hslLightness < 0.5
        property color colText: {
            if (wallpaperSafetyTriggered)
                return CF.ColorUtils.mix(Appearance.colors.colOnLayer0, Appearance.colors.colPrimary, 0.75);
            return (GlobalStates.screenLocked && shouldBlur) ? Appearance.colors.colOnLayer0 : CF.ColorUtils.colorWithLightness(Appearance.colors.colPrimary, (dominantColorIsDark ? 0.8 : 0.12));
        }
        Behavior on colText {
            animation: Appearance.animation.elementMoveFast.colorAnimation.createObject(this)
        }

        // Layer props
        screen: modelData
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: (GlobalStates.screenLocked && !scaleAnim.running) ? WlrLayer.Overlay : WlrLayer.Background
        // WlrLayershell.layer: WlrLayer.Bottom
        WlrLayershell.namespace: "quickshell:background"
        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }
        color: {
            if (!bgRoot.wallpaperSafetyTriggered || bgRoot.wallpaperIsVideo)
                return "transparent";
            return CF.ColorUtils.mix(Appearance.colors.colLayer0, Appearance.colors.colPrimary, 0.75);
        }
        Behavior on color {
            animation: Appearance.animation.elementMoveFast.colorAnimation.createObject(this)
        }

        onWallpaperPathChanged: {
            bgRoot.updateZoomScale();
            bgRoot.wallpaperChangeAwaitingProviderCheck = true;
            if (!externalWallpaperProviderCheck.running)
                externalWallpaperProviderCheck.running = true;
            // Clock position gets updated after zoom scale is updated
        }
        onThumbnailPathChanged: {
            // Keep the old provider state intact while switchwall.sh updates the two paths in sequence.
            if (Config.options.background.wallpaperPath === bgRoot.lastWallpaperPath) {
                bgRoot.lastThumbnailPath = Config.options.background.thumbnailPath;
                bgRoot.lastWallpaperUsesExternalProvider = bgRoot.pathUsesExternalProvider(bgRoot.lastWallpaperPath);
            }
        }

        // Wallpaper zoom scale
        function updateZoomScale() {
            getWallpaperSizeProc.path = bgRoot.wallpaperPath;
            getWallpaperSizeProc.running = true;
        }
        Process {
            id: getWallpaperSizeProc
            property string path: bgRoot.wallpaperPath
            command: ["magick", "identify", "-format", "%w %h", path]
            stdout: StdioCollector {
                id: wallpaperSizeOutputCollector
                onStreamFinished: {
                    const output = wallpaperSizeOutputCollector.text;
                    const [width, height] = output.split(" ").map(Number);
                    const [screenWidth, screenHeight] = [bgRoot.screen.width, bgRoot.screen.height];
                    bgRoot.wallpaperWidth = width;
                    bgRoot.wallpaperHeight = height;

                    // Perfect image; scale = 1
                    // Small picture; scale > 1; will zoom in the picture
                    // Big picture; scale < 1; will zoom out the picture
                    // Choose max number so every side will fit
                    bgRoot.minSuitableScale = Math.max(screenWidth / width, screenHeight / height);
                }
            }
        }

        Item {
            anchors.fill: parent

            // Wallpaper
            StyledImage {
                id: wallpaper
                visible: opacity > 0 && !blurLoader.active
                opacity: (status === Image.Ready && !bgRoot.wallpaperIsVideo) ? 1 : 0
                cache: false
                smooth: false

                property int workspaceIndex: (bgRoot.monitor?.activeWorkspace?.id ?? 1) - 1
                property real middleFraction: 0.5
                property real fraction: {
                    // 0 - start of the picture
                    // 1 - end of the picture
                    if (bgRoot.totalWorkspaces <= 1) {
                        return middleFraction;
                    }
                    return Math.max(0, Math.min(1, workspaceIndex / (bgRoot.totalWorkspaces - 1)));
                }

                property real usedFractionX: {
                    let usedFraction = middleFraction;
                    if (Config.options.background.parallax.enableWorkspace && !bgRoot.verticalParallax) {
                        usedFraction = fraction;
                    }
                    if (Config.options.background.parallax.enableSidebar) {
                        let sidebarFraction = bgRoot.parallaxRation / bgRoot.workspaceChunkSize / 2;
                        usedFraction += (sidebarFraction * GlobalStates.sidebarRightOpen - sidebarFraction * GlobalStates.sidebarLeftOpen);
                    }
                    return Math.max(0, Math.min(1, usedFraction));
                }
                property real usedFractionY: {
                    let usedFraction = middleFraction;
                    if (Config.options.background.parallax.enableWorkspace && bgRoot.verticalParallax) {
                        usedFraction = fraction;
                    }
                    return Math.max(0, Math.min(1, usedFraction));
                }

                x: {
                    if (bgRoot.screen.width > width) {
                        // Center the picture
                        return (bgRoot.screen.width - width) / 2;
                    }
                    return - bgRoot.parallaxTotalPixelsX * usedFractionX;
                }
                y: {
                    if (bgRoot.screen.height > height) {
                        // Center the picture
                        return (bgRoot.screen.height - height) / 2;
                    }
                    return - bgRoot.parallaxTotalPixelsY * usedFractionY;
                }

                source: bgRoot.wallpaperSafetyTriggered ? "" : bgRoot.wallpaperPath
                fillMode: Image.PreserveAspectCrop
                Behavior on x {
                    NumberAnimation {
                        duration: 600
                        easing.type: Easing.OutCubic
                    }
                }
                Behavior on y {
                    NumberAnimation {
                        duration: 600
                        easing.type: Easing.OutCubic
                    }
                }
                width: bgRoot.scaledWallpaperWidth
                height: bgRoot.scaledWallpaperHeight
            }

            // QML transitions are used only for static images; video providers remain untouched.
            StyledImage {
                id: previousTransitionImage
                x: {
                    const p = bgRoot.transitionProgress;
                    const type = bgRoot.transitionType;
                    if (["slide", "slide-left", "slide-up-left", "slide-down-left"].includes(type)) return -parent.width * (1 - p);
                    if (["slide-right", "slide-up-right", "slide-down-right"].includes(type)) return parent.width * (1 - p);
                    return 0;
                }
                y: {
                    const p = bgRoot.transitionProgress;
                    const type = bgRoot.transitionType;
                    if (["slide-up", "slide-up-left", "slide-up-right"].includes(type)) return -parent.height * (1 - p);
                    if (["slide-down", "slide-down-left", "slide-down-right"].includes(type)) return parent.height * (1 - p);
                    return 0;
                }
                width: parent.width
                height: parent.height
                source: bgRoot.transitionPreviousPath
                visible: bgRoot.transitionLayerActive && status === Image.Ready && opacity > 0
                opacity: ["crossfade", "zoom-in", "zoom-out", "rotate-in"].includes(bgRoot.transitionType) ? bgRoot.transitionProgress : 1
                scale: bgRoot.transitionType === "zoom-out" || bgRoot.transitionType === "rotate-in" ? 1 + (1 - bgRoot.transitionProgress) * 0.12 : 1
                cache: true
                smooth: false
                asynchronous: true
                fillMode: Image.PreserveAspectCrop
            }

            Item {
                id: wipeReveal
                property bool horizontalWipe: ["wipe-left", "wipe-right"].includes(bgRoot.transitionType)
                property bool verticalWipe: ["wipe-up", "wipe-down"].includes(bgRoot.transitionType)
                property bool centerReveal: bgRoot.transitionType === "center-reveal"
                property bool horizontalSplit: bgRoot.transitionType === "split-horizontal"
                property bool verticalSplit: bgRoot.transitionType === "split-vertical"
                property real revealFraction: 1 - bgRoot.transitionProgress
                x: bgRoot.transitionType === "wipe-right" ? parent.width * bgRoot.transitionProgress
                    : centerReveal || verticalSplit ? parent.width * bgRoot.transitionProgress / 2 : 0
                y: bgRoot.transitionType === "wipe-down" ? parent.height * bgRoot.transitionProgress
                    : centerReveal || horizontalSplit ? parent.height * bgRoot.transitionProgress / 2 : 0
                width: horizontalWipe || centerReveal || verticalSplit ? parent.width * revealFraction : parent.width
                height: verticalWipe || centerReveal || horizontalSplit ? parent.height * revealFraction : parent.height
                clip: true
                visible: bgRoot.transitionLayerActive && !["fade", "fade-white", "fade-color", "vertical-blinds", "horizontal-blinds"].includes(bgRoot.transitionType) && nextTransitionImage.status === Image.Ready

                StyledImage {
                    id: nextTransitionImage
                    width: parent.parent.width
                    height: parent.parent.height
                    x: {
                        const type = bgRoot.transitionType;
                        if (wipeReveal.centerReveal || wipeReveal.verticalSplit || type === "wipe-right") return -wipeReveal.x;
                        if (["slide", "slide-left", "slide-up-left", "slide-down-left"].includes(type)) return width * bgRoot.transitionProgress;
                        if (["slide-right", "slide-up-right", "slide-down-right"].includes(type)) return -width * bgRoot.transitionProgress;
                        return 0;
                    }
                    y: {
                        const type = bgRoot.transitionType;
                        if (wipeReveal.centerReveal || wipeReveal.horizontalSplit || type === "wipe-down") return -wipeReveal.y;
                        if (["slide-up", "slide-up-left", "slide-up-right"].includes(type)) return height * bgRoot.transitionProgress;
                        if (["slide-down", "slide-down-left", "slide-down-right"].includes(type)) return -height * bgRoot.transitionProgress;
                        return 0;
                    }
                    source: bgRoot.transitionNextPath
                    visible: bgRoot.transitionLayerActive && status === Image.Ready && opacity > 0
                    opacity: ["crossfade", "zoom-in", "zoom-out", "rotate-in"].includes(bgRoot.transitionType) ? 1 - bgRoot.transitionProgress : 1
                    scale: bgRoot.transitionType === "zoom-in" ? 0.88 + (1 - bgRoot.transitionProgress) * 0.12
                        : bgRoot.transitionType === "zoom-out" ? 1.12 - (1 - bgRoot.transitionProgress) * 0.12
                        : bgRoot.transitionType === "rotate-in" ? 0.82 + (1 - bgRoot.transitionProgress) * 0.18 : 1
                    rotation: bgRoot.transitionType === "rotate-in" ? 180 * bgRoot.transitionProgress : 0
                    cache: true
                    smooth: false
                    asynchronous: true
                    fillMode: Image.PreserveAspectCrop
                }
            }

            Item {
                id: blindReveal
                anchors.fill: parent
                visible: bgRoot.transitionLayerActive && ["vertical-blinds", "horizontal-blinds"].includes(bgRoot.transitionType)
                Repeater {
                    model: 6
                    delegate: Item {
                        id: blindSlice
                        required property int index
                        property bool verticalBlinds: bgRoot.transitionType === "vertical-blinds"
                        property real localReveal: Math.max(0, Math.min(1, (1 - bgRoot.transitionProgress) * 2 - index / 5))
                        x: verticalBlinds ? index * blindReveal.width / 6 : 0
                        y: verticalBlinds ? 0 : index * blindReveal.height / 6
                        width: verticalBlinds ? blindReveal.width / 6 : blindReveal.width * localReveal
                        height: verticalBlinds ? blindReveal.height * localReveal : blindReveal.height / 6
                        clip: true
                        StyledImage {
                            width: blindReveal.width
                            height: blindReveal.height
                            x: -blindSlice.x
                            y: -blindSlice.y
                            source: bgRoot.transitionNextPath
                            cache: true
                            smooth: false
                            asynchronous: true
                            fillMode: Image.PreserveAspectCrop
                        }
                    }
                }
            }

            Rectangle {
                id: fadeCurtain
                anchors.fill: parent
                color: bgRoot.transitionType === "fade-white" ? "white"
                    : bgRoot.transitionType === "fade-color" ? Appearance.colors.colPrimary : "black"
                opacity: 0
                visible: opacity > 0
            }

            Connections {
                target: previousTransitionImage
                function onStatusChanged() { bgRoot.tryStartWallpaperTransition(); }
            }
            Connections {
                target: nextTransitionImage
                function onStatusChanged() { bgRoot.tryStartWallpaperTransition(); }
            }

            Process {
                id: externalWallpaperProviderCheck
                command: ["bash", "-c", "pgrep -f '[m]pvpaper' >/dev/null"]
                onExited: (exitCode, exitStatus) => {
                    bgRoot.externalWallpaperProviderRunning = exitCode === 0;
                    if (bgRoot.wallpaperChangeAwaitingProviderCheck) {
                        bgRoot.wallpaperChangeAwaitingProviderCheck = false;
                        bgRoot.handleWallpaperPathChange(exitCode === 0);
                    }
                }
            }

            Timer {
                id: transitionStartTimeout
                interval: 2500
                repeat: false
                onTriggered: {
                    if (bgRoot.transitionPending)
                        bgRoot.cancelWallpaperTransition();
                }
            }

            NumberAnimation {
                id: wallpaperProgressAnimation
                target: bgRoot
                property: "transitionProgress"
                from: 1
                to: 0
                duration: bgRoot.wallpaperTransitionDuration
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Appearance.animationCurves.expressiveEffects
                onFinished: bgRoot.finishWallpaperTransition()
            }

            SequentialAnimation {
                id: wallpaperFadeAnimation
                NumberAnimation {
                    target: fadeCurtain
                    property: "opacity"
                    from: 0
                    to: 1
                    duration: Math.max(100, bgRoot.wallpaperTransitionDuration / 2)
                    easing.type: Easing.InOutCubic
                }
                ScriptAction {
                    script: {
                        bgRoot.transitionPreviousPath = "";
                        bgRoot.transitionNextPath = "";
                    }
                }
                NumberAnimation {
                    target: fadeCurtain
                    property: "opacity"
                    from: 1
                    to: 0
                    duration: Math.max(100, bgRoot.wallpaperTransitionDuration / 2)
                    easing.type: Easing.InOutCubic
                }
                ScriptAction { script: bgRoot.finishWallpaperTransition() }
            }

            Loader {
                id: blurLoader
                active: Config.options.lock.blur.enable && (GlobalStates.screenLocked || scaleAnim.running)
                anchors.fill: wallpaper
                scale: GlobalStates.screenLocked ? Config.options.lock.blur.extraZoom : 1
                Behavior on scale {
                    NumberAnimation {
                        id: scaleAnim
                        duration: 400
                        easing.type: Easing.BezierSpline
                        easing.bezierCurve: Appearance.animationCurves.expressiveDefaultSpatial
                    }
                }
                sourceComponent: GaussianBlur {
                    source: wallpaper
                    radius: GlobalStates.screenLocked ? Config.options.lock.blur.radius : 0
                    samples: radius * 2 + 1

                    Rectangle {
                        opacity: GlobalStates.screenLocked ? 1 : 0
                        anchors.fill: parent
                        color: CF.ColorUtils.transparentize(Appearance.colors.colLayer0, 0.7)
                    }
                }
            }

            WidgetCanvas {
                id: widgetCanvas
                width: parent.width
                height: parent.height
                readonly property real parallaxFactor: {
                    var f = Config.options.background.parallax.widgetsFactor;
                    return f / bgRoot.parallaxRation;
                }
                readonly property real baseWallpaperOffsetX: (bgRoot.screen.width - wallpaper.width) / 2
                readonly property real baseWallpaperOffsetY: (bgRoot.screen.height - wallpaper.height) / 2
                readonly property real wallpaperTotalOffsetX: wallpaper.x - baseWallpaperOffsetX
                readonly property real wallpaperTotalOffsetY: wallpaper.y - baseWallpaperOffsetY
                readonly property bool locked: GlobalStates.screenLocked
                x: wallpaperTotalOffsetX * parallaxFactor * !locked
                y: wallpaperTotalOffsetY * parallaxFactor * !locked

                transitions: Transition {
                    PropertyAnimation {
                        properties: "width,height"
                        duration: Appearance.animation.elementMove.duration
                        easing.type: Appearance.animation.elementMove.type
                        easing.bezierCurve: Appearance.animation.elementMove.bezierCurve
                    }
                    AnchorAnimation {
                        duration: Appearance.animation.elementMove.duration
                        easing.type: Appearance.animation.elementMove.type
                        easing.bezierCurve: Appearance.animation.elementMove.bezierCurve
                    }
                }

                FadeLoader {
                    shown: Config.options.background.widgets.weather.enable
                    sourceComponent: WeatherWidget {
                        screenWidth: bgRoot.screen.width
                        screenHeight: bgRoot.screen.height
                        scaledScreenWidth: bgRoot.screen.width
                        scaledScreenHeight: bgRoot.screen.height
                        wallpaperScale: 1
                    }
                }

                FadeLoader {
                    shown: Config.options.background.widgets.clock.enable
                    sourceComponent: ClockWidget {
                        screenWidth: bgRoot.screen.width
                        screenHeight: bgRoot.screen.height
                        scaledScreenWidth: bgRoot.screen.width
                        scaledScreenHeight: bgRoot.screen.height
                        wallpaperScale: 1
                        wallpaperSafetyTriggered: bgRoot.wallpaperSafetyTriggered
                    }
                }
            }
        }
    }
}
