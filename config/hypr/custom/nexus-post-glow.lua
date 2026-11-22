-- Aegis Post-Glow: native inner glow & depth shadow enrichment (applied after custom/glow.lua).
hl.config({
    decoration = {
        glow = {
            enabled = true,
            range = 18,
            render_power = 2,
            color = "rgba(b8245458)",
            color_inactive = "rgba(47464d22)",
        },
        shadow = {
            render_power = 3,
            offset = { 0, 4 },
            color_inactive = "rgba(00000048)",
        },
    },
})
