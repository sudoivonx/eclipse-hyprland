import QtQuick
import qs.services

QuickToggleModel {
    id: root
    name: Translation.tr("Game mode")
    toggled: PulsarGameMode.active
    icon: "gamepad"

    mainAction: () => PulsarGameMode.toggleManual()
    tooltipText: Translation.tr("Game mode")
}
