local aegis_glow_rgb = "b82454"

hl.config({
    general = {
        col = {
            active_border = "rgba(" .. aegis_glow_rgb .. "F2)",
        },
    },
    decoration = {
        glow = {
            enabled = false,
        },
        shadow = {
            enabled = true,
            range = 43,
            render_power = 2,
            sharp = false,
            color = "rgba(" .. aegis_glow_rgb .. "68)",
            color_inactive = "rgba(" .. aegis_glow_rgb .. "00)",
            offset = { 0, 0 },
            scale = 1.0,
        },
    },
})
