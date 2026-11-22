pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs
import qs.services
import qs.modules.common
import qs.modules.common.widgets

Scope {
    id: bar
    property bool showBarBackground: Config.options.bar.showBackground

    Variants {
        // For each monitor
        model: {
            const screens = Quickshell.screens;
            const list = Config.options.bar.screenList;
            if (!list || list.length === 0)
                return screens;
            return screens.filter(screen => list.includes(screen.name));
        }
        LazyLoader {
            id: barLoader
            active: GlobalStates.barOpen && !GlobalStates.screenLocked
            required property ShellScreen modelData
            component: PanelWindow { // Bar window
                id: barRoot
                screen: barLoader.modelData

                Timer {
                    id: hideBarTimer
                    interval: 1500
                    repeat: false
                    onTriggered: barRoot.hoverShow = false
                }

                Timer {
                    id: showBarTimer
                    interval: (Config?.options.bar.autoHide.showWhenPressingSuper.delay ?? 100)
                    repeat: false
                    onTriggered: {
                        barRoot.superShow = true
                    }
                }
                Connections {
                    target: GlobalStates
                    function onSuperDownChanged() {
                        if (!Config.options.bar.floatingIsland.autoHide || !Config?.options.bar.autoHide.showWhenPressingSuper.enable) return;
                        if (GlobalStates.superDown) showBarTimer.restart();
                        else {
                            showBarTimer.stop();
                            barRoot.superShow = false;
                        }
                    }
                }
                property bool superShow: false
                property bool hoverShow: false
                property bool mustShow: hoverShow || superShow
                exclusionMode: ExclusionMode.Ignore
                exclusiveZone: (Config.options.bar.floatingIsland.autoHide && (!mustShow || !Config?.options.bar.autoHide.pushWindows)) ? 0 :
                    Appearance.sizes.baseBarHeight + (Config.options.bar.cornerStyle === 1 ? Appearance.sizes.hyprlandGapsOut : 0)
                WlrLayershell.namespace: "quickshell:bar"
                implicitHeight: Appearance.sizes.barHeight + Appearance.rounding.screenRounding + (Config.options.bar.floatingIsland.autoHide ? Config.options.bar.floatingIsland.topMargin : 0)
                mask: Region {
                    item: hoverMaskRegion
                }
                color: "transparent"

                // Positioning
                anchors {
                    top: !Config.options.bar.bottom
                    bottom: Config.options.bar.bottom
                    left: true
                    right: true
                }

                // Keep the layer-shell surface horizontally stationary; hoverMaskRegion clips input.
                margins {
                    left: 0
                    right: 0
                    top: barRoot.anchors.bottom ? 0 : (Config.options.bar.floatingIsland.autoHide ? 0 : Config.options.bar.floatingIsland.topMargin)
                    bottom: barRoot.anchors.bottom ? (Config.options.bar.floatingIsland.autoHide ? 0 : Config.options.bar.floatingIsland.topMargin) : 0
                }

                // Include in focus grab
                Component.onCompleted: {
                    GlobalFocusGrab.addPersistent(barRoot);
                }
                Component.onDestruction: {
                    GlobalFocusGrab.removePersistent(barRoot);
                }

                MouseArea  {
                    id: hoverRegion
                    hoverEnabled: true
                    onEntered: {
                        hideBarTimer.stop()
                        barRoot.hoverShow = true
                    }
                    onExited: {
                        if (Config.options.bar.floatingIsland.autoHide)
                            hideBarTimer.restart()
                        else
                            barRoot.hoverShow = false
                    }
                    anchors {
                        fill: parent
                        rightMargin: (Config.options.interactions.deadPixelWorkaround.enable && barRoot.anchors.right) * 1
                        bottomMargin: (Config.options.interactions.deadPixelWorkaround.enable && barRoot.anchors.bottom) * 1
                    }

                    Item {
                        id: hoverMaskRegion
                        width: barContent.width
                        height: barContent.height
                            + 2 * Config.options.bar.autoHide.hoverRegionWidth
                        anchors {
                            horizontalCenter: parent.horizontalCenter
                            top: Config.options.bar.bottom ? undefined : parent.top
                            bottom: Config.options.bar.bottom ? parent.bottom : undefined
                            topMargin: Config.options.bar.bottom ? 0
                                : Math.max(0, Config.options.bar.floatingIsland.topMargin
                                    - Config.options.bar.autoHide.hoverRegionWidth)
                            bottomMargin: Config.options.bar.bottom
                                ? Math.max(0, Config.options.bar.floatingIsland.topMargin
                                    - Config.options.bar.autoHide.hoverRegionWidth)
                                : 0
                        }
                    }

                    FloatingIslandContent {
                        id: barContent
                        
                        implicitHeight: Appearance.sizes.barHeight

                        // Soft floating-island entrance and exit.
                        opacity: (!Config.options.bar.floatingIsland.autoHide || mustShow) ? 1.0 : 0.82
                        scale: (!Config.options.bar.floatingIsland.autoHide || mustShow) ? 1.0 : 0.97
                        transformOrigin: Config.options.bar.bottom ? Item.Bottom : Item.Top

                        Behavior on opacity {
                            NumberAnimation {
                                duration: 260
                                easing.type: Easing.OutCubic
                            }
                        }
                        Behavior on scale {
                            NumberAnimation {
                                duration: 420
                                easing.type: Easing.OutCubic
                            }
                        }
                        // Fluid width: fit the visible modules, driven directly by un-animated target width.
                        readonly property real targetIslandWidth: Math.max(320, Math.min(
                            barRoot.screen.width - 24,
                            Config.options.bar.floatingIsland.maxWidth,
                            (Config.options.bar.floatingIsland.dynamicWidth
                                ? Math.max(360, barContent.preferredIslandWidth)
                                : Config.options.bar.floatingIsland.fixedWidth)
                                + Config.options.bar.floatingIsland.extraWidth))
                        width: targetIslandWidth
                        Behavior on width {
                            NumberAnimation {
                                duration: 280
                                easing.type: Easing.OutCubic
                            }
                        }
                        anchors {
                            horizontalCenter: parent.horizontalCenter
                            top: parent.top
                            bottom: undefined
                            topMargin: (Config.options.bar.floatingIsland.autoHide && !mustShow) ? (Config.options.bar.autoHide.hoverRegionWidth - Appearance.sizes.barHeight) : Config.options.bar.floatingIsland.topMargin
                            bottomMargin: (Config.options.interactions.deadPixelWorkaround.enable && barRoot.anchors.bottom) * -1
                            rightMargin: (Config.options.interactions.deadPixelWorkaround.enable && barRoot.anchors.right) * -1
                        }
                        Behavior on anchors.topMargin {
                            NumberAnimation {
                                duration: 460
                                easing.type: Easing.OutCubic
                            }
                        }
                        Behavior on anchors.bottomMargin {
                            NumberAnimation {
                                duration: 460
                                easing.type: Easing.OutCubic
                            }
                        }

                        states: State {
                            name: "bottom"
                            when: Config.options.bar.bottom
                            AnchorChanges {
                                target: barContent
                                anchors {
                                    horizontalCenter: parent.horizontalCenter
                                    top: undefined
                                    bottom: parent.bottom
                                }
                            }
                            PropertyChanges {
                                barContent.anchors.topMargin: 0
                                barContent.anchors.bottomMargin: (Config.options.bar.floatingIsland.autoHide && !mustShow) ? (Config.options.bar.autoHide.hoverRegionWidth - Appearance.sizes.barHeight) : Config.options.bar.floatingIsland.topMargin
                            }
                        }
                    }

                    // Round decorators
                    Loader {
                        id: roundDecorators
                        anchors {
                            left: parent.left
                            right: parent.right
                            top: barContent.bottom
                            bottom: undefined
                        }
                        height: Appearance.rounding.screenRounding
                        active: false // The floating capsule draws its own rounded silhouette.

                        states: State {
                            name: "bottom"
                            when: Config.options.bar.bottom
                            AnchorChanges {
                                target: roundDecorators
                                anchors {
                                    right: parent.right
                                    left: parent.left
                                    top: undefined
                                    bottom: barContent.top
                                }
                            }
                        }

                        sourceComponent: Item {
                            implicitHeight: Appearance.rounding.screenRounding
                            RoundCorner {
                                id: leftCorner
                                anchors {
                                    top: parent.top
                                    bottom: parent.bottom
                                    left: parent.left
                                }

                                implicitSize: Appearance.rounding.screenRounding
                                color: showBarBackground ? Appearance.colors.colLayer0 : "transparent"

                                corner: RoundCorner.CornerEnum.TopLeft
                                states: State {
                                    name: "bottom"
                                    when: Config.options.bar.bottom
                                    PropertyChanges {
                                        leftCorner.corner: RoundCorner.CornerEnum.BottomLeft
                                    }
                                }
                            }
                            RoundCorner {
                                id: rightCorner
                                anchors {
                                    right: parent.right
                                    top: !Config.options.bar.bottom ? parent.top : undefined
                                    bottom: Config.options.bar.bottom ? parent.bottom : undefined
                                }
                                implicitSize: Appearance.rounding.screenRounding
                                color: showBarBackground ? Appearance.colors.colLayer0 : "transparent"

                                corner: RoundCorner.CornerEnum.TopRight
                                states: State {
                                    name: "bottom"
                                    when: Config.options.bar.bottom
                                    PropertyChanges {
                                        rightCorner.corner: RoundCorner.CornerEnum.BottomRight
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    IpcHandler {
        target: "bar"

        function toggle(): void {
            GlobalStates.barOpen = !GlobalStates.barOpen
        }

        function close(): void {
            GlobalStates.barOpen = false
        }

        function open(): void {
            GlobalStates.barOpen = true
        }
    }

    GlobalShortcut {
        name: "barToggle"
        description: "Toggles bar on press"

        onPressed: {
            GlobalStates.barOpen = !GlobalStates.barOpen;
        }
    }

    GlobalShortcut {
        name: "barOpen"
        description: "Opens bar on press"

        onPressed: {
            GlobalStates.barOpen = true;
        }
    }

    GlobalShortcut {
        name: "barClose"
        description: "Closes bar on press"

        onPressed: {
            GlobalStates.barOpen = false;
        }
    }
}
