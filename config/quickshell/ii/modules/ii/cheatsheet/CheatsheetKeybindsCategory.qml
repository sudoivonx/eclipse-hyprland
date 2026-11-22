pragma ComponentBehavior: Bound

import qs.services
import qs.modules.common
import qs.modules.common.functions
import qs.modules.common.widgets
import QtQuick
import QtQuick.Layouts
import Quickshell

// Notes:
// We deal with keybinds being numbered 1, 2, etc by discarding 2+, keeping 1 and replacing it with a generic "<Number>"
Column {
    id: root
    required property string categoryName
    readonly property bool isCategorized: categoryName?.length > 0
    property int maxBindWidth: 0
    property real columnSpacing: 40
    property real titleSpacing: 7

    // Excellent symbol explaination and source :
    // http://xahlee.info/comp/unicode_computing_symbols.html
    // https://www.nerdfonts.com/cheat-sheet
    property var macSymbolMap: ({
        "Ctrl": "󰘴",
        "Alt": "󰘵",
        "Shift": "󰘶",
        "Space": "󱁐",
        "Tab": "↹",
        "Equal": "󰇼",
        "Minus": "",
        "Print": "",
        "BackSpace": "󰭜",
        "Delete": "⌦",
        "Return": "󰌑",
        "Period": ".",
        "Escape": "⎋"
      })
    property var functionSymbolMap: ({
        "F1":  "󱊫",
        "F2":  "󱊬",
        "F3":  "󱊭",
        "F4":  "󱊮",
        "F5":  "󱊯",
        "F6":  "󱊰",
        "F7":  "󱊱",
        "F8":  "󱊲",
        "F9":  "󱊳",
        "F10": "󱊴",
        "F11": "󱊵",
        "F12": "󱊶",
    })

    property var mouseSymbolMap: ({
        "mouse_up": "󱕐",
        "mouse_down": "󱕑",
        "mouse:272": "L󰍽",
        "mouse:273": "R󰍽",
        "Scroll ↑/↓": "󱕒",
        "Page_↑/↓": "⇞/⇟",
    })

    property var keyBlacklist: ["SUPER_L", "SUPER_R"]
    property var keySubstitutions: Object.assign({
        "Super": "",
        "mouse_up": "Scroll ↓",    // ikr, weird
        "mouse_down": "Scroll ↑",  // trust me bro
        "mouse:272": "LMB",
        "mouse:273": "RMB",
        "mouse:275": "MouseBack",
        "Slash": "/",
        "Hash": "#",
        "Return": "Enter",
        // "Shift": "",
      },
      !!Config.options.cheatsheet.superKey ? {
          "Super": Config.options.cheatsheet.superKey,
      }: {},
      Config.options.cheatsheet.useMacSymbol ? macSymbolMap : {},
      Config.options.cheatsheet.useFnSymbol ? functionSymbolMap : {},
      Config.options.cheatsheet.useMouseSymbol ? mouseSymbolMap : {},
    )

    function modMaskToStringList(modMask: int): list<string> {
        var list = [];
        // Funny mathematical order but we wanna have this natural user-facing order
        if (modMask & (1 << 2)) { list.push("Ctrl"); }
        if (modMask & (1 << 6)) { list.push("Super"); }
        if (modMask & (1 << 0)) { list.push("Shift"); }
        if (modMask & (1 << 3)) { list.push("Alt"); }
        if (modMask & (1 << 1)) { list.push("Caps"); }
        if (modMask & (1 << 4)) { list.push("Mod2"); }
        if (modMask & (1 << 5)) { list.push("Mod3"); }
        if (modMask & (1 << 7)) { list.push("Mod5"); }
        return list;
    }

    visible: repeater.model.length > 0
    spacing: titleSpacing

    StyledText {
        text: root.isCategorized ? root.translatedCategory(root.categoryName) : "Diğer"
        font.pixelSize: Appearance.font.pixelSize.title
    }

    function translatedCategory(name) {
        const categories = {
            "Shell": "Arayüz",
            "Utilities": "Araçlar",
            "Screen": "Ekran",
            "Media": "Medya",
            "Window": "Pencere",
            "Workspace": "Çalışma Alanı",
            "Session": "Oturum",
            "App": "Uygulamalar"
        };
        return categories[name] || name;
    }

    function hasDescription(bind) {
        return bind.description?.length > 0;
    }

    function isCategory(bind, categoryName) {
        return bind.description.substring(0, bind.description.indexOf(":")) === categoryName;
    }

    function isUncategorized(bind) {
        return bind.description.indexOf(":") === -1;
    }

    function containsNonFirstRepetitive(bind) {
        const key = bind.key;
        if (key.includes("mouse") || key.includes("page")) return false;
        // Contains non-1 number
        if (/\d/.test(key) && !key.includes("1")) return true;
        // Contains non-left direction
        if (/^(right|up|down)\b/i.test(key)) return true;
        return false;
    }

    function containsFirstRepetitive(bind) {
        const key = bind.key;
        return key.includes("1") || /left/i.test(key);
    }

    function transformKey(key) {
        const replaced = root.keySubstitutions[key] || key;
        const denumbered = replaced.replace("1", "<Number>");
        const dedirectioned = denumbered.replace("Left", "<Direction>");
        return dedirectioned;
    }

    function translateDescription(description) {
        const tr = {
            "Toggle search": "Aramayı aç/kapat",
            "Toggle overview": "Genel görünümü aç/kapat",
            "Toggle left sidebar": "Sol kenar çubuğunu aç/kapat",
            "Toggle right sidebar": "Sağ kenar çubuğunu aç/kapat",
            "Toggle cheatsheet": "Kısayol rehberini aç/kapat",
            "Toggle on-screen keyboard": "Ekran klavyesini aç/kapat",
            "Toggle media controls": "Medya denetimlerini aç/kapat",
            "Toggle widget overlay": "Araç takımı katmanını aç/kapat",
            "Toggle session menu": "Oturum menüsünü aç/kapat",
            "Toggle bar": "Üst çubuğu aç/kapat",
            "Change wallpaper": "Duvar kâğıdını değiştir",
            "Random wallpaper": "Rastgele duvar kâğıdı seç",
            "Toggle light/dark mode": "Açık/koyu temayı değiştir",
            "Restart widgets": "Bileşenleri yeniden başlat",
            "Cycle panel family": "Panel düzenini değiştir",
            "Clipboard history >> clipboard": "Pano geçmişi",
            "Emoji >> clipboard": "Emoji seçici",
            "Screen snip": "Ekran bölgesinin görüntüsünü al",
            "Character recognition >> clipboard": "Metni tanı ve panoya kopyala",
            "Translate screen content": "Ekrandaki metni çevir",
            "Pick color #RRGGBB >> clipboard": "Renk seç ve panoya kopyala",
            "Record region (no sound)": "Bölgeyi kaydet (sessiz)",
            "Record screen (with sound)": "Ekranı kaydet (sesli)",
            "Screenshot >> clipboard": "Ekran görüntüsünü panoya kopyala",
            "Screenshot >> clipboard & file": "Ekran görüntüsünü panoya ve dosyaya kaydet",
            "Generate AI summary for selected text": "Seçili metnin yapay zekâ özetini oluştur",
            "Zoom out": "Uzaklaştır",
            "Zoom in": "Yakınlaştır",
            "Next track": "Sonraki parça",
            "Previous track": "Önceki parça",
            "Play/pause media": "Medyayı oynat/duraklat",
            "Toggle mute": "Sesi aç/kapat",
            "Toggle mic": "Mikrofonu aç/kapat",
            "Move": "Taşı",
            "Resize": "Boyutlandır",
            "Focus <Direction>": "Yöne odaklan",
            "Move <Direction>": "Yöne taşı",
            "Close": "Kapat",
            "Forcefully zap a window": "Pencereyi zorla kapat",
            "Float/Tile": "Kayan/döşemeli modu değiştir",
            "Maximize": "Pencereyi büyüt",
            "Fullscreen": "Tam ekran",
            "Fullscreen spoof": "Tam ekran benzetimi",
            "Pin": "Sabitle",
            "Send to workspace <Direction>": "Çalışma alanına gönder",
            "Send to workspace <Number>": "<Number> numaralı çalışma alanına gönder",
            "Focus <Number>": "<Number> numaralı çalışma alanına geç",
            "Toggle scratchpad": "Geçici alanı aç/kapat",
            "Send to scratchpad": "Geçici alana gönder",
            "Lock": "Ekranı kilitle",
            "Sleep": "Uykuya al",
            "Shut down": "Bilgisayarı kapat",
            "Terminal": "Terminal",
            "File manager": "Dosya yöneticisi",
            "Browser": "Tarayıcı",
            "Code editor": "Kod düzenleyici",
            "Office software": "Ofis uygulaması",
            "Text editor": "Metin düzenleyici",
            "Volume mixer": "Ses mikseri",
            "Settings app": "Ayarlar",
            "Task manager": "Görev yöneticisi",
            "Edit user keybinds": "Özel kısayolları düzenle"
        };
        return tr[description] || description;
    }

    function transformDescription(bind, categoryName) {
        const description = bind.description;
        const regex = new RegExp("\\s*" + categoryName + "\\s*:\\s*");
        let transformed = description.replace(regex, "");
        if (containsFirstRepetitive(bind)) {
            transformed = transformed.replace("1", "<Number>");
            transformed = transformed.replace(/ \b(left|right|up|down)\b/i, " <Direction>");
        }
        return translateDescription(transformed);
    }

    Column {
        spacing: 4
        Repeater {
            id: repeater
            model: {
                if (!root.isCategorized) {
                    return HyprlandKeybinds.keybinds.filter(bind => root.hasDescription(bind) && root.isUncategorized(bind) && !root.containsNonFirstRepetitive(bind));
                }
                return HyprlandKeybinds.keybinds.filter(bind => root.hasDescription(bind) && root.isCategory(bind, root.categoryName) && !root.containsNonFirstRepetitive(bind));
            }
            delegate: BindLine {
                required property var modelData
                keyData: modelData
                categoryName: root.categoryName
            }
        }
    }

    component BindLine: Row {
        id: bindLine
        required property var keyData
        property string categoryName: ""

        Row {
            spacing: 16
            Row {
                id: modRow
                Component.onCompleted: root.maxBindWidth = Math.max(root.maxBindWidth, implicitWidth)
                width: root.maxBindWidth
                spacing: 4
                Repeater {
                    model: {
                        const modList = root.modMaskToStringList(bindLine.keyData.modmask).map(mod => root.keySubstitutions[mod] || mod)
                        if (modList.length == 0) return []
                        if (Config.options.cheatsheet.splitButtons) return modList;
                        return [modList.join(" ")]
                    }
                    delegate: KeyboardKey {
                        required property var modelData
                        key: root.transformKey(modelData)
                        pixelSize: Config.options.cheatsheet.fontSize.key
                    }
                }
                StyledText {
                    id: keybindPlus
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !keyBlacklist.includes(bindLine.keyData.key) && bindLine.keyData.modmask > 0
                    text: "+"
                }
                KeyboardKey {
                    id: keybindKey
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !keyBlacklist.includes(bindLine.keyData.key)
                    key: root.transformKey(bindLine.keyData.key)
                    pixelSize: Config.options.cheatsheet.fontSize.key
                    color: Appearance.colors.colOnLayer0
                }
            }
            Item {
                anchors.verticalCenter: parent.verticalCenter
                implicitWidth: commentText.implicitWidth + root.columnSpacing
                implicitHeight: commentText.implicitHeight
                StyledText {
                    id: commentText
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    font.pixelSize: Config.options.cheatsheet.fontSize.comment || Appearance.font.pixelSize.smaller
                    text: root.transformDescription(bindLine.keyData, bindLine.categoryName)
                }
            }
        }
    }
}