import QtQuick

Loader {
    id: root
    anchors.fill: parent
    property var settingsRoot: null

    function loadSettingsPage() {
        setSource(Qt.resolvedUrl("AdvancedConfig.qml"), {
            "sectionFilter": "audio",
            "settingsRoot": settingsRoot
        });
    }

    Component.onCompleted: loadSettingsPage()
    onSettingsRootChanged: {
        if (item)
            item.settingsRoot = settingsRoot;
    }
}
