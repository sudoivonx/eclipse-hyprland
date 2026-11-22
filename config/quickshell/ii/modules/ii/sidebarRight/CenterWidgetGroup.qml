import qs.modules.common
import qs.modules.common.widgets
import qs.services
import qs.modules.ii.sidebarRight.notifications
import Qt5Compat.GraphicalEffects
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    radius: Appearance.rounding.normal
    color: Qt.rgba(Appearance.colors.colLayer1.r, Appearance.colors.colLayer1.g, Appearance.colors.colLayer1.b, 0.30)
    border.width: 1
    border.color: Qt.rgba(Appearance.colors.colLayer0Border.r, Appearance.colors.colLayer0Border.g, Appearance.colors.colLayer0Border.b, 0.42)

    NotificationList {
        anchors.fill: parent
        anchors.margins: 5
    }
}
