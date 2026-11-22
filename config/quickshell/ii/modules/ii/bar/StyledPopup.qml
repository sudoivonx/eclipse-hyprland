import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions
import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland

LazyLoader {
    id: root

    property Item hoverTarget
    default property Item contentItem
    property real popupBackgroundMargin: 0
    property real popupContentPadding: 10
    property real popupBackgroundOpacity: 1
    property real targetContentHeight: -1
    property string popupLayerNamespace: "quickshell:popup"
    property bool contentHoverTracking: false
    property bool contentHovered: false
    property bool animated: false
    property int popupOpenDelay: 0
    property int popupCloseDelay: 280
    property bool hoverOpened: false
    property bool closing: false
    property Timer openTimer: Timer {
        interval: root.popupOpenDelay
        repeat: false
        running: root.popupOpenDelay > 0 && !!root.hoverTarget && root.hoverTarget.containsMouse && !root.hoverOpened
        onTriggered: {
            if (root.hoverTarget?.containsMouse)
                root.hoverOpened = true;
        }
    }
    property Timer closeTimer: Timer {
        interval: root.popupCloseDelay
        repeat: false
        running: root.popupCloseDelay > 0 && root.hoverOpened && !!root.hoverTarget && !root.hoverTarget.containsMouse && !(root.contentHoverTracking && root.contentHovered)
        onTriggered: {
            root.hoverOpened = false;
            if (root.animated) {
                root.closing = true;
                root.closeAnimationTimer.restart();
            }
        }
    }
    property Timer closeAnimationTimer: Timer {
        interval: 170
        repeat: false
        onTriggered: root.closing = false
    }
    property Connections hoverTargetConnections: Connections {
        target: root.hoverTarget
        enabled: root.contentHoverTracking && !!root.hoverTarget
        function onContainsMouseChanged() {
            if (root.hoverTarget?.containsMouse) {
                const alreadyOpen = root.hoverOpened || root.contentHovered || root.closeTimer.running || root.closing;
                root.closeAnimationTimer.stop();
                root.closing = false;
                if (alreadyOpen || root.popupOpenDelay <= 0)
                    root.hoverOpened = true;
                else
                    root.hoverOpened = false;
            }
        }
    }

    // Load the popup as soon as the pointer enters so the open timer can run;
    // the panel itself stays hidden until the configured delay has elapsed.
    active: hoverTarget && (
        hoverTarget.containsMouse
        || (contentHoverTracking && (contentHovered || root.closeTimer.running || (root.animated && root.closing)))
    )

    onContentHoveredChanged: {
        if (!root.contentHoverTracking) return;
        if (root.contentHovered) {
            root.closeAnimationTimer.stop();
            root.closing = false;
        }
    }

    component: PanelWindow {
        id: popupWindow
        color: "transparent"
        visible: root.popupOpenDelay <= 0 || root.hoverOpened || root.contentHovered || root.closeTimer.running || root.closing
        screen: root.hoverTarget?.QsWindow?.window?.screen ?? root.QsWindow?.window?.screen ?? null
        property bool popupShown: false

        Timer {
            interval: 1
            running: true
            onTriggered: popupWindow.popupShown = true
        }

        anchors.left: !Config.options.bar.vertical || (Config.options.bar.vertical && !Config.options.bar.bottom)
        anchors.right: Config.options.bar.vertical && Config.options.bar.bottom
        anchors.top: Config.options.bar.vertical || (!Config.options.bar.vertical && !Config.options.bar.bottom)
        anchors.bottom: !Config.options.bar.vertical && Config.options.bar.bottom

        readonly property real effectiveContentHeight: root.targetContentHeight >= 0
            ? Math.max(root.targetContentHeight, root.contentItem.implicitHeight)
            : root.contentItem.implicitHeight
        implicitWidth: popupBackground.implicitWidth + Appearance.sizes.elevationMargin * 2 + root.popupBackgroundMargin
        implicitHeight: effectiveContentHeight + root.popupContentPadding * 2 + Appearance.sizes.elevationMargin * 2 + root.popupBackgroundMargin

        mask: Region {
            item: popupBackground
        }

        exclusionMode: ExclusionMode.Ignore
        exclusiveZone: 0
        margins {
            left: {
                if (Config.options.bar.vertical) return Appearance.sizes.verticalBarWidth;
                const target = root.hoverTarget;
                const hostWindow = target?.QsWindow?.window;
                const screen = popupWindow.screen;
                if (!target || !screen || !hostWindow) return 0;
                const hostScreen = hostWindow.screen;
                const hostContent = hostWindow.contentItem;
                if (!hostScreen || !hostContent) return 0;
                // Map through the bar's scene, then add its layer-shell output inset.
                const contentX = target.mapToItem(
                    hostContent,
                    (target.width - popupWindow.implicitWidth) / 2,
                    target.height
                ).x;
                const targetX = hostScreen.x + (hostWindow.margins?.left ?? 0) + contentX - screen.x;
                const maxX = Math.max(0, screen.width - popupWindow.implicitWidth);
                return Math.max(0, Math.min(targetX, maxX));
            }
            top: {
                if (!Config.options.bar.vertical) return Appearance.sizes.barHeight;
                const target = root.hoverTarget;
                const hostWindow = target?.QsWindow?.window;
                const screen = popupWindow.screen;
                if (!target || !screen || !hostWindow) return 0;
                const hostScreen = hostWindow.screen;
                const hostContent = hostWindow.contentItem;
                if (!hostScreen || !hostContent) return 0;
                const contentY = target.mapToItem(
                    hostContent,
                    0,
                    (target.height - popupWindow.implicitHeight) / 2
                ).y;
                const targetY = hostScreen.y + (hostWindow.margins?.top ?? 0) + contentY - screen.y;
                const maxY = Math.max(0, screen.height - popupWindow.implicitHeight);
                return Math.max(0, Math.min(targetY, maxY));
            }
            right: Appearance.sizes.verticalBarWidth
            bottom: Appearance.sizes.barHeight
        }
        WlrLayershell.namespace: root.popupLayerNamespace
        WlrLayershell.layer: WlrLayer.Overlay

        StyledRectangularShadow {
            target: popupBackground
        }

        Rectangle {
            id: popupBackground
            readonly property real margin: root.popupContentPadding
            anchors {
                left: parent.left
                right: parent.right
                top: !popupWindow.anchors.bottom ? parent.top : undefined
                bottom: popupWindow.anchors.bottom ? parent.bottom : undefined
                leftMargin: Appearance.sizes.elevationMargin + root.popupBackgroundMargin * (!popupWindow.anchors.left)
                rightMargin: Appearance.sizes.elevationMargin + root.popupBackgroundMargin * (!popupWindow.anchors.right)
                topMargin: Appearance.sizes.elevationMargin + root.popupBackgroundMargin * (!popupWindow.anchors.top)
                bottomMargin: Appearance.sizes.elevationMargin + root.popupBackgroundMargin * (!popupWindow.anchors.bottom)
            }
            implicitWidth: root.contentItem.implicitWidth + margin * 2
            implicitHeight: root.contentItem.implicitHeight + margin * 2
            height: implicitHeight
            color: ColorUtils.applyAlpha(Appearance.m3colors.m3surfaceContainer, root.popupBackgroundOpacity)
            radius: Appearance.rounding.small
            children: [root.contentItem]

            border.width: 1
            border.color: ColorUtils.transparentize(Appearance.colors.colLayer0Border, 0.35)
            opacity: root.animated ? (root.closing ? 0 : popupWindow.popupShown ? 1 : 0) : 1
            scale: root.animated ? (root.closing ? 0.985 : popupWindow.popupShown ? 1 : 0.97) : 1

            Behavior on opacity {
                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
            }
            Behavior on scale {
                NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
            }
        }
    }
}
