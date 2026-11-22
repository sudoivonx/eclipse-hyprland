import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions as CF

Item {
    id: root

    property string profileName: ""
    property string statusMessage: ""
    property bool busy: false
    property var profiles: []
    property var backups: []
    property string managerAction: ""
    property string pendingProfile: ""
    property string pendingBackupId: ""
    property string pendingOperation: ""
    property string selectedBackupId: ""
    property string verifiedBackupId: ""
    property var restorePreview: null
    property bool pendingRequiresConfirmation: false
    property bool pendingRequiresHyprlandReload: false
    property var settingsRoot: null
    property string managerPath: CF.FileUtils.trimFileProtocol(Directories.config) + "/quickshell/ii/modules/settings/nexus-settings.py"

    function runManager(args) {
        if (root.busy)
            return;
        root.managerAction = args[0] === "--dry-run" ? "backup-preview" : args[0];
        root.busy = true;
        root.statusMessage = Translation.tr("Working…");
        managerProcess.exec(["python3", root.managerPath].concat(args));
    }

    function refreshProfiles() {
        root.runManager(["profile-list"]);
    }

    function refreshBackups() {
        root.selectedBackupId = "";
        root.verifiedBackupId = "";
        root.restorePreview = null;
        root.runManager(["backup-list"]);
    }

    function verifyBackup(backupId) {
        root.selectedBackupId = backupId;
        root.verifiedBackupId = "";
        root.restorePreview = null;
        root.runManager(["backup-verify", backupId]);
    }

    function previewBackupRestore(backupId) {
        if (root.verifiedBackupId !== backupId)
            return;
        root.restorePreview = null;
        root.runManager(["--dry-run", "backup-restore", backupId]);
    }

    function requestBackupRestore(backupId) {
        if (root.busy || root.selectedBackupId !== backupId || root.verifiedBackupId !== backupId || !root.restorePreview || root.restorePreview.backupId !== backupId)
            return;
        root.pendingOperation = "backup-restore";
        root.pendingBackupId = backupId;
        confirmDialog.open();
    }

    function requestProfileAction(operation, name, requiresConfirmation, requiresHyprlandReload) {
        root.pendingOperation = operation;
        root.pendingProfile = name;
        root.pendingRequiresConfirmation = requiresConfirmation === true;
        root.pendingRequiresHyprlandReload = requiresHyprlandReload === true;
        confirmDialog.open();
    }

    function handleResult(exitCode) {
        root.busy = false;
        const action = root.managerAction;
        root.managerAction = "";
        let response = null;
        try {
            response = JSON.parse(managerOutput.text);
        } catch (error) {
            root.statusMessage = Translation.tr("NEXUS could not read the action result. No success was assumed.");
            return;
        }
        if (exitCode !== 0 || response.status === "error") {
            if (action === "backup-verify" || action === "backup-preview") {
                root.verifiedBackupId = "";
                root.restorePreview = null;
            }
            root.statusMessage = response.message || Translation.tr("The action failed safely.");
            return;
        }
        if (action === "backup-list") {
            root.backups = response.backups || [];
            root.statusMessage = root.backups.length === 0 ? Translation.tr("No backups are available.") : Translation.tr("Backups refreshed.");
            return;
        }
        if (action === "backup-verify") {
            if (response.status !== "verified") {
                root.verifiedBackupId = "";
                root.statusMessage = Translation.tr("This backup could not be verified.");
                return;
            }
            root.verifiedBackupId = response.backupId;
            root.statusMessage = Translation.tr("Backup verified. Preparing a read-only restore preview.");
            Qt.callLater(function() { root.previewBackupRestore(response.backupId); });
            return;
        }
        if (action === "backup-preview") {
            if (response.status !== "dry_run" || response.backupId !== root.verifiedBackupId) {
                root.verifiedBackupId = "";
                root.restorePreview = null;
                root.statusMessage = Translation.tr("A safe restore preview could not be prepared.");
                return;
            }
            root.restorePreview = response;
            root.statusMessage = Translation.tr("Preview ready: %1 added, %2 replaced, %3 removed.").arg(response.addedCount).arg(response.replacedCount).arg(response.removedCount);
            return;
        }
        if (action === "backup-restore") {
            if (response.status !== "restored") {
                root.statusMessage = Translation.tr("The backup restore did not complete.");
                return;
            }
            root.statusMessage = Translation.tr("Configuration restored. Safety backup: %1. Reopen affected applications if they do not reflect the restored files.").arg(response.safetyBackupId);
            if (root.settingsRoot) {
                root.settingsRoot.refreshCatalogState();
                root.settingsRoot.refreshAppsCatalog();
                root.settingsRoot.refreshHyprlandOptionsStatus();
                root.settingsRoot.reloadInitialState();
            }
            Qt.callLater(root.refreshBackups);
            return;
        }
        if (response.status === "ok") {
            root.profiles = response.profiles || [];
            root.statusMessage = root.profiles.length === 0 ? Translation.tr("No saved profiles yet.") : Translation.tr("Profiles refreshed.");
            Qt.callLater(root.refreshBackups);
        } else if (response.status === "profile_saved") {
            root.statusMessage = Translation.tr("Profile saved.");
            Qt.callLater(root.refreshProfiles);
        } else if (response.status === "profile_copied") {
            root.statusMessage = Translation.tr("Profile copied.");
            Qt.callLater(root.refreshProfiles);
        } else if (response.status === "profile_deleted") {
            root.statusMessage = Translation.tr("Profile deleted.");
            Qt.callLater(root.refreshProfiles);
        } else if (response.runtimeVerified === true) {
            root.statusMessage = Translation.tr("Supported Hyprland values were saved and verified live.");
            Qt.callLater(root.refreshProfiles);
        } else if (response.status === "written_to_config" || response.status === "undo_written_to_config") {
            root.statusMessage = Translation.tr("The configuration file was updated. Quickshell and any related runtime effects have not yet been independently verified.");
            Qt.callLater(root.refreshProfiles);
        } else if (response.status === "no_changes") {
            root.statusMessage = Translation.tr("These settings already match the saved starting values.");
        } else {
            root.statusMessage = Translation.tr("Action completed without a live runtime verification.");
        }
        if (root.settingsRoot) {
            if (action !== "profile-list" && action !== "backup-list") {
                root.settingsRoot.refreshCatalogState();
                root.settingsRoot.refreshAppsCatalog();
            }
            root.settingsRoot.refreshHyprlandOptionsStatus();
            root.settingsRoot.reloadInitialState();
        }
    }

    Component.onCompleted: root.refreshProfiles()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Rectangle {
                Layout.preferredWidth: 42
                Layout.preferredHeight: 44
                radius: Appearance.rounding.small
                color: Appearance.colors.colLayer1Base
                MaterialSymbol {
                    anchors.centerIn: parent
                    text: "account_tree"
                    iconSize: 22
                    color: Appearance.colors.colPrimary
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                StyledText {
                    text: Translation.tr("Profiles and recovery")
                    font.pixelSize: Appearance.font.pixelSize.large
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnLayer0
                }
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Save and restore a set of settings while keeping the original starting values separate.")
                    color: Appearance.colors.colSubtext
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 122
            radius: Appearance.rounding.normal
            color: Appearance.m3colors.m3surfaceContainerLow

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                StyledText {
                    text: Translation.tr("Save current profile")
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnLayer0
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    StyledTextInput {
                        id: profileNameInput
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        selectByMouse: true
                        text: root.profileName
                        onTextChanged: root.profileName = text
                        Accessible.name: Translation.tr("Profile name")
                    }
                    RippleButton {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: 44
                        buttonRadius: Appearance.rounding.small
                        enabled: !root.busy && root.profileName.trim().length > 0
                        colBackground: Appearance.colors.colPrimary
                        colBackgroundHover: Appearance.colors.colPrimaryHover
                        onClicked: root.runManager(["profile-save", root.profileName.trim()])
                        contentItem: StyledText {
                            text: Translation.tr("Save profile")
                            color: Appearance.colors.colOnPrimary
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.weight: Font.DemiBold
                        }
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Profiles include settings with a verified restore path. Expert settings can be included with confirmation; sensitive settings stay out of profiles. App-specific window rules, window glow and motion profiles may reload Hyprland. Other script-backed and live settings remain excluded until reviewed.")
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colSubtext
                    wrapMode: Text.WordWrap
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            StyledText {
                text: Translation.tr("Saved profiles")
                font.weight: Font.DemiBold
                color: Appearance.colors.colOnLayer0
            }
            Item { Layout.fillWidth: true }
            StyledText {
                text: root.profiles.length.toString()
                color: Appearance.colors.colSubtext
            }
            RippleButton {
                Layout.preferredWidth: 44
                Layout.preferredHeight: 40
                buttonRadius: Appearance.rounding.full
                enabled: !root.busy
                Accessible.name: Translation.tr("Refresh profiles")
                onClicked: root.refreshProfiles()
                contentItem: MaterialSymbol {
                    anchors.centerIn: parent
                    text: "refresh"
                    iconSize: 18
                }
            }
        }

        ListView {
            id: profileList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: root.profiles
            delegate: Rectangle {
                required property var modelData
                width: profileList.width
                height: 64
                radius: Appearance.rounding.small
                color: Appearance.colors.colLayer1Base
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 8
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        StyledText {
                            Layout.fillWidth: true
                            text: modelData.name
                            color: Appearance.colors.colOnLayer1
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        StyledText {
                            text: modelData.settingCount + " " + Translation.tr("managed settings")
                            color: Appearance.colors.colSubtext
                            font.pixelSize: Appearance.font.pixelSize.smaller
                        }
                    }
                    RippleButton {
                        Layout.preferredWidth: 60
                        Layout.preferredHeight: 44
                        buttonRadius: Appearance.rounding.small
                        enabled: !root.busy
                        onClicked: root.requestProfileAction("profile-load", modelData.name, modelData.requiresConfirmation, modelData.requiresHyprlandReload)
                        contentItem: StyledText {
                            text: Translation.tr("Load")
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    RippleButton {
                        Layout.preferredWidth: 60
                        Layout.preferredHeight: 44
                        buttonRadius: Appearance.rounding.small
                        enabled: !root.busy
                        Accessible.name: Translation.tr("Copy profile")
                        onClicked: root.runManager(["profile-copy", modelData.name])
                        contentItem: MaterialSymbol {
                            anchors.centerIn: parent
                            text: "content_copy"
                            iconSize: 18
                        }
                    }
                    RippleButton {
                        Layout.preferredWidth: 60
                        Layout.preferredHeight: 44
                        buttonRadius: Appearance.rounding.small
                        enabled: !root.busy
                        Accessible.name: Translation.tr("Delete profile")
                        onClicked: root.requestProfileAction("profile-delete", modelData.name, false)
                        contentItem: MaterialSymbol {
                            anchors.centerIn: parent
                            text: "delete"
                            iconSize: 18
                        }
                    }
                }
            }
            StyledText {
                anchors.centerIn: parent
                visible: root.profiles.length === 0 && !root.busy
                text: Translation.tr("No saved profiles yet.")
                color: Appearance.colors.colSubtext
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 190
            radius: Appearance.rounding.normal
            color: Appearance.m3colors.m3surfaceContainerLow

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    StyledText {
                        Layout.fillWidth: true
                        text: Translation.tr("Configuration backups")
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colOnLayer0
                    }
                    RippleButton {
                        Layout.preferredWidth: 40
                        Layout.preferredHeight: 36
                        buttonRadius: Appearance.rounding.full
                        enabled: !root.busy
                        Accessible.name: Translation.tr("Refresh backups")
                        onClicked: root.refreshBackups()
                        contentItem: MaterialSymbol {
                            anchors.centerIn: parent
                            text: "refresh"
                            iconSize: 18
                        }
                    }
                }

                ListView {
                    id: backupList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 4
                    model: root.backups
                    delegate: Rectangle {
                        required property var modelData
                        width: backupList.width
                        height: 58
                        radius: Appearance.rounding.small
                        color: Appearance.colors.colLayer1Base
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 6
                            spacing: 6
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                StyledText {
                                    Layout.fillWidth: true
                                    text: modelData.backupId
                                    color: Appearance.colors.colOnLayer1
                                    font.pixelSize: Appearance.font.pixelSize.smaller
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideMiddle
                                }
                                StyledText {
                                    text: modelData.status === "verified"
                                          ? modelData.createdAt + " · " + modelData.fileCount + " " + Translation.tr("files") + " · " + modelData.bytes + " " + Translation.tr("bytes")
                                          : Translation.tr("Backup needs verification or repair")
                                    color: modelData.status === "verified" ? Appearance.colors.colSubtext : Appearance.colors.colError
                                    font.pixelSize: Appearance.font.pixelSize.smaller
                                }
                            }
                            RippleButton {
                                Layout.preferredWidth: 84
                                Layout.preferredHeight: 40
                                buttonRadius: Appearance.rounding.small
                                enabled: !root.busy
                                onClicked: root.verifyBackup(modelData.backupId)
                                contentItem: StyledText {
                                    text: Translation.tr("Verify")
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                            RippleButton {
                                Layout.preferredWidth: 82
                                Layout.preferredHeight: 40
                                buttonRadius: Appearance.rounding.small
                                enabled: !root.busy && modelData.status === "verified" && root.selectedBackupId === modelData.backupId && root.verifiedBackupId === modelData.backupId && root.restorePreview && root.restorePreview.backupId === modelData.backupId
                                colBackground: Appearance.colors.colPrimary
                                onClicked: root.requestBackupRestore(modelData.backupId)
                                contentItem: StyledText {
                                    text: Translation.tr("Restore")
                                    color: Appearance.colors.colOnPrimary
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                        }
                    }
                    StyledText {
                        anchors.centerIn: parent
                        visible: root.backups.length === 0 && !root.busy
                        text: Translation.tr("No backups are available.")
                        color: Appearance.colors.colSubtext
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            color: Appearance.colors.colLayer1Hover
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            RippleButton {
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                buttonRadius: Appearance.rounding.small
                enabled: !root.busy
                colBackground: Appearance.colors.colLayer1Base
                onClicked: root.requestProfileAction("undo", "", true)
                contentItem: StyledText {
                    text: Translation.tr("Undo last NEXUS change")
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                }
            }
            RippleButton {
                Layout.fillWidth: true
                Layout.preferredHeight: 46
                buttonRadius: Appearance.rounding.small
                enabled: !root.busy
                colBackground: Appearance.colors.colErrorContainer
                onClicked: {
                    root.pendingOperation = "reset-all";
                    root.pendingProfile = "";
                    root.pendingRequiresConfirmation = true;
                    confirmDialog.open();
                }
                contentItem: StyledText {
                    text: Translation.tr("Restore NEXUS starting values")
                    color: Appearance.colors.colOnErrorContainer
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.WordWrap
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            text: root.statusMessage
            color: root.statusMessage.indexOf("failed") >= 0 ? Appearance.colors.colError : Appearance.colors.colSubtext
            wrapMode: Text.WordWrap
        }
    }

    Dialog {
        id: confirmDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        title: root.pendingOperation === "backup-restore" ? Translation.tr("Restore this backup?") : root.pendingOperation === "reset-all" ? Translation.tr("Restore starting values?") : root.pendingOperation === "profile-delete" ? Translation.tr("Delete this profile?") : root.pendingOperation === "undo" ? Translation.tr("Undo the last NEXUS change?") : Translation.tr("Load this profile?")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: {
            if (root.pendingOperation === "backup-restore")
                root.runManager(["backup-restore", root.pendingBackupId, "--confirm-risk"]);
            else if (root.pendingOperation === "reset-all")
                root.runManager(["reset-all", "--confirm-risk"]);
            else if (root.pendingOperation === "undo")
                root.runManager(["undo", "--confirm-risk"]);
            else if (root.pendingOperation === "profile-load") {
                const args = [root.pendingOperation, root.pendingProfile];
                if (root.pendingRequiresConfirmation)
                    args.push("--confirm-risk");
                root.runManager(args);
            } else
                root.runManager([root.pendingOperation, root.pendingProfile]);
        }
        contentItem: StyledText {
            width: 400
            text: root.pendingOperation === "backup-restore"
                  ? Translation.tr("Restore backup %1? A total of %2 managed files are affected: %3 added, %4 replaced and %5 newer than this backup may be removed. NEXUS creates a verified safety backup first. No application reload will be issued.").arg(root.pendingBackupId).arg(root.restorePreview ? root.restorePreview.addedCount + root.restorePreview.replacedCount + root.restorePreview.removedCount : 0).arg(root.restorePreview ? root.restorePreview.addedCount : 0).arg(root.restorePreview ? root.restorePreview.replacedCount : 0).arg(root.restorePreview ? root.restorePreview.removedCount : 0)
                  : root.pendingOperation === "reset-all"
                  ? Translation.tr("This restores captured settings. Some settings require confirmation. Hyprland may reload if custom window rules, window glow or motion settings change.")
                  : root.pendingOperation === "profile-delete"
                    ? Translation.tr("This permanently removes the saved profile file.")
                    : root.pendingOperation === "undo"
                      ? Translation.tr("This restores the previous NEXUS state. Some changes may reload Hyprland; newer edits are protected by conflict checks.")
                      : root.pendingRequiresConfirmation
                        ? root.pendingRequiresHyprlandReload
                          ? Translation.tr("This profile includes settings that need confirmation and may reload Hyprland. Visual effects are not independently verified.")
                          : Translation.tr("This profile includes expert settings that need confirmation. Live effects are not independently verified.")
                        : Translation.tr("This updates managed settings in their existing sources. NEXUS verifies supported live Hyprland values; other visual effects may remain unverified.")
            wrapMode: Text.WordWrap
            color: Appearance.colors.colOnLayer1
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
}
