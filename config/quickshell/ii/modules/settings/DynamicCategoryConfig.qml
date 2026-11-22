import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.services
import qs.modules.common
import qs.modules.common.widgets

ContentPage {
    id: root

    forceWidth: true
    baseWidth: embedded ? Math.max(200, width - 40) : Math.max(520, width - 32)
    bottomContentPadding: embedded ? 28 : 24
    interactive: !embedded

    property var settingsRoot: null
    property var pageData: null
    property bool supplementalOnly: false
    property bool embedded: false
    property int valueRevision: 0
    property string appIconFilter: ""
    property int visibleAppLimit: 24
    readonly property bool isAppsPage: Boolean(root.pageData && String(root.pageData.categoryId || "").toLocaleLowerCase() === "apps" && !root.supplementalOnly)

    function syncEmbeddedScrollBehavior() {
        // StyledFlickable installs a wheel-capturing MouseArea inside Flickable's contentItem
        // that does not check `interactive`. Disable it when embedded inside another ContentPage
        // so outer page scrolling works smoothly.
        const containers = root.contentItem ? [root.children, root.contentItem.children] : [root.children];
        for (let c = 0; c < containers.length; ++c) {
            const list = containers[c];
            if (!list)
                continue;
            for (let i = 0; i < list.length; ++i) {
                const ch = list[i];
                if (ch && ch.acceptedButtons !== undefined && ch.containsMouse !== undefined)
                    ch.enabled = !root.embedded;
            }
        }
        if (root.ScrollBar && root.ScrollBar.vertical)
            root.ScrollBar.vertical.visible = !root.embedded;
    }

    onEmbeddedChanged: syncEmbeddedScrollBehavior()

    onPageDataChanged: {
        if (root.isAppsPage && root.settingsRoot && typeof root.settingsRoot.refreshAppsCatalog === "function") {
            const existing = root.toList(root.settingsRoot.appsCatalog);
            if (existing.length === 0)
                root.settingsRoot.refreshAppsCatalog();
        }
    }

    Component.onCompleted: {
        syncEmbeddedScrollBehavior();
        if (root.isAppsPage && root.settingsRoot && typeof root.settingsRoot.refreshAppsCatalog === "function") {
            const existing = root.toList(root.settingsRoot.appsCatalog);
            if (existing.length === 0)
                root.settingsRoot.refreshAppsCatalog();
        }
    }

    function isListLike(v) {
        return v !== null && v !== undefined && typeof v === "object" && typeof v.length === "number" && typeof v !== "string";
    }

    function toList(v) {
        if (!isListLike(v))
            return [];
        const out = [];
        for (let i = 0; i < v.length; ++i)
            out.push(v[i]);
        return out;
    }

    readonly property var renderedSubcategories: {
        const _catalog = root.settingsRoot ? root.toList(root.settingsRoot.settingsCatalog) : [];
        const _page = root.pageData;
        if (!root.settingsRoot || !_page || _catalog.length === 0)
            return [];

        const byId = {};
        for (let i = 0; i < _catalog.length; ++i) {
            const item = _catalog[i];
            if (item && item.id)
                byId[item.id] = item;
        }

        const pageSubcats = root.toList(_page.subcategories);
        const pageSettingIds = root.toList(_page.settingIds);
        const rawSubs = pageSubcats.length > 0
            ? pageSubcats
            : (pageSettingIds.length > 0
                ? [{ id: String(_page.categoryId || "general") + ".general", title: Translation.tr("General"), settingIds: pageSettingIds }]
                : []);

        const out = [];
        for (let i = 0; i < rawSubs.length; ++i) {
            const sub = rawSubs[i];
            const subIds = sub ? root.toList(sub.settingIds) : [];
            if (!sub || subIds.length === 0)
                continue;
            const items = [];
            for (let j = 0; j < subIds.length; ++j) {
                const sid = subIds[j];
                const defn = byId[sid];
                if (root.isRenderableSetting(defn))
                    items.push(defn);
            }
            if (items.length > 0) {
                out.push({
                    id: sub.id || (String(_page.categoryId || "cat") + ".sub" + i),
                    title: sub.title || Translation.tr("General"),
                    settings: items
                });
            }
        }
        return out;
    }

    function isUniversalAdapterSetting(setting) {
        if (!setting)
            return false;
        const sk = String(setting.sourceKind || "");
        return sk === "desktop-appearance-adapter"
            || sk === "app-customization-adapter"
            || sk === "hyprland-godmode-adapter"
            || sk === "hyprland-options-adapter";
    }

    function isRenderableSetting(setting) {
        if (!setting || !root.settingsRoot)
            return false;
        if (!root.settingsRoot.isVerifiedSetting(setting))
            return false;
        if (setting.verification && (setting.verification.manageable === false || setting.verification.applicable === false))
            return false;
        if (setting.sourceKind !== "config-json" && !root.isUniversalAdapterSetting(setting))
            return false;
        if (setting.controlType === "readonly-info" || setting.controlType === "custom-editor")
            return false;
        const tags = setting.semantics ? root.toList(setting.semantics.tags) : [];
        if (tags.indexOf("complex-object-list") >= 0)
            return false;
        if (root.supplementalOnly && tags.indexOf("has-static-ui") >= 0)
            return false;
        const vt = String(setting.valueType || "");
        return vt === "boolean" || vt === "integer" || vt === "number" || vt === "string" || vt === "array";
    }

    function readSettingValue(setting) {
        if (!setting)
            return undefined;
        if (setting.sourceKind === "config-json")
            return root.readConfigValue(setting.path);
        if (root.isUniversalAdapterSetting(setting) && root.settingsRoot) {
            const ext = root.settingsRoot.externalSettingValues;
            if (ext && setting.id in ext)
                return ext[setting.id];
        }
        return undefined;
    }

    function coerceTypedValue(newValue, expectedType) {
        if (expectedType === "boolean")
            return Boolean(newValue);
        if (expectedType === "integer") {
            const n = Math.round(Number(newValue));
            return Number.isFinite(n) ? n : undefined;
        }
        if (expectedType === "number") {
            const n = Number(newValue);
            return Number.isFinite(n) ? n : undefined;
        }
        if (expectedType === "string")
            return String(newValue === undefined || newValue === null ? "" : newValue);
        if (expectedType === "array") {
            if (!root.isListLike(newValue))
                return undefined;
            const copy = [];
            for (let i = 0; i < newValue.length; ++i)
                copy.push(String(newValue[i]));
            return copy;
        }
        return newValue;
    }

    function writeSettingValue(setting, newValue, expectedType) {
        if (!setting)
            return false;
        if (setting.sourceKind === "config-json")
            return root.writeConfigValue(setting.path, newValue, expectedType);
        if (root.isUniversalAdapterSetting(setting) && root.settingsRoot && typeof root.settingsRoot.setAdapterSetting === "function") {
            const typedVal = root.coerceTypedValue(newValue, expectedType);
            if (typedVal === undefined)
                return false;
            return root.settingsRoot.setAdapterSetting(setting.id, typedVal);
        }
        return false;
    }

    function readConfigValue(path) {
        if (!path)
            return undefined;
        if (root.settingsRoot && typeof root.settingsRoot.valueAt === "function")
            return root.settingsRoot.valueAt(path);
        let value = Config.options;
        const parts = path.split(".");
        for (let i = 0; i < parts.length; ++i) {
            if (value === null || value === undefined || typeof value !== "object" || !(parts[i] in value))
                return undefined;
            value = value[parts[i]];
        }
        return value;
    }

    function writeConfigValue(path, newValue, expectedType) {
        if (!path)
            return false;
        const keys = path.split(".");
        let obj = Config.options;
        for (let i = 0; i < keys.length - 1; ++i) {
            if (!obj || typeof obj !== "object" || !(keys[i] in obj))
                return false;
            obj = obj[keys[i]];
        }
        const leafKey = keys[keys.length - 1];
        if (!obj || typeof obj !== "object" || !(leafKey in obj))
            return false;

        let typedValue = newValue;
        if (expectedType === "boolean") {
            typedValue = Boolean(newValue);
        } else if (expectedType === "integer") {
            const n = Math.round(Number(newValue));
            if (!Number.isFinite(n))
                return false;
            typedValue = n;
        } else if (expectedType === "number") {
            const n = Number(newValue);
            if (!Number.isFinite(n))
                return false;
            typedValue = n;
        } else if (expectedType === "string") {
            typedValue = String(newValue === undefined || newValue === null ? "" : newValue);
        } else if (expectedType === "array") {
            if (!root.isListLike(newValue))
                return false;
            const copy = [];
            for (let i = 0; i < newValue.length; ++i)
                copy.push(String(newValue[i]));
            typedValue = copy;
        }

        if (expectedType !== "array" && obj[leafKey] === typedValue)
            return true;
        obj[leafKey] = typedValue;
        root.valueRevision += 1;
        return true;
    }

    function allowsEmptyChoice(setting) {
        if (!setting || setting.valueType === "integer")
            return false;
        if (String(setting.id || "").indexOf("apps.defaults.") === 0)
            return true;
        const rawChoices = root.toList(setting.choices);
        for (let i = 0; i < rawChoices.length; ++i) {
            if (String(rawChoices[i]) === "")
                return true;
        }
        return false;
    }

    function listInputPlaceholder(setting) {
        const sid = String(setting && setting.id ? setting.id : "");
        if (sid === "hyprland.custom.keybinds")
            return Translation.tr("MODS+KEY => COMMAND (e.g. SUPER+SHIFT+B => firefox)");
        if (sid === "hyprland.custom.env")
            return Translation.tr("KEY=VALUE (e.g. MOZ_ENABLE_WAYLAND=1)");
        if (sid === "hyprland.custom.autostart")
            return Translation.tr("Startup command (e.g. discord --start-minimized)");
        if (sid === "apps.icons.overrides")
            return Translation.tr("appId=iconNameOrPath (e.g. kitty=utilities-terminal)");
        if (sid === "apps.visibility.hiddenApps")
            return Translation.tr("Desktop app ID to hide (e.g. htop)");
        if (sid === "launcher.pinnedApps")
            return Translation.tr("Desktop app ID to pin (e.g. kitty)");
        return Translation.tr("Add item…");
    }

    function stringInputPlaceholder(setting) {
        const sid = String(setting && setting.id ? setting.id : "");
        if (sid === "hyprland.input.kb_variant")
            return Translation.tr("e.g. altgr-intl, dvorak (empty = default)");
        if (sid === "hyprland.input.kb_options")
            return Translation.tr("e.g. caps:escape, grp:alt_shift_toggle (empty = none)");
        if (sid === "desktop.gtk.font")
            return Translation.tr("e.g. Google Sans Flex, Medium 11");
        return (setting && (setting.title || setting.path)) ? String(setting.title || setting.path) : "";
    }

    function parseChoiceOptions(setting, currentVal) {
        const rawChoices = root.toList(setting ? setting.choices : null);
        if (rawChoices.length === 0)
            return [];
        const isInt = setting.valueType === "integer";
        const result = [];
        let hasExplicitEmpty = false;
        for (let i = 0; i < rawChoices.length; ++i) {
            const raw = String(rawChoices[i]);
            if (isInt) {
                const match = raw.match(/^\s*(-?\d+)\s*:\s*(.+)$/);
                if (match) {
                    result.push({ displayName: raw.trim(), value: Number(match[1]) });
                    continue;
                }
                const num = Number(raw);
                if (Number.isFinite(num)) {
                    result.push({ displayName: raw, value: num });
                    continue;
                }
            }
            if (!isInt && raw === "") {
                hasExplicitEmpty = true;
                result.push({ displayName: Translation.tr("Default (auto)"), value: "" });
                continue;
            }
            result.push({ displayName: raw, value: raw });
        }
        const activeVal = arguments.length >= 2
            ? currentVal
            : root.readSettingValue(setting);
        const allowsEmptyDefault = !isInt && String(setting.id || "").indexOf("apps.defaults.") === 0;
        if (allowsEmptyDefault && !hasExplicitEmpty) {
            result.unshift({ displayName: Translation.tr("Not set (system default)"), value: "" });
        } else if (!isInt && !hasExplicitEmpty && (activeVal === "" || activeVal === undefined || activeVal === null)) {
            result.unshift({ displayName: Translation.tr("Not set"), value: "" });
        }
        if (activeVal !== undefined && activeVal !== null) {
            const normalizedActive = isInt ? Number(activeVal) : String(activeVal);
            const validActive = isInt ? Number.isFinite(normalizedActive) : normalizedActive.length > 0;
            if (validActive && !result.some(item => item.value === normalizedActive))
                result.unshift({ displayName: String(normalizedActive), value: normalizedActive });
        }
        return result;
    }

    function shouldUseSlider(setting, currentVal) {
        if (!setting || setting.valueType !== "number")
            return false;
        const lim = setting.limits;
        if (lim && typeof lim.minimum === "number" && typeof lim.maximum === "number")
            return lim.minimum >= -1.0 && lim.maximum <= 1.0 && lim.maximum > lim.minimum;
        const cur = Number(currentVal);
        if (!Number.isFinite(cur) || cur < 0.0 || cur > 1.0)
            return false;
        const lower = String(setting.id || "").toLowerCase();
        return lower.indexOf("opacity") >= 0
            || lower.indexOf("transparency") >= 0
            || lower.indexOf("scale") >= 0
            || lower.indexOf("factor") >= 0
            || lower.indexOf("harmony") >= 0
            || lower.indexOf("boost") >= 0
            || lower.indexOf("zoom") >= 0;
    }

    function spinMin(setting, currentVal) {
        const lim = setting && setting.limits ? setting.limits : null;
        if (lim && typeof lim.minimum === "number")
            return Math.round(lim.minimum);
        const cur = Number(currentVal);
        if (Number.isFinite(cur) && cur < 0)
            return Math.min(-1000, Math.floor(cur) * 2);
        return 0;
    }

    function spinMax(setting, currentVal) {
        const lim = setting && setting.limits ? setting.limits : null;
        if (lim && typeof lim.maximum === "number")
            return Math.round(lim.maximum);
        const cur = Number(currentVal);
        const base = Number.isFinite(cur) ? Math.abs(Math.ceil(cur)) : 100;
        return Math.max(10000, base * 2);
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 16

        Repeater {
            model: root.renderedSubcategories

            delegate: Rectangle {
                id: subcatCard
                required property var modelData
                readonly property string subId: String(modelData.id || "")
                readonly property bool expanded: root.settingsRoot ? root.settingsRoot.isSubcategoryExpanded(subId) : true

                Layout.fillWidth: true
                implicitHeight: subcatColumn.implicitHeight + 24
                radius: Appearance.rounding.normal
                color: Appearance.m3colors.m3surfaceContainerLow

                ColumnLayout {
                    id: subcatColumn
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 10

                    RippleButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 38
                        buttonRadius: Appearance.rounding.small
                        colBackground: "transparent"
                        colBackgroundHover: Appearance.colors.colLayer1Hover
                        onClicked: {
                            if (root.settingsRoot)
                                root.settingsRoot.toggleSubcategoryExpanded(subcatCard.subId);
                        }
                        contentItem: RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            spacing: 8

                            MaterialSymbol {
                                text: subcatCard.expanded ? "expand_more" : "chevron_right"
                                iconSize: 20
                                color: Appearance.colors.colPrimary
                            }
                            StyledText {
                                Layout.fillWidth: true
                                text: subcatCard.modelData.title || ""
                                font.pixelSize: Appearance.font.pixelSize.large
                                font.weight: Font.DemiBold
                                color: Appearance.colors.colOnLayer0
                            }
                            StyledText {
                                text: String(subcatCard.modelData.settings.length)
                                font.pixelSize: Appearance.font.pixelSize.smaller
                                color: Appearance.colors.colSubtext
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: subcatCard.expanded
                        spacing: 8

                        Repeater {
                            model: subcatCard.modelData.settings

                            delegate: Rectangle {
                                id: settingCard
                                required property var modelData
                                readonly property var setting: modelData
                                readonly property var currentVal: {
                                    const _vrev = root.valueRevision;
                                    const _erev = root.settingsRoot ? root.settingsRoot.externalValuesRevision : 0;
                                    return root.readSettingValue(setting);
                                }
                                readonly property var choiceList: root.parseChoiceOptions(setting, settingCard.currentVal)
                                readonly property bool isHighlighted: Boolean(root.settingsRoot && root.settingsRoot.selectedSettingId === setting.id)
                                property bool readyToWrite: false

                                Component.onCompleted: readyToWrite = true

                                Layout.fillWidth: true
                                implicitHeight: settingInner.implicitHeight + 18
                                radius: Appearance.rounding.small
                                color: isHighlighted ? Appearance.colors.colSecondaryContainer : Appearance.colors.colLayer1Base
                                border.width: isHighlighted ? 1 : 0
                                border.color: Appearance.colors.colPrimary

                                ColumnLayout {
                                    id: settingInner
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 9
                                    spacing: 6

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 8

                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 2

                                            StyledText {
                                                Layout.fillWidth: true
                                                text: settingCard.setting.title || settingCard.setting.id
                                                font.weight: Font.Medium
                                                color: Appearance.colors.colOnLayer0
                                                wrapMode: Text.WordWrap
                                            }
                                            StyledText {
                                                Layout.fillWidth: true
                                                readonly property string descText: String(settingCard.setting.description || "").trim()
                                                visible: descText.length > 0 && descText !== String(settingCard.setting.title || "").trim()
                                                text: descText
                                                font.pixelSize: Appearance.font.pixelSize.smaller
                                                color: Appearance.colors.colSubtext
                                                wrapMode: Text.WordWrap
                                                maximumLineCount: 3
                                                elide: Text.ElideRight
                                            }
                                            StyledText {
                                                Layout.fillWidth: true
                                                text: settingCard.setting.path || settingCard.setting.id
                                                font.pixelSize: Math.max(10, Appearance.font.pixelSize.smaller - 1)
                                                color: Appearance.colors.colSubtext
                                                opacity: 0.72
                                                elide: Text.ElideRight
                                            }
                                        }

                                        RippleButton {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 30
                                            buttonRadius: Appearance.rounding.full
                                            colBackground: "transparent"
                                            colBackgroundHover: Appearance.colors.colLayer1Hover
                                            Accessible.name: Translation.tr("Inspect setting")
                                            onClicked: {
                                                if (root.settingsRoot)
                                                    root.settingsRoot.selectedSettingId = settingCard.setting.id;
                                            }
                                            contentItem: MaterialSymbol {
                                                anchors.centerIn: parent
                                                text: "info"
                                                iconSize: 17
                                                color: Appearance.colors.colSubtext
                                            }
                                        }
                                    }

                                    // 1. Boolean -> ConfigSwitch
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "boolean"
                                        visible: active
                                        sourceComponent: ConfigSwitch {
                                            id: boolSwitch
                                            buttonIcon: "toggle_on"
                                            text: settingCard.setting.title || settingCard.setting.id
                                            checked: Boolean(settingCard.currentVal)
                                            onClicked: {
                                                if (settingCard.readyToWrite)
                                                    root.writeSettingValue(settingCard.setting, checked, "boolean");
                                            }
                                            Connections {
                                                target: settingCard
                                                function onCurrentValChanged() {
                                                    const nextVal = Boolean(settingCard.currentVal);
                                                    if (boolSwitch.checked !== nextVal)
                                                        boolSwitch.checked = nextVal;
                                                }
                                            }
                                        }
                                    }

                                    // 2. Enum choices (string or integer) -> StyledComboBox
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.choiceList.length > 0 && (settingCard.setting.valueType === "string" || settingCard.setting.valueType === "integer")
                                        visible: active
                                        sourceComponent: StyledComboBox {
                                            id: choiceCombo
                                            Layout.fillWidth: true
                                            buttonIcon: "list"
                                            textRole: "displayName"
                                            model: settingCard.choiceList
                                            function syncIndex() {
                                                const rawCur = settingCard.currentVal;
                                                const cur = (rawCur === undefined || rawCur === null) ? "" : rawCur;
                                                const idx = settingCard.choiceList.findIndex(item => item.value === cur);
                                                const targetIdx = idx >= 0 ? idx : 0;
                                                if (choiceCombo.currentIndex !== targetIdx)
                                                    choiceCombo.currentIndex = targetIdx;
                                            }
                                            Component.onCompleted: syncIndex()
                                            Connections {
                                                target: settingCard
                                                function onCurrentValChanged() { choiceCombo.syncIndex(); }
                                                function onChoiceListChanged() { choiceCombo.syncIndex(); }
                                            }
                                            onActivated: index => {
                                                if (index >= 0 && index < settingCard.choiceList.length) {
                                                    const chosenVal = settingCard.choiceList[index].value;
                                                    if (chosenVal === "" && !root.allowsEmptyChoice(settingCard.setting))
                                                        return;
                                                    root.writeSettingValue(settingCard.setting, chosenVal, settingCard.setting.valueType);
                                                }
                                            }
                                        }
                                    }

                                    // 3. Integer without choices -> ConfigSpinBox
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "integer" && settingCard.choiceList.length === 0
                                        visible: active
                                        sourceComponent: ConfigSpinBox {
                                            id: intSpinBox
                                            property bool syncingFromModel: false
                                            icon: "pin"
                                            text: settingCard.setting.title || settingCard.setting.id
                                            from: root.spinMin(settingCard.setting, settingCard.currentVal)
                                            to: root.spinMax(settingCard.setting, settingCard.currentVal)
                                            stepSize: 1
                                            value: Number.isFinite(Number(settingCard.currentVal)) ? Math.round(Number(settingCard.currentVal)) : from
                                            onValueChanged: {
                                                const curNum = Number(settingCard.currentVal);
                                                if (settingCard.readyToWrite && !syncingFromModel && Number.isFinite(curNum) && value !== Math.round(curNum))
                                                    root.writeSettingValue(settingCard.setting, value, "integer");
                                            }
                                            Connections {
                                                target: settingCard
                                                function onCurrentValChanged() {
                                                    const curNum = Number(settingCard.currentVal);
                                                    if (!Number.isFinite(curNum))
                                                        return;
                                                    const nextVal = Math.round(curNum);
                                                    if (intSpinBox.value !== nextVal) {
                                                        intSpinBox.syncingFromModel = true;
                                                        intSpinBox.value = nextVal;
                                                        intSpinBox.syncingFromModel = false;
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    // 4a. Normalized Number (0..1) -> StyledSlider
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "number" && root.shouldUseSlider(settingCard.setting, settingCard.currentVal)
                                        visible: active
                                        sourceComponent: RowLayout {
                                            id: sliderRow
                                            Layout.fillWidth: true
                                            spacing: 10
                                            property real pendingSliderValue: Number.NaN

                                            Timer {
                                                id: adapterSliderDebounce
                                                interval: 90
                                                repeat: false
                                                onTriggered: {
                                                    if (Number.isFinite(sliderRow.pendingSliderValue)) {
                                                        const v = sliderRow.pendingSliderValue;
                                                        sliderRow.pendingSliderValue = Number.NaN;
                                                        root.writeSettingValue(settingCard.setting, v, "number");
                                                    }
                                                }
                                            }

                                            StyledSlider {
                                                id: numSlider
                                                Layout.fillWidth: true
                                                animateValue: false
                                                from: (settingCard.setting.limits && typeof settingCard.setting.limits.minimum === "number") ? settingCard.setting.limits.minimum : 0.0
                                                to: (settingCard.setting.limits && typeof settingCard.setting.limits.maximum === "number") ? settingCard.setting.limits.maximum : 1.0
                                                stepSize: 0.01
                                                value: Number.isFinite(Number(settingCard.currentVal)) ? Number(settingCard.currentVal) : from
                                                onMoved: {
                                                    const rounded = Number(value.toFixed(2));
                                                    if (root.isUniversalAdapterSetting(settingCard.setting)) {
                                                        sliderRow.pendingSliderValue = rounded;
                                                        adapterSliderDebounce.restart();
                                                    } else {
                                                        root.writeSettingValue(settingCard.setting, rounded, "number");
                                                    }
                                                }
                                                onPressedChanged: {
                                                    if (!pressed && adapterSliderDebounce.running && Number.isFinite(sliderRow.pendingSliderValue)) {
                                                        adapterSliderDebounce.stop();
                                                        const v = sliderRow.pendingSliderValue;
                                                        sliderRow.pendingSliderValue = Number.NaN;
                                                        root.writeSettingValue(settingCard.setting, v, "number");
                                                    }
                                                }
                                                Connections {
                                                    target: settingCard
                                                    function onCurrentValChanged() {
                                                        if (numSlider.pressed)
                                                            return;
                                                        const nextVal = Number(settingCard.currentVal);
                                                        if (Number.isFinite(nextVal) && Math.abs(numSlider.value - nextVal) > 0.0001)
                                                            numSlider.value = nextVal;
                                                    }
                                                }
                                            }
                                            StyledText {
                                                text: Number.isFinite(numSlider.value) ? numSlider.value.toFixed(2) : "0.00"
                                                font.pixelSize: Appearance.font.pixelSize.small
                                                color: Appearance.colors.colSubtext
                                            }
                                        }
                                    }

                                    // 4b. Unbounded / fractional Number -> Decimal MaterialTextField + Apply
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "number" && !root.shouldUseSlider(settingCard.setting, settingCard.currentVal)
                                        visible: active
                                        sourceComponent: RowLayout {
                                            id: decRow
                                            Layout.fillWidth: true
                                            spacing: 8

                                            function commitDecimal() {
                                                const raw = decField.text.trim();
                                                if (!raw)
                                                    return;
                                                const parsed = Number(raw);
                                                if (!Number.isFinite(parsed))
                                                    return;
                                                const lim = settingCard.setting.limits;
                                                let finalVal = parsed;
                                                if (lim && typeof lim.minimum === "number" && finalVal < lim.minimum)
                                                    finalVal = lim.minimum;
                                                if (lim && typeof lim.maximum === "number" && finalVal > lim.maximum)
                                                    finalVal = lim.maximum;
                                                root.writeSettingValue(settingCard.setting, finalVal, "number");
                                                decField.text = String(finalVal);
                                            }

                                            MaterialTextField {
                                                id: decField
                                                Layout.fillWidth: true
                                                placeholderText: settingCard.setting.title || settingCard.setting.path
                                                inputMethodHints: Qt.ImhFormattedNumbersOnly
                                                validator: DoubleValidator {
                                                    locale: "C"
                                                    notation: DoubleValidator.StandardNotation
                                                    decimals: 6
                                                    bottom: (settingCard.setting.limits && typeof settingCard.setting.limits.minimum === "number") ? settingCard.setting.limits.minimum : -1000000000
                                                    top: (settingCard.setting.limits && typeof settingCard.setting.limits.maximum === "number") ? settingCard.setting.limits.maximum : 1000000000
                                                }
                                                text: Number.isFinite(Number(settingCard.currentVal)) ? String(settingCard.currentVal) : ""
                                                onAccepted: decRow.commitDecimal()
                                                Connections {
                                                    target: settingCard
                                                    function onCurrentValChanged() {
                                                        if (decField.activeFocus)
                                                            return;
                                                        const nextStr = Number.isFinite(Number(settingCard.currentVal)) ? String(settingCard.currentVal) : "";
                                                        if (decField.text !== nextStr)
                                                            decField.text = nextStr;
                                                    }
                                                }
                                            }

                                            RippleButton {
                                                Layout.preferredWidth: 72
                                                Layout.preferredHeight: 38
                                                buttonRadius: Appearance.rounding.small
                                                colBackground: Appearance.colors.colSecondaryContainer
                                                colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                                onClicked: decRow.commitDecimal()
                                                contentItem: StyledText {
                                                    text: Translation.tr("Apply")
                                                    color: Appearance.colors.colOnSecondaryContainer
                                                    horizontalAlignment: Text.AlignHCenter
                                                    verticalAlignment: Text.AlignVCenter
                                                }
                                            }
                                        }
                                    }

                                    // 5. String without choices -> MaterialTextField + Apply
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "string" && settingCard.choiceList.length === 0
                                        visible: active
                                        sourceComponent: ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 4
                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 8
                                                MaterialTextField {
                                                    id: strField
                                                    Layout.fillWidth: true
                                                    placeholderText: root.stringInputPlaceholder(settingCard.setting)
                                                    text: settingCard.currentVal !== undefined && settingCard.currentVal !== null ? String(settingCard.currentVal) : ""
                                                    onAccepted: root.writeSettingValue(settingCard.setting, text, "string")
                                                    Connections {
                                                        target: settingCard
                                                        function onCurrentValChanged() {
                                                            if (strField.activeFocus)
                                                                return;
                                                            const nextStr = settingCard.currentVal !== undefined && settingCard.currentVal !== null ? String(settingCard.currentVal) : "";
                                                            if (strField.text !== nextStr)
                                                                strField.text = nextStr;
                                                        }
                                                    }
                                                }
                                                RippleButton {
                                                    Layout.preferredWidth: 72
                                                    Layout.preferredHeight: 38
                                                    buttonRadius: Appearance.rounding.small
                                                    colBackground: Appearance.colors.colSecondaryContainer
                                                    colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                                    onClicked: root.writeSettingValue(settingCard.setting, strField.text, "string")
                                                    contentItem: StyledText {
                                                        text: Translation.tr("Apply")
                                                        color: Appearance.colors.colOnSecondaryContainer
                                                        horizontalAlignment: Text.AlignHCenter
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                }
                                            }
                                            StyledText {
                                                visible: settingCard.setting.sensitive === true
                                                text: Translation.tr("Sensitive value: hidden from shared profiles")
                                                font.pixelSize: Appearance.font.pixelSize.smaller
                                                color: Appearance.colors.colSubtext
                                            }
                                        }
                                    }

                                    // 6. Primitive string Array -> Interactive List Editor
                                    Loader {
                                        Layout.fillWidth: true
                                        active: settingCard.setting.valueType === "array"
                                        visible: active
                                        sourceComponent: ColumnLayout {
                                            id: listEditorCol
                                            Layout.fillWidth: true
                                            spacing: 6
                                            readonly property var itemsList: root.toList(settingCard.currentVal)

                                            Flow {
                                                Layout.fillWidth: true
                                                spacing: 6
                                                Repeater {
                                                    model: listEditorCol.itemsList
                                                    delegate: Rectangle {
                                                        id: chipRect
                                                        required property var modelData
                                                        required property int index
                                                        implicitWidth: chipRow.implicitWidth + 14
                                                        implicitHeight: 28
                                                        radius: Appearance.rounding.small
                                                        color: Appearance.colors.colSecondaryContainer

                                                        RowLayout {
                                                            id: chipRow
                                                            anchors.centerIn: parent
                                                            spacing: 6
                                                            StyledText {
                                                                text: String(chipRect.modelData)
                                                                font.pixelSize: Appearance.font.pixelSize.smaller
                                                                color: Appearance.colors.colOnSecondaryContainer
                                                            }
                                                            RippleButton {
                                                                Layout.preferredWidth: 20
                                                                Layout.preferredHeight: 20
                                                                buttonRadius: Appearance.rounding.full
                                                                colBackground: "transparent"
                                                                colBackgroundHover: Appearance.colors.colLayer1Hover
                                                                onClicked: {
                                                                    const cur = root.toList(settingCard.currentVal);
                                                                    const next = [];
                                                                    for (let k = 0; k < cur.length; ++k) {
                                                                        if (k !== chipRect.index)
                                                                            next.push(String(cur[k]));
                                                                    }
                                                                    root.writeSettingValue(settingCard.setting, next, "array");
                                                                }
                                                                contentItem: MaterialSymbol {
                                                                    anchors.centerIn: parent
                                                                    text: "close"
                                                                    iconSize: 13
                                                                    color: Appearance.colors.colOnSecondaryContainer
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }

                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 8
                                                MaterialTextField {
                                                    id: newListItemField
                                                    Layout.fillWidth: true
                                                    placeholderText: root.listInputPlaceholder(settingCard.setting)
                                                    onAccepted: {
                                                        const val = text.trim();
                                                        if (!val)
                                                            return;
                                                        const cur = root.toList(settingCard.currentVal);
                                                        root.writeSettingValue(settingCard.setting, cur.concat([val]), "array");
                                                        text = "";
                                                    }
                                                }
                                                RippleButton {
                                                    Layout.preferredWidth: 68
                                                    Layout.preferredHeight: 38
                                                    buttonRadius: Appearance.rounding.small
                                                    colBackground: Appearance.colors.colSecondaryContainer
                                                    colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                                    onClicked: {
                                                        const val = newListItemField.text.trim();
                                                        if (!val)
                                                            return;
                                                        const cur = root.toList(settingCard.currentVal);
                                                        root.writeSettingValue(settingCard.setting, cur.concat([val]), "array");
                                                        newListItemField.text = "";
                                                    }
                                                    contentItem: StyledText {
                                                        text: Translation.tr("Add")
                                                        color: Appearance.colors.colOnSecondaryContainer
                                                        horizontalAlignment: Text.AlignHCenter
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Visual Per-Application Icon Customizer (shown inside the Applications & Icons category)
        Rectangle {
            id: appIconCustomizerCard
            visible: root.isAppsPage
            Layout.fillWidth: true
            implicitHeight: visible ? appIconCustomizerCol.implicitHeight + 24 : 0
            radius: Appearance.rounding.normal
            color: Appearance.m3colors.m3surfaceContainerLow

            readonly property var allMatchingApps: {
                if (!root.isAppsPage || !root.settingsRoot)
                    return [];
                const all = root.toList(root.settingsRoot.appsCatalog);
                const q = root.appIconFilter.trim().toLocaleLowerCase();
                const out = [];
                for (let i = 0; i < all.length; ++i) {
                    const a = all[i];
                    if (!a)
                        continue;
                    if (q.length > 0) {
                        const hay = (String(a.name || "") + " " + String(a.id || "") + " " + String(a.icon || "")).toLocaleLowerCase();
                        if (hay.indexOf(q) < 0)
                            continue;
                    }
                    out.push(a);
                }
                return out;
            }

            readonly property var filteredApps: allMatchingApps.slice(0, root.visibleAppLimit)

            ColumnLayout {
                id: appIconCustomizerCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    MaterialSymbol {
                        text: "app_shortcut"
                        iconSize: 20
                        color: Appearance.colors.colPrimary
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: Translation.tr("Installed applications: icons & launcher visibility")
                        font.pixelSize: Appearance.font.pixelSize.large
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colOnLayer0
                    }
                    RippleButton {
                        Layout.preferredHeight: 32
                        implicitWidth: refreshAppsLabel.implicitWidth + 20
                        buttonRadius: Appearance.rounding.small
                        colBackground: Appearance.colors.colLayer1Base
                        colBackgroundHover: Appearance.colors.colLayer1Hover
                        onClicked: {
                            if (root.settingsRoot)
                                root.settingsRoot.refreshAppsCatalog();
                        }
                        contentItem: StyledText {
                            id: refreshAppsLabel
                            anchors.centerIn: parent
                            text: Translation.tr("Refresh")
                            font.pixelSize: Appearance.font.pixelSize.smaller
                            color: Appearance.colors.colOnLayer1
                        }
                    }
                }

                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Search any installed application to change its icon (theme icon name or SVG/PNG path) or hide/show it in app launchers. Updates ~/.local/share/applications/*.desktop transactionally.")
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colSubtext
                    wrapMode: Text.WordWrap
                }

                MaterialTextField {
                    Layout.fillWidth: true
                    placeholderText: Translation.tr("Filter applications by name, desktop ID, or icon…")
                    text: root.appIconFilter
                    onTextChanged: {
                        root.appIconFilter = text;
                        root.visibleAppLimit = 24;
                    }
                }

                StyledText {
                    Layout.fillWidth: true
                    text: Translation.tr("Showing %1 of %2 applications").arg(appIconCustomizerCard.filteredApps.length).arg(appIconCustomizerCard.allMatchingApps.length)
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: Appearance.colors.colSubtext
                }

                Repeater {
                    model: appIconCustomizerCard.filteredApps

                    delegate: Rectangle {
                        id: appRowCard
                        required property var modelData
                        readonly property string appId: String(modelData && modelData.id ? modelData.id : "")
                        readonly property bool isHiddenByNexus: {
                            const _erev = root.settingsRoot ? root.settingsRoot.externalValuesRevision : 0;
                            if (modelData && modelData.hiddenByNexus === true)
                                return true;
                            const ext = root.settingsRoot ? root.settingsRoot.externalSettingValues : null;
                            const hiddenList = ext && ("apps.visibility.hiddenApps" in ext)
                                ? root.toList(ext["apps.visibility.hiddenApps"])
                                : [];
                            return appId.length > 0 && hiddenList.indexOf(appId) >= 0;
                        }
                        readonly property bool isSystemHidden: Boolean(modelData && modelData.noDisplay === true) && !isHiddenByNexus
                        Layout.fillWidth: true
                        implicitHeight: appRowInner.implicitHeight + 16
                        radius: Appearance.rounding.small
                        color: Appearance.colors.colLayer1Base

                        ColumnLayout {
                            id: appRowInner
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 8
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Image {
                                    Layout.preferredWidth: 28
                                    Layout.preferredHeight: 28
                                    sourceSize.width: 28
                                    sourceSize.height: 28
                                    fillMode: Image.PreserveAspectFit
                                    opacity: (appRowCard.isHiddenByNexus || appRowCard.isSystemHidden) ? 0.55 : 1.0
                                    source: {
                                        const ic = String(appRowCard.modelData.icon || "");
                                        if (!ic)
                                            return "";
                                        if (ic.indexOf("/") === 0)
                                            return "file://" + ic;
                                        return Quickshell.iconPath(ic, true);
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    StyledText {
                                        Layout.fillWidth: true
                                        text: String(appRowCard.modelData.name || appRowCard.modelData.id || "")
                                        font.weight: Font.Medium
                                        color: Appearance.colors.colOnLayer0
                                        elide: Text.ElideRight
                                    }
                                    StyledText {
                                        Layout.fillWidth: true
                                        text: String(appRowCard.modelData.id || "")
                                            + (appRowCard.modelData.hasIconOverride ? " • " + Translation.tr("Customized") : "")
                                            + (appRowCard.isHiddenByNexus ? " • " + Translation.tr("Hidden") : (appRowCard.isSystemHidden ? " • " + Translation.tr("System hidden") : ""))
                                        font.pixelSize: Appearance.font.pixelSize.smaller
                                        color: (appRowCard.modelData.hasIconOverride || appRowCard.isHiddenByNexus) ? Appearance.colors.colPrimary : Appearance.colors.colSubtext
                                        elide: Text.ElideRight
                                    }
                                }

                                RippleButton {
                                    visible: !appRowCard.isSystemHidden
                                    Layout.preferredHeight: 32
                                    implicitWidth: appVisRow.implicitWidth + 16
                                    buttonRadius: Appearance.rounding.small
                                    toggled: appRowCard.isHiddenByNexus
                                    colBackground: Appearance.colors.colLayer1Hover
                                    colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                    colBackgroundToggled: Appearance.colors.colSecondaryContainer
                                    colBackgroundToggledHover: Appearance.colors.colSecondaryContainerHover
                                    Accessible.name: appRowCard.isHiddenByNexus
                                        ? Translation.tr("Show in launcher")
                                        : Translation.tr("Hide from launcher")
                                    onClicked: {
                                        if (root.settingsRoot && typeof root.settingsRoot.setAppHidden === "function")
                                            root.settingsRoot.setAppHidden(appRowCard.appId, !appRowCard.isHiddenByNexus);
                                    }
                                    contentItem: RowLayout {
                                        id: appVisRow
                                        anchors.centerIn: parent
                                        spacing: 4
                                        MaterialSymbol {
                                            text: appRowCard.isHiddenByNexus ? "visibility" : "visibility_off"
                                            iconSize: 15
                                            color: appRowCard.isHiddenByNexus ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                        }
                                        StyledText {
                                            text: appRowCard.isHiddenByNexus ? Translation.tr("Show") : Translation.tr("Hide")
                                            font.pixelSize: Appearance.font.pixelSize.smaller
                                            color: appRowCard.isHiddenByNexus ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                        }
                                    }
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                MaterialTextField {
                                    id: appIconInput
                                    Layout.fillWidth: true
                                    placeholderText: Translation.tr("Icon name or file path")
                                    text: String(appRowCard.modelData.icon || "")
                                    onAccepted: {
                                        if (root.settingsRoot && text.trim().length > 0)
                                            root.settingsRoot.setAppIcon(appRowCard.modelData.id, text.trim());
                                    }
                                }

                                RippleButton {
                                    Layout.preferredWidth: 66
                                    Layout.preferredHeight: 36
                                    buttonRadius: Appearance.rounding.small
                                    colBackground: Appearance.colors.colSecondaryContainer
                                    colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                    onClicked: {
                                        if (root.settingsRoot && appIconInput.text.trim().length > 0)
                                            root.settingsRoot.setAppIcon(appRowCard.modelData.id, appIconInput.text.trim());
                                    }
                                    contentItem: StyledText {
                                        text: Translation.tr("Apply")
                                        color: Appearance.colors.colOnSecondaryContainer
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }

                                RippleButton {
                                    visible: appRowCard.modelData.hasIconOverride === true
                                    Layout.preferredWidth: 64
                                    Layout.preferredHeight: 36
                                    buttonRadius: Appearance.rounding.small
                                    colBackground: Appearance.colors.colLayer1Hover
                                    colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                                    onClicked: {
                                        if (root.settingsRoot)
                                            root.settingsRoot.resetAppIcon(appRowCard.modelData.id);
                                    }
                                    contentItem: StyledText {
                                        text: Translation.tr("Reset")
                                        color: Appearance.colors.colOnLayer1
                                        horizontalAlignment: Text.AlignHCenter
                                        verticalAlignment: Text.AlignVCenter
                                    }
                                }
                            }
                        }
                    }
                }

                RippleButton {
                    visible: appIconCustomizerCard.allMatchingApps.length > appIconCustomizerCard.filteredApps.length
                    Layout.fillWidth: true
                    Layout.preferredHeight: 36
                    buttonRadius: Appearance.rounding.small
                    colBackground: Appearance.colors.colLayer1Base
                    colBackgroundHover: Appearance.colors.colLayer1Hover
                    onClicked: root.visibleAppLimit += 48
                    contentItem: StyledText {
                        text: Translation.tr("Show more applications (%1 remaining)").arg(appIconCustomizerCard.allMatchingApps.length - appIconCustomizerCard.filteredApps.length)
                        font.pixelSize: Appearance.font.pixelSize.smaller
                        color: Appearance.colors.colOnLayer1
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        StyledText {
            Layout.fillWidth: true
            visible: !root.embedded && root.renderedSubcategories.length === 0 && !root.isAppsPage
            text: Translation.tr("No additional configurable settings in this category.")
            color: Appearance.colors.colSubtext
            horizontalAlignment: Text.AlignHCenter
        }
    }
}
