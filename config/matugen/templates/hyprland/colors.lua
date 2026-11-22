hl.config({
    general = {
        col = {
            active_border   = "rgba({{colors.outline_variant.default.hex_stripped}}F2)",
            inactive_border = "rgba({{colors.outline_variant.default.hex_stripped}}CC)",
        },
    },
    decoration = {
        glow = {
            enabled = false,
        },
        shadow = {
            enabled = true,
            range = 28,
            render_power = 2,
            sharp = false,
            color = "rgba({{colors.outline_variant.default.hex_stripped}}4A)",
            color_inactive = "rgba({{colors.outline_variant.default.hex_stripped}}00)",
            offset = { 0, 0 },
            scale = 1.0,
        },
    },

    misc = {
        background_color = "rgba({{colors.surface.dark.hex_stripped}}FF)",
    },
})

hl.window_rule({
    match        = { pin = 1 },
    border_color = "rgba({{colors.primary.default.hex_stripped}}AA) rgba({{colors.primary.default.hex_stripped}}77)",
})
