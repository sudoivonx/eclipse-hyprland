-- This file sources other files in `hyprland` and `custom` folders
-- You wanna add your stuff in files in `custom`

-- Internal stuff --
require("hyprland.lib")
require("hyprland.services")

-- Environment variables --
require("hyprland.env")
if is_file_exists(HOME .. "/.config/hypr/custom/env.lua") then
    require("custom.env")
end

-- Default configurations --
require("hyprland.execs")
require("hyprland.general")
require("hyprland.rules")
require("hyprland.colors")
require("hyprland.keybinds")

-- Custom configurations --
if is_file_exists(HOME .. "/.config/hypr/custom/execs.lua") then
    require("custom.execs")
end
if is_file_exists(HOME .. "/.config/hypr/custom/general.lua") then
    require("custom.general")
end
if is_file_exists(HOME .. "/.config/hypr/custom/rules.lua") then
    require("custom.rules")
end
if is_file_exists(HOME .. "/.config/hypr/custom/keybinds.lua") then
    require("custom.keybinds")
end

-- nwg-displays support --
if is_file_exists(HOME .. "/.config/hypr/workspaces.lua") then
    require("workspaces")
end
if is_file_exists(HOME .. "/.config/hypr/monitors.lua") then
    require("monitors")
end

-- Shell overrides --
require("hyprland.shellOverrides.main")

-- Aegis: kalıcı kullanıcı glow rengi; Matugen dosyasından sonra uygulanır.
if is_file_exists(HOME .. "/.config/hypr/custom/glow.lua") then
    dofile(HOME .. "/.config/hypr/custom/glow.lua")
end

-- NEXUS POST-GLOW HOOK BEGIN
-- NEXUS Hyprland Controls: persistent shadow overrides applied after custom/glow.lua.
if is_file_exists(HOME .. "/.config/hypr/custom/nexus-post-glow.lua") then
    dofile(HOME .. "/.config/hypr/custom/nexus-post-glow.lua")
end
-- NEXUS POST-GLOW HOOK END

