hl.config({
    general = {
        col = {
            active_border   = "rgba(47464dF2)",
            inactive_border = "rgba(47464dCC)",
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
            color = "rgba(47464d4A)",
            color_inactive = "rgba(47464d00)",
            offset = { 0, 0 },
            scale = 1.0,
        },
    },

    misc = {
        background_color = "rgba(141315FF)",
    },
})

hl.window_rule({
    match        = { pin = 1 },
    border_color = "rgba(faf5ffAA) rgba(faf5ff77)",
})
