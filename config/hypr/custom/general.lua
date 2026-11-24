-- Aegis Motion: yumuşak, sıçramasız Bezier eğrileri
hl.curve("aegisSmoothOut", {
    type = "bezier",
    points = {{0.22, 1.00}, {0.36, 1.00}}
})
hl.curve("aegisSmoothIn", {
    type = "bezier",
    points = {{0.40, 0.00}, {0.68, 0.35}}
})
hl.curve("aegisSpatialPop", {
    type = "bezier",
    points = {{0.16, 1.00}, {0.30, 1.00}}
})

hl.config({
    decoration = {
        active_opacity = 0.80,
    },
})

-- AEGIS WINDOW EFFECTS BEGIN
-- Gelişmiş ayarlardaki geçici pencere kontrolleri tarafından yönetilir.
hl.config({
    decoration = {
        inactive_opacity = 0.80,
        dim_inactive = true,
        dim_strength = 0.05,
    },
})
-- AEGIS WINDOW EFFECTS END

-- AEGIS MOTION PROFILE BEGIN
-- AEGIS MOTION PROFILE NAME: full
-- Gelişmiş menü tarafından yönetilen geçici profiller.
hl.animation({ leaf = "windowsIn", enabled = true, speed = 3.0, bezier = "aegisSpatialPop", style = "popin 86%" })
hl.animation({ leaf = "fadeIn", enabled = true, speed = 2.8, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 2.2, bezier = "aegisSmoothIn", style = "popin 92%" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 2.0, bezier = "aegisSmoothIn" })
hl.animation({ leaf = "workspaces", enabled = true, speed = 5.5, bezier = "aegisSmoothOut", style = "slidefade 22%" })
hl.animation({ leaf = "windowsMove", enabled = true, speed = 3.2, bezier = "aegisSmoothOut", style = "slide" })
hl.animation({ leaf = "specialWorkspaceIn", enabled = true, speed = 3.0, bezier = "aegisSmoothOut", style = "slidevert" })
hl.animation({ leaf = "specialWorkspaceOut", enabled = true, speed = 2.2, bezier = "aegisSmoothIn", style = "slidevert" })
hl.animation({ leaf = "border", enabled = true, speed = 8.0, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "layersIn", enabled = true, speed = 2.8, bezier = "aegisSpatialPop", style = "popin 94%" })
hl.animation({ leaf = "layersOut", enabled = true, speed = 2.2, bezier = "aegisSmoothIn", style = "popin 96%" })
hl.animation({ leaf = "fadeLayersIn", enabled = true, speed = 2.6, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadeLayersOut", enabled = true, speed = 2.0, bezier = "aegisSmoothIn" })
hl.animation({ leaf = "fadeSwitch", enabled = true, speed = 2.8, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadeShadow", enabled = true, speed = 2.8, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadeDim", enabled = true, speed = 2.8, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadeGlow", enabled = true, speed = 2.8, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadePopupsIn", enabled = true, speed = 2.4, bezier = "aegisSmoothOut" })
hl.animation({ leaf = "fadePopupsOut", enabled = true, speed = 2.0, bezier = "aegisSmoothIn" })
hl.config({
    decoration = {
        wobble = {
            enabled = true,
            mesh = 16,
            intensity = 0.45,
            stiffness = 220,
            damping = 18,
        },
    },
})
-- AEGIS MOTION PROFILE END

-- AEGIS ACRYLIC GLASS BEGIN
-- Aegis Gelişmiş Ayarlar tarafından yönetilen Acrylic cam profili.
hl.config({
    decoration = {
        blur = {
            enabled = true,
            variant = "acrylic",
            size = 22,
            passes = 6,
            ignore_opacity = true,
            acrylic = {
                clarity = 0.22,
            },
        },
    },
})
-- AEGIS ACRYLIC GLASS END

-- Aegis Visual Quality: optik Acrylic lens, popup bulanıklığı ve katman derinliği.
hl.config({
    decoration = {
        blur = {
            xray = true,
            popups = true,
            popups_ignorealpha = 0.4,
            vibrancy = 0.65,
            vibrancy_darkness = 0.15,
            contrast = 0.98,
            brightness = 1.05,
            noise = 0.035,
            acrylic = {
                refraction = 28,
                bulb = 52,
                aberration = 0.03,
                tint = "rgba(eef5ff18)",
            },
        },
    },
})
