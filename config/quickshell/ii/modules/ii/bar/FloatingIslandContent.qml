import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import Quickshell
import Quickshell.Services.Mpris
import qs
import qs.services
import qs.modules.common
import qs.modules.common.functions
import qs.modules.common.widgets

Item {
    id: root

    readonly property bool mediaPlaying:
        MprisController.activePlayer?.playbackState === MprisPlaybackState.Playing

    readonly property color islandAccent:
        ColorUtils.mix(Appearance.colors.colPrimary,
                       Appearance.colors.colSecondary, 0.52)

    readonly property real sidePadding: Config.options.bar.floatingIsland.sidePadding
    readonly property real sectionGap: Config.options.bar.floatingIsland.sectionGap

    implicitHeight: Appearance.sizes.barHeight

    // Un-animated center target width so barContent.width and centerGroup animate in 1:1 lockstep.
    readonly property real targetCenterWidth:
        root.mediaPlaying && Config.options.bar.floatingIsland.showMedia
            ? Math.min(280, mediaWidget.implicitWidth)
            : (Config.options.bar.floatingIsland.showClock
                ? clockWidget.implicitWidth : 0)

    // Symmetric side groups keep the clock at the true center.
    readonly property real preferredIslandWidth:
        Math.max(leftGroup.visible ? leftGroup.implicitWidth : 0,
                 rightGroup.visible ? rightGroup.implicitWidth : 0) * 2
        + (centerGroup.visible ? root.targetCenterWidth : 0)
        + sectionGap * 2
        + sidePadding * 2

    implicitWidth: preferredIslandWidth

    // Soft accent glow using shader SDF RectangularShadow (zero per-frame FBO reallocation).
    RectangularShadow {
        id: glow
        anchors.fill: capsule
        radius: capsule.radius
        blur: 14
        spread: 2
        offset: Qt.vector2d(0, 0)
        color: ColorUtils.transparentize(root.islandAccent, 0.42)
        opacity: Config.options.bar.floatingIsland.glowStrength / 100
        visible: Config.options.bar.showBackground
            && Config.options.bar.floatingIsland.glowEnabled
        cached: false
    }

    // The existing Matugen colors determine the glass tint.
    Rectangle {
        id: capsule
        anchors.fill: parent
        radius: height / 2

        color: Config.options.bar.showBackground
            && Config.options.bar.floatingIsland.glassEnabled
            ? ColorUtils.transparentize(
                ColorUtils.mix(
                    Appearance.colors.colLayer0Base,
                    root.islandAccent,
                    1 - Config.options.bar.floatingIsland.accentMix / 100
                ),
                1 - Config.options.bar.floatingIsland.glassOpacity / 100)
            : "transparent"

        border.width: Config.options.bar.showBackground
            && (Config.options.bar.floatingIsland.glassEnabled
                || Config.options.bar.floatingIsland.glowEnabled) ? 1 : 0
        border.color: ColorUtils.transparentize(
            root.islandAccent,
            1 - Config.options.bar.floatingIsland.accentMix / 100)
    }

    Item {
        id: contents
        anchors.fill: parent
        anchors.leftMargin: root.sidePadding
        anchors.rightMargin: root.sidePadding

        // LEFT: scroll the empty area beside workspaces to change brightness.
        FocusedScrollMouseArea {
            id: brightnessArea
            z: 0
            anchors {
                left: parent.left
                right: centerGroup.left
                top: parent.top
                bottom: parent.bottom
            }

            onScrollDown: {
                if (Config.options.bar.floatingIsland.scrollBrightness)
                    Brightness.decreaseBrightness()
            }
            onScrollUp: {
                if (Config.options.bar.floatingIsland.scrollBrightness)
                    Brightness.increaseBrightness()
            }
            onMovedAway: GlobalStates.osdBrightnessOpen = false
            onPressed: event => {
                if (event.button === Qt.LeftButton)
                    GlobalStates.sidebarLeftOpen = !GlobalStates.sidebarLeftOpen;
            }

            ScrollHint {
                reveal: brightnessArea.hovered
                icon: Hyprsunset.gamma === 100 ? "light_mode" : "wb_twilight"
                tooltipText: Translation.tr("Scroll to change brightness")
                side: "left"
                anchors.right: parent.right
                anchors.rightMargin: 5
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // LEFT: compact workspace indicators.
        RowLayout {
            id: leftGroup
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            spacing: 0
            visible: Config.options.bar.floatingIsland.showWorkspaces

            Workspaces {
                id: workspaces
                vertical: false
                workspaceButtonWidth: 20
                Layout.alignment: Qt.AlignVCenter
            }
        }

        // CENTER: clock when idle, media information during playback.
        Item {
            id: centerGroup
            visible: Config.options.bar.floatingIsland.showClock
                || (root.mediaPlaying && Config.options.bar.floatingIsland.showMedia)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            implicitHeight: Math.max(clockWidget.implicitHeight,
                                     mediaWidget.implicitHeight)
            implicitWidth: root.targetCenterWidth

            clip: true

            Behavior on implicitWidth {
                NumberAnimation {
                    duration: 280
                    easing.type: Easing.OutCubic
                }
            }

            ClockWidget {
                id: clockWidget
                anchors.centerIn: parent
                showDate: false
                opacity: (!root.mediaPlaying || !Config.options.bar.floatingIsland.showMedia)
                    && Config.options.bar.floatingIsland.showClock ? 1 : 0
                enabled: (!root.mediaPlaying || !Config.options.bar.floatingIsland.showMedia)
                    && Config.options.bar.floatingIsland.showClock

                Behavior on opacity {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
            }

            Media {
                id: mediaWidget
                anchors.centerIn: parent
                width: Math.min(280, implicitWidth)
                opacity: root.mediaPlaying && Config.options.bar.floatingIsland.showMedia ? 1 : 0
                enabled: root.mediaPlaying && Config.options.bar.floatingIsland.showMedia

                Behavior on opacity {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
            }
        }

        // RIGHT: scroll this area to change volume.
        FocusedScrollMouseArea {
            id: volumeArea
            z: 0
            anchors {
                left: centerGroup.right
                right: parent.right
                top: parent.top
                bottom: parent.bottom
            }

            onScrollDown: {
                if (Config.options.bar.floatingIsland.scrollVolume)
                    Audio.decrementVolume()
            }
            onScrollUp: {
                if (Config.options.bar.floatingIsland.scrollVolume)
                    Audio.incrementVolume()
            }
            onMovedAway: GlobalStates.osdVolumeOpen = false
            onPressed: event => {
                if (event.button === Qt.LeftButton)
                    GlobalStates.sidebarRightOpen = !GlobalStates.sidebarRightOpen;
            }

            ScrollHint {
                reveal: volumeArea.hovered
                icon: "volume_up"
                tooltipText: Translation.tr("Scroll to change volume")
                side: "right"
                anchors.left: parent.left
                anchors.leftMargin: 5
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // RIGHT: status icons and the NEXUS panel trigger.
        RowLayout {
            id: rightGroup
            visible: Config.options.bar.floatingIsland.showBattery
                || Config.options.bar.floatingIsland.showUtilityButtons
                || Config.options.bar.floatingIsland.showNexusButton
                || Config.options.bar.floatingIsland.showInfoButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: root.sectionGap

            BatteryIndicator {
                visible: Battery.available && Config.options.bar.floatingIsland.showBattery
                Layout.alignment: Qt.AlignVCenter
            }

            UtilButtons {
                id: floatingUtilityButtons
                visible: Config.options.bar.floatingIsland.showUtilityButtons
                Layout.alignment: Qt.AlignVCenter
            }

            RippleButton {
                id: infoButton
                visible: Config.options.bar.floatingIsland.showInfoButton
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: 34
                implicitHeight: 34
                buttonRadius: Appearance.rounding.full
                colBackground: ColorUtils.transparentize(Appearance.colors.colLayer1Hover, 1)
                colBackgroundHover: Appearance.colors.colLayer1Hover
                colRipple: Appearance.colors.colLayer1Active

                onPressed: {
                    Quickshell.execDetached([
                        "qs", "-p", Quickshell.shellPath(""),
                        "ipc", "call", "cheatsheet", "toggle"
                    ])
                }

                MaterialSymbol {
                    anchors.centerIn: parent
                    text: "info"
                    iconSize: 19
                    color: Appearance.colors.colOnLayer0
                }
            }

            RippleButton {
                id: nexusButton
                visible: Config.options.bar.floatingIsland.showNexusButton
                implicitWidth: 34
                implicitHeight: 34
                buttonRadius: Appearance.rounding.full
                colBackground: ColorUtils.transparentize(root.islandAccent, 0.72)
                colBackgroundHover: Appearance.colors.colPrimaryHover
                colRipple: Appearance.colors.colPrimaryActive
                colBackgroundToggled: Appearance.colors.colPrimaryContainer
                colBackgroundToggledHover: Appearance.colors.colPrimaryContainerHover
                colRippleToggled: Appearance.colors.colPrimaryContainerActive
                toggled: GlobalStates.sidebarRightOpen
                Layout.alignment: Qt.AlignVCenter

                onPressed: {
                    GlobalStates.sidebarRightOpen = !GlobalStates.sidebarRightOpen
                }

                MaterialSymbol {
                    anchors.centerIn: parent
                    text: "hub"
                    iconSize: 20
                    color: nexusButton.toggled
                        ? Appearance.colors.colOnPrimaryContainer
                        : Appearance.colors.colOnLayer0
                }
            }
        }
    }
}
