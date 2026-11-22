#!/usr/bin/env bash

XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"

color=$(tr -d '\n' < "$XDG_STATE_HOME/quickshell/user/generated/color.txt")

current_mode=$(gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null | tr -d "'")
if [[ "$current_mode" == "prefer-dark" ]]; then
    mode_flag="-d"
else
    mode_flag="-l"
fi

# Parse --scheme-variant flag
scheme_variant_str=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --scheme-variant)
            scheme_variant_str="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Map string variant to integer
case "$scheme_variant_str" in
    scheme-content) sv_num=0 ;;
    scheme-expressive) sv_num=1 ;;
    scheme-fidelity) sv_num=2 ;;
    scheme-monochrome) sv_num=3 ;;
    scheme-neutral) sv_num=4 ;;
    scheme-tonal-spot) sv_num=5 ;;
    scheme-vibrant) sv_num=6 ;;
    scheme-rainbow) sv_num=7 ;;
    scheme-fruit-salad) sv_num=8 ;;
    "") sv_num=5 ;;
    *)
        echo "Unknown scheme variant: $scheme_variant_str" >&2
        exit 1
        ;;
esac

if [[ -n "${PULSAR_TINT_APP_WINDOW_SURFACES+x}" ]]; then
    tint_enabled="${PULSAR_TINT_APP_WINDOW_SURFACES,,}"
else
    tint_enabled=$(jq -r '.appearance.wallpaperTheming.tintAppWindowSurfaces // false' "$HOME/.config/illogical-impulse/config.json" 2>/dev/null || printf 'false')
fi
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/pulsar"
cache_file="$cache_dir/kde-theme.fingerprint"
mkdir -p "$cache_dir"

hash_kde_outputs() {
    {
        find "$HOME/.local/share/color-schemes" -maxdepth 1 -type f -name 'MaterialYou*.colors' -print0 2>/dev/null | sort -z | xargs -0r sha256sum
        [[ ! -f "$HOME/.config/kdeglobals" ]] || sha256sum "$HOME/.config/kdeglobals"
    } | sha256sum | awk '{print $1}'
}

kde_config_hash=$(find "$HOME/.config" -maxdepth 3 -type f -iname '*kde-material-you-colors*' -print0 2>/dev/null | sort -z | xargs -0r sha256sum | sha256sum | awk '{print $1}')
wrapper_hash=$(sha256sum "$0" | awk '{print $1}')
tint_helper="$HOME/.config/quickshell/ii/scripts/colors/apply_kde_surface_tint.py"
tint_helper_hash=$(sha256sum "$tint_helper" 2>/dev/null | awk '{print $1}')
input_fingerprint=$(printf '%s\n' "$color" "$mode_flag" "$sv_num" "$tint_enabled" "$kde_config_hash" "$wrapper_hash" "$tint_helper_hash" | sha256sum | awk '{print $1}')
current_output_hash=$(hash_kde_outputs)
cached_input=$(sed -n '1p' "$cache_file" 2>/dev/null || true)
cached_output=$(sed -n '2p' "$cache_file" 2>/dev/null || true)
if [[ "$cached_input" == "$input_fingerprint" && "$cached_output" == "$current_output_hash" ]]; then
    echo "Pulsar: KDE/Qt palette unchanged; generation skipped."
    exit 0
fi

source "$(eval echo $ILLOGICAL_IMPULSE_VIRTUAL_ENV)/bin/activate"
if [[ "$mode_flag" == "-d" ]]; then
    active_scheme="$HOME/.local/share/color-schemes/MaterialYouDark.colors"
else
    active_scheme="$HOME/.local/share/color-schemes/MaterialYouLight.colors"
fi
scheme_before=$(stat -c '%y' "$active_scheme" 2>/dev/null || printf 'missing')
kdeglobals_before=$(stat -c '%y' "$HOME/.config/kdeglobals" 2>/dev/null || printf 'missing')
# The upstream generator is a watcher by default. We only need its initial
# scheme write here; Konsole is disabled because Kitty is the configured terminal.
kde-material-you-colors "$mode_flag" --color "$color" -sv "$sv_num" \
    --titlebar-opacity 0 --titlebar-opacity-dark 0 --disable-konsole &
generator_pid=$!
schemes_written=false
for attempt in {1..60}; do
    sleep 0.25
    scheme_now=$(stat -c '%y' "$active_scheme" 2>/dev/null || printf 'missing')
    kdeglobals_now=$(stat -c '%y' "$HOME/.config/kdeglobals" 2>/dev/null || printf 'missing')
    if [[ "$scheme_now" != "$scheme_before" && "$kdeglobals_now" != "$kdeglobals_before" ]]; then
        schemes_written=true
        break
    fi
    kill -0 "$generator_pid" 2>/dev/null || break
done
kill -TERM "$generator_pid" 2>/dev/null || true
wait "$generator_pid" 2>/dev/null || true
if [[ "$schemes_written" != "true" ]]; then
    echo "Pulsar: KDE color scheme did not finish writing within 15 seconds." >&2
else
    if [[ "$tint_enabled" == "true" ]]; then
        python3 "$tint_helper"
    fi
    current_output_hash=$(hash_kde_outputs)
    cache_temp=$(mktemp "$cache_file.XXXXXX")
    printf '%s\n%s\n' "$input_fingerprint" "$current_output_hash" > "$cache_temp"
    mv -f "$cache_temp" "$cache_file"
fi
deactivate
