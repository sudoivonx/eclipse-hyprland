#!/usr/bin/env bash

QUICKSHELL_CONFIG_NAME="ii"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_DIR="$XDG_CONFIG_HOME/quickshell/$QUICKSHELL_CONFIG_NAME"
CACHE_DIR="$XDG_CACHE_HOME/quickshell"
STATE_DIR="$XDG_STATE_HOME/quickshell"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHELL_CONFIG_FILE="$XDG_CONFIG_HOME/illogical-impulse/config.json"
MATUGEN_DIR="$XDG_CONFIG_HOME/matugen"
terminalscheme="$SCRIPT_DIR/terminal/scheme-base.json"

handle_kde_material_you_colors() {
    # Check if Qt app theming is enabled in config
    if [ -f "$SHELL_CONFIG_FILE" ]; then
        enable_qt_apps=$(jq -r '.appearance.wallpaperTheming.enableQtApps' "$SHELL_CONFIG_FILE")
        if [ "$enable_qt_apps" == "false" ]; then
            return
        fi
    fi

    # The UI passes its current value explicitly so this process does not race
    # the asynchronous config-file write.
    local tint_enabled="${tint_override:-}"
    if [[ -z "$tint_enabled" && -f "$SHELL_CONFIG_FILE" ]]; then
        tint_enabled=$(jq -r '.appearance.wallpaperTheming.tintAppWindowSurfaces // false' "$SHELL_CONFIG_FILE")
    fi

    # Map $type_flag to allowed scheme variants for kde-material-you-colors-wrapper.sh
    local kde_scheme_variant=""
    case "$type_flag" in
        scheme-content|scheme-expressive|scheme-fidelity|scheme-fruit-salad|scheme-monochrome|scheme-neutral|scheme-rainbow|scheme-tonal-spot)
            kde_scheme_variant="$type_flag"
            ;;
        *)
            kde_scheme_variant="scheme-tonal-spot" # default
            ;;
    esac
    PULSAR_TINT_APP_WINDOW_SURFACES="$tint_enabled" \
        "$XDG_CONFIG_HOME"/matugen/templates/kde/kde-material-you-colors-wrapper.sh --scheme-variant "$kde_scheme_variant"
}

set_gsettings_if_changed() {
    local schema="$1" key="$2" desired="$3" current
    command -v gsettings >/dev/null 2>&1 || return 0
    current=$(gsettings get "$schema" "$key" 2>/dev/null | tr -d "'") || return 0
    [[ "$current" == "$desired" ]] || gsettings set "$schema" "$key" "$desired"
}

pre_process() {
    local mode_flag="$1"
    # Avoid writing identical appearance preferences to the settings backend.
    if [[ "$mode_flag" == "dark" ]]; then
        set_gsettings_if_changed org.gnome.desktop.interface color-scheme prefer-dark
        set_gsettings_if_changed org.gnome.desktop.interface gtk-theme adw-gtk3-dark
    elif [[ "$mode_flag" == "light" ]]; then
        set_gsettings_if_changed org.gnome.desktop.interface color-scheme prefer-light
        set_gsettings_if_changed org.gnome.desktop.interface gtk-theme adw-gtk3
    fi

    if [ ! -d "$CACHE_DIR"/user/generated ]; then
        mkdir -p "$CACHE_DIR"/user/generated
    fi
}

post_process() {
    local screen_width="$1"
    local screen_height="$2"
    local wallpaper_path="$3"

    # Wait for the KDE/Qt scheme to finish so UI switches have a reliable,
    # observable completion point. The editor-only hook can remain async.
    handle_kde_material_you_colors
    "$SCRIPT_DIR/code/material-code-set-color.sh" &
}

apply_system_accent() {
    local palette_file="$STATE_DIR/user/generated/colors.json"
    local accent_name
    [[ -f "$palette_file" ]] || return 0
    command -v gsettings >/dev/null 2>&1 || return 0
    gsettings range org.gnome.desktop.interface accent-color >/dev/null 2>&1 || return 0

    accent_name=$(python3 - "$palette_file" <<'PYACCENT'
import colorsys
import json
import sys
from pathlib import Path

try:
    palette = json.loads(Path(sys.argv[1]).read_text())
    value = (palette.get("source_color") or palette["primary"]).strip().lstrip("#")[:6]
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
except (OSError, KeyError, ValueError, TypeError):
    raise SystemExit(1)
hue, saturation, _ = colorsys.rgb_to_hsv(r, g, b)
if saturation < 0.08:
    print("slate")
else:
    choices = ((210, "blue"), (180, "teal"), (130, "green"), (55, "yellow"),
               (28, "orange"), (0, "red"), (330, "pink"), (275, "purple"))
    degrees = hue * 360
    print(min(choices, key=lambda item: min(abs(degrees - item[0]), 360 - abs(degrees - item[0])))[1])
PYACCENT
) || return 0
    if [[ -n "$accent_name" ]]; then
        local current_accent
        current_accent=$(gsettings get org.gnome.desktop.interface accent-color 2>/dev/null | tr -d "'") || return 0
        if [[ "$current_accent" != "$accent_name" ]] && ! gsettings set org.gnome.desktop.interface accent-color "$accent_name"; then
            echo "Pulsar: could not publish the generated accent through GSettings." >&2
        fi
    fi
}

check_and_prompt_upscale() {
    local img="$1"
    min_width_desired="$(hyprctl monitors -j | jq '([.[].width] | max)' | xargs)" # max monitor width
    min_height_desired="$(hyprctl monitors -j | jq '([.[].height] | max)' | xargs)" # max monitor height

    if command -v identify &>/dev/null && [ -f "$img" ]; then
        local img_width img_height
        if is_video "$img"; then # Not check resolution for videos, just let em pass
            img_width=$min_width_desired
            img_height=$min_height_desired
        else
            img_width=$(identify -format "%w" "$img" 2>/dev/null)
            img_height=$(identify -format "%h" "$img" 2>/dev/null)
        fi
        if [[ "$img_width" -lt "$min_width_desired" || "$img_height" -lt "$min_height_desired" ]]; then
            action=$(notify-send "Upscale?" \
                "Image resolution (${img_width}x${img_height}) is lower than screen resolution (${min_width_desired}x${min_height_desired})" \
                -A "open_upscayl=Open Upscayl"\
                -a "Wallpaper switcher")
            if [[ "$action" == "open_upscayl" ]]; then
                if command -v upscayl &>/dev/null; then
                    nohup upscayl > /dev/null 2>&1 &
                else
                    action2=$(notify-send \
                        -a "Wallpaper switcher" \
                        -c "im.error" \
                        -A "install_upscayl=Install Upscayl (Arch)" \
                        "Install Upscayl?" \
                        "yay -S upscayl-bin")
                    if [[ "$action2" == "install_upscayl" ]]; then
                        kitty -1 yay -S upscayl-bin
                        if command -v upscayl &>/dev/null; then
                            nohup upscayl > /dev/null 2>&1 &
                        fi
                    fi
                fi
            fi
        fi
    fi
}

CUSTOM_DIR="$XDG_CONFIG_HOME/hypr/custom"
RESTORE_SCRIPT_DIR="$CUSTOM_DIR/scripts"
RESTORE_SCRIPT="$RESTORE_SCRIPT_DIR/__restore_video_wallpaper.sh"

remove_restore() {
    mkdir -p "$RESTORE_SCRIPT_DIR"
    cat > "$RESTORE_SCRIPT.tmp" << 'EOF'
#!/usr/bin/env bash
# Managed static wallpaper restore stub.
exit 0
EOF
    mv "$RESTORE_SCRIPT.tmp" "$RESTORE_SCRIPT"
    chmod +x "$RESTORE_SCRIPT"
}

set_wallpaper_path() {
    local path="$1"
    if [ -f "$SHELL_CONFIG_FILE" ]; then
        jq --arg path "$path" '.background.wallpaperPath = $path' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"
    fi
}

set_thumbnail_path() {
    local path="$1"
    if [ -f "$SHELL_CONFIG_FILE" ]; then
        jq --arg path "$path" '.background.thumbnailPath = $path' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"
    fi
}

categorize_wallpaper() {
    img_cat=$("$SCRIPT_DIR/../ai/gemini-categorize-wallpaper.sh" "$1")
    echo "$img_cat" > "$STATE_DIR/user/generated/wallpaper/category.txt"
}

switch() {
    imgpath="$1"
    mode_flag="$2"
    type_flag="$3"
    color_flag="$4"
    color="$5"

    aiStylingEnabled=$(jq -r '.background.widgets.clock.cookie.aiStyling' "$SHELL_CONFIG_FILE")
    if [[ "$aiStylingEnabled" == "true" ]]; then
        categorize_wallpaper "$imgpath" &
    fi

    read scale screenx screeny screensizey < <(hyprctl monitors -j | jq '.[] | select(.focused) | .scale, .x, .y, .height' | xargs)
    cursorposx=$(hyprctl cursorpos -j | jq '.x' 2>/dev/null) || cursorposx=960
    cursorposx=$(bc <<< "scale=0; ($cursorposx - $screenx) * $scale / 1")
    cursorposy=$(hyprctl cursorpos -j | jq '.y' 2>/dev/null) || cursorposy=540
    cursorposy=$(bc <<< "scale=0; ($cursorposy - $screeny) * $scale / 1")
    cursorposy_inverted=$((screensizey - cursorposy))

    matugen_args=(--source-color-index 0)

    if [[ "$color_flag" == "1" ]]; then
        matugen_args+=(color hex "$color")
        generate_colors_material_args=(--color "$color")
    else
        if [[ -z "$imgpath" ]]; then
            echo 'Aborted'
            exit 0
        fi
        check_and_prompt_upscale "$imgpath" &
        matugen_args+=(image "$imgpath")
        generate_colors_material_args=(--path "$imgpath")
        set_wallpaper_path "$imgpath"
        set_thumbnail_path "$imgpath"
        remove_restore
    fi

    # Determine mode if not set
    if [[ -z "$mode_flag" ]]; then
        current_mode=$(gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null | tr -d "'")
        if [[ "$current_mode" == "prefer-dark" ]]; then
            mode_flag="dark"
        else
            mode_flag="light"
        fi
    fi

    # enforce dark mode for terminal
    if [[ -n "$mode_flag" ]]; then
        matugen_args+=(--mode "$mode_flag")
        if [[ $(jq -r '.appearance.wallpaperTheming.terminalGenerationProps.forceDarkMode' "$SHELL_CONFIG_FILE") == "true" ]]; then
            generate_colors_material_args+=(--mode "dark")
        else
            generate_colors_material_args+=(--mode "$mode_flag")
        fi
    fi
    [[ -n "$type_flag" ]] && matugen_args+=(--type "$type_flag") && generate_colors_material_args+=(--scheme "$type_flag")
    generate_colors_material_args+=(--termscheme "$terminalscheme" --blend_bg_fg)
    generate_colors_material_args+=(--cache "$STATE_DIR/user/generated/color.txt")

    pre_process "$mode_flag"

    # Check if app and shell theming is enabled in config
    if [ -f "$SHELL_CONFIG_FILE" ]; then
        enable_apps_shell=$(jq -r '.appearance.wallpaperTheming.enableAppsAndShell' "$SHELL_CONFIG_FILE")
        if [ "$enable_apps_shell" == "false" ]; then
            echo "App and shell theming disabled, skipping matugen and color generation"
            return
        fi
    fi

    # Set harmony and related properties
    if [ -f "$SHELL_CONFIG_FILE" ]; then
        harmony=$(jq -r '.appearance.wallpaperTheming.terminalGenerationProps.harmony' "$SHELL_CONFIG_FILE")
        harmonize_threshold=$(jq -r '.appearance.wallpaperTheming.terminalGenerationProps.harmonizeThreshold' "$SHELL_CONFIG_FILE")
        term_fg_boost=$(jq -r '.appearance.wallpaperTheming.terminalGenerationProps.termFgBoost' "$SHELL_CONFIG_FILE")
        [[ "$harmony" != "null" && -n "$harmony" ]] && generate_colors_material_args+=(--harmony "$harmony")
        [[ "$harmonize_threshold" != "null" && -n "$harmonize_threshold" ]] && generate_colors_material_args+=(--harmonize_threshold "$harmonize_threshold")
        [[ "$term_fg_boost" != "null" && -n "$term_fg_boost" ]] && generate_colors_material_args+=(--term_fg_boost "$term_fg_boost")
    fi

    gtk_window_tint="${tint_override:-}"
    if [[ -z "$gtk_window_tint" && -f "$SHELL_CONFIG_FILE" ]]; then
        gtk_window_tint=$(jq -r '.appearance.wallpaperTheming.tintAppWindowSurfaces // false' "$SHELL_CONFIG_FILE")
    fi
    [[ "$gtk_window_tint" == "true" ]] || gtk_window_tint="false"
    hypr_colors_file="$XDG_CONFIG_HOME/hypr/hyprland/colors.lua"
    hypr_colors_before=""
    [[ ! -f "$hypr_colors_file" ]] || hypr_colors_before=$(sha256sum "$hypr_colors_file" | awk '{print $1}')
    if ! PULSAR_GTK_WINDOW_TINT="$gtk_window_tint" \
        PULSAR_TINT_APP_WINDOW_SURFACES="$gtk_window_tint" \
        bash "$SCRIPT_DIR/run_matugen_transactional.sh" "$MATUGEN_DIR/config.toml" "${matugen_args[@]}"; then
        echo "Pulsar: color generation failed; keeping the last valid palette." >&2
        return 1
    fi
    apply_system_accent
    source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"
    python3 "$SCRIPT_DIR/generate_colors_material.py" "${generate_colors_material_args[@]}" \
        > "$STATE_DIR"/user/generated/material_colors.scss
    deactivate
    "$SCRIPT_DIR"/applycolor.sh

    hypr_colors_after=""
    [[ ! -f "$hypr_colors_file" ]] || hypr_colors_after=$(sha256sum "$hypr_colors_file" | awk '{print $1}')
    hypr_reload_pending="$XDG_STATE_HOME/aegis/pulsar-hyprland-reload.pending"
    if [[ "$hypr_colors_before" != "$hypr_colors_after" || -e "$hypr_reload_pending" ]]; then
        if command -v hyprctl &>/dev/null && hyprctl reload >/dev/null 2>&1; then
            rm -f "$hypr_reload_pending"
            echo "Pulsar: Hyprland reloaded because its generated palette changed."
        else
            mkdir -p "$(dirname "$hypr_reload_pending")"
            : > "$hypr_reload_pending"
            echo "Pulsar: Hyprland palette changed but reload failed; retry is pending." >&2
        fi
    else
        echo "Pulsar: Hyprland palette unchanged; reload skipped."
    fi

    # Pass screen width, height, and wallpaper path to post_process
    max_width_desired="$(hyprctl monitors -j | jq '([.[].width] | min)' | xargs)"
    max_height_desired="$(hyprctl monitors -j | jq '([.[].height] | min)' | xargs)"
    post_process "$max_width_desired" "$max_height_desired" "$imgpath"
}

main() {
    imgpath=""
    mode_flag=""
    type_flag=""
    color_flag=""
    color=""
    noswitch_flag=""
    tint_override=""

    get_type_from_config() {
        jq -r '.appearance.palette.type' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "auto"
    }
    get_accent_color_from_config() {
        jq -r '.appearance.palette.accentColor' "$SHELL_CONFIG_FILE" 2>/dev/null || echo ""
    }
    set_accent_color() {
        local color="$1" current
        current=$(get_accent_color_from_config)
        [[ "$current" == "null" ]] && current=""
        [[ "$current" == "$color" ]] && return 0
        jq --arg color "$color" '.appearance.palette.accentColor = $color' "$SHELL_CONFIG_FILE" > "$SHELL_CONFIG_FILE.tmp" && mv "$SHELL_CONFIG_FILE.tmp" "$SHELL_CONFIG_FILE"
    }

    detect_scheme_type_from_image() {
        local img="$1"
        source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"
        "$SCRIPT_DIR"/scheme_for_image.py "$img" 2>/dev/null | tr -d '\n'
        deactivate
    }

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --tint-app-window-surfaces)
                if [[ "${2:-}" != "true" && "${2:-}" != "false" ]]; then
                    echo "[switchwall.sh] Invalid tint-app-window-surfaces value." >&2
                    return 2
                fi
                tint_override="$2"
                shift 2
                ;;
            --mode)
                mode_flag="$2"
                shift 2
                ;;
            --type)
                type_flag="$2"
                shift 2
                ;;
            --color)
                if [[ "$2" =~ ^#?[A-Fa-f0-9]{6}$ ]]; then
                    set_accent_color "$2"
                    shift 2
                elif [[ "$2" == "clear" ]]; then
                    set_accent_color ""
                    shift 2
                else
                    set_accent_color $(hyprpicker --no-fancy)
                    shift
                fi
                ;;
            --image)
                imgpath="$2"
                shift 2
                ;;
            --noswitch)
                noswitch_flag="1"
                imgpath=$(jq -r '.background.wallpaperPath' "$SHELL_CONFIG_FILE" 2>/dev/null || echo "")
                shift
                ;;
            *)
                if [[ -z "$imgpath" ]]; then
                    imgpath="$1"
                fi
                shift
                ;;
        esac
    done

    # If accentColor is set in config, use it
    config_color="$(get_accent_color_from_config)"
    if [[ "$config_color" =~ ^#?[A-Fa-f0-9]{6}$ ]]; then
        color_flag="1"
        color="$config_color"
    fi

    # If type_flag is not set, get it from config
    if [[ -z "$type_flag" ]]; then
        type_flag="$(get_type_from_config)"
    fi

    # Validate type_flag (allow 'auto' as well)
    allowed_types=(scheme-content scheme-expressive scheme-fidelity scheme-fruit-salad scheme-monochrome scheme-neutral scheme-rainbow scheme-tonal-spot auto)
    valid_type=0
    for t in "${allowed_types[@]}"; do
        if [[ "$type_flag" == "$t" ]]; then
            valid_type=1
            break
        fi
    done
    if [[ $valid_type -eq 0 ]]; then
        echo "[switchwall.sh] Warning: Invalid type '$type_flag', defaulting to 'auto'" >&2
        type_flag="auto"
    fi

    # Only prompt for wallpaper if not using --color and not using --noswitch and no imgpath set
    if [[ -z "$imgpath" && -z "$color_flag" && -z "$noswitch_flag" ]]; then
        cd "$(xdg-user-dir PICTURES)/Wallpapers/showcase" 2>/dev/null || cd "$(xdg-user-dir PICTURES)/Wallpapers" 2>/dev/null || cd "$(xdg-user-dir PICTURES)" || return 1
        imgpath="$(kdialog --getopenfilename . --title 'Choose wallpaper')"
    fi

    if [[ -n "$imgpath" && -z "$noswitch_flag" ]]; then
        set_accent_color ""
        color_flag=""
        color=""
    fi

    # If type_flag is 'auto', detect scheme type from image (after imgpath is set)
    if [[ "$type_flag" == "auto" ]]; then
        if [[ -n "$imgpath" && -f "$imgpath" ]]; then
            detected_type="$(detect_scheme_type_from_image "$imgpath")"
            # Only use detected_type if it's valid
            valid_detected=0
            for t in "${allowed_types[@]}"; do
                if [[ "$detected_type" == "$t" && "$detected_type" != "auto" ]]; then
                    valid_detected=1
                    break
                fi
            done
            if [[ $valid_detected -eq 1 ]]; then
                type_flag="$detected_type"
            else
                echo "[switchwall] Warning: Could not auto-detect a valid scheme, defaulting to 'scheme-tonal-spot'" >&2
                type_flag="scheme-tonal-spot"
            fi
        else
            echo "[switchwall] Warning: No image to auto-detect scheme from, defaulting to 'scheme-tonal-spot'" >&2
            type_flag="scheme-tonal-spot"
        fi
    fi

    # If mode_flag is dark or light, try to find a variant with that mode suffix
    if [[ "$mode_flag" == "dark" || "$mode_flag" == "light" ]]; then
        # Get directory, filename without extension, and extension
        local imgdir="$(dirname "$imgpath")"
        local imgbase="$(basename "$imgpath")"
        local imgname="${imgbase%.*}"
        local imgext="${imgbase##*.}"

        # Strip existing -dark or -light suffix
        local stripped_name="${imgname%-dark}"
        stripped_name="${stripped_name%-light}"

        # Construct the new path with the requested mode suffix
        local new_imgpath="${imgdir}/${stripped_name}-${mode_flag}.${imgext}"
        local new_stripped_imgpath="${imgdir}/${stripped_name}.${imgext}"

        # If the variant exists, use it
        if [[ -f "$new_imgpath" ]]; then
            imgpath="$new_imgpath"
        elif [[ -f "$new_stripped_imgpath" ]]; then
            imgpath="$new_stripped_imgpath"
        fi
    fi

    switch "$imgpath" "$mode_flag" "$type_flag" "$color_flag" "$color"
}

main "$@"
