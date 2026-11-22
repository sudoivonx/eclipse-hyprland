"""Transactional NEXUS adapter for simplified Hyprland controls (general, blur, shadow, animations, input, misc, autostart, env, keybinds)."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
from typing import Any, Callable, Mapping
import uuid


class HyprlandGodModeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HyprlandGodModePaths:
    main_general: Path
    main_colors: Path
    custom_dir: Path
    hyprctl: str = "hyprctl"
    allow_live_hyprctl: bool = False
    hyprctl_runner: Callable[[list[str]], Any] | None = None

    @property
    def custom_general(self) -> Path:
        return self.custom_dir / "general.lua"

    @property
    def custom_execs(self) -> Path:
        return self.custom_dir / "execs.lua"

    @property
    def custom_env(self) -> Path:
        return self.custom_dir / "env.lua"

    @property
    def custom_keybinds(self) -> Path:
        return self.custom_dir / "keybinds.lua"

    @property
    def custom_post_glow(self) -> Path:
        return self.custom_dir / "nexus-post-glow.lua"

    @property
    def hyprland_lua(self) -> Path:
        return self.custom_dir.parent / "hyprland.lua"


_CTRL_BEGIN = "-- NEXUS HYPRLAND CONTROLS BEGIN"
_CTRL_END = "-- NEXUS HYPRLAND CONTROLS END"
_POST_GLOW_BEGIN = "-- NEXUS POST-GLOW SHADOWS BEGIN"
_POST_GLOW_END = "-- NEXUS POST-GLOW SHADOWS END"
_HYPRLAND_LUA_HOOK_BEGIN = "-- NEXUS POST-GLOW HOOK BEGIN"
_HYPRLAND_LUA_HOOK_END = "-- NEXUS POST-GLOW HOOK END"
_AUTOSTART_BEGIN = "-- NEXUS AUTOSTART BEGIN"
_AUTOSTART_END = "-- NEXUS AUTOSTART END"
_ENV_BEGIN = "-- NEXUS ENV BEGIN"
_ENV_END = "-- NEXUS ENV END"
_KEYBINDS_BEGIN = "-- NEXUS KEYBINDS BEGIN"
_KEYBINDS_END = "-- NEXUS KEYBINDS END"

POST_GLOW_SHADOW_IDS: frozenset[str] = frozenset(
    {
        "hyprland.decoration.shadow.enabled",
        "hyprland.decoration.shadow.range",
        "hyprland.decoration.shadow.render_power",
        "hyprland.decoration.shadow.sharp",
        "hyprland.decoration.shadow.scale",
    }
)


def is_post_glow_shadow_setting(setting_id: str) -> bool:
    return setting_id in POST_GLOW_SHADOW_IDS


_TXN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_KB_LAYOUT_RE = re.compile(r"^[A-Za-z0-9_, -]{1,64}$")
_KB_VARIANT_RE = re.compile(r"^[A-Za-z0-9_, -]{1,128}$")
_KB_OPTIONS_RE = re.compile(r"^[A-Za-z0-9_:, -]{1,256}$")
_ACCEL_CUSTOM_RE = re.compile(r"^custom\s+[0-9]+(?:\.[0-9]+)?(?:\s+[0-9]+(?:\.[0-9]+)?)+$")
_SAFE_SINGLE_LINE_RE = re.compile(r"^[^\r\n\x00]{1,512}$")


# NOTE: Excludes general:gaps_in, general:gaps_out, decoration:rounding
# (managed by hyprland-options-adapter).
OPTION_SPECS: dict[str, dict[str, Any]] = {
    # --- Borders & Layout ---
    "hyprland.general.border_size": {
        "option": "general:border_size",
        "title": "Window border thickness",
        "description": "Pixel width of window borders in Hyprland.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 20},
        "default": 3,
        "featureGroup": "layout-borders",
        "keywords": ["border", "thickness", "kenarlik", "pencere", "hyprland"],
    },
    "hyprland.general.gaps_workspaces": {
        "option": "general:gaps_workspaces",
        "title": "Workspace slide gap",
        "description": "Extra gap in pixels shown between workspaces during slide transitions.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 200},
        "default": 50,
        "featureGroup": "layout-borders",
        "keywords": ["workspace", "gaps", "bosluk", "hyprland"],
    },
    "hyprland.general.resize_on_border": {
        "option": "general:resize_on_border",
        "title": "Resize windows by dragging border",
        "description": "Allows resizing tiled and floating windows by clicking and dragging their borders.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "layout-borders",
        "keywords": ["resize", "border", "mouse", "boyutlandir", "hyprland"],
    },
    "hyprland.general.allow_tearing": {
        "option": "general:allow_tearing",
        "title": "Allow screen tearing (low latency gaming)",
        "description": "Permits immediate presentation tearing when requested by fullscreen games.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "layout-borders",
        "keywords": ["tearing", "gaming", "latency", "vsync", "hyprland"],
    },
    "hyprland.general.no_focus_fallback": {
        "option": "general:no_focus_fallback",
        "title": "Prevent directional focus wraparound",
        "description": "Stops movefocus from wrapping to the opposite edge when no window exists in that direction.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "layout-borders",
        "keywords": ["focus", "fallback", "odak", "hyprland"],
    },
    "hyprland.general.layout": {
        "option": "general:layout",
        "title": "Tiling layout engine",
        "description": "Chooses between dwindle (binary split) and master-stack tiling layouts.",
        "valueType": "string",
        "choices": ["dwindle", "master"],
        "default": "dwindle",
        "featureGroup": "layout-borders",
        "keywords": ["layout", "dwindle", "master", "tiling", "duzen", "hyprland"],
    },
    "hyprland.general.snap.enabled": {
        "option": "general:snap:enabled",
        "title": "Floating window snapping",
        "description": "Snaps floating windows to nearby window edges and monitor borders.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "layout-borders",
        "keywords": ["snap", "floating", "yapisma", "hyprland"],
    },
    "hyprland.general.snap.window_gap": {
        "option": "general:snap:window_gap",
        "title": "Snap distance to windows",
        "description": "Pixel threshold for snapping floating windows to other windows.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 64},
        "default": 4,
        "featureGroup": "layout-borders",
        "keywords": ["snap", "gap", "window", "hyprland"],
    },
    "hyprland.general.snap.monitor_gap": {
        "option": "general:snap:monitor_gap",
        "title": "Snap distance to monitor edges",
        "description": "Pixel threshold for snapping floating windows to screen edges.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 64},
        "default": 5,
        "featureGroup": "layout-borders",
        "keywords": ["snap", "monitor", "edge", "hyprland"],
    },
    "hyprland.decoration.rounding_power": {
        "option": "decoration:rounding_power",
        "title": "Corner curvature (circle to squircle)",
        "description": "Controls corner curve exponent (2.0 = circular, higher = squircle).",
        "valueType": "number",
        "limits": {"minimum": 1.0, "maximum": 10.0},
        "default": 2.5,
        "featureGroup": "layout-borders",
        "keywords": ["rounding", "squircle", "corner", "kose", "hyprland"],
    },
    "hyprland.dwindle.preserve_split": {
        "option": "dwindle:preserve_split",
        "title": "Preserve dwindle split direction",
        "description": "Keeps split orientation fixed when moving or resizing tiled windows.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "layout-borders",
        "keywords": ["dwindle", "split", "tiling", "hyprland"],
    },
    "hyprland.dwindle.smart_split": {
        "option": "dwindle:smart_split",
        "title": "Smart split based on cursor position",
        "description": "Chooses split side dynamically from cursor quadrant inside the active window.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "layout-borders",
        "keywords": ["dwindle", "smart", "split", "hyprland"],
    },
    "hyprland.dwindle.smart_resizing": {
        "option": "dwindle:smart_resizing",
        "title": "Smart border resizing",
        "description": "Resizes the nearest window edge based on cursor position.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "layout-borders",
        "keywords": ["dwindle", "resize", "hyprland"],
    },
    "hyprland.master.mfact": {
        "option": "master:mfact",
        "title": "Master window split ratio",
        "description": "Screen fraction reserved for the master window in master-stack layout (0.05 to 0.95).",
        "valueType": "number",
        "limits": {"minimum": 0.05, "maximum": 0.95},
        "default": 0.55,
        "featureGroup": "layout-borders",
        "keywords": ["master", "mfact", "ratio", "split", "layout", "tiling", "hyprland"],
    },
    "hyprland.master.orientation": {
        "option": "master:orientation",
        "title": "Master layout orientation",
        "description": "Placement of the master window area when using master-stack tiling layout.",
        "valueType": "string",
        "choices": ["left", "right", "top", "bottom", "center"],
        "default": "left",
        "featureGroup": "layout-borders",
        "keywords": ["master", "orientation", "layout", "tiling", "left", "right", "center", "hyprland"],
    },
    # --- Blur & Glass ---
    "hyprland.decoration.blur.enabled": {
        "option": "decoration:blur:enabled",
        "title": "Enable background blur",
        "description": "Toggles real-time Kawase/Acrylic blur behind translucent windows and panels.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "blur",
        "keywords": ["blur", "bulaniklik", "glass", "cam", "hyprland"],
    },
    "hyprland.decoration.blur.size": {
        "option": "decoration:blur:size",
        "title": "Blur radius",
        "description": "Strength/radius of the background blur kernel.",
        "valueType": "integer",
        "limits": {"minimum": 1, "maximum": 40},
        "default": 10,
        "featureGroup": "blur",
        "keywords": ["blur", "size", "radius", "bulaniklik", "hyprland"],
    },
    "hyprland.decoration.blur.passes": {
        "option": "decoration:blur:passes",
        "title": "Blur quality passes",
        "description": "Number of blur shader passes (higher = smoother blur, more GPU usage).",
        "valueType": "integer",
        "limits": {"minimum": 1, "maximum": 8},
        "default": 3,
        "featureGroup": "blur",
        "keywords": ["blur", "passes", "quality", "gpu", "hyprland"],
    },
    "hyprland.decoration.blur.xray": {
        "option": "decoration:blur:xray",
        "title": "Blur X-Ray (wallpaper through floating)",
        "description": "Makes floating windows ignore tiled windows behind them when sampling blur.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "blur",
        "keywords": ["blur", "xray", "wallpaper", "hyprland"],
    },
    "hyprland.decoration.blur.new_optimizations": {
        "option": "decoration:blur:new_optimizations",
        "title": "Blur GPU optimizations",
        "description": "Enables Hyprland blur caching optimizations to reduce GPU load.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "blur",
        "keywords": ["blur", "performance", "gpu", "optimization", "hyprland"],
    },
    "hyprland.decoration.blur.brightness": {
        "option": "decoration:blur:brightness",
        "title": "Blur brightness",
        "description": "Brightness multiplier applied to blurred backgrounds (0.0 to 2.0).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 2.0},
        "default": 1.0,
        "featureGroup": "blur",
        "keywords": ["blur", "brightness", "parlaklik", "hyprland"],
    },
    "hyprland.decoration.blur.contrast": {
        "option": "decoration:blur:contrast",
        "title": "Blur contrast",
        "description": "Contrast multiplier applied to blurred backgrounds (0.0 to 2.0).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 2.0},
        "default": 0.89,
        "featureGroup": "blur",
        "keywords": ["blur", "contrast", "kontrast", "hyprland"],
    },
    "hyprland.decoration.blur.noise": {
        "option": "decoration:blur:noise",
        "title": "Blur frosted grain noise",
        "description": "Subtle frosted-glass noise added to blurred surfaces (0.0 to 1.0).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 1.0},
        "default": 0.05,
        "featureGroup": "blur",
        "keywords": ["blur", "noise", "grain", "frosted", "hyprland"],
    },
    "hyprland.decoration.blur.vibrancy": {
        "option": "decoration:blur:vibrancy",
        "title": "Blur color vibrancy",
        "description": "Boosts color saturation behind blurred surfaces (0.0 to 1.0).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 1.0},
        "default": 0.5,
        "featureGroup": "blur",
        "keywords": ["blur", "vibrancy", "color", "saturation", "hyprland"],
    },
    "hyprland.decoration.blur.popups": {
        "option": "decoration:blur:popups",
        "title": "Blur context menus and popups",
        "description": "Applies background blur behind right-click menus and popups.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "blur",
        "keywords": ["blur", "popups", "menus", "hyprland"],
    },
    # --- Shadows, Opacity & Dimming ---
    "hyprland.decoration.active_opacity": {
        "option": "decoration:active_opacity",
        "title": "Focused window opacity",
        "description": "Opacity of the currently focused window (0.10 to 1.00).",
        "valueType": "number",
        "limits": {"minimum": 0.1, "maximum": 1.0},
        "default": 0.8,
        "featureGroup": "shadows-dimming",
        "keywords": ["opacity", "transparency", "active", "saydamlik", "opaklik", "hyprland"],
    },
    "hyprland.decoration.inactive_opacity": {
        "option": "decoration:inactive_opacity",
        "title": "Unfocused window opacity",
        "description": "Opacity of background/unfocused windows (0.10 to 1.00).",
        "valueType": "number",
        "limits": {"minimum": 0.1, "maximum": 1.0},
        "default": 0.8,
        "featureGroup": "shadows-dimming",
        "keywords": ["opacity", "transparency", "inactive", "saydamlik", "opaklik", "hyprland"],
    },
    "hyprland.decoration.dim_inactive": {
        "option": "decoration:dim_inactive",
        "title": "Dim unfocused windows",
        "description": "Darkens inactive windows slightly to emphasize the focused window.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "shadows-dimming",
        "keywords": ["dim", "inactive", "focus", "karartma", "hyprland"],
    },
    "hyprland.decoration.dim_strength": {
        "option": "decoration:dim_strength",
        "title": "Inactive window dim strength",
        "description": "How strongly unfocused windows are dimmed (0.00 to 1.00).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 1.0},
        "default": 0.35,
        "featureGroup": "shadows-dimming",
        "keywords": ["dim", "strength", "karartma", "hyprland"],
    },
    "hyprland.decoration.dim_special": {
        "option": "decoration:dim_special",
        "title": "Special workspace backdrop dim",
        "description": "Dimming applied behind scratchpad/special workspaces (0.00 to 1.00).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 1.0},
        "default": 0.2,
        "featureGroup": "shadows-dimming",
        "keywords": ["dim", "special", "scratchpad", "hyprland"],
    },
    "hyprland.decoration.shadow.enabled": {
        "option": "decoration:shadow:enabled",
        "title": "Enable window drop shadows",
        "description": "Draws soft drop shadows underneath windows.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "shadows-dimming",
        "keywords": ["shadow", "golge", "decoration", "hyprland"],
    },
    "hyprland.decoration.shadow.range": {
        "option": "decoration:shadow:range",
        "title": "Shadow spread range",
        "description": "Radius in pixels of window drop shadows.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 100},
        "default": 28,
        "featureGroup": "shadows-dimming",
        "keywords": ["shadow", "range", "size", "golge", "hyprland"],
    },
    "hyprland.decoration.shadow.render_power": {
        "option": "decoration:shadow:render_power",
        "title": "Shadow falloff sharpness",
        "description": "Controls shadow fade falloff (1 = softest, 4 = sharpest).",
        "valueType": "integer",
        "limits": {"minimum": 1, "maximum": 4},
        "default": 2,
        "featureGroup": "shadows-dimming",
        "keywords": ["shadow", "falloff", "power", "golge", "hyprland"],
    },
    "hyprland.decoration.shadow.sharp": {
        "option": "decoration:shadow:sharp",
        "title": "Hard-edged shadows",
        "description": "Renders crisp, non-blurred drop shadows.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "shadows-dimming",
        "keywords": ["shadow", "sharp", "golge", "hyprland"],
    },
    "hyprland.decoration.shadow.scale": {
        "option": "decoration:shadow:scale",
        "title": "Shadow scale",
        "description": "Relative scale of window shadows (0.50 to 1.50).",
        "valueType": "number",
        "limits": {"minimum": 0.5, "maximum": 1.5},
        "default": 1.0,
        "featureGroup": "shadows-dimming",
        "keywords": ["shadow", "scale", "golge", "hyprland"],
    },
    # --- Animations & Gestures ---
    "hyprland.animations.enabled": {
        "option": "animations:enabled",
        "title": "Enable Hyprland animations",
        "description": "Master switch for all window, workspace, and layer animations in Hyprland.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "animations",
        "keywords": ["animations", "motion", "animasyon", "hareket", "hyprland"],
    },
    "hyprland.gestures.workspace_swipe_distance": {
        "option": "gestures:workspace_swipe_distance",
        "title": "Workspace swipe gesture distance",
        "description": "Touchpad swipe distance in pixels required to switch workspaces.",
        "valueType": "integer",
        "limits": {"minimum": 100, "maximum": 2000},
        "default": 700,
        "featureGroup": "animations",
        "keywords": ["gestures", "swipe", "workspace", "touchpad", "hyprland"],
    },
    "hyprland.gestures.workspace_swipe_cancel_ratio": {
        "option": "gestures:workspace_swipe_cancel_ratio",
        "title": "Workspace swipe cancel threshold",
        "description": "Fraction of swipe distance below which a workspace swipe cancels (0.0 to 1.0).",
        "valueType": "number",
        "limits": {"minimum": 0.0, "maximum": 1.0},
        "default": 0.2,
        "featureGroup": "animations",
        "keywords": ["gestures", "swipe", "cancel", "hyprland"],
    },
    "hyprland.gestures.workspace_swipe_create_new": {
        "option": "gestures:workspace_swipe_create_new",
        "title": "Swipe past last workspace creates new",
        "description": "Allows touchpad swipe to open a fresh empty workspace at the end.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "animations",
        "keywords": ["gestures", "swipe", "workspace", "hyprland"],
    },
    "hyprland.gestures.workspace_swipe_direction_lock": {
        "option": "gestures:workspace_swipe_direction_lock",
        "title": "Lock workspace swipe direction",
        "description": "Prevents diagonal finger drift during workspace swipe gestures.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "animations",
        "keywords": ["gestures", "swipe", "lock", "hyprland"],
    },
    # --- Keyboard, Mouse & Touchpad ---
    "hyprland.input.kb_layout": {
        "option": "input:kb_layout",
        "title": "Keyboard layout (XKB)",
        "description": "Active keyboard layout(s) in Hyprland (e.g. 'tr', 'us', 'tr,us').",
        "valueType": "string",
        "choices": ["tr", "us", "tr,us", "us,tr", "de", "fr", "gb", "es", "ru"],
        "default": "tr",
        "featureGroup": "input-keyboard",
        "keywords": ["keyboard", "klavye", "layout", "duzen", "turkish", "tr", "us", "hyprland"],
    },
    "hyprland.input.kb_variant": {
        "option": "input:kb_variant",
        "title": "Keyboard layout variant (XKB)",
        "description": "Optional XKB layout variant (e.g. 'altgr-intl', 'dvorak', 'colemak'; empty = layout default).",
        "valueType": "string",
        "allowEmpty": True,
        "default": "",
        "featureGroup": "input-keyboard",
        "keywords": ["keyboard", "klavye", "variant", "xkb", "dvorak", "colemak", "hyprland"],
    },
    "hyprland.input.kb_options": {
        "option": "input:kb_options",
        "title": "Keyboard XKB options",
        "description": "Comma-separated XKB rules (e.g. 'caps:escape', 'grp:alt_shift_toggle'; empty = none).",
        "valueType": "string",
        "allowEmpty": True,
        "default": "",
        "featureGroup": "input-keyboard",
        "keywords": ["keyboard", "klavye", "options", "xkb", "caps", "escape", "toggle", "hyprland"],
    },
    "hyprland.input.sensitivity": {
        "option": "input:sensitivity",
        "title": "Mouse & pointer sensitivity",
        "description": "Pointer speed adjustment in Hyprland (-1.0 = slowest, 0.0 = default, 1.0 = fastest).",
        "valueType": "number",
        "limits": {"minimum": -1.0, "maximum": 1.0},
        "default": 0.0,
        "featureGroup": "input-keyboard",
        "keywords": ["mouse", "pointer", "sensitivity", "speed", "fare", "hassasiyet", "hyprland"],
    },
    "hyprland.input.accel_profile": {
        "option": "input:accel_profile",
        "title": "Mouse acceleration profile",
        "description": "Pointer acceleration mode: default (auto), adaptive, or flat (raw input for gaming).",
        "valueType": "string",
        "choices": ["", "adaptive", "flat"],
        "allowEmpty": True,
        "omitLuaWhenEmpty": True,
        "default": "",
        "featureGroup": "input-keyboard",
        "keywords": ["mouse", "acceleration", "accel", "flat", "adaptive", "gaming", "raw", "fare", "hyprland"],
    },
    "hyprland.input.numlock_by_default": {
        "option": "input:numlock_by_default",
        "title": "Enable NumLock on startup",
        "description": "Turns NumLock on automatically when Hyprland starts.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "input-keyboard",
        "keywords": ["numlock", "keyboard", "klavye", "hyprland"],
    },
    "hyprland.input.repeat_delay": {
        "option": "input:repeat_delay",
        "title": "Key repeat delay (ms)",
        "description": "Delay in milliseconds before a held key starts repeating.",
        "valueType": "integer",
        "limits": {"minimum": 100, "maximum": 1000},
        "default": 250,
        "featureGroup": "input-keyboard",
        "keywords": ["keyboard", "repeat", "delay", "klavye", "hyprland"],
    },
    "hyprland.input.repeat_rate": {
        "option": "input:repeat_rate",
        "title": "Key repeat rate (chars/sec)",
        "description": "Number of key repeats per second while holding a key.",
        "valueType": "integer",
        "limits": {"minimum": 5, "maximum": 120},
        "default": 35,
        "featureGroup": "input-keyboard",
        "keywords": ["keyboard", "repeat", "rate", "klavye", "hyprland"],
    },
    "hyprland.input.follow_mouse": {
        "option": "input:follow_mouse",
        "title": "Window focus follows mouse",
        "description": "Controls how moving the pointer changes keyboard focus between windows.",
        "valueType": "integer",
        "choices": [
            "0: Disabled (click to focus)",
            "1: Always follow cursor",
            "2: Separate cursor & keyboard focus",
            "3: Full cursor separation",
        ],
        "limits": {"minimum": 0, "maximum": 3},
        "default": 1,
        "featureGroup": "input-keyboard",
        "keywords": ["mouse", "focus", "follow", "fare", "odak", "hyprland"],
    },
    "hyprland.input.touchpad.natural_scroll": {
        "option": "input:touchpad:natural_scroll",
        "title": "Touchpad natural scrolling",
        "description": "Inverts touchpad scroll direction so content follows finger motion.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "input-keyboard",
        "keywords": ["touchpad", "scroll", "natural", "dokunmatik", "hyprland"],
    },
    "hyprland.input.touchpad.disable_while_typing": {
        "option": "input:touchpad:disable_while_typing",
        "title": "Disable touchpad while typing",
        "description": "Ignores accidental palm touches while typing on the keyboard.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "input-keyboard",
        "keywords": ["touchpad", "typing", "palm", "dokunmatik", "hyprland"],
    },
    "hyprland.input.touchpad.clickfinger_behavior": {
        "option": "input:touchpad:clickfinger_behavior",
        "title": "Multi-finger click (clickfinger)",
        "description": "Uses 1/2/3 finger clicks for left/right/middle click instead of button zones.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "input-keyboard",
        "keywords": ["touchpad", "clickfinger", "right click", "hyprland"],
    },
    "hyprland.input.touchpad.scroll_factor": {
        "option": "input:touchpad:scroll_factor",
        "title": "Touchpad scroll speed multiplier",
        "description": "Multiplier for touchpad scrolling speed (0.10 to 3.00).",
        "valueType": "number",
        "limits": {"minimum": 0.1, "maximum": 3.0},
        "default": 0.7,
        "featureGroup": "input-keyboard",
        "keywords": ["touchpad", "scroll", "speed", "factor", "hyprland"],
    },
    "hyprland.input.touchpad.tap-to-click": {
        "option": "input:touchpad:tap-to-click",
        "luaKey": "input.touchpad.tap_to_click",
        "title": "Touchpad tap-to-click",
        "description": "Tapping the touchpad with 1, 2, or 3 fingers triggers left, right, or middle click.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "input-keyboard",
        "keywords": ["touchpad", "tap", "click", "dokunmatik", "tiklama", "hyprland"],
    },
    # --- System Behavior, Display & Cursor Zoom ---
    "hyprland.misc.vrr": {
        "option": "misc:vrr",
        "title": "Adaptive Sync / Variable Refresh Rate (VRR)",
        "description": "Controls FreeSync / G-Sync variable refresh rate mode.",
        "valueType": "integer",
        "choices": [
            "0: Off",
            "1: Always On",
            "2: Fullscreen Only",
            "3: Fullscreen Video & Games",
        ],
        "limits": {"minimum": 0, "maximum": 3},
        "default": 0,
        "featureGroup": "misc",
        "keywords": ["vrr", "freesync", "gsync", "adaptive sync", "monitor", "gaming", "hyprland"],
    },
    "hyprland.misc.disable_hyprland_logo": {
        "option": "misc:disable_hyprland_logo",
        "title": "Hide default Hyprland wallpaper logo",
        "description": "Disables the built-in Hyprland background logo rendering.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["logo", "wallpaper", "hyprland", "misc"],
    },
    "hyprland.misc.disable_splash_rendering": {
        "option": "misc:disable_splash_rendering",
        "title": "Hide Hyprland splash text",
        "description": "Disables the random quote splash rendered on the background.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["splash", "text", "hyprland", "misc"],
    },
    "hyprland.misc.force_default_wallpaper": {
        "option": "misc:force_default_wallpaper",
        "title": "Hyprland default wallpaper mode",
        "description": "Controls Hyprland's built-in fallback wallpaper (-1 = random, 0 = disabled, 1-2 = mascot wallpaper).",
        "valueType": "integer",
        "choices": [
            "-1: Random (default)",
            "0: Disabled (plain)",
            "1: Mascot wallpaper 1",
            "2: Mascot wallpaper 2",
        ],
        "limits": {"minimum": -1, "maximum": 2},
        "default": -1,
        "featureGroup": "misc",
        "keywords": ["wallpaper", "default", "mascot", "anime", "background", "hyprland", "misc"],
    },
    "hyprland.misc.animate_manual_resizes": {
        "option": "misc:animate_manual_resizes",
        "title": "Animate manual window resizing",
        "description": "Smoothly animates windows while resizing them with the mouse.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "misc",
        "keywords": ["animate", "resize", "mouse", "hyprland"],
    },
    "hyprland.misc.animate_mouse_windowdragging": {
        "option": "misc:animate_mouse_windowdragging",
        "title": "Animate mouse window dragging",
        "description": "Smoothly animates windows moved by mouse drag.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "misc",
        "keywords": ["animate", "drag", "window", "hyprland"],
    },
    "hyprland.misc.enable_swallow": {
        "option": "misc:enable_swallow",
        "title": "Terminal window swallowing",
        "description": "Temporarily hides the launching terminal window while its GUI child app is open.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "misc",
        "keywords": ["swallow", "terminal", "kitty", "hyprland"],
    },
    "hyprland.misc.focus_on_activate": {
        "option": "misc:focus_on_activate",
        "title": "Focus windows requesting activation",
        "description": "Automatically switches focus to apps requesting activation (e.g. clicked links).",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["focus", "activate", "odak", "hyprland"],
    },
    "hyprland.misc.mouse_move_enables_dpms": {
        "option": "misc:mouse_move_enables_dpms",
        "title": "Wake display on mouse movement",
        "description": "Wakes a manually turned-off display when the mouse moves.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["dpms", "wake", "mouse", "display", "hyprland"],
    },
    "hyprland.misc.key_press_enables_dpms": {
        "option": "misc:key_press_enables_dpms",
        "title": "Wake display on key press",
        "description": "Wakes a manually turned-off display when any key is pressed.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["dpms", "wake", "keyboard", "display", "hyprland"],
    },
    "hyprland.xwayland.force_zero_scaling": {
        "option": "xwayland:force_zero_scaling",
        "title": "Crisp XWayland apps (zero scaling)",
        "description": "Prevents blurry fractional scaling on legacy X11/XWayland applications.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["xwayland", "scaling", "blurry", "dpi", "hyprland"],
    },
    "hyprland.cursor.zoom_factor": {
        "option": "cursor:zoom_factor",
        "title": "Screen magnifier zoom factor",
        "description": "Live Hyprland screen zoom level around the cursor (1.0 = normal, up to 5.0).",
        "valueType": "number",
        "limits": {"minimum": 1.0, "maximum": 5.0},
        "default": 1.0,
        "featureGroup": "misc",
        "keywords": ["zoom", "magnifier", "cursor", "yakinlastir", "hyprland"],
    },
    "hyprland.cursor.zoom_rigid": {
        "option": "cursor:zoom_rigid",
        "title": "Rigid cursor zoom tracking",
        "description": "Keeps the cursor centered rigidly while screen zoom is active.",
        "valueType": "boolean",
        "default": False,
        "featureGroup": "misc",
        "keywords": ["zoom", "cursor", "rigid", "hyprland"],
    },
    "hyprland.binds.hide_special_on_workspace_change": {
        "option": "binds:hide_special_on_workspace_change",
        "title": "Hide scratchpad on workspace switch",
        "description": "Closes special/scratchpad workspace automatically when changing workspaces.",
        "valueType": "boolean",
        "default": True,
        "featureGroup": "misc",
        "keywords": ["binds", "special", "workspace", "scratchpad", "hyprland"],
    },
    "hyprland.binds.scroll_event_delay": {
        "option": "binds:scroll_event_delay",
        "title": "Mouse wheel bind cooldown (ms)",
        "description": "Minimum delay in milliseconds between scroll-wheel keybind triggers.",
        "valueType": "integer",
        "limits": {"minimum": 0, "maximum": 1000},
        "default": 0,
        "featureGroup": "misc",
        "keywords": ["binds", "scroll", "wheel", "delay", "hyprland"],
    },
}

CUSTOM_LIST_SPECS: dict[str, dict[str, Any]] = {
    "hyprland.custom.autostart": {
        "title": "Startup applications (exec-once)",
        "description": "Commands launched automatically when Hyprland starts (persisted in ~/.config/hypr/custom/execs.lua).",
        "valueType": "array",
        "controlType": "array",
        "featureGroup": "startup-env-binds",
        "keywords": ["autostart", "startup", "exec", "baslangic", "uygulama", "hyprland"],
    },
    "hyprland.custom.env": {
        "title": "Hyprland environment variables",
        "description": "Session environment variables in 'KEY=VALUE' format (persisted in ~/.config/hypr/custom/env.lua).",
        "valueType": "array",
        "controlType": "array",
        "featureGroup": "startup-env-binds",
        "keywords": ["env", "environment", "variable", "ortam", "degisken", "hyprland"],
    },
    "hyprland.custom.keybinds": {
        "title": "Custom Hyprland keybinds",
        "description": "Simplified shortcuts in 'MODS+KEY => COMMAND' format (e.g. 'SUPER+SHIFT+B => firefox'), persisted in ~/.config/hypr/custom/keybinds.lua.",
        "valueType": "array",
        "controlType": "array",
        "featureGroup": "startup-env-binds",
        "keywords": ["keybind", "shortcut", "hotkey", "kisayol", "tus", "hyprland"],
    },
}

ALL_SETTING_IDS: tuple[str, ...] = tuple(OPTION_SPECS.keys()) + tuple(CUSTOM_LIST_SPECS.keys())


def _lua_key_for_setting(setting_id: str) -> str:
    spec = OPTION_SPECS[setting_id]
    lua_key = spec.get("luaKey")
    if isinstance(lua_key, str) and lua_key:
        return lua_key
    return spec["option"].replace(":", ".")


_LUA_KEY_TO_SETTING_ID: dict[str, str] = {}
for _sid, _spec in OPTION_SPECS.items():
    _LUA_KEY_TO_SETTING_ID[_spec["option"].replace(":", ".")] = _sid
    if isinstance(_spec.get("luaKey"), str) and _spec["luaKey"]:
        _LUA_KEY_TO_SETTING_ID[_spec["luaKey"]] = _sid


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise HyprlandGodModeError("unsafe_state_directory", "NEXUS state directory is not owned by this user.")


@contextmanager
def _state_lock(state_root: Path):
    locks_dir = state_root / "locks"
    _ensure_private_dir(locks_dir)
    lock_file = locks_dir / "hyprland-godmode.lock"
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _is_user_regular_file(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.exists():
            return False
        st = path.stat()
        return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
    except OSError:
        return False


def _atomic_write_text(path: Path, text: str, default_mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    orig_stat = path.stat() if path.exists() and not path.is_symlink() else None
    attrs: dict[str, bytes] = {}
    if orig_stat is not None:
        try:
            for name in os.listxattr(path, follow_symlinks=False):
                attrs[name] = os.getxattr(path, name, follow_symlinks=False)
        except OSError:
            attrs = {}
    fd, tmp_name = tempfile.mkstemp(prefix=f".nexus-{path.name}-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        mode = stat.S_IMODE(orig_stat.st_mode) if orig_stat is not None else default_mode
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        for name, val in attrs.items():
            try:
                os.setxattr(tmp, name, val, follow_symlinks=False)
            except OSError:
                pass
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    _atomic_write_text(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        default_mode=0o600,
    )


def _lua_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _lua_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, str):
        return _lua_quote(value)
    raise HyprlandGodModeError("value_invalid", f"Unsupported Lua value type: {type(value).__name__}")


def _extract_managed_block(text: str, begin_marker: str, end_marker: str) -> str | None:
    start = text.find(begin_marker)
    if start < 0:
        return None
    end = text.find(end_marker, start + len(begin_marker))
    if end < 0:
        return None
    return text[start + len(begin_marker):end]


def _replace_managed_block(text: str, begin_marker: str, end_marker: str, body: str) -> str:
    block = f"{begin_marker}\n{body.rstrip()}\n{end_marker}\n" if body.strip() else ""
    start = text.find(begin_marker)
    if start >= 0:
        end = text.find(end_marker, start + len(begin_marker))
        if end >= 0:
            after_end = end + len(end_marker)
            if after_end < len(text) and text[after_end:after_end + 1] == "\n":
                after_end += 1
            before = text[:start]
            after = text[after_end:]
            if not block:
                return (before.rstrip("\n") + "\n" + after.lstrip("\n")).rstrip("\n") + "\n" if (before.strip() or after.strip()) else "\n"
            return before + block + after
    if not block:
        return text
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix.strip():
        prefix += "\n"
    return prefix + block


def _parse_nested_lua_overrides(block: str) -> dict[str, Any]:
    """Parse NEXUS managed block entries written as `["section.key"] = <literal>,`."""
    values: dict[str, Any] = {}
    for line in block.splitlines():
        m = re.match(r'^\s*\["([a-zA-Z0-9_.:-]+)"\]\s*=\s*(.+?)\s*,?\s*(?:--.*)?$', line)
        if not m:
            continue
        dot_key = m.group(1).replace(":", ".")
        sid = _LUA_KEY_TO_SETTING_ID.get(dot_key, f"hyprland.{dot_key}")
        if sid not in OPTION_SPECS:
            continue
        raw_val = m.group(2).strip()
        spec = OPTION_SPECS[sid]
        vt = spec["valueType"]
        try:
            if vt == "boolean":
                if raw_val in ("true", "false"):
                    values[sid] = raw_val == "true"
            elif vt == "integer":
                values[sid] = int(raw_val)
            elif vt == "number":
                values[sid] = float(raw_val)
            elif vt == "string":
                values[sid] = json.loads(raw_val)
        except (ValueError, json.JSONDecodeError):
            continue
    return values


def _render_controls_block(values: Mapping[str, Any]) -> str:
    rendered_entries: list[str] = []
    for sid in sorted(values):
        spec = OPTION_SPECS.get(sid)
        if spec is None:
            continue
        val = values[sid]
        if spec.get("omitLuaWhenEmpty") and val == "":
            continue
        lua_key = _lua_key_for_setting(sid)
        rendered_entries.append(f'    ["{lua_key}"] = {_lua_literal(val)},')
    if not rendered_entries:
        return ""
    lines = [
        "-- Managed by NEXUS Hyprland Controls (safe transactional block).",
        "hl.config({",
        *rendered_entries,
        "})",
    ]
    return "\n".join(lines)


def _read_managed_block_controls(path: Path, begin_marker: str, end_marker: str) -> dict[str, Any]:
    if not _is_user_regular_file(path):
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    block = _extract_managed_block(text, begin_marker, end_marker)
    if not block:
        return {}
    return _parse_nested_lua_overrides(block)


def _read_managed_controls(paths: HyprlandGodModePaths) -> dict[str, Any]:
    raw = _read_managed_block_controls(paths.custom_general, _CTRL_BEGIN, _CTRL_END)
    return {k: v for k, v in raw.items() if not is_post_glow_shadow_setting(k)}


def _read_post_glow_controls(paths: HyprlandGodModePaths) -> dict[str, Any]:
    raw = _read_managed_block_controls(paths.custom_post_glow, _POST_GLOW_BEGIN, _POST_GLOW_END)
    return {k: v for k, v in raw.items() if is_post_glow_shadow_setting(k)}


def _hyprland_lua_loads_post_glow_after_glow(text: str) -> bool:
    active_lines = [line for line in text.splitlines() if not line.lstrip().startswith("--")]
    joined = "\n".join(active_lines)
    post_idx = joined.rfind("nexus-post-glow.lua")
    if post_idx < 0:
        return False
    glow_matches = [m.start() for m in re.finditer(r"(?<![A-Za-z0-9_-])glow\.lua", joined)]
    glow_idx = glow_matches[-1] if glow_matches else -1
    return glow_idx < 0 or post_idx > glow_idx


def _ensure_post_glow_hook_text(text: str) -> str:
    if _hyprland_lua_loads_post_glow_after_glow(text):
        return text
    cleaned = _replace_managed_block(text, _HYPRLAND_LUA_HOOK_BEGIN, _HYPRLAND_LUA_HOOK_END, "")
    hook_body = (
        "-- NEXUS Hyprland Controls: persistent shadow overrides applied after custom/glow.lua.\n"
        'if is_file_exists(HOME .. "/.config/hypr/custom/nexus-post-glow.lua") then\n'
        '    dofile(HOME .. "/.config/hypr/custom/nexus-post-glow.lua")\n'
        "end"
    )
    return _replace_managed_block(cleaned, _HYPRLAND_LUA_HOOK_BEGIN, _HYPRLAND_LUA_HOOK_END, hook_body)


def _parse_base_lua_values(lua_files: tuple[Path, ...]) -> dict[str, Any]:
    """Read literal values from existing hl.config({...}) files in load order."""
    from nexus_adapter_registry import parse_hl_config_blocks

    found: dict[str, Any] = {}
    for p in lua_files:
        if not _is_user_regular_file(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            parsed = parse_hl_config_blocks(text)
            entries = parsed.items() if isinstance(parsed, dict) else ((k, v) for k, v, _ in parsed)
            for dot_key, val in entries:
                sid = _LUA_KEY_TO_SETTING_ID.get(dot_key, f"hyprland.{dot_key}")
                spec = OPTION_SPECS.get(sid)
                if spec is None:
                    continue
                vt = spec["valueType"]
                if vt == "boolean" and isinstance(val, bool):
                    found[sid] = val
                elif vt == "integer" and isinstance(val, int) and not isinstance(val, bool):
                    found[sid] = int(val)
                elif vt == "number" and isinstance(val, (int, float)) and not isinstance(val, bool):
                    found[sid] = round(float(val), 4)
                elif vt == "string" and isinstance(val, str):
                    found[sid] = val
        except Exception:
            continue
    return found


def _read_custom_list(paths: HyprlandGodModePaths, setting_id: str) -> list[str]:
    if setting_id == "hyprland.custom.autostart":
        if not _is_user_regular_file(paths.custom_execs):
            return []
        block = _extract_managed_block(paths.custom_execs.read_text(encoding="utf-8", errors="replace"), _AUTOSTART_BEGIN, _AUTOSTART_END)
        if not block:
            return []
        out: list[str] = []
        for line in block.splitlines():
            m = re.match(r'^\s*hl\.exec_cmd\((".*")\)\s*$', line)
            if m:
                try:
                    out.append(str(json.loads(m.group(1))))
                except json.JSONDecodeError:
                    pass
        return out

    if setting_id == "hyprland.custom.env":
        if not _is_user_regular_file(paths.custom_env):
            return []
        block = _extract_managed_block(paths.custom_env.read_text(encoding="utf-8", errors="replace"), _ENV_BEGIN, _ENV_END)
        if not block:
            return []
        out_env: list[str] = []
        for line in block.splitlines():
            m = re.match(r'^\s*hl\.env\(("[^"]+"),\s*(".*")\)\s*$', line)
            if m:
                try:
                    k = str(json.loads(m.group(1)))
                    v = str(json.loads(m.group(2)))
                    out_env.append(f"{k}={v}")
                except json.JSONDecodeError:
                    pass
        return out_env

    if setting_id == "hyprland.custom.keybinds":
        if not _is_user_regular_file(paths.custom_keybinds):
            return []
        block = _extract_managed_block(paths.custom_keybinds.read_text(encoding="utf-8", errors="replace"), _KEYBINDS_BEGIN, _KEYBINDS_END)
        if not block:
            return []
        out_kb: list[str] = []
        for line in block.splitlines():
            m = re.match(r'^\s*hl\.bind\(("[^"]+"),\s*hl\.dsp\.exec_cmd\((".*")\),\s*\{.*\}\)\s*$', line)
            if m:
                try:
                    combo = str(json.loads(m.group(1)))
                    cmd = str(json.loads(m.group(2)))
                    out_kb.append(f"{combo} => {cmd}")
                except json.JSONDecodeError:
                    pass
        return out_kb

    return []


def _render_custom_list_block(setting_id: str, items: list[str]) -> str:
    if not items:
        return ""
    if setting_id == "hyprland.custom.autostart":
        lines = ["-- Managed by NEXUS Startup Applications.", 'hl.on("hyprland.start", function()']
        for cmd in items:
            lines.append(f"    hl.exec_cmd({_lua_quote(cmd)})")
        lines.append("end)")
        return "\n".join(lines)
    if setting_id == "hyprland.custom.env":
        lines = ["-- Managed by NEXUS Environment Variables."]
        for pair in items:
            k, v = pair.split("=", 1)
            lines.append(f"hl.env({_lua_quote(k)}, {_lua_quote(v)})")
        return "\n".join(lines)
    if setting_id == "hyprland.custom.keybinds":
        lines = ["-- Managed by NEXUS Custom Keybinds."]
        for entry in items:
            combo, cmd = entry.split("=>", 1)
            lines.append(
                f'hl.bind({_lua_quote(combo.strip())}, hl.dsp.exec_cmd({_lua_quote(cmd.strip())}), {{ description = "NEXUS custom keybind" }})'
            )
        return "\n".join(lines)
    return ""


def _run_hyprctl(paths: HyprlandGodModePaths, args: list[str], timeout: float = 4.0) -> tuple[int, str, str]:
    cmd = [paths.hyprctl, *args]
    if paths.hyprctl_runner is not None:
        raw = paths.hyprctl_runner(cmd)
        if isinstance(raw, tuple) and len(raw) == 3:
            return int(raw[0]), str(raw[1]), str(raw[2])
        return 0, str(raw), ""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HyprlandGodModeError("hyprland_unavailable", "Hyprland could not be reached.") from exc


def _read_live_option(paths: HyprlandGodModePaths, setting_id: str) -> Any | None:
    if not paths.allow_live_hyprctl:
        return None
    spec = OPTION_SPECS[setting_id]
    try:
        rc, out, _ = _run_hyprctl(paths, ["-j", "getoption", spec["option"]])
    except HyprlandGodModeError:
        return None
    if rc != 0 or not out:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    vt = spec["valueType"]
    if vt == "boolean":
        if isinstance(data.get("bool"), bool):
            return data["bool"]
        if isinstance(data.get("int"), int):
            return bool(data["int"])
    elif vt == "integer":
        if isinstance(data.get("int"), int) and not isinstance(data.get("int"), bool):
            return int(data["int"])
    elif vt == "number":
        if isinstance(data.get("float"), (int, float)) and not isinstance(data.get("float"), bool):
            return round(float(data["float"]), 4)
        if isinstance(data.get("int"), int) and not isinstance(data.get("int"), bool):
            return float(data["int"])
    elif vt == "string":
        if isinstance(data.get("str"), str):
            raw_str = data["str"]
            return "" if raw_str == "[[EMPTY]]" else raw_str
    return None


def setting_available(setting_id: str, paths: HyprlandGodModePaths) -> bool:
    if setting_id not in OPTION_SPECS and setting_id not in CUSTOM_LIST_SPECS:
        return False
    return _is_user_regular_file(paths.main_general) and paths.custom_dir.is_dir()


def validate_setting_value(setting_id: str, value: Any) -> Any:
    if setting_id in OPTION_SPECS:
        spec = OPTION_SPECS[setting_id]
        vt = spec["valueType"]
        lim = spec.get("limits") or {}
        if vt == "boolean":
            if not isinstance(value, bool):
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a boolean.")
            return value
        if vt == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a whole integer.")
            if "minimum" in lim and value < lim["minimum"]:
                raise HyprlandGodModeError("value_out_of_range", f"{setting_id} must be >= {lim['minimum']}.")
            if "maximum" in lim and value > lim["maximum"]:
                raise HyprlandGodModeError("value_out_of_range", f"{setting_id} must be <= {lim['maximum']}.")
            return int(value)
        if vt == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a finite number.")
            val = round(float(value), 4)
            if "minimum" in lim and val < float(lim["minimum"]):
                raise HyprlandGodModeError("value_out_of_range", f"{setting_id} must be >= {lim['minimum']}.")
            if "maximum" in lim and val > float(lim["maximum"]):
                raise HyprlandGodModeError("value_out_of_range", f"{setting_id} must be <= {lim['maximum']}.")
            return val
        if vt == "string":
            if not isinstance(value, str):
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a string.")
            cleaned = value.strip()
            allow_empty = bool(spec.get("allowEmpty", False))
            if not cleaned:
                if allow_empty:
                    return ""
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a non-empty single-line string.")
            if not _SAFE_SINGLE_LINE_RE.fullmatch(cleaned):
                raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a valid single-line string.")
            if setting_id == "hyprland.general.layout" and cleaned not in ("dwindle", "master"):
                raise HyprlandGodModeError("value_invalid", "Layout must be 'dwindle' or 'master'.")
            if setting_id == "hyprland.master.orientation" and cleaned not in ("left", "right", "top", "bottom", "center"):
                raise HyprlandGodModeError("value_invalid", "Master orientation must be left, right, top, bottom, or center.")
            if setting_id == "hyprland.input.kb_layout" and not _KB_LAYOUT_RE.fullmatch(cleaned):
                raise HyprlandGodModeError("value_invalid", "Keyboard layout contains unsupported characters.")
            if setting_id == "hyprland.input.kb_variant" and not _KB_VARIANT_RE.fullmatch(cleaned):
                raise HyprlandGodModeError("value_invalid", "Keyboard variant contains unsupported characters.")
            if setting_id == "hyprland.input.kb_options" and not _KB_OPTIONS_RE.fullmatch(cleaned):
                raise HyprlandGodModeError("value_invalid", "Keyboard options contain unsupported characters.")
            if setting_id == "hyprland.input.accel_profile" and cleaned not in ("adaptive", "flat") and not _ACCEL_CUSTOM_RE.fullmatch(cleaned):
                raise HyprlandGodModeError("value_invalid", "Acceleration profile must be empty (default), 'adaptive', 'flat', or 'custom <step> <points>'.")
            return cleaned

    if setting_id in CUSTOM_LIST_SPECS:
        if not isinstance(value, list):
            raise HyprlandGodModeError("value_invalid", f"{setting_id} must be a list of strings.")
        cleaned_list: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise HyprlandGodModeError("value_invalid", f"All entries in {setting_id} must be strings.")
            s = item.strip()
            if not s or not _SAFE_SINGLE_LINE_RE.fullmatch(s):
                raise HyprlandGodModeError("value_invalid", f"Invalid single-line entry in {setting_id}.")
            if setting_id == "hyprland.custom.env":
                if "=" not in s:
                    raise HyprlandGodModeError("value_invalid", "Environment entries must use 'KEY=VALUE' format.")
                k, v = s.split("=", 1)
                k = k.strip()
                if not _ENV_KEY_RE.fullmatch(k):
                    raise HyprlandGodModeError("value_invalid", f"Invalid environment variable name: {k!r}")
                s = f"{k}={v.strip()}"
            elif setting_id == "hyprland.custom.keybinds":
                if "=>" not in s:
                    raise HyprlandGodModeError("value_invalid", "Keybinds must use 'MODS+KEY => COMMAND' format.")
                combo, cmd = s.split("=>", 1)
                combo = combo.strip()
                cmd = cmd.strip()
                if not combo or not cmd:
                    raise HyprlandGodModeError("value_invalid", "Keybind must specify both a shortcut and a command.")
                s = f"{combo} => {cmd}"
            if s not in cleaned_list:
                cleaned_list.append(s)
        return cleaned_list

    raise HyprlandGodModeError("setting_unsupported", f"Unsupported Hyprland setting: {setting_id}")


def _base_lua_files(paths: HyprlandGodModePaths) -> tuple[Path, ...]:
    return (
        paths.main_general,
        paths.main_colors,
        paths.custom_general,
        paths.custom_dir / "glow.lua",
        paths.custom_post_glow,
    )


def read_setting(setting_id: str, paths: HyprlandGodModePaths) -> Any:
    if not setting_available(setting_id, paths):
        raise HyprlandGodModeError("source_unavailable", f"Hyprland configuration is unavailable for {setting_id}.")
    if setting_id in CUSTOM_LIST_SPECS:
        return _read_custom_list(paths, setting_id)
    live = _read_live_option(paths, setting_id)
    if live is not None:
        return live
    if is_post_glow_shadow_setting(setting_id):
        post_glow = _read_post_glow_controls(paths)
        if setting_id in post_glow:
            return post_glow[setting_id]
    else:
        managed = _read_managed_controls(paths)
        if setting_id in managed:
            return managed[setting_id]
    base = _parse_base_lua_values(_base_lua_files(paths))
    if setting_id in base:
        return base[setting_id]
    return OPTION_SPECS[setting_id]["default"]


def read_all_settings(paths: HyprlandGodModePaths) -> dict[str, Any]:
    if not (_is_user_regular_file(paths.main_general) and paths.custom_dir.is_dir()):
        return {}
    base = _parse_base_lua_values(_base_lua_files(paths))
    managed = _read_managed_controls(paths)
    post_glow = _read_post_glow_controls(paths)
    out: dict[str, Any] = {}
    for sid, spec in OPTION_SPECS.items():
        if paths.allow_live_hyprctl:
            live = _read_live_option(paths, sid)
            if live is not None:
                out[sid] = live
                continue
        if is_post_glow_shadow_setting(sid):
            if sid in post_glow:
                out[sid] = post_glow[sid]
            elif sid in base:
                out[sid] = base[sid]
            else:
                out[sid] = spec["default"]
        else:
            if sid in managed:
                out[sid] = managed[sid]
            elif sid in base:
                out[sid] = base[sid]
            else:
                out[sid] = spec["default"]
    for sid in CUSTOM_LIST_SPECS:
        out[sid] = _read_custom_list(paths, sid)
    return out


def _eval_live_option(paths: HyprlandGodModePaths, setting_id: str, value: Any) -> bool:
    if not paths.allow_live_hyprctl:
        return False
    spec = OPTION_SPECS[setting_id]
    try:
        if spec.get("omitLuaWhenEmpty") and value == "":
            # Hyprland Lua rejects empty strings for options like input.accel_profile;
            # omitting the key from custom/general.lua and reloading restores [[EMPTY]].
            rc, _, _ = _run_hyprctl(paths, ["reload"])
            if rc != 0:
                return False
        else:
            lua_key = _lua_key_for_setting(setting_id)
            expr = f"hl.config({{ [{_lua_quote(lua_key)}] = {_lua_literal(value)} }})"
            rc, _, _ = _run_hyprctl(paths, ["eval", expr])
            if rc != 0:
                return False
    except HyprlandGodModeError:
        return False
    # Verify live value matches
    deadline = time.monotonic() + 2.0
    while True:
        actual = _read_live_option(paths, setting_id)
        if actual is not None:
            if isinstance(value, float) and isinstance(actual, (int, float)):
                if abs(float(actual) - value) <= 0.01:
                    return True
            elif actual == value:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _target_for_setting(paths: HyprlandGodModePaths, setting_id: str) -> tuple[Path, str, str]:
    if is_post_glow_shadow_setting(setting_id):
        return paths.custom_post_glow, _POST_GLOW_BEGIN, _POST_GLOW_END
    if setting_id in OPTION_SPECS:
        return paths.custom_general, _CTRL_BEGIN, _CTRL_END
    if setting_id == "hyprland.custom.autostart":
        return paths.custom_execs, _AUTOSTART_BEGIN, _AUTOSTART_END
    if setting_id == "hyprland.custom.env":
        return paths.custom_env, _ENV_BEGIN, _ENV_END
    if setting_id == "hyprland.custom.keybinds":
        return paths.custom_keybinds, _KEYBINDS_BEGIN, _KEYBINDS_END
    raise HyprlandGodModeError("setting_unsupported", f"Unsupported Hyprland setting: {setting_id}")


def apply_setting(
    paths: HyprlandGodModePaths,
    state_root: Path,
    setting_id: str,
    value: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    validated = validate_setting_value(setting_id, value)
    if not setting_available(setting_id, paths):
        raise HyprlandGodModeError("source_unavailable", f"Hyprland configuration is unavailable for {setting_id}.")

    current = read_setting(setting_id, paths)
    same = (
        abs(float(current) - float(validated)) <= 0.0001
        if isinstance(validated, float) and isinstance(current, (int, float))
        else current == validated
    )
    if same:
        return {
            "status": "no_changes",
            "settingId": setting_id,
            "value": validated,
            "runtimeVerified": False,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "settingId": setting_id,
            "value": validated,
            "runtimeVerified": False,
        }

    target, begin_m, end_m = _target_for_setting(paths, setting_id)
    with _state_lock(state_root):
        if target.is_symlink():
            raise HyprlandGodModeError("source_unsupported", f"Refusing to modify symbolic link: {target.name}")
        existed = _is_user_regular_file(target)
        before_text = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        before_bytes = before_text.encode("utf-8")

        if is_post_glow_shadow_setting(setting_id):
            managed = _read_post_glow_controls(paths)
            managed[setting_id] = validated
            body = _render_controls_block(managed)
        elif setting_id in OPTION_SPECS:
            managed = _read_managed_controls(paths)
            if OPTION_SPECS[setting_id].get("omitLuaWhenEmpty") and validated == "":
                managed.pop(setting_id, None)
            else:
                managed[setting_id] = validated
            body = _render_controls_block(managed)
        else:
            body = _render_custom_list_block(setting_id, validated)

        after_text = _replace_managed_block(before_text, begin_m, end_m, body)
        after_bytes = after_text.encode("utf-8")

        planned_writes: list[tuple[Path, bool, bytes, str, bytes]] = [
            (target, existed, before_bytes, after_text, after_bytes)
        ]

        # Ensure hyprland.lua loads custom/nexus-post-glow.lua AFTER custom/glow.lua so shadow edits persist on reload/reboot.
        if is_post_glow_shadow_setting(setting_id):
            hl_lua = paths.hyprland_lua
            if hl_lua.is_symlink():
                raise HyprlandGodModeError("source_unsupported", f"Refusing to modify symbolic link: {hl_lua.name}")
            if _is_user_regular_file(hl_lua):
                hl_before_text = hl_lua.read_text(encoding="utf-8", errors="replace")
                hl_after_text = _ensure_post_glow_hook_text(hl_before_text)
                if hl_after_text != hl_before_text:
                    planned_writes.append(
                        (
                            hl_lua,
                            True,
                            hl_before_text.encode("utf-8"),
                            hl_after_text,
                            hl_after_text.encode("utf-8"),
                        )
                    )

        txn_id = uuid.uuid4().hex
        txn_dir = state_root / "hyprland-godmode-transactions" / txn_id
        _ensure_private_dir(txn_dir)

        files_meta: list[dict[str, Any]] = []
        primary_snap_name: str | None = None
        for idx, (fpath, f_existed, f_before, _, f_after) in enumerate(planned_writes):
            snap_name: str | None = None
            if f_existed:
                snap_name = "target.before" if idx == 0 else f"file-{idx}.before"
                snap = txn_dir / snap_name
                snap.write_bytes(f_before)
                os.chmod(snap, 0o600)
                if idx == 0:
                    primary_snap_name = snap_name
            files_meta.append(
                {
                    "path": str(fpath),
                    "existed": f_existed,
                    "snapshot": snap_name,
                    "beforeSha256": _sha256_bytes(f_before) if f_existed else None,
                    "existsAfter": True,
                    "afterSha256": _sha256_bytes(f_after),
                }
            )

        meta = {
            "schema": "nexus-hyprland-godmode-txn-v1",
            "transactionId": txn_id,
            "settingId": setting_id,
            "previousValue": current,
            "newValue": validated,
            "targetPath": str(target),
            "existed": existed,
            "snapshot": primary_snap_name,
            "beforeSha256": _sha256_bytes(before_bytes) if existed else None,
            "afterSha256": _sha256_bytes(after_bytes),
            "files": files_meta,
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "undone": False,
        }
        _atomic_json(txn_dir / "meta.json", meta)

        written_indices: list[int] = []
        try:
            for idx, (fpath, _, _, f_after_text, _) in enumerate(planned_writes):
                _atomic_write_text(fpath, f_after_text, default_mode=0o644)
                written_indices.append(idx)
        except Exception:
            for idx in reversed(written_indices):
                fpath, f_existed, f_before, _, _ = planned_writes[idx]
                try:
                    if f_existed:
                        _atomic_write_text(fpath, f_before.decode("utf-8"), default_mode=0o644)
                    else:
                        fpath.unlink(missing_ok=True)
                except Exception:
                    pass
            raise

        runtime_verified = False
        if setting_id in OPTION_SPECS and paths.allow_live_hyprctl:
            runtime_verified = _eval_live_option(paths, setting_id, validated)

    return {
        "status": "applied" if runtime_verified else "written_to_config",
        "settingId": setting_id,
        "value": validated,
        "previousValue": current,
        "transactionId": txn_id,
        "runtimeVerified": runtime_verified,
        "runtimeStatus": (
            "hyprland-live-option-verified"
            if runtime_verified
            else "saved-to-custom-lua-reload-applies"
        ),
    }


def undo_transaction(
    paths: HyprlandGodModePaths,
    state_root: Path,
    transaction_id: str,
) -> dict[str, Any]:
    if not _TXN_ID_RE.fullmatch(transaction_id or ""):
        raise HyprlandGodModeError("undo_snapshot_invalid", "Invalid Hyprland transaction identifier.")
    with _state_lock(state_root):
        txn_dir = state_root / "hyprland-godmode-transactions" / transaction_id
        meta_path = txn_dir / "meta.json"
        if not meta_path.is_file():
            raise HyprlandGodModeError("undo_snapshot_invalid", "The saved Hyprland snapshot is missing.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("undone"):
            raise HyprlandGodModeError("undo_already_done", "This Hyprland change was already undone.")

        files_meta = meta.get("files")
        if not isinstance(files_meta, list) or not files_meta:
            files_meta = [
                {
                    "path": meta["targetPath"],
                    "existed": bool(meta.get("existed")),
                    "snapshot": meta.get("snapshot"),
                    "beforeSha256": meta.get("beforeSha256"),
                    "existsAfter": True,
                    "afterSha256": meta.get("afterSha256"),
                }
            ]

        # Atomic preflight: validate every target file and backup snapshot before modifying anything.
        restore_plan: list[tuple[Path, bool, bytes | None]] = []
        for entry in files_meta:
            target = Path(entry["path"])
            if target.is_symlink():
                raise HyprlandGodModeError("undo_conflict", f"{target.name} became a symbolic link after NEXUS updated it.")
            if entry.get("existsAfter", True):
                if not target.is_file() or _sha256_bytes(target.read_bytes()) != entry.get("afterSha256"):
                    raise HyprlandGodModeError("undo_conflict", f"{target.name} changed externally after NEXUS updated it.")
            elif target.exists():
                raise HyprlandGodModeError("undo_conflict", f"{target.name} was recreated externally after NEXUS removed it.")

            if entry.get("existed"):
                snap_name = entry.get("snapshot")
                if not snap_name:
                    raise HyprlandGodModeError("undo_snapshot_invalid", f"Hyprland backup missing for {target.name}.")
                snap = txn_dir / str(snap_name)
                if not snap.is_file():
                    raise HyprlandGodModeError("undo_snapshot_invalid", f"Hyprland backup missing for {target.name}.")
                raw = snap.read_bytes()
                if _sha256_bytes(raw) != entry.get("beforeSha256"):
                    raise HyprlandGodModeError("undo_snapshot_invalid", "Hyprland backup failed checksum verification.")
                restore_plan.append((target, True, raw))
            else:
                restore_plan.append((target, False, None))

        for target, existed_before, raw in restore_plan:
            if existed_before and raw is not None:
                _atomic_write_text(target, raw.decode("utf-8"))
            else:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass

        runtime_verified = False
        sid = meta.get("settingId")
        prev_val = meta.get("previousValue")
        if sid in OPTION_SPECS and paths.allow_live_hyprctl and prev_val is not None:
            runtime_verified = _eval_live_option(paths, sid, prev_val)

        meta["undone"] = True
        meta["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _atomic_json(meta_path, meta)

    return {
        "status": "undo_written_to_config",
        "settingId": sid,
        "restoredValue": prev_val,
        "transactionId": transaction_id,
        "runtimeVerified": runtime_verified,
    }
