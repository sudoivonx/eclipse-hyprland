//@ pragma UseQApplication
//@ pragma Env QS_NO_RELOAD_POPUP=1
//@ pragma Env QT_QUICK_CONTROLS_STYLE=Basic
//@ pragma Env QT_QUICK_FLICKABLE_WHEEL_DECELERATION=10000
//@ pragma Env QT_SCALE_FACTOR=1

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import Quickshell
import Quickshell.Io
import qs.services
import qs.modules.common
import qs.modules.common.widgets
import qs.modules.common.functions as CF

ApplicationWindow {
    id: root

    property string firstRunFilePath: CF.FileUtils.trimFileProtocol(Directories.state + "/user/first_run.txt")
    property string firstRunFileContent: "This file is just here to confirm you've been greeted :>"
    property bool showNextTime: false
    property real contentPadding: 14
    property string searchQuery: ""
    property bool expertMode: true
    property bool copied: false
    property int currentPage: 0
    property string selectedSettingId: ""
    property var settingsCatalog: []
    property var categoryTree: ({})
    property var dynamicCategories: []
    property var searchIndex: []
    property var collapsedCategories: ({})
    property var expandedSubcategories: ({})
    property var initialValues: ({})
    property var initialCursorValues: ({})
    property var initialWindowRules: []
    property bool initialWindowRulesCaptured: false
    property int initialWindowGlowFieldCount: -1
    property int currentWindowGlowFieldCount: -1
    property string initialMotionProfile: ""
    property string currentMotionProfile: ""
    property var initialHyprlandOptions: ({})
    property var currentHyprlandOptions: ({})
    property bool hyprlandOptionsRuntimeVerified: false
    property var externalSettingValues: ({})
    property var initialExternalSettingValues: ({})
    property int externalValuesRevision: 0
    property var appsCatalog: []
    property var installedIconThemes: []
    property bool appsCatalogLoading: false
    property bool adapterSetBusy: false
    property var adapterSetQueue: []
    property bool baselineMigrationAttempted: false
    property var cursorCurrentValues: ({})
    property var cursorThemeChoices: []
    property int currentWindowRuleCount: -1
    property bool cursorRuntimeVerified: false
    property bool initialStateReady: false
    property string nexusStatusText: ""
    property bool nexusActionBusy: false
    property var pendingNexusArgs: []
    property string pendingNexusText: ""
    property bool showSupplementalControls: false
    readonly property string nexusStateRoot: (Quickshell.env("XDG_STATE_HOME") || (Quickshell.env("HOME") + "/.local/state")) + "/aegis/nexus"
    readonly property string nexusScriptPath: CF.FileUtils.trimFileProtocol(Directories.config) + "/quickshell/ii/modules/settings/nexus-settings.py"
    readonly property string nexusCatalogPath: CF.FileUtils.trimFileProtocol(Directories.config) + "/quickshell/ii/modules/settings/nexus-settings.json"
    readonly property string nexusInitialStatePath: nexusStateRoot + "/initial-state.json"
    readonly property string categoryTreeSchema: "nexus-category-tree-v1"
    property var pages: [
    ].concat(root.resolveDynamicPages(root.dynamicCategories, root.categoryComponentDescriptors, root.utilityPages))
    readonly property var utilityPages: [
        {
            pageKey: "utility:nexus",
            name: Translation.tr("NEXUS"),
            icon: "hub",
            component: "modules/settings/NexusProfiles.qml",
            summary: Translation.tr("Profiles, starting values and safe rollback."),
            sections: [Translation.tr("Saved profiles"), Translation.tr("Starting values"), Translation.tr("Undo and recovery")],
            keywords: "nexus profile save load copy defaults reset undo rollback recovery yedek başlangıç varsayılan"
        }
    ]
    readonly property var categoryComponentDescriptors: [
        {
            name: Translation.tr("Quick"),
            categoryId: "quick",
            category: "Quick",
            icon: "instant_mix",
            component: "modules/settings/QuickConfig.qml",
            summary: Translation.tr("Wallpaper, colors, bar placement and screen appearance."),
            sections: [Translation.tr("Wallpaper & Colors"), Translation.tr("Bar & screen")],
            keywords: "wallpaper colors palette matugen dark light theme bar screen position style round corner"
        },
        {
            name: Translation.tr("General"),
            categoryId: "general",
            category: "General",
            icon: "browse",
            component: "modules/settings/GeneralConfig.qml",
            summary: Translation.tr("Audio, battery, language, policies, sounds and time."),
            sections: [Translation.tr("Audio"), Translation.tr("Battery"), Translation.tr("Language"), Translation.tr("Policies"), Translation.tr("Sounds"), Translation.tr("Time"), Translation.tr("Work safety")],
            keywords: "audio volume earbang microphone battery charging health language interface translation policies sounds time clock format safety"
        },
        {
            name: Translation.tr("Bar"),
            categoryId: "bar",
            category: "Bar",
            icon: "toast",
            iconRotation: 180,
            component: "modules/settings/BarConfig.qml",
            summary: Translation.tr("Notifications, layout, tray, utility buttons and workspaces."),
            sections: [Translation.tr("Notifications"), Translation.tr("Positioning"), Translation.tr("Floating Island"), Translation.tr("Tray"), Translation.tr("Utility buttons"), Translation.tr("Weather"), Translation.tr("Workspaces"), Translation.tr("Tooltips")],
            keywords: "notifications unread count position corner group floating island height width glass accent controls tray utility weather workspaces tooltips"
        },
        {
            name: Translation.tr("Background"),
            categoryId: "background",
            category: "Background",
            icon: "texture",
            component: "modules/settings/BackgroundConfig.qml",
            summary: Translation.tr("Parallax, clock styles and weather widgets."),
            sections: [Translation.tr("Parallax"), Translation.tr("Widget: Clock"), Translation.tr("Widget: Weather")],
            keywords: "background parallax vertical horizontal workspace clock digital analog locked cookie dial hour minute second hand date quote weather"
        },
        {
            name: Translation.tr("Interface"),
            categoryId: "interface",
            category: "Interface",
            icon: "bottom_app_bar",
            component: "modules/settings/InterfaceConfig.qml",
            summary: Translation.tr("Dock, lock screen, overlays, sidebars, OSD, overview and fonts."),
            sections: [Translation.tr("Cheat sheet"), Translation.tr("Dock"), Translation.tr("Lock screen"), Translation.tr("Notifications"), Translation.tr("Overlay: General"), Translation.tr("Overlay: Crosshair"), Translation.tr("Overlay: Floating Image"), Translation.tr("Region selector (screen snipping/Google Lens)"), Translation.tr("Sidebars"), Translation.tr("On-screen display"), Translation.tr("Overview"), Translation.tr("Wallpaper selector"), Translation.tr("Fonts")],
            keywords: "interface cheatsheet super key symbol dock lock screen security style blurred notifications monitor overlay crosshair floating image screen snip screenshot google lens region rectangular circle sidebars quick toggles sliders osd overview wallpaper selector font main numbers title monospace nerd reading expressive"
        },
        {
            name: Translation.tr("Input"),
            categoryId: "input",
            category: "Input",
            icon: "mouse",
            component: "modules/settings/CursorConfig.qml",
            summary: Translation.tr("Scrolling, interaction behavior, cursor theme and size."),
            sections: [Translation.tr("Interactions"), Translation.tr("Cursor theme"), Translation.tr("Cursor size")],
            keywords: "cursor theme size pointer mouse gtk flatpak xwayland interactions scrolling touchpad wheel dead pixel fare imleç tema boyut"
        },
        {
            name: Translation.tr("Services"),
            categoryId: "services",
            category: "Services",
            icon: "settings",
            component: "modules/settings/ServicesConfig.qml",
            summary: Translation.tr("AI, music recognition, networking, search, paths and weather."),
            sections: [Translation.tr("AI"), Translation.tr("Music Recognition"), Translation.tr("Networking"), Translation.tr("Resources"), Translation.tr("Save paths"), Translation.tr("Search"), Translation.tr("Weather")],
            keywords: "services ai model prompt music recognition networking resources save paths screenshot video search prefixes web search weather"
        },
        {
            name: "Görünüm",
            categoryId: "appearance",
            category: "Appearance",
            expertOnly: true,
            icon: "palette",
            component: "modules/settings/AppearanceConfig.qml",
            summary: "Renk üretimi, sistem ikon temaları, GTK/Qt temaları, yazı tipleri ve duvar kağıdı paleti.",
            sections: ["Renk üretimi", "Sistem ikonları ve temalar", "GTK ve Qt uygulamaları", "Terminal renkleri"],
            keywords: "appearance look color generation matugen wallpaper shell utilities qt gtk kde icon icons icon theme ikon simge font dark theme görünüm renk üretimi duvar kağıdı palet uygulama teması"
        },
        {
            name: "Hyprland",
            categoryId: "hyprland",
            category: "Hyprland",
            icon: "deployed_code",
            component: "modules/settings/DynamicCategoryConfig.qml",
            summary: "Kenarlıklar, bulanıklık, gölgeler, animasyonlar, klavye/touchpad, VRR, başlangıç, ortam ve kısayollar.",
            sections: ["Layout & Borders", "Blur", "Shadows & Dimming", "Animations", "Input & Keyboard", "Misc", "Startup, Env & Keybinds"],
            keywords: "hyprland border gaps rounding blur shadow opacity dim animations gestures keyboard layout klavye touchpad vrr xwayland zoom autostart startup env keybinds shortcut kisayol"
        },
        {
            name: Translation.tr("Applications & Icons"),
            categoryId: "apps",
            category: "Applications",
            icon: "apps",
            component: "modules/settings/DynamicCategoryConfig.qml",
            summary: Translation.tr("Default apps, per-app desktop & Hyprland icons, and launcher visibility."),
            sections: [Translation.tr("Application Icons"), Translation.tr("Default Applications")],
            keywords: "apps applications icons desktop launcher dock hyprland default browser file manager editor pdf video audio icon override uygulama simge ikon tarayici dosya"
        },
        {
            name: "Pencereler",
            categoryId: "windows",
            category: "Windows",
            expertOnly: true,
            icon: "window",
            component: "modules/settings/WindowsConfig.qml",
            summary: "Pencere aralıkları, köşe görünümü, davranışları, kuralları ve cam efektleri.",
            sections: ["Pencere aralıkları ve köşeler", "Pencere Glow", "Pencere davranışı", "Opaklık istisnaları", "Resim içinde resim", "Özel pencereler", "Cam bulanıklığı"],
            keywords: "windows window gaps rounding rules opacity fullscreen pip blur acrylic glow pencereler pencere aralık boşluk yuvarlak köşe kurallar opaklık saydamlık resim içinde resim cam"
        },
        {
            name: "Efektler",
            categoryId: "effects",
            category: "Effects",
            expertOnly: true,
            icon: "auto_awesome",
            component: "modules/settings/EffectsConfig.qml",
            summary: "Bildirimlerin cam görünümü, rengi ve animasyonları.",
            sections: ["Bildirim Liquid Glass"],
            keywords: "effects notifications liquid glass transparency reflection neon source profile animation efektler bildirim cam saydamlık yansıma renk animasyon"
        },
        {
            name: "Hareket",
            categoryId: "motion",
            category: "Motion",
            expertOnly: true,
            icon: "animation",
            component: "modules/settings/MotionConfig.qml",
            summary: "Sistem hareket profili ve duvar kağıdı geçişleri.",
            sections: ["Hareket yoğunluğu", "Duvar kağıdı geçişleri"],
            keywords: "motion animations profile wallpaper transitions movement duration type hareket animasyon profil duvar kağıdı geçiş süre"
        },
        {
            name: "Ses",
            categoryId: "audio",
            category: "Audio",
            expertOnly: true,
            icon: "equalizer",
            component: "modules/settings/AudioConfig.qml",
            summary: "Ses görselleştiricisinin görünümü ve tepkisi.",
            sections: ["Ses görselleştirici"],
            keywords: "audio visualizer bars sensitivity smoothing style sound ses görselleştirici çubuk hassasiyet yumuşatma stil"
        },
        {
            name: "Oyun",
            categoryId: "gaming",
            category: "Gaming",
            expertOnly: true,
            icon: "sports_esports",
            component: "modules/settings/GamingConfig.qml",
            summary: "Pulsar oyun modu ve otomatik etkinleştirme.",
            sections: ["Pulsar Game Mode"],
            keywords: "gaming games game mode pulsar automatic oyun oyun modu otomatik"
        },
        {
            name: Translation.tr("NEXUS"),
            icon: "hub",
            component: "modules/settings/NexusProfiles.qml",
            summary: Translation.tr("Profiles, starting values and safe rollback."),
            sections: [Translation.tr("Saved profiles"), Translation.tr("Starting values"), Translation.tr("Undo and recovery")],
            keywords: "nexus profile save load copy defaults reset undo rollback recovery yedek başlangıç varsayılan"
        }
    ]
    readonly property var matchingPages: {
        const query = root.searchQuery.trim().toLocaleLowerCase();
        const candidates = root.pages.filter(page => (root.expertMode || page.expertOnly !== true) && (page.settingCount === undefined || page.settingCount > 0));
        if (query.length === 0)
            return candidates;
        return candidates.filter(page => {
            const subcatTitles = (page.subcategories || []).map(sub => sub.title || "").join(" ");
            const searchable = [page.name, page.summary, page.keywords, (page.sections || []).join(" "), subcatTitles].join(" ").toLocaleLowerCase();
            return searchable.includes(query);
        });
    }
    readonly property var matchingSettings: {
        const query = root.searchQuery.trim().toLocaleLowerCase();
        if (query.length === 0)
            return [];
        const indexMap = {};
        for (let i = 0; i < root.searchIndex.length; ++i) {
            const entry = root.searchIndex[i];
            if (entry && entry.id)
                indexMap[entry.id] = entry;
        }
        return root.settingsCatalog.filter(setting => {
            if (!root.isVerifiedSetting(setting))
                return false;
            if (!root.expertMode && (setting.expertOnly === true || root.isExpertCategory(setting.category)))
                return false;
            const idxEntry = indexMap[setting.id];
            if (idxEntry && idxEntry.manageable === false)
                return false;
            const idxKeywords = idxEntry ? root.toList(idxEntry.keywords).join(" ") : "";
            const idxCategory = idxEntry ? [idxEntry.categoryId || "", idxEntry.subcategoryId || ""].join(" ") : "";
            const searchable = [setting.title, setting.description, setting.category, setting.id, root.toList(setting.keywords).join(" "), idxKeywords, idxCategory].join(" ").toLocaleLowerCase();
            return searchable.includes(query);
        });
    }
    readonly property var navigationItems: {
        const items = root.matchingPages.map(page => ({ kind: "category", page: page }));
        for (let i = 0; i < root.matchingSettings.length; ++i)
            items.push({ kind: "setting", setting: root.matchingSettings[i] });
        return items;
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

    function isVerifiedSetting(setting) {
        if (!setting)
            return false;
        if (setting.status === "adapter-review-required")
            return false;
        if (setting.verification) {
            if (setting.verification.verified === false)
                return false;
            if (setting.verification.manageable === false)
                return false;
            if (setting.verification.applicable === false)
                return false;
        }
        const tags = setting.semantics ? root.toList(setting.semantics.tags) : [];
        if (tags.indexOf("complex-object-list") >= 0)
            return false;
        return !setting.verification || setting.verification.verified === true;
    }

    function isUniversalAdapterSource(sourceKind) {
        return sourceKind === "desktop-appearance-adapter"
            || sourceKind === "app-customization-adapter"
            || sourceKind === "hyprland-godmode-adapter"
            || sourceKind === "hyprland-options-adapter";
    }

    function isSupplementalSetting(setting) {
        if (!setting || !root.isVerifiedSetting(setting))
            return false;
        if (setting.sourceKind !== "config-json" && !root.isUniversalAdapterSource(setting.sourceKind))
            return false;
        if (setting.controlType === "readonly-info" || setting.controlType === "custom-editor")
            return false;
        const tags = setting.semantics ? root.toList(setting.semantics.tags) : [];
        return tags.indexOf("has-static-ui") < 0 && tags.indexOf("complex-object-list") < 0;
    }

    function supplementalCountForPage(pageObj) {
        if (!pageObj || !pageObj.categoryId)
            return 0;
        if (pageObj.component === "modules/settings/DynamicCategoryConfig.qml"
            || pageObj.component === "modules/settings/CursorConfig.qml")
            return 0;
        const targetId = String(pageObj.categoryId).toLocaleLowerCase();
        let count = 0;
        for (let i = 0; i < root.settingsCatalog.length; ++i) {
            const s = root.settingsCatalog[i];
            if (s && String(s.categoryId || "").toLocaleLowerCase() === targetId && root.isSupplementalSetting(s))
                ++count;
        }
        return count;
    }

    function supplementalTabLabel(pageObj) {
        const count = root.supplementalCountForPage(pageObj);
        const catId = pageObj && pageObj.categoryId ? String(pageObj.categoryId).toLocaleLowerCase() : "";
        if (catId === "appearance")
            return Translation.tr("Desktop, Icons & GTK/Qt") + " (" + String(count) + ")";
        return Translation.tr("Additional settings") + " (" + String(count) + ")";
    }

    function currentPageObject() {
        if (!root.pages || root.pages.length === 0)
            return null;
        const idx = Math.max(0, Math.min(root.currentPage, root.pages.length - 1));
        return root.pages[idx];
    }

    function resolveDynamicPages(categories, descriptors, utilities) {
        const descriptorList = descriptors || [];
        const utilityList = utilities || [];
        const validCategories = (categories || []).filter(cat => cat && cat.settingCount > 0);
        if (validCategories.length === 0)
            return descriptorList;
        const resolved = [];
        const seenComponents = {};
        for (let i = 0; i < validCategories.length; ++i) {
            const cat = validCategories[i];
            const catId = String(cat.id || "").toLocaleLowerCase();
            const catTitle = String(cat.title || "");
            let matched = null;
            for (let j = 0; j < descriptorList.length; ++j) {
                const desc = descriptorList[j];
                if ((desc.categoryId && desc.categoryId.toLocaleLowerCase() === catId)
                    || (desc.category && desc.category.toLocaleLowerCase() === catId)
                    || (desc.name && desc.name.toLocaleLowerCase() === catTitle.toLocaleLowerCase())) {
                    matched = desc;
                    break;
                }
            }
            const subcats = root.toList(cat.subcategories).filter(sub => !sub.settingIds || root.toList(sub.settingIds).length > 0);
            const subcatSections = subcats.map(sub => sub.title).filter(title => title && title.length > 0);
            const componentPath = (matched && matched.component) ? matched.component : (cat.component || "modules/settings/DynamicCategoryConfig.qml");
            const isCollapsed = root.collapsedCategories[cat.id] === true;
            const pageObj = {
                pageKey: "cat:" + catId,
                name: matched ? matched.name : (cat.title || cat.id),
                categoryId: cat.id,
                category: (matched && matched.category) ? matched.category : (cat.title || cat.id),
                expertOnly: cat.expertOnly === true || (matched ? matched.expertOnly === true : false),
                icon: (matched && matched.icon) ? matched.icon : (cat.icon || "tune"),
                iconRotation: (matched && matched.iconRotation) ? matched.iconRotation : 0,
                component: componentPath,
                summary: (matched && matched.summary) ? matched.summary : (cat.summary || ""),
                sections: subcatSections.length > 0 ? subcatSections : ((matched && matched.sections) ? matched.sections : []),
                subcategories: subcats,
                settingIds: root.toList(cat.settingIds),
                settingCount: Number(cat.settingCount || 0),
                expanded: !isCollapsed,
                collapsed: isCollapsed,
                keywords: [(matched && matched.keywords) ? matched.keywords : "", cat.id || "", cat.title || "", subcatSections.join(" ")].join(" ")
            };
            resolved.push(pageObj);
            if (componentPath !== "modules/settings/DynamicCategoryConfig.qml")
                seenComponents[componentPath] = true;
        }
        for (let k = 0; k < utilityList.length; ++k) {
            if (!seenComponents[utilityList[k].component])
                resolved.push(utilityList[k]);
        }
        return resolved;
    }

    function toggleCategoryCollapsed(categoryId) {
        if (!categoryId)
            return;
        const next = Object.assign({}, root.collapsedCategories);
        next[categoryId] = !next[categoryId];
        root.collapsedCategories = next;
    }

    function isSubcategoryExpanded(subcategoryId) {
        if (!subcategoryId)
            return true;
        return root.expandedSubcategories[subcategoryId] !== false;
    }

    function toggleSubcategoryExpanded(subcategoryId) {
        if (!subcategoryId)
            return;
        const next = Object.assign({}, root.expandedSubcategories);
        next[subcategoryId] = !root.isSubcategoryExpanded(subcategoryId);
        root.expandedSubcategories = next;
    }

    function refreshCatalogState() {
        catalogStateProcess.exec(["python3", root.nexusScriptPath, "catalog-state", "--json"]);
    }

    function acceptCatalogState(response) {
        if (!response || typeof response !== "object")
            return;
        const prevById = {};
        for (let i = 0; i < root.settingsCatalog.length; ++i) {
            const prev = root.settingsCatalog[i];
            if (prev && prev.id)
                prevById[prev.id] = prev;
        }

        const tree = response.categoryTree || response.tree || (response.schema === root.categoryTreeSchema ? response : null);
        if (tree && Array.isArray(tree.categories)) {
            root.categoryTree = tree;
            root.dynamicCategories = tree.categories.filter(cat => cat && cat.settingCount > 0);
            root.searchIndex = Array.isArray(tree.searchIndex)
                ? tree.searchIndex.filter(entry => entry && entry.manageable !== false)
                : [];
        }

        const catById = {};
        for (let i = 0; i < root.dynamicCategories.length; ++i) {
            const cat = root.dynamicCategories[i];
            if (cat && cat.id)
                catById[String(cat.id).toLocaleLowerCase()] = cat;
        }
        const descById = {};
        for (let i = 0; i < root.categoryComponentDescriptors.length; ++i) {
            const desc = root.categoryComponentDescriptors[i];
            if (desc && desc.categoryId)
                descById[String(desc.categoryId).toLocaleLowerCase()] = desc;
        }
        const assignments = (root.categoryTree && root.categoryTree.assignments) ? root.categoryTree.assignments : {};

        if (Array.isArray(response.definitions) && response.definitions.length > 0) {
            const merged = [];
            for (let i = 0; i < response.definitions.length; ++i) {
                const rawSetting = response.definitions[i];
                if (!root.isVerifiedSetting(rawSetting))
                    continue;
                const assign = assignments[rawSetting.id] || null;
                const prev = prevById[rawSetting.id] || null;
                const catId = assign && assign.categoryId
                    ? String(assign.categoryId)
                    : String((prev && (prev.categoryId || prev.category)) || rawSetting.categoryId || rawSetting.category || "").toLocaleLowerCase();
                const catIdLower = catId.toLocaleLowerCase();
                const subId = assign && assign.subcategoryId ? String(assign.subcategoryId) : "";
                const catObj = catById[catIdLower] || null;
                const desc = descById[catIdLower] || null;
                const resolvedCategory = (desc && desc.category)
                    ? desc.category
                    : (catObj && catObj.title ? catObj.title : ((prev && prev.category) || rawSetting.category || catId));
                const resolvedComponent = (desc && desc.component)
                    ? desc.component
                    : ((catObj && catObj.component) ? catObj.component : "modules/settings/DynamicCategoryConfig.qml");
                const resolvedExpertOnly = (catObj && catObj.expertOnly === true)
                    || (desc && desc.expertOnly === true)
                    || (prev && prev.expertOnly === true)
                    || rawSetting.expertOnly === true;
                merged.push(Object.assign({}, rawSetting, {
                    categoryId: catId,
                    subcategoryId: subId,
                    category: resolvedCategory,
                    component: resolvedComponent,
                    expertOnly: resolvedExpertOnly
                }));
            }
            root.settingsCatalog = merged;
        }
        if (response.externalSettingValues && typeof response.externalSettingValues === "object") {
            root.externalSettingValues = Object.assign({}, response.externalSettingValues);
            root.externalValuesRevision += 1;
        }
        if (response.initialExternalSettingValues && typeof response.initialExternalSettingValues === "object") {
            root.initialExternalSettingValues = Object.assign({}, root.initialExternalSettingValues, response.initialExternalSettingValues);
        }
        root.maybeMigrateGodMenuBaseline();
        if (root.currentPage >= root.pages.length)
            root.currentPage = Math.max(0, root.pages.length - 1);
    }

    function pageIndexForPage(page) {
        if (!page)
            return 0;
        if (page.pageKey) {
            for (let i = 0; i < root.pages.length; ++i) {
                if (root.pages[i].pageKey === page.pageKey)
                    return i;
            }
        }
        if (page.categoryId) {
            const cid = String(page.categoryId).toLocaleLowerCase();
            for (let i = 0; i < root.pages.length; ++i) {
                if (String(root.pages[i].categoryId || "").toLocaleLowerCase() === cid)
                    return i;
            }
        }
        if (page.category) {
            const cname = String(page.category).toLocaleLowerCase();
            for (let i = 0; i < root.pages.length; ++i) {
                if (String(root.pages[i].category || "").toLocaleLowerCase() === cname)
                    return i;
            }
        }
        if (page.component) {
            for (let i = 0; i < root.pages.length; ++i) {
                if (root.pages[i].component === page.component)
                    return i;
            }
        }
        return 0;
    }

    function pageIndexForSetting(setting) {
        if (!setting)
            return 0;
        const assignments = (root.categoryTree && root.categoryTree.assignments) ? root.categoryTree.assignments : {};
        const assign = assignments[setting.id] || null;
        const cid = String((assign && assign.categoryId) || setting.categoryId || setting.category || "").toLocaleLowerCase();
        if (cid) {
            for (let i = 0; i < root.pages.length; ++i) {
                const p = root.pages[i];
                if (String(p.categoryId || "").toLocaleLowerCase() === cid
                    || String(p.category || "").toLocaleLowerCase() === cid)
                    return i;
            }
        }
        if (setting.component)
            return root.pageIndexFor(setting.component);
        return 0;
    }

    function pageIndexFor(componentPath) {
        for (let i = 0; i < root.pages.length; ++i) {
            if (root.pages[i].pageKey === componentPath
                || root.pages[i].categoryId === componentPath
                || root.pages[i].component === componentPath)
                return i;
        }
        return 0;
    }

    function selectPage(page) {
        root.selectedSettingId = "";
        root.showSupplementalControls = false;
        root.currentPage = root.pageIndexForPage(page);
    }

    function selectSetting(setting) {
        if (!setting)
            return;
        root.selectedSettingId = setting.id;
        root.currentPage = root.pageIndexForSetting(setting);
        const curPage = root.currentPageObject();
        if (curPage && curPage.component !== "modules/settings/DynamicCategoryConfig.qml" && root.isSupplementalSetting(setting))
            root.showSupplementalControls = true;
        else
            root.showSupplementalControls = false;
    }

    function selectedDefinition() {
        for (let i = 0; i < root.settingsCatalog.length; ++i) {
            if (root.settingsCatalog[i].id === root.selectedSettingId)
                return root.settingsCatalog[i];
        }
        return null;
    }

    function isExpertCategory(category) {
        const target = String(category || "").toLocaleLowerCase();
        return root.pages.some(page => (
            page.category === category
            || page.categoryId === category
            || (target.length > 0 && (String(page.category || "").toLocaleLowerCase() === target || String(page.categoryId || "").toLocaleLowerCase() === target))
        ) && page.expertOnly === true);
    }

    function categoryDisplayName(category) {
        const target = String(category || "").toLocaleLowerCase();
        for (let i = 0; i < root.pages.length; ++i) {
            const p = root.pages[i];
            if (p.category === category
                || p.categoryId === category
                || (target.length > 0 && (String(p.category || "").toLocaleLowerCase() === target || String(p.categoryId || "").toLocaleLowerCase() === target)))
                return p.name;
        }
        return category;
    }

    function categoryForPage(componentPath) {
        const cur = root.currentPageObject();
        if (cur && cur.component === componentPath && (cur.category || cur.categoryId))
            return cur.category || cur.categoryId;
        for (let i = 0; i < root.pages.length; ++i) {
            if (root.pages[i].component === componentPath && root.pages[i].category)
                return root.pages[i].category;
        }
        for (let i = 0; i < root.settingsCatalog.length; ++i) {
            if (root.settingsCatalog[i].component === componentPath)
                return root.settingsCatalog[i].category;
        }
        return "";
    }

    function safeSettingCount(category) {
        const target = String(category || "").toLocaleLowerCase();
        if (!target)
            return 0;
        let count = 0;
        for (let i = 0; i < root.settingsCatalog.length; ++i) {
            const setting = root.settingsCatalog[i];
            if ((setting.category === category
                    || String(setting.category || "").toLocaleLowerCase() === target
                    || String(setting.categoryId || "").toLocaleLowerCase() === target)
                && root.isVerifiedSetting(setting)
                && root.hasInitialValue(setting)
                && setting.resetSupported)
                ++count;
        }
        return count;
    }

    function valueAt(path) {
        if (!path)
            return undefined;
        let value = Config.options;
        const parts = path.split(".");
        for (let i = 0; i < parts.length; ++i) {
            if (value === null || value === undefined || typeof value !== "object" || !(parts[i] in value))
                return undefined;
            value = value[parts[i]];
        }
        return value;
    }

    function displayValue(setting, initial) {
        if (!setting)
            return Translation.tr("Not verified in this session");
        if (setting.sourceKind === "cursor-adapter") {
            const key = setting.path.replace("cursor.", "");
            const values = initial ? root.initialCursorValues : root.cursorCurrentValues;
            if (!values || !(key in values))
                return Translation.tr("Not available");
            return String(values[key]);
        }
        if (setting.sourceKind === "window-rule-adapter") {
            const count = initial
                ? (root.initialWindowRulesCaptured ? root.initialWindowRules.length : -1)
                : root.currentWindowRuleCount;
            if (count < 0)
                return Translation.tr("Not available");
            return String(count) + (count === 1 ? " saved window rule" : " saved window rules")
                + Translation.tr("; live effect not verified");
        }
        if (setting.sourceKind === "window-glow-adapter") {
            const count = initial
                ? root.initialWindowGlowFieldCount
                : root.currentWindowGlowFieldCount;
            if (count < 0)
                return Translation.tr("Not available");
            return String(count) + Translation.tr(" saved glow values; visual effect not verified");
        }
        if (setting.sourceKind === "motion-profile-adapter") {
            const profile = initial ? root.initialMotionProfile : root.currentMotionProfile;
            return profile.length > 0 ? profile : Translation.tr("Not available");
        }
        if (setting.sourceKind === "hyprland-options-adapter") {
            const values = initial ? root.initialHyprlandOptions : root.currentHyprlandOptions;
            if (!values || !(setting.id in values))
                return Translation.tr("Not available");
            return String(values[setting.id]) + Translation.tr(" px");
        }
        if (root.isUniversalAdapterSource(setting.sourceKind)) {
            const _rev = root.externalValuesRevision;
            const values = initial ? root.initialExternalSettingValues : root.externalSettingValues;
            if (!values || !(setting.id in values))
                return Translation.tr("Not available");
            const val = values[setting.id];
            if (typeof val === "boolean")
                return val ? Translation.tr("On") : Translation.tr("Off");
            if (typeof val === "object") {
                const serialized = JSON.stringify(val);
                return serialized.length > 96 ? serialized.slice(0, 93) + "…" : serialized;
            }
            const text = String(val);
            return text.length > 96 ? text.slice(0, 93) + "…" : text;
        }
        if (setting.sourceKind !== "config-json")
            return Translation.tr("Not verified in this session");
        if (setting.sensitive)
            return Translation.tr("Hidden for privacy");
        const values = initial ? root.initialValues : null;
        const value = initial ? (values && setting.path in values ? values[setting.path] : undefined) : root.valueAt(setting.path);
        if (value === undefined)
            return Translation.tr("Not available");
        if (typeof value === "boolean")
            return value ? Translation.tr("On") : Translation.tr("Off");
        if (typeof value === "object") {
            const serialized = JSON.stringify(value);
            return serialized.length > 96 ? serialized.slice(0, 93) + "…" : serialized;
        }
        const text = String(value);
        return text.length > 96 ? text.slice(0, 93) + "…" : text;
    }

    function hasInitialValue(setting) {
        if (!setting || !root.initialStateReady)
            return false;
        if (setting.sourceKind === "cursor-adapter") {
            const key = setting.path.replace("cursor.", "");
            return root.initialCursorValues && key in root.initialCursorValues;
        }
        if (setting.sourceKind === "window-rule-adapter")
            return root.initialWindowRulesCaptured;
        if (setting.sourceKind === "window-glow-adapter")
            return root.initialWindowGlowFieldCount >= 0;
        if (setting.sourceKind === "motion-profile-adapter")
            return root.initialMotionProfile.length > 0;
        if (setting.sourceKind === "hyprland-options-adapter")
            return root.initialHyprlandOptions && setting.id in root.initialHyprlandOptions;
        if (root.isUniversalAdapterSource(setting.sourceKind))
            return root.initialExternalSettingValues && setting.id in root.initialExternalSettingValues;
        return setting.sourceKind === "config-json" && root.initialValues && setting.path in root.initialValues;
    }

    function acceptCursorStatus(response) {
        if (!response || response.status !== "ok")
            return;
        root.cursorCurrentValues = response.current || {};
        root.cursorThemeChoices = response.themes || [];
        root.cursorRuntimeVerified = response.runtimeVerified === true;
    }

    function refreshCursorStatus() {
        cursorStatusProcess.exec(["python3", root.nexusScriptPath, "cursor-status"]);
    }

    function refreshWindowRuleStatus() {
        windowRuleStatusProcess.exec(["python3", root.nexusScriptPath, "window-rules-status"]);
    }

    function refreshWindowGlowStatus() {
        windowGlowStatusProcess.exec(["python3", root.nexusScriptPath, "window-glow-status"]);
    }

    function refreshMotionProfileStatus() {
        motionProfileStatusProcess.exec(["python3", root.nexusScriptPath, "motion-profile-status"]);
    }

    function refreshHyprlandOptionsStatus() {
        hyprlandOptionsStatusProcess.exec(["python3", root.nexusScriptPath, "hyprland-options-status"]);
    }

    function refreshAppsCatalog() {
        if (root.appsCatalogLoading)
            return;
        root.appsCatalogLoading = true;
        appsCatalogProcess.exec(["python3", root.nexusScriptPath, "apps-catalog", "--json"]);
    }

    function _drainAdapterSetQueue() {
        if (root.adapterSetBusy || root.adapterSetQueue.length === 0)
            return;
        const next = root.adapterSetQueue[0];
        root.adapterSetQueue = root.adapterSetQueue.slice(1);
        root.adapterSetBusy = true;
        root.nexusStatusText = Translation.tr("Applying…");
        adapterSetProcess.currentSettingId = next.settingId || "";
        adapterSetProcess.currentAppAction = next.appAction === true;
        adapterSetProcess.exec(["python3", root.nexusScriptPath].concat(next.args));
    }

    function maybeMigrateGodMenuBaseline() {
        if (root.baselineMigrationAttempted || !root.initialStateReady)
            return;
        if (Object.keys(root.externalSettingValues || {}).length === 0)
            return;
        if (Object.keys(root.initialExternalSettingValues || {}).length > 0)
            return;
        root.baselineMigrationAttempted = true;
        baselineMigrateProcess.exec(["python3", root.nexusScriptPath, "initialize"]);
    }

    function setAdapterSetting(settingId, value) {
        if (!settingId)
            return false;
        const sid = String(settingId);
        const item = {
            settingId: sid,
            appAction: sid.indexOf("apps.") === 0,
            args: ["setting-set", sid, JSON.stringify(value)]
        };
        const nextQueue = [];
        let replaced = false;
        for (let i = 0; i < root.adapterSetQueue.length; ++i) {
            const existing = root.adapterSetQueue[i];
            if (existing && existing.settingId === sid && existing.args && existing.args[0] === "setting-set") {
                nextQueue.push(item);
                replaced = true;
            } else {
                nextQueue.push(existing);
            }
        }
        if (!replaced)
            nextQueue.push(item);
        root.adapterSetQueue = nextQueue;
        root._drainAdapterSetQueue();
        return true;
    }

    function setAppIcon(appId, iconNameOrPath) {
        if (!appId || !iconNameOrPath)
            return false;
        root.adapterSetQueue = root.adapterSetQueue.concat([{
            settingId: "apps.icons.overrides",
            appAction: true,
            args: ["app-icon-set", String(appId), String(iconNameOrPath)]
        }]);
        root._drainAdapterSetQueue();
        return true;
    }

    function resetAppIcon(appId) {
        if (!appId)
            return false;
        root.adapterSetQueue = root.adapterSetQueue.concat([{
            settingId: "apps.icons.overrides",
            appAction: true,
            args: ["app-icon-reset", String(appId)]
        }]);
        root._drainAdapterSetQueue();
        return true;
    }

    function setAppHidden(appId, hideApp) {
        const cleanId = String(appId || "").trim();
        if (!cleanId)
            return false;
        root.adapterSetQueue = root.adapterSetQueue.concat([{
            settingId: "apps.visibility.hiddenApps",
            appAction: true,
            args: ["app-visibility-set", cleanId, hideApp ? "hide" : "show"]
        }]);
        root._drainAdapterSetQueue();
        return true;
    }

    function categoryNeedsRiskConfirmation(category) {
        const target = String(category || "").toLocaleLowerCase();
        return root.settingsCatalog.some(setting => (
            setting.category === category
            || (target.length > 0 && (String(setting.category || "").toLocaleLowerCase() === target || String(setting.categoryId || "").toLocaleLowerCase() === target))
        ) && setting.resetSupported && setting.risk === "confirmation-required");
    }

    function reloadInitialState() {
        nexusInitialFile.reload();
    }

    function searchNextMatch() {
        if (root.matchingSettings.length > 0) {
            root.selectSetting(root.matchingSettings[0]);
            return;
        }
        if (root.matchingPages.length > 0)
            root.selectPage(root.matchingPages[0]);
    }

    function confirmNexusAction(args, message) {
        root.pendingNexusArgs = args;
        root.pendingNexusText = message;
        nexusConfirmDialog.open();
    }

    function runNexusAction(args) {
        if (root.nexusActionBusy)
            return;
        root.nexusActionBusy = true;
        root.nexusStatusText = Translation.tr("Working…");
        nexusActionProcess.exec(["python3", root.nexusScriptPath].concat(args));
    }

    function handleNexusResult(exitCode) {
        root.nexusActionBusy = false;
        let response = null;
        try {
            response = JSON.parse(nexusActionOutput.text);
        } catch (error) {
            root.nexusStatusText = Translation.tr("NEXUS could not read the action result. No success was assumed.");
            return;
        }
        if (exitCode !== 0 || response.status === "error") {
            root.nexusStatusText = response.message || Translation.tr("The action failed safely.");
            root.refreshCatalogState();
            root.refreshCursorStatus();
            root.refreshWindowRuleStatus();
            root.refreshWindowGlowStatus();
            root.refreshMotionProfileStatus();
            root.refreshHyprlandOptionsStatus();
            return;
        }
        if (Number(response.unsupportedCount || 0) > 0)
            root.nexusStatusText = Translation.tr("Supported values were restored where a starting value was available; some settings are not ready for reset yet.");
        else if (response.runtimeVerified === true)
            root.nexusStatusText = Translation.tr("The requested Hyprland values were saved and verified live.");
        else if (response.status === "written_to_config" || response.status === "undo_written_to_config")
            root.nexusStatusText = Translation.tr("The settings files were updated. The live application effect has not yet been independently verified.");
        else if (response.status === "no_changes")
            root.nexusStatusText = Translation.tr("This setting already matches its saved starting value.");
        else
            root.nexusStatusText = Translation.tr("Action completed without live runtime verification.");
        root.refreshCatalogState();
        root.refreshAppsCatalog();
        root.refreshCursorStatus();
        root.refreshWindowRuleStatus();
        root.refreshWindowGlowStatus();
        root.refreshMotionProfileStatus();
        root.refreshHyprlandOptionsStatus();
    }

    onSearchQueryChanged: {
        if (root.searchQuery.trim().length === 0) {
            root.selectedSettingId = "";
            return;
        }
        if (root.matchingSettings.length > 0) {
            if (!root.matchingSettings.some(setting => setting.id === root.selectedSettingId))
                root.selectSetting(root.matchingSettings[0]);
            return;
        }
        root.selectedSettingId = "";
        const curPage = root.currentPageObject();
        if (curPage && !root.matchingPages.some(page => (page.pageKey && curPage.pageKey) ? page.pageKey === curPage.pageKey : page.component === curPage.component))
            root.searchNextMatch();
    }

    onExpertModeChanged: {
        const curPage = root.currentPageObject();
        if (!root.expertMode && curPage && curPage.expertOnly === true)
            root.currentPage = 0;
        const selected = root.selectedDefinition();
        if (!root.expertMode && selected && (selected.expertOnly === true || root.isExpertCategory(selected.category)))
            root.selectedSettingId = "";
    }

    visible: true
    onClosing: Qt.quit()
    // Keep the existing Hyprland title match so the settings window retains its current rule.
    title: "illogical-impulse Settings"

    Component.onCompleted: {
        MaterialThemeLoader.reapplyTheme()
        Config.readWriteDelay = 0
        root.refreshCatalogState()
        root.refreshCursorStatus()
        root.refreshWindowRuleStatus()
        root.refreshWindowGlowStatus()
        root.refreshMotionProfileStatus()
        root.refreshHyprlandOptionsStatus()
    }

    FileView {
        id: nexusCatalogFile
        path: root.nexusCatalogPath
        watchChanges: false
        preload: true
        onLoaded: {
            try {
                const payload = JSON.parse(text);
                root.settingsCatalog = (payload.definitions || []).filter(setting => root.isVerifiedSetting(setting));
            } catch (error) {
                root.nexusStatusText = Translation.tr("NEXUS settings catalogue could not be read.");
            }
        }
        onLoadFailed: error => root.nexusStatusText = Translation.tr("NEXUS settings catalogue is unavailable.")
    }

    Process {
        id: catalogStateProcess
        stdout: StdioCollector {
            id: catalogStateOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(catalogStateOutput.text);
                if (exitCode === 0 && (response.status === "ok" || response.schema === root.categoryTreeSchema || response.categoryTree)) {
                    root.acceptCatalogState(response);
                } else {
                    root.nexusStatusText = (response && response.message) ? response.message : Translation.tr("NEXUS category tree is unavailable.");
                }
            } catch (error) {
                root.nexusStatusText = Translation.tr("NEXUS category tree could not be parsed.");
            }
        }
    }

    FileView {
        id: nexusInitialFile
        path: root.nexusInitialStatePath
        watchChanges: false
        preload: true
        onLoaded: {
            try {
                const payload = JSON.parse(text);
                root.initialValues = payload.values || {};
                root.initialCursorValues = payload.externalValues && payload.externalValues.cursor ? payload.externalValues.cursor : {};
                const customWindowRules = payload.externalValues ? payload.externalValues.customWindowRules : undefined;
                root.initialWindowRulesCaptured = Array.isArray(customWindowRules);
                root.initialWindowRules = root.initialWindowRulesCaptured ? customWindowRules : [];
                const windowGlow = payload.externalValues ? payload.externalValues.windowGlow : undefined;
                root.initialWindowGlowFieldCount = windowGlow && typeof windowGlow === "object"
                    ? Object.keys(windowGlow).length : -1;
                root.initialMotionProfile = payload.externalValues && typeof payload.externalValues.motionProfile === "string"
                    ? payload.externalValues.motionProfile : "";
                root.initialHyprlandOptions = payload.externalValues && payload.externalValues.hyprlandOptions
                    ? payload.externalValues.hyprlandOptions : {};
                if (payload.externalValues && payload.externalValues.godMenuValues && typeof payload.externalValues.godMenuValues === "object")
                    root.initialExternalSettingValues = Object.assign({}, root.initialExternalSettingValues, payload.externalValues.godMenuValues);
                root.initialStateReady = true;
                root.maybeMigrateGodMenuBaseline();
            } catch (error) {
                root.initialStateReady = false;
                root.initialWindowRulesCaptured = false;
                root.initialWindowGlowFieldCount = -1;
                root.initialMotionProfile = "";
                root.initialHyprlandOptions = {};
            }
        }
        onLoadFailed: error => {
            root.initialStateReady = false;
            root.initialWindowRulesCaptured = false;
            root.initialWindowGlowFieldCount = -1;
            root.initialMotionProfile = "";
            root.initialHyprlandOptions = {};
        }
    }

    Process {
        id: hyprlandOptionsStatusProcess
        stdout: StdioCollector {
            id: hyprlandOptionsStatusOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(hyprlandOptionsStatusOutput.text);
                if (exitCode === 0 && response.status === "ok") {
                    root.currentHyprlandOptions = response.values || {};
                    root.hyprlandOptionsRuntimeVerified = response.runtimeVerified === true;
                    if (response.values && typeof response.values === "object") {
                        root.externalSettingValues = Object.assign({}, root.externalSettingValues, response.values);
                        root.externalValuesRevision += 1;
                    }
                } else {
                    root.currentHyprlandOptions = {};
                    root.hyprlandOptionsRuntimeVerified = false;
                }
            } catch (error) {
                root.currentHyprlandOptions = {};
                root.hyprlandOptionsRuntimeVerified = false;
            }
        }
    }

    Process {
        id: windowRuleStatusProcess
        stdout: StdioCollector {
            id: windowRuleStatusOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(windowRuleStatusOutput.text);
                root.currentWindowRuleCount = exitCode === 0 && response.status === "ok"
                    ? Number(response.currentCount) : -1;
            } catch (error) {
                root.currentWindowRuleCount = -1;
            }
        }
    }

    Process {
        id: windowGlowStatusProcess
        stdout: StdioCollector {
            id: windowGlowStatusOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(windowGlowStatusOutput.text);
                root.currentWindowGlowFieldCount = exitCode === 0 && response.status === "ok"
                    ? Number(response.fieldCount) : -1;
            } catch (error) {
                root.currentWindowGlowFieldCount = -1;
            }
        }
    }

    Process {
        id: motionProfileStatusProcess
        stdout: StdioCollector {
            id: motionProfileStatusOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(motionProfileStatusOutput.text);
                root.currentMotionProfile = exitCode === 0 && response.status === "ok"
                    ? String(response.profile || "") : "";
            } catch (error) {
                root.currentMotionProfile = "";
            }
        }
    }

    minimumWidth: 860
    minimumHeight: 560
    width: 1320
    height: 800
    color: Appearance.m3colors.m3background

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.contentPadding
        spacing: 12

        Keys.onPressed: event => {
            if (event.modifiers !== Qt.ControlModifier)
                return;
            if (event.key === Qt.Key_PageDown) {
                root.currentPage = Math.min(root.currentPage + 1, root.pages.length - 1);
                event.accepted = true;
            } else if (event.key === Qt.Key_PageUp) {
                root.currentPage = Math.max(root.currentPage - 1, 0);
                event.accepted = true;
            } else if (event.key === Qt.Key_Tab) {
                root.currentPage = (root.currentPage + 1) % root.pages.length;
                event.accepted = true;
            } else if (event.key === Qt.Key_Backtab) {
                root.currentPage = (root.currentPage - 1 + root.pages.length) % root.pages.length;
                event.accepted = true;
            }
        }

        Item {
            visible: Config.options?.windows.showTitlebar
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 62 : 0

            RowLayout {
                anchors.fill: parent
                spacing: 12

                Rectangle {
                    Layout.preferredWidth: 42
                    Layout.preferredHeight: 42
                    radius: Appearance.rounding.small
                    color: Appearance.colors.colSecondaryContainer

                    MaterialSymbol {
                        anchors.centerIn: parent
                        text: "tune"
                        iconSize: 23
                        color: Appearance.colors.colOnSecondaryContainer
                    }
                }

                ColumnLayout {
                    spacing: 1
                    StyledText {
                        text: "NEXUS"
                        font.pixelSize: Appearance.font.pixelSize.larger
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colOnLayer0
                    }
                    StyledText {
                        text: Translation.tr("Control center")
                        font.pixelSize: Appearance.font.pixelSize.small
                        color: Appearance.colors.colSubtext
                    }
                }

                Item { Layout.fillWidth: true }

                StyledText {
                    visible: root.searchQuery.length > 0
                    text: root.matchingPages.length + " " + Translation.tr("matching categories")
                    color: Appearance.colors.colSubtext
                }

                RippleButton {
                    implicitWidth: 42
                    implicitHeight: 42
                    buttonRadius: Appearance.rounding.full
                    onClicked: root.close()
                    contentItem: MaterialSymbol {
                        anchors.centerIn: parent
                        text: "close"
                        iconSize: 20
                        color: Appearance.colors.colOnLayer0
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            Rectangle {
                id: sidebar
                Layout.fillHeight: true
                Layout.preferredWidth: root.width < 1020 ? 220 : 258
                Layout.minimumWidth: 210
                radius: Appearance.rounding.large
                color: Appearance.m3colors.m3surfaceContainerLow

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 46
                        radius: Appearance.rounding.small
                        color: Appearance.colors.colLayer1Base

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 6
                            spacing: 8

                            MaterialSymbol {
                                text: "search"
                                iconSize: 20
                                color: Appearance.colors.colSubtext
                            }

                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true

                                StyledText {
                                    anchors.left: parent.left
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: searchInput.text.length === 0
                                    text: Translation.tr("Search categories and settings")
                                    color: Appearance.colors.colSubtext
                                    font.pixelSize: Appearance.font.pixelSize.small
                                }

                                StyledTextInput {
                                    id: searchInput
                                    anchors.fill: parent
                                    selectByMouse: true
                                    text: root.searchQuery
                                    onTextChanged: root.searchQuery = text
                                    Keys.onPressed: event => {
                                        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                            root.searchNextMatch();
                                            event.accepted = true;
                                        } else if (event.key === Qt.Key_Escape) {
                                            root.searchQuery = "";
                                            event.accepted = true;
                                        }
                                    }
                                }
                            }

                            RippleButton {
                                visible: root.searchQuery.length > 0
                                Layout.preferredWidth: 30
                                Layout.preferredHeight: 30
                                buttonRadius: Appearance.rounding.full
                                onClicked: {
                                    root.searchQuery = "";
                                    searchInput.forceActiveFocus();
                                }
                                contentItem: MaterialSymbol {
                                    anchors.centerIn: parent
                                    text: "close"
                                    iconSize: 17
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText {
                            text: root.searchQuery.trim().length > 0 ? Translation.tr("Matches") : Translation.tr("Categories")
                            font.pixelSize: Appearance.font.pixelSize.small
                            font.weight: Font.DemiBold
                            color: Appearance.colors.colSubtext
                        }
                        Item { Layout.fillWidth: true }
                        StyledText {
                            text: root.searchQuery.trim().length > 0 ? root.navigationItems.length.toString() : root.matchingPages.length + "/" + root.pages.filter(page => root.expertMode || page.expertOnly !== true).length
                            font.pixelSize: Appearance.font.pixelSize.smaller
                            color: Appearance.colors.colSubtext
                        }
                    }

                    ListView {
                        id: pageList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 4
                        model: root.searchQuery.trim().length > 0 ? root.navigationItems : root.matchingPages.map(page => ({ kind: "category", page: page }))

                        delegate: RippleButton {
                            id: categoryButton
                            required property var modelData
                            property bool settingResult: modelData.kind === "setting"
                            property var entry: settingResult ? modelData.setting : modelData.page
                            property int pageIndex: settingResult ? root.pageIndexForSetting(entry) : root.pageIndexForPage(entry)
                            width: pageList.width
                            height: settingResult ? 60 : 52
                            buttonRadius: Appearance.rounding.small
                            toggled: settingResult ? root.selectedSettingId === entry.id : root.selectedSettingId.length === 0 && root.currentPage === pageIndex
                            colBackground: "transparent"
                            colBackgroundHover: Appearance.colors.colLayer1Hover
                            colBackgroundToggled: Appearance.colors.colSecondaryContainer
                            colBackgroundToggledHover: Appearance.colors.colSecondaryContainerHover
                            onClicked: settingResult ? root.selectSetting(entry) : root.selectPage(entry)
                            Accessible.name: settingResult ? entry.title + ", " + root.categoryDisplayName(entry.category) : entry.name

                            contentItem: RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 11

                                MaterialSymbol {
                                    text: categoryButton.settingResult ? "tune" : categoryButton.entry.icon
                                    rotation: categoryButton.settingResult ? 0 : (categoryButton.entry.iconRotation || 0)
                                    iconSize: 20
                                    color: categoryButton.toggled ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 0
                                    StyledText {
                                        Layout.fillWidth: true
                                        text: categoryButton.settingResult ? categoryButton.entry.title : categoryButton.entry.name
                                        font.weight: categoryButton.toggled ? Font.DemiBold : Font.Normal
                                        color: categoryButton.toggled ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                        elide: Text.ElideRight
                                    }
                                    StyledText {
                                        visible: categoryButton.settingResult
                                        Layout.fillWidth: true
                                        text: categoryButton.settingResult ? root.categoryDisplayName(categoryButton.entry.category) : ""
                                        font.pixelSize: Appearance.font.pixelSize.smaller
                                        color: categoryButton.toggled ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colSubtext
                                        elide: Text.ElideRight
                                    }
                                }

                                MaterialSymbol {
                                    visible: categoryButton.toggled
                                    text: "chevron_right"
                                    iconSize: 18
                                    color: Appearance.colors.colOnSecondaryContainer
                                }
                            }
                        }

                        StyledText {
                            anchors.centerIn: parent
                            visible: root.navigationItems.length === 0
                            text: Translation.tr("No matching categories or settings")
                            color: Appearance.colors.colSubtext
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Appearance.colors.colLayer1Hover
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText {
                            text: Translation.tr("Quick access")
                            font.pixelSize: Appearance.font.pixelSize.small
                            font.weight: Font.DemiBold
                            color: Appearance.colors.colSubtext
                        }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6

                        Repeater {
                            model: root.pages.filter(page =>
                                (root.expertMode || page.expertOnly !== true)
                                && ["quick", "interface", "windows", "general"].includes(String(page.categoryId || page.category || "").toLocaleLowerCase())
                            ).slice(0, 3)
                            delegate: RippleButton {
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                visible: root.expertMode || modelData.expertOnly !== true
                                buttonRadius: Appearance.rounding.small
                                colBackground: Appearance.colors.colLayer1Base
                                colBackgroundHover: Appearance.colors.colLayer1Hover
                                onClicked: root.selectPage(modelData)
                                contentItem: RowLayout {
                                    spacing: 5
                                    MaterialSymbol {
                                        text: modelData.icon
                                        iconSize: 17
                                    }
                                    StyledText {
                                        Layout.fillWidth: true
                                        text: modelData.name
                                        font.pixelSize: Appearance.font.pixelSize.smaller
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }

                    RippleButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 42
                        buttonRadius: Appearance.rounding.small
                        colBackground: Appearance.colors.colLayer1Base
                        colBackgroundHover: Appearance.colors.colLayer1Hover
                        downAction: () => Qt.openUrlExternally(Directories.config + "/illogical-impulse/config.json")
                        altAction: () => {
                            Quickshell.clipboardText = CF.FileUtils.trimFileProtocol(Directories.config + "/illogical-impulse/config.json");
                            copiedLabelTimer.restart();
                        }

                        contentItem: RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 8
                            MaterialSymbol {
                                text: root.copied ? "check" : "code"
                                iconSize: 18
                            }
                            StyledText {
                                Layout.fillWidth: true
                                text: root.copied ? Translation.tr("Path copied") : Translation.tr("Open config file")
                                elide: Text.ElideRight
                            }
                            StyledText {
                                text: "⋯"
                                color: Appearance.colors.colSubtext
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: mainPanel
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 610
                radius: Appearance.rounding.large
                color: Appearance.m3colors.m3surfaceContainerLow

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 54
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 42
                            Layout.preferredHeight: 42
                            radius: Appearance.rounding.small
                            color: Appearance.colors.colLayer1Base
                            MaterialSymbol {
                                anchors.centerIn: parent
                                text: root.currentPageObject() ? root.currentPageObject().icon : "tune"
                                rotation: (root.currentPageObject() && root.currentPageObject().iconRotation) ? root.currentPageObject().iconRotation : 0
                                iconSize: 22
                                color: Appearance.colors.colPrimary
                            }
                        }

                        ColumnLayout {
                            spacing: 0
                            StyledText {
                                text: root.currentPageObject() ? root.currentPageObject().name : ""
                                font.pixelSize: Appearance.font.pixelSize.larger
                                font.weight: Font.DemiBold
                                color: Appearance.colors.colOnLayer0
                            }
                            StyledText {
                                Layout.fillWidth: true
                                text: root.currentPageObject() ? root.currentPageObject().summary : ""
                                font.pixelSize: Appearance.font.pixelSize.small
                                color: Appearance.colors.colSubtext
                                elide: Text.ElideRight
                            }
                        }

                        Item { Layout.fillWidth: true }

                        RippleButton {
                            implicitHeight: 38
                            buttonRadius: Appearance.rounding.full
                            toggled: root.expertMode
                            colBackground: Appearance.colors.colLayer1Base
                            colBackgroundHover: Appearance.colors.colLayer1Hover
                            colBackgroundToggled: Appearance.colors.colSecondaryContainer
                            onClicked: root.expertMode = !root.expertMode
                            contentItem: RowLayout {
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                spacing: 7
                                MaterialSymbol {
                                    text: root.expertMode ? "tune" : "settings"
                                    iconSize: 17
                                    color: root.expertMode ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                }
                                StyledText {
                                    text: root.expertMode ? Translation.tr("Expert mode on") : Translation.tr("Expert mode off")
                                    font.pixelSize: Appearance.font.pixelSize.small
                                    color: root.expertMode ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: pageContentContainer
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: Appearance.rounding.small
                        color: Appearance.m3colors.m3surface
                        clip: true

                        readonly property var activePage: root.currentPageObject()
                        readonly property int supplementalCount: root.supplementalCountForPage(activePage)
                        readonly property bool showingSupplemental: root.showSupplementalControls && supplementalCount > 0

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: visible ? 44 : 0
                                visible: pageContentContainer.supplementalCount > 0
                                color: Appearance.m3colors.m3surfaceContainerLow

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    spacing: 8

                                    RippleButton {
                                        Layout.preferredHeight: 30
                                        implicitWidth: stdTabText.implicitWidth + 24
                                        buttonRadius: Appearance.rounding.full
                                        toggled: !root.showSupplementalControls
                                        colBackground: "transparent"
                                        colBackgroundHover: Appearance.colors.colLayer1Hover
                                        colBackgroundToggled: Appearance.colors.colSecondaryContainer
                                        colBackgroundToggledHover: Appearance.colors.colSecondaryContainerHover
                                        onClicked: root.showSupplementalControls = false
                                        contentItem: StyledText {
                                            id: stdTabText
                                            anchors.centerIn: parent
                                            text: (root.currentPageObject() ? root.currentPageObject().name : Translation.tr("Standard"))
                                            font.pixelSize: Appearance.font.pixelSize.small
                                            font.weight: !root.showSupplementalControls ? Font.DemiBold : Font.Normal
                                            color: !root.showSupplementalControls ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                        }
                                    }

                                    RippleButton {
                                        Layout.preferredHeight: 30
                                        implicitWidth: supTabText.implicitWidth + 24
                                        buttonRadius: Appearance.rounding.full
                                        toggled: root.showSupplementalControls
                                        colBackground: "transparent"
                                        colBackgroundHover: Appearance.colors.colLayer1Hover
                                        colBackgroundToggled: Appearance.colors.colSecondaryContainer
                                        colBackgroundToggledHover: Appearance.colors.colSecondaryContainerHover
                                        onClicked: root.showSupplementalControls = true
                                        contentItem: StyledText {
                                            id: supTabText
                                            anchors.centerIn: parent
                                            text: root.supplementalTabLabel(root.currentPageObject())
                                            font.pixelSize: Appearance.font.pixelSize.small
                                            font.weight: root.showSupplementalControls ? Font.DemiBold : Font.Normal
                                            color: root.showSupplementalControls ? Appearance.colors.colOnSecondaryContainer : Appearance.colors.colOnLayer1
                                        }
                                    }

                                    Item { Layout.fillWidth: true }
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                                Layout.fillHeight: true

                                Loader {
                                    id: pageLoader
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    active: Config.ready
                                    visible: !pageContentContainer.showingSupplemental
                                    opacity: 1.0

                                    function syncItemProperties() {
                                        if (!pageLoader.item)
                                            return;
                                        const curPage = root.currentPageObject();
                                        if ("settingsRoot" in pageLoader.item)
                                            pageLoader.item.settingsRoot = root;
                                        if ("pageData" in pageLoader.item)
                                            pageLoader.item.pageData = curPage;
                                        if ("supplementalOnly" in pageLoader.item)
                                            pageLoader.item.supplementalOnly = false;
                                    }

                                    function applyCurrentPageSource() {
                                        const curPage = root.currentPageObject();
                                        if (!curPage || !curPage.component)
                                            return;
                                        const resolvedUrl = Qt.resolvedUrl(curPage.component);
                                        if (pageLoader.source === resolvedUrl && pageLoader.item) {
                                            pageLoader.syncItemProperties();
                                        } else if (curPage.component === "modules/settings/DynamicCategoryConfig.qml") {
                                            pageLoader.setSource(resolvedUrl, {
                                                "settingsRoot": root,
                                                "pageData": curPage
                                            });
                                        } else {
                                            pageLoader.setSource(resolvedUrl);
                                        }
                                    }

                                    Component.onCompleted: pageLoader.applyCurrentPageSource()
                                    onLoaded: pageLoader.syncItemProperties()

                                    Connections {
                                        target: root
                                        function onCurrentPageChanged() {
                                            root.showSupplementalControls = false;
                                            switchAnim.complete();
                                            switchAnim.start();
                                        }
                                        function onPagesChanged() {
                                            pageLoader.applyCurrentPageSource();
                                        }
                                    }

                                    SequentialAnimation {
                                        id: switchAnim

                                        NumberAnimation {
                                            target: pageLoader
                                            properties: "opacity"
                                            from: 1
                                            to: 0
                                            duration: 100
                                            easing.type: Appearance.animation.elementMoveExit.type
                                            easing.bezierCurve: Appearance.animationCurves.emphasizedFirstHalf
                                        }
                                        ParallelAnimation {
                                            ScriptAction {
                                                script: pageLoader.applyCurrentPageSource()
                                            }
                                            PropertyAction {
                                                target: pageLoader
                                                property: "anchors.topMargin"
                                                value: 28
                                            }
                                        }
                                        ParallelAnimation {
                                            NumberAnimation {
                                                target: pageLoader
                                                properties: "opacity"
                                                from: 0
                                                to: 1
                                                duration: 180
                                                easing.type: Appearance.animation.elementMoveEnter.type
                                                easing.bezierCurve: Appearance.animationCurves.emphasizedLastHalf
                                            }
                                            NumberAnimation {
                                                target: pageLoader
                                                properties: "anchors.topMargin"
                                                to: 8
                                                duration: 180
                                                easing.type: Appearance.animation.elementMoveEnter.type
                                                easing.bezierCurve: Appearance.animationCurves.emphasizedLastHalf
                                            }
                                        }
                                    }
                                }

                                Loader {
                                    id: supplementalLoader
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    active: Config.ready && pageContentContainer.showingSupplemental
                                    visible: active
                                    source: active ? Qt.resolvedUrl("modules/settings/DynamicCategoryConfig.qml") : ""
                                    onLoaded: syncSupplementalProps()
                                    function syncSupplementalProps() {
                                        if (!item)
                                            return;
                                        item.settingsRoot = root;
                                        item.pageData = root.currentPageObject();
                                        item.supplementalOnly = true;
                                    }
                                    Connections {
                                        target: root
                                        function onCurrentPageChanged() {
                                            supplementalLoader.syncSupplementalProps();
                                        }
                                        function onPagesChanged() {
                                            supplementalLoader.syncSupplementalProps();
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: detailPanel
                visible: root.width >= 1280
                Layout.fillHeight: true
                Layout.preferredWidth: visible ? 248 : 0
                radius: Appearance.rounding.large
                color: Appearance.m3colors.m3surfaceContainerLow

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    visible: root.selectedSettingId.length === 0
                    spacing: 12

                    StyledText {
                        text: Translation.tr("Category overview")
                        font.pixelSize: Appearance.font.pixelSize.small
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colSubtext
                    }

                    StyledText {
                        Layout.fillWidth: true
                        text: root.currentPageObject() ? root.currentPageObject().name : ""
                        font.pixelSize: Appearance.font.pixelSize.large
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colOnLayer0
                        wrapMode: Text.WordWrap
                    }

                    StyledText {
                        Layout.fillWidth: true
                        text: root.currentPageObject() ? root.currentPageObject().summary : ""
                        color: Appearance.colors.colOnLayer1
                        wrapMode: Text.WordWrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Appearance.colors.colLayer1Hover
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        StyledText {
                            text: Translation.tr("Sections")
                            font.pixelSize: Appearance.font.pixelSize.small
                            font.weight: Font.DemiBold
                            color: Appearance.colors.colSubtext
                        }
                        Item { Layout.fillWidth: true }
                        RippleButton {
                            visible: Boolean(root.currentPageObject() && root.currentPageObject().categoryId)
                            Layout.preferredWidth: 28
                            Layout.preferredHeight: 28
                            buttonRadius: Appearance.rounding.full
                            onClicked: {
                                if (root.currentPageObject() && root.currentPageObject().categoryId)
                                    root.toggleCategoryCollapsed(root.currentPageObject().categoryId);
                            }
                            contentItem: MaterialSymbol {
                                anchors.centerIn: parent
                                text: (root.currentPageObject() && root.currentPageObject().collapsed) ? "expand_more" : "expand_less"
                                iconSize: 18
                                color: Appearance.colors.colSubtext
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        visible: !(root.currentPageObject() && root.currentPageObject().collapsed)
                        spacing: 7
                        Repeater {
                            model: {
                                const cur = root.currentPageObject();
                                if (!cur)
                                    return [];
                                if (cur.subcategories && cur.subcategories.length > 0)
                                    return cur.subcategories;
                                return (cur.sections || []).map(title => ({ id: title, title: title, settingIds: [] }));
                            }
                            delegate: ColumnLayout {
                                id: subcatRow
                                required property var modelData
                                property bool subExpanded: root.isSubcategoryExpanded(modelData.id || modelData.title)
                                Layout.fillWidth: true
                                spacing: 4
                                RippleButton {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 28
                                    buttonRadius: Appearance.rounding.small
                                    colBackground: "transparent"
                                    colBackgroundHover: Appearance.colors.colLayer1Hover
                                    onClicked: root.toggleSubcategoryExpanded(subcatRow.modelData.id || subcatRow.modelData.title)
                                    contentItem: RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 4
                                        anchors.rightMargin: 4
                                        spacing: 8
                                        MaterialSymbol {
                                            text: subcatRow.subExpanded ? "expand_more" : "chevron_right"
                                            iconSize: 16
                                            color: Appearance.colors.colPrimary
                                        }
                                        StyledText {
                                            Layout.fillWidth: true
                                            text: subcatRow.modelData.title || ""
                                            font.pixelSize: Appearance.font.pixelSize.small
                                            color: Appearance.colors.colOnLayer1
                                            elide: Text.ElideRight
                                        }
                                        StyledText {
                                            visible: root.toList(subcatRow.modelData.settingIds).length > 0
                                            text: {
                                                const cnt = root.toList(subcatRow.modelData.settingIds).length;
                                                return cnt > 0 ? String(cnt) : "";
                                            }
                                            font.pixelSize: Appearance.font.pixelSize.smaller
                                            color: Appearance.colors.colSubtext
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Item { Layout.fillHeight: true }

                    RippleButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        visible: {
                            const cur = root.currentPageObject();
                            if (!cur)
                                return false;
                            const catKey = cur.categoryId || cur.category || root.categoryForPage(cur.component);
                            return root.safeSettingCount(catKey) > 0;
                        }
                        enabled: visible && !root.nexusActionBusy
                        buttonRadius: Appearance.rounding.small
                        colBackground: Appearance.colors.colLayer1Base
                        colBackgroundHover: Appearance.colors.colLayer1Hover
                        onClicked: {
                            const cur = root.currentPageObject();
                            const category = cur ? (cur.categoryId || cur.category || root.categoryForPage(cur.component)) : "";
                            const args = ["reset-category", category];
                            let message = Translation.tr("Reset the supported settings in this category to their saved starting values?");
                            if (root.categoryNeedsRiskConfirmation(category)) {
                                args.push("--confirm-risk");
                                message += " " + Translation.tr("This may reload Hyprland for window rules or glow settings.");
                            }
                            root.confirmNexusAction(args, message);
                        }
                        contentItem: StyledText {
                            text: Translation.tr("Reset category defaults")
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    StyledText {
                        Layout.fillWidth: true
                        visible: root.nexusStatusText.length > 0
                        text: root.nexusStatusText
                        color: root.nexusStatusText.toLowerCase().indexOf("failed") >= 0 ? Appearance.colors.colError : Appearance.colors.colSubtext
                        font.pixelSize: Appearance.font.pixelSize.smaller
                        wrapMode: Text.WordWrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 88
                        radius: Appearance.rounding.small
                        color: Appearance.colors.colLayer1Base

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 8
                            MaterialSymbol {
                                text: (root.currentPageObject() && root.currentPageObject().expertOnly === true) ? "warning" : "check_circle"
                                iconSize: 19
                                color: Appearance.colors.colPrimary
                            }
                            StyledText {
                                Layout.fillWidth: true
                                text: Translation.tr("Every setting keeps the behavior it already has.")
                                font.pixelSize: Appearance.font.pixelSize.smaller
                                color: Appearance.colors.colSubtext
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 11
                    visible: root.selectedSettingId.length > 0

                    StyledText {
                        text: Translation.tr("Setting details")
                        font.pixelSize: Appearance.font.pixelSize.small
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colSubtext
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: root.selectedDefinition() ? root.selectedDefinition().title : ""
                        font.pixelSize: Appearance.font.pixelSize.large
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colOnLayer0
                        wrapMode: Text.WordWrap
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: root.selectedDefinition() ? root.selectedDefinition().description : ""
                        color: Appearance.colors.colOnLayer1
                        wrapMode: Text.WordWrap
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Appearance.colors.colLayer1Hover
                    }
                    StyledText {
                        text: Translation.tr("Current value")
                        font.pixelSize: Appearance.font.pixelSize.small
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colSubtext
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: root.displayValue(root.selectedDefinition(), false)
                        color: Appearance.colors.colOnLayer1
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                    }
                    StyledText {
                        text: Translation.tr("Saved starting value")
                        font.pixelSize: Appearance.font.pixelSize.small
                        font.weight: Font.DemiBold
                        color: Appearance.colors.colSubtext
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: root.hasInitialValue(root.selectedDefinition()) ? root.displayValue(root.selectedDefinition(), true) : Translation.tr("Starting values are unavailable")
                        color: Appearance.colors.colOnLayer1
                        wrapMode: Text.WordWrap
                        elide: Text.ElideRight
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: Appearance.colors.colLayer1Hover
                    }
                    StyledText {
                        Layout.fillWidth: true
                        text: root.selectedDefinition() ? root.selectedDefinition().source + "\n" + root.selectedDefinition().applyMethod : ""
                        font.pixelSize: Appearance.font.pixelSize.smaller
                        color: Appearance.colors.colSubtext
                        wrapMode: Text.WordWrap
                    }
                    Item { Layout.fillHeight: true }
                    RippleButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        visible: root.selectedDefinition() && root.selectedDefinition().resetSupported && (!root.selectedDefinition().verification || root.selectedDefinition().verification.verified) && root.hasInitialValue(root.selectedDefinition())
                        enabled: visible && !root.nexusActionBusy
                        buttonRadius: Appearance.rounding.small
                        colBackground: Appearance.colors.colSecondaryContainer
                        colBackgroundHover: Appearance.colors.colSecondaryContainerHover
                        onClicked: {
                            const setting = root.selectedDefinition();
                            if (setting.risk === "confirmation-required")
                                root.confirmNexusAction(["reset", root.selectedSettingId, "--confirm-risk"], Translation.tr("Reset this setting to its saved starting value? Hyprland may reload for window rules, glow or motion settings."));
                            else
                                root.runNexusAction(["reset", root.selectedSettingId]);
                        }
                        contentItem: StyledText {
                            text: Translation.tr("Reset this setting")
                            color: Appearance.colors.colOnSecondaryContainer
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    StyledText {
                        Layout.fillWidth: true
                        visible: root.selectedDefinition() && (!root.selectedDefinition().resetSupported || (root.selectedDefinition().verification && !root.selectedDefinition().verification.verified))
                        text: Translation.tr("Reset is disabled until this setting has a verified adapter and rollback path.")
                        color: Appearance.colors.colSubtext
                        wrapMode: Text.WordWrap
                    }
                    StyledText {
                        Layout.fillWidth: true
                        visible: root.nexusStatusText.length > 0
                        text: root.nexusStatusText
                        color: root.nexusStatusText.toLowerCase().indexOf("failed") >= 0 ? Appearance.colors.colError : Appearance.colors.colSubtext
                        font.pixelSize: Appearance.font.pixelSize.smaller
                        wrapMode: Text.WordWrap
                    }
                }
}
        }
    }

    Dialog {
        id: nexusConfirmDialog
        modal: true
        anchors.centerIn: Overlay.overlay
        title: Translation.tr("Confirm settings change")
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: root.runNexusAction(root.pendingNexusArgs)
        contentItem: StyledText {
            width: 400
            text: root.pendingNexusText
            color: Appearance.colors.colOnLayer1
            wrapMode: Text.WordWrap
        }
    }

    Process {
        id: nexusActionProcess
        stdout: StdioCollector {
            id: nexusActionOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => root.handleNexusResult(exitCode)
    }

    Process {
        id: cursorStatusProcess
        stdout: StdioCollector {
            id: cursorStatusOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            try {
                const response = JSON.parse(cursorStatusOutput.text);
                if (exitCode === 0 && response.status === "ok") {
                    root.acceptCursorStatus(response);
                } else if (response.status === "error") {
                    root.cursorRuntimeVerified = false;
                }
            } catch (error) {
                root.cursorRuntimeVerified = false;
            }
        }
    }

    Process {
        id: adapterSetProcess
        property string currentSettingId: ""
        property bool currentAppAction: false
        stdout: StdioCollector {
            id: adapterSetOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            root.adapterSetBusy = false;
            let response = null;
            try {
                response = JSON.parse(adapterSetOutput.text);
            } catch (error) {
                root.nexusStatusText = Translation.tr("Setting update failed safely.");
                root._drainAdapterSetQueue();
                return;
            }
            if (exitCode !== 0 || !response || response.status === "error") {
                root.nexusStatusText = (response && response.message) ? response.message : Translation.tr("Setting update failed safely.");
            } else {
                if (adapterSetProcess.currentSettingId && "value" in response) {
                    const updated = Object.assign({}, root.externalSettingValues);
                    updated[adapterSetProcess.currentSettingId] = response.value;
                    root.externalSettingValues = updated;
                    root.externalValuesRevision += 1;
                }
                if (response.runtimeVerified === true)
                    root.nexusStatusText = Translation.tr("Saved and verified live in Hyprland.");
                else if (response.status === "no_changes")
                    root.nexusStatusText = Translation.tr("No changes were needed.");
                else
                    root.nexusStatusText = Translation.tr("Saved to system configuration files (undoable in NEXUS).");
                if (adapterSetProcess.currentAppAction
                    || adapterSetProcess.currentSettingId === "apps.icons.overrides"
                    || adapterSetProcess.currentSettingId === "apps.visibility.hiddenApps")
                    root.refreshAppsCatalog();
                if (root.initialStateReady && adapterSetProcess.currentSettingId && !(adapterSetProcess.currentSettingId in root.initialExternalSettingValues))
                    root.reloadInitialState();
                root.refreshHyprlandOptionsStatus();
            }
            root._drainAdapterSetQueue();
        }
    }

    Process {
        id: baselineMigrateProcess
        stdout: StdioCollector {
            id: baselineMigrateOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode === 0) {
                root.reloadInitialState();
                root.refreshCatalogState();
            }
        }
    }

    Process {
        id: appsCatalogProcess
        stdout: StdioCollector {
            id: appsCatalogOutput
            waitForEnd: true
        }
        onExited: (exitCode, exitStatus) => {
            root.appsCatalogLoading = false;
            try {
                const response = JSON.parse(appsCatalogOutput.text);
                if (exitCode === 0 && response && response.status === "ok") {
                    root.appsCatalog = Array.isArray(response.apps) ? response.apps : [];
                    root.installedIconThemes = Array.isArray(response.iconThemes) ? response.iconThemes : [];
                }
            } catch (error) {
                // Keep previous appsCatalog safely
            }
        }
    }

    Timer {
        id: copiedLabelTimer
        interval: 1500
        onTriggered: root.copied = false
    }
}
