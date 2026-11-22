import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions as CF

ContentPage {
    id: root

    forceWidth: true
    baseWidth: width
    bottomContentPadding: 12

    property var settingsRoot: null
    property var pageData: null
    property real interactionsHeight: 0
    property bool hasInteractions: false
    readonly property var inputPageData: {
        if (root.pageData)
            return root.pageData;
        const pages = root.settingsRoot ? root.settingsRoot.pages : null;
        if (!pages || typeof pages.length !== "number")
            return null;
        for (let i = 0; i < pages.length; ++i) {
            const p = pages[i];
            if (p && String(p.categoryId || "").toLocaleLowerCase() === "input")
                return p;
        }
        return null;
    }
    onSettingsRootChanged: inputInteractionsLoader.syncProps()
    onInputPageDataChanged: inputInteractionsLoader.syncProps()
    property string managerPath: CF.FileUtils.trimFileProtocol(Directories.config) + "/quickshell/ii/modules/settings/nexus-settings.py"
    property var themes: []
    property string currentTheme: ""
    property string draftTheme: ""
    property int currentSize: 24
    property int draftSize: 24
    property bool stateReady: false
    property bool busy: false
    property string operation: ""
    property string statusMessage: ""
    property bool keepStatusOnNextRefresh: false
    property int baselineCheckCount: 0
    property bool conflictRepairAvailable: false

    function refreshStatus(keepMessage) {
        if (root.busy)
            return;
        root.busy = true;
        root.operation = "status";
        root.keepStatusOnNextRefresh = keepMessage === true;
        if (!root.keepStatusOnNextRefresh)
            root.statusMessage = Translation.tr("Reading saved cursor settings…");
        managerProcess.exec(["python3", root.managerPath, "cursor-status"]);
    }

    function applyDraft() {
        if (!root.stateReady || root.busy || (root.settingsRoot && root.settingsRoot.nexusActionBusy) || root.themes.indexOf(root.draftTheme) < 0)
            return;
        if (root.draftSize < 8 || root.draftSize > 128) {
            root.statusMessage = Translation.tr("Choose a cursor size from 8 to 128.");
            return;
        }
        if (root.settingsRoot && !root.settingsRoot.hasInitialValue({ sourceKind: "cursor-adapter", path: "cursor.theme" })) {
            root.busy = true;
            root.operation = "initialize";
            root.statusMessage = Translation.tr("Saving the current cursor values as the starting point…");
            root.settingsRoot.nexusActionBusy = true;
            managerProcess.exec(["python3", root.managerPath, "initialize"]);
            return;
        }
        root.startApply();
    }

    function startApply() {
        if (root.settingsRoot && !root.settingsRoot.hasInitialValue({ sourceKind: "cursor-adapter", path: "cursor.theme" })) {
            root.statusMessage = Translation.tr("Starting cursor values are not available, so no change was made.");
            root.busy = false;
            if (root.settingsRoot)
                root.settingsRoot.nexusActionBusy = false;
            return;
        }
        root.busy = true;
        root.operation = "apply";
        root.statusMessage = Translation.tr("Saving cursor settings…");
        if (root.settingsRoot)
            root.settingsRoot.nexusActionBusy = true;
        managerProcess.exec(["python3", root.managerPath, "cursor-set", root.draftTheme, String(root.draftSize)]);
    }

    function reconcileFromCanonical() {
        if (!root.conflictRepairAvailable || root.busy || (root.settingsRoot && root.settingsRoot.nexusActionBusy))
            return;
        root.busy = true;
        root.operation = "reconcile";
        root.statusMessage = Translation.tr("Synchronizing GTK cursor files from environment.d + Hyprland…");
        if (root.settingsRoot)
            root.settingsRoot.nexusActionBusy = true;
        managerProcess.exec([
            "python3", root.managerPath, "cursor-reconcile",
            "--source", "environment.d+hyprland", "--confirm-risk"
        ]);
    }

    function handleResult(exitCode) {
        root.busy = false;
        if ((root.operation === "apply" || root.operation === "initialize" || root.operation === "reconcile") && root.settingsRoot)
            root.settingsRoot.nexusActionBusy = false;
        let response = null;
        try {
            response = JSON.parse(managerOutput.text);
        } catch (error) {
            root.statusMessage = Translation.tr("NEXUS could not read the result. No change was assumed.");
            return;
        }
        if (root.operation === "status" && response.status === "conflict") {
            root.stateReady = false;
            root.conflictRepairAvailable = response.reconciliationAvailable === true;
            root.statusMessage = response.message || Translation.tr("Cursor settings disagree. No values were changed.");
            return;
        }
        if (exitCode !== 0 || response.status === "error") {
            root.statusMessage = response.message || Translation.tr("The cursor settings could not be updated safely.");
            root.keepStatusOnNextRefresh = false;
            if (root.operation === "apply" || root.operation === "reconcile")
                root.refreshStatus(true);
            if (root.settingsRoot)
                root.settingsRoot.refreshCursorStatus();
            return;
        }
        if (root.operation === "initialize") {
            if (response.status !== "baseline_captured" && response.status !== "baseline_exists") {
                root.statusMessage = Translation.tr("Starting cursor values could not be saved. No cursor change was made.");
                if (root.settingsRoot)
                    root.settingsRoot.nexusActionBusy = false;
                return;
            }
            root.statusMessage = Translation.tr("Checking the saved starting cursor values…");
            if (root.settingsRoot) {
                root.settingsRoot.nexusActionBusy = true;
                root.settingsRoot.reloadInitialState();
            }
            root.baselineCheckCount = 0;
            baselineWaitTimer.start();
            return;
        }
        if (root.operation === "status") {
            root.themes = response.themes || [];
            root.currentTheme = response.current.theme;
            root.currentSize = response.current.size;
            root.draftTheme = root.currentTheme;
            root.draftSize = root.currentSize;
            root.stateReady = true;
            if (!root.keepStatusOnNextRefresh) {
                root.statusMessage = root.themes.length > 0
                    ? Translation.tr("Saved cursor settings are ready.")
                    : Translation.tr("No complete cursor themes were found in the installed theme folders.");
            }
            root.keepStatusOnNextRefresh = false;
            if (root.settingsRoot)
                root.settingsRoot.acceptCursorStatus(response);
        } else if (response.status === "written_to_config") {
            root.conflictRepairAvailable = false;
            root.statusMessage = root.operation === "reconcile"
                ? Translation.tr("GTK settings now match environment.d + Hyprland. Live application has not been verified; no session reload was issued.")
                : Translation.tr("Saved to settings. Live application has not yet been verified; reopen apps or start a new session when needed.");
            root.refreshStatus(true);
            if (root.settingsRoot)
                root.settingsRoot.refreshCursorStatus();
        } else if (response.status === "no_changes") {
            root.statusMessage = Translation.tr("These cursor settings are already saved.");
        } else {
            root.statusMessage = Translation.tr("The action completed without live runtime verification.");
        }
    }

    Component.onCompleted: root.refreshStatus()

    ColumnLayout {
        Layout.fillWidth: true
        Layout.margins: 14
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Rectangle {
                Layout.preferredWidth: 42
                Layout.preferredHeight: 42
                radius: Appearance.rounding.small
                color: Appearance.colors.colLayer1Base
                MaterialSymbol {
                    anchors.centerIn: parent
                    text: "mouse"
                    iconSize: 22
                    color: Appearance.colors.colPrimary
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                StyledText {
                    text: Translation.tr("Cursor")
                    font.pixelSize: Appearance.font.pixelSize.large
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnLayer0
                }
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Choose an installed pointer theme and size. NEXUS saves the preference and synchronizes the supported desktop settings.")
                    color: Appearance.colors.colSubtext
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 126
            radius: Appearance.rounding.normal
            color: Appearance.m3colors.m3surfaceContainerLow

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                StyledText {
                    text: Translation.tr("Cursor theme")
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnLayer0
                }
                StyledComboBox {
                    id: themeSelector
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    buttonIcon: "mouse"
                    textRole: "displayName"
                    Accessible.name: Translation.tr("Installed cursor theme")
                    model: root.themes.map(theme => ({ displayName: theme, value: theme }))
                    currentIndex: {
                        const index = model.findIndex(item => item.value === root.draftTheme);
                        return index >= 0 ? index : 0;
                    }
                    enabled: root.stateReady && !root.busy && !(root.settingsRoot && root.settingsRoot.nexusActionBusy) && root.themes.length > 0
                    onActivated: index => {
                        if (index >= 0 && index < model.length)
                            root.draftTheme = model[index].value;
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    text: root.currentTheme.length > 0
                        ? Translation.tr("Currently saved: ") + root.currentTheme
                        : Translation.tr("Theme options are discovered from installed cursor themes.")
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colSubtext
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 114
            radius: Appearance.rounding.normal
            color: Appearance.m3colors.m3surfaceContainerLow

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                StyledText {
                    text: Translation.tr("Cursor size")
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnLayer0
                }
                ConfigSpinBox {
                    id: cursorSizeSelector
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    text: Translation.tr("Size in pixels")
                    icon: "format_size"
                    from: 8
                    to: 128
                    stepSize: 1
                    value: root.draftSize
                    enabled: root.stateReady && !root.busy && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
                    Accessible.name: Translation.tr("Cursor size from 8 to 128")
                    onValueChanged: root.draftSize = value
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            RippleButton {
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                buttonRadius: Appearance.rounding.small
                enabled: root.stateReady && !root.busy && !(root.settingsRoot && root.settingsRoot.nexusActionBusy) && root.themes.indexOf(root.draftTheme) >= 0
                colBackground: Appearance.colors.colPrimary
                colBackgroundHover: Appearance.colors.colPrimaryHover
                Accessible.name: Translation.tr("Apply cursor theme and size")
                onClicked: root.applyDraft()
                contentItem: StyledText {
                    text: Translation.tr("Apply cursor settings")
                    color: Appearance.colors.colOnPrimary
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.weight: Font.DemiBold
                }
            }
            RippleButton {
                Layout.preferredWidth: 48
                Layout.preferredHeight: 46
                buttonRadius: Appearance.rounding.small
                enabled: !root.busy
                Accessible.name: Translation.tr("Refresh installed cursor themes")
                onClicked: root.refreshStatus()
                contentItem: MaterialSymbol {
                    anchors.centerIn: parent
                    text: "refresh"
                    iconSize: 19
                    color: Appearance.colors.colOnLayer1
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            text: root.statusMessage
            color: root.statusMessage.toLowerCase().indexOf("could not") >= 0 || root.statusMessage.toLowerCase().indexOf("failed") >= 0
                ? Appearance.colors.colError : Appearance.colors.colSubtext
            font.pixelSize: Appearance.font.pixelSize.small
            wrapMode: Text.WordWrap
        }

        Rectangle {
            Layout.fillWidth: true
            visible: root.conflictRepairAvailable
            implicitHeight: conflictRepairLayout.implicitHeight + 24
            radius: Appearance.rounding.small
            color: Appearance.colors.colLayer1Base

            ColumnLayout {
                id: conflictRepairLayout
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("The GTK cursor mirrors disagree. You selected environment.d + Hyprland as the source; the repair updates only GTK3 and GTK4 files and keeps a recoverable undo record.")
                    color: Appearance.colors.colSubtext
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    wrapMode: Text.WordWrap
                }

                RippleButton {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    enabled: root.conflictRepairAvailable && !root.busy && !(root.settingsRoot && root.settingsRoot.nexusActionBusy)
                    buttonRadius: Appearance.rounding.small
                    colBackground: Appearance.colors.colLayer1Base
                    colBackgroundHover: Appearance.colors.colLayer1Hover
                    onClicked: cursorReconcileDialog.open()
                    contentItem: StyledText {
                        text: Translation.tr("Align GTK cursor settings")
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 74
            radius: Appearance.rounding.small
            color: Appearance.colors.colLayer1Base
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 9
                MaterialSymbol {
                    text: "info"
                    iconSize: 18
                    color: Appearance.colors.colPrimary
                }
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("NEXUS saves the preference but does not verify live application. Reopen affected apps; programs that inherit session variables may need a new login session.")
                    color: Appearance.colors.colSubtext
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    wrapMode: Text.WordWrap
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            visible: root.settingsRoot && !root.settingsRoot.hasInitialValue({ sourceKind: "cursor-adapter", path: "cursor.theme" })
            text: Translation.tr("The current cursor values will be saved as the starting point before the first change.")
            color: Appearance.colors.colSubtext
            font.pixelSize: Appearance.font.pixelSize.smaller
            wrapMode: Text.WordWrap
        }

        Loader {
            id: inputInteractionsLoader
            Layout.fillWidth: true
            Layout.preferredHeight: root.interactionsHeight
            visible: root.hasInteractions
            active: root.inputPageData !== null
            source: Qt.resolvedUrl("DynamicCategoryConfig.qml")

            function syncProps() {
                const dyn = inputInteractionsLoader.item;
                if (!dyn) {
                    root.interactionsHeight = 0;
                    root.hasInteractions = false;
                    return;
                }
                dyn["embedded"] = true;
                dyn["settingsRoot"] = root.settingsRoot;
                dyn["pageData"] = root.inputPageData;
                root.interactionsHeight = Qt.binding(function() { return dyn["contentHeight"] || 0; });
                root.hasInteractions = Qt.binding(function() {
                    const subs = dyn["renderedSubcategories"];
                    return Boolean(subs && subs.length > 0);
                });
            }

            onLoaded: syncProps()
        }

    }

    Process {
        id: managerProcess
        stdout: StdioCollector {
            id: managerOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => root.handleResult(exitCode)
    }

    Dialog {
        id: cursorReconcileDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        title: Translation.tr("Align cursor mirrors")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: root.reconcileFromCanonical()
        contentItem: StyledText {
            width: 420
            text: Translation.tr("Update GTK3 and GTK4 cursor settings to match the selected environment.d + Hyprland values? NEXUS will save an undo record. The live cursor effect will not be reloaded or assumed successful.")
            color: Appearance.colors.colOnLayer1
            wrapMode: Text.WordWrap
        }
    }

    Timer {
        id: baselineWaitTimer
        interval: 100
        repeat: true
        onTriggered: {
            if (root.settingsRoot && root.settingsRoot.hasInitialValue({ sourceKind: "cursor-adapter", path: "cursor.theme" })) {
                baselineWaitTimer.stop();
                root.startApply();
                return;
            }
            root.baselineCheckCount += 1;
            if (root.baselineCheckCount >= 30) {
                baselineWaitTimer.stop();
                root.statusMessage = Translation.tr("Saved starting cursor values could not be confirmed. No cursor change was made.");
                if (root.settingsRoot)
                    root.settingsRoot.nexusActionBusy = false;
            }
        }
    }
}
