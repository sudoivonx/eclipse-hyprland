-- AEGIS WINDOW GLASS RULES BEGIN
-- Genel blur kuralını, dağıtımla gelen no_blur=true kuralından sonra aç.
hl.window_rule({
    name = "aegis-glass-enable-blur-by-default",
    match = { class = ".*" },
    no_blur = false,
})

-- İsimsiz bağlam menülerinde mevcut blur istisnasını koru.
hl.window_rule({
    name = "aegis-glass-preserve-empty-context-menu-exception",
    match = { class = "^()$", title = "^()$" },
    no_blur = true,
})

-- AEGIS OPACITY OPTIONS BEGIN
-- Aegis Gelişmiş Ayarlar tarafından yönetilir.
local aegisOpaqueOpacity = "1.0 override 1.0 override 1.0 override"
hl.window_rule({
    name = "aegis-opaque-blender",
    match = { class = "^(blender|Blender|org\\.blender\\.Blender)$" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-davinci-resolve",
    match = { class = "^(resolve|davinci-resolve)$" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-vlc",
    match = { class = "^(vlc|org\\.videolan\\.VLC)$" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-photo-viewers",
    match = { class = "^(eog|loupe|org\\.gnome\\.Loupe|imv|swayimg|gwenview|org\\.kde\\.gwenview)$" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-game-content",
    match = { content = "game" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-steam-games",
    match = { class = "^steam_app.*$" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-photo-content",
    match = { content = "photo" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-video-content",
    match = { content = "video" },
    opacity = aegisOpaqueOpacity,
})

hl.window_rule({
    name = "aegis-opaque-fullscreen",
    match = { fullscreen = true },
    opacity = aegisOpaqueOpacity,
})

-- AEGIS OPACITY OPTIONS END

-- AEGIS PICTURE-IN-PICTURE BEGIN
hl.window_rule({
    name = "aegis-opaque-zen-picture-in-picture",
    match = { title = "^Görüntü içinde görüntü$" },
    opacity = "1.0 override 1.0 override 1.0 override",
})
-- AEGIS PICTURE-IN-PICTURE END

-- AEGIS CUSTOM OPACITY BEGIN
-- Yalnızca Aegis özel pencere seçimleri tarafından yönetilir.
local aegisCustomOpaqueOpacity = "1.0 override 1.0 override 1.0 override"
-- AEGIS CUSTOM OPACITY END

-- AEGIS WINDOW GLASS RULES END
