#!/usr/bin/env bash
# ==============================================================================
# Eclipse Hyprland & Quickshell ("ii" + NEXUS God Menu) Multi-Distro Installer
# Repository: https://github.com/sudoivonx/eclipse-hyprland
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_CONFIG_DIR="$SCRIPT_DIR/config"
REPO_WALLPAPER="$SCRIPT_DIR/wallpapers/default.png"

DRY_RUN=0
SKIP_PACKAGES=0
NO_BACKUP=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
Usage: ./install.sh [OPTIONS]

Options:
  --dry-run        Simulate all steps without modifying any files or installing packages
  --skip-packages  Skip system package installation (deploy configs & wallpaper only)
  --no-backup      Skip backing up existing configuration files before deployment
  -y, --yes        Proceed non-interactively without confirmation prompts
  -h, --help       Show this help message and exit
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --skip-packages)
            SKIP_PACKAGES=1
            shift
            ;;
        --no-backup)
            NO_BACKUP=1
            shift
            ;;
        -y|--yes)
            ASSUME_YES=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "[ERROR] Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

log() {
    printf '\033[1;35m[eclipse-hyprland]\033[0m %s\n' "$*"
}

warn() {
    printf '\033[1;33m[WARN]\033[0m %s\n' "$*" >&2
}

die() {
    printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2
    exit 1
}

[[ -d "$REPO_CONFIG_DIR" ]] || die "Missing config directory: $REPO_CONFIG_DIR"
[[ -f "$REPO_WALLPAPER" ]] || die "Missing default wallpaper: $REPO_WALLPAPER"

TARGET_HOME="${HOME:?HOME environment variable must be set}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$TARGET_HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$TARGET_HOME/.local/state}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$STATE_HOME/eclipse-hyprland/backups/$TIMESTAMP"

resolve_pictures_dir() {
    local pic_dir=""
    if command -v xdg-user-dir >/dev/null 2>&1; then
        pic_dir="$(HOME="$TARGET_HOME" XDG_CONFIG_HOME="$CONFIG_HOME" xdg-user-dir PICTURES 2>/dev/null || true)"
    fi
    if [[ -z "$pic_dir" || "$pic_dir" == "$TARGET_HOME" ]]; then
        if [[ -f "$CONFIG_HOME/user-dirs.dirs" ]]; then
            local raw
            raw="$(grep -E '^XDG_PICTURES_DIR=' "$CONFIG_HOME/user-dirs.dirs" | tail -n1 | cut -d= -f2- | tr -d '"' || true)"
            if [[ -n "$raw" ]]; then
                pic_dir="${raw/\$HOME/$TARGET_HOME}"
            fi
        fi
    fi
    if [[ -z "$pic_dir" ]]; then
        pic_dir="$TARGET_HOME/Pictures"
    fi
    printf '%s\n' "$pic_dir"
}

detect_distro_family() {
    local id="" like=""
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        id="${ID:-}"
        like="${ID_LIKE:-}"
    fi
    if [[ "$id" == "fedora" || "$like" == *"fedora"* ]] || command -v dnf >/dev/null 2>&1; then
        printf 'fedora\n'
    elif [[ "$id" == "arch" || "$like" == *"arch"* ]] || command -v pacman >/dev/null 2>&1; then
        printf 'arch\n'
    elif [[ "$id" == "ubuntu" || "$id" == "debian" || "$like" == *"debian"* || "$like" == *"ubuntu"* ]] || command -v apt-get >/dev/null 2>&1; then
        printf 'debian\n'
    else
        printf 'unknown\n'
    fi
}

install_system_packages() {
    local family
    family="$(detect_distro_family)"
    log "Detected distribution family: $family"

    local fedora_pkgs=(
        hyprland hypridle hyprlock hyprpicker xdg-desktop-portal-hyprland
        kitty fuzzel wlogout fish starship cava fastfetch
        wl-clipboard cliphist grim slurp wf-recorder brightnessctl playerctl
        pipewire wireplumber pavucontrol NetworkManager-tui
        python3 python3-pip python3-gobject python3-pillow python3-pyside6
        qt6-qtbase qt6-qtdeclarative qt6-qtwayland qt6-qtsvg kvantum
        gtk3 gtk4 adw-gtk3-theme breeze-icon-theme
        jq bc curl unzip fontconfig
    )
    local arch_pkgs=(
        hyprland hypridle hyprlock hyprpicker xdg-desktop-portal-hyprland
        quickshell matugen
        kitty fuzzel wlogout fish starship cava fastfetch
        wl-clipboard cliphist grim slurp wf-recorder brightnessctl playerctl
        pipewire wireplumber pavucontrol
        python python-gobject python-pillow pyside6
        qt6-base qt6-declarative qt6-wayland qt6-svg kvantum
        gtk3 gtk4 adw-gtk-theme breeze-icons
        jq bc curl unzip fontconfig
    )
    local debian_pkgs=(
        hyprland xdg-desktop-portal-hyprland
        kitty fuzzel wlogout fish cava
        wl-clipboard cliphist grim slurp wf-recorder brightnessctl playerctl
        pipewire wireplumber pavucontrol
        python3 python3-pip python3-gi python3-pil python3-pyside6.qtquick
        qml6-module-qtquick qml6-module-qtquick-controls qml6-module-qtquick-layouts
        qt6-wayland kvantum
        libgtk-3-0 libgtk-4-1 breeze-icon-theme
        jq bc curl unzip fontconfig
    )

    if [[ "$DRY_RUN" -eq 1 ]]; then
        case "$family" in
            fedora) log "[DRY-RUN] Would install Fedora packages via dnf: ${fedora_pkgs[*]}" ;;
            arch)   log "[DRY-RUN] Would install Arch packages via pacman: ${arch_pkgs[*]}" ;;
            debian) log "[DRY-RUN] Would install Debian/Ubuntu packages via apt-get: ${debian_pkgs[*]}" ;;
            *)      warn "[DRY-RUN] Unknown package manager; please install Hyprland & Quickshell dependencies manually." ;;
        esac
        return 0
    fi

    if [[ "$ASSUME_YES" -ne 1 ]]; then
        read -r -p "[eclipse-hyprland] Install system packages for '$family'? [y/N] " ans
        if [[ ! "$ans" =~ ^[Yy]$ ]]; then
            log "Skipping package installation by user choice."
            return 0
        fi
    fi

    case "$family" in
        fedora)
            sudo dnf install -y --skip-unavailable "${fedora_pkgs[@]}" || warn "Some Fedora packages were unavailable; continuing with config deployment."
            ;;
        arch)
            sudo pacman -S --needed --noconfirm "${arch_pkgs[@]}" || warn "Some Arch packages were unavailable in enabled repos; continuing with config deployment."
            ;;
        debian)
            sudo apt-get update && sudo apt-get install -y "${debian_pkgs[@]}" || warn "Some Debian/Ubuntu packages were unavailable; continuing with config deployment."
            ;;
        *)
            warn "Unsupported package manager. Proceeding with configuration deployment only."
            ;;
    esac
}

CONFIG_ITEMS=(
    "hypr"
    "quickshell/ii"
    "illogical-impulse"
    "matugen"
    "kitty"
    "fuzzel"
    "wlogout"
    "gtk-3.0"
    "gtk-4.0"
    "Kvantum"
    "fontconfig"
    "starship.toml"
    "cava"
    "fish"
    "kdeglobals"
)

backup_existing_configs() {
    local any_existing=0
    for item in "${CONFIG_ITEMS[@]}"; do
        if [[ -e "$CONFIG_HOME/$item" || -L "$CONFIG_HOME/$item" ]]; then
            any_existing=1
            break
        fi
    done

    if [[ "$any_existing" -eq 0 ]]; then
        log "No pre-existing target configs found in $CONFIG_HOME; backup not required."
        return 0
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[DRY-RUN] Would back up existing configs from $CONFIG_HOME to $BACKUP_DIR"
        for item in "${CONFIG_ITEMS[@]}"; do
            if [[ -e "$CONFIG_HOME/$item" || -L "$CONFIG_HOME/$item" ]]; then
                log "[DRY-RUN]   backup: $CONFIG_HOME/$item -> $BACKUP_DIR/$item"
            fi
        done
        return 0
    fi

    log "Backing up existing configurations to $BACKUP_DIR ..."
    mkdir -p "$BACKUP_DIR"
    for item in "${CONFIG_ITEMS[@]}"; do
        if [[ -e "$CONFIG_HOME/$item" || -L "$CONFIG_HOME/$item" ]]; then
            mkdir -p "$(dirname "$BACKUP_DIR/$item")"
            cp -a "$CONFIG_HOME/$item" "$BACKUP_DIR/$item"
        fi
    done
    log "Backup completed: $BACKUP_DIR"
}

deploy_configs_and_wallpaper() {
    local xdg_pic_dir
    xdg_pic_dir="$(resolve_pictures_dir)"
    local std_wall_dir="$TARGET_HOME/Pictures/Wallpapers"
    local xdg_wall_dir="$xdg_pic_dir/Wallpapers"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "[DRY-RUN] Would deploy configurations from $REPO_CONFIG_DIR to $CONFIG_HOME"
        for item in "${CONFIG_ITEMS[@]}"; do
            log "[DRY-RUN]   deploy: $REPO_CONFIG_DIR/$item -> $CONFIG_HOME/$item"
        done
        log "[DRY-RUN] Would install default wallpaper to $std_wall_dir/default.png"
        if [[ "$xdg_wall_dir" != "$std_wall_dir" ]]; then
            log "[DRY-RUN] Would also install default wallpaper to $xdg_wall_dir/default.png"
        fi
        log "[DRY-RUN] Would expand __HOME__ -> $TARGET_HOME across deployed configuration files"
        return 0
    fi

    mkdir -p "$CONFIG_HOME"
    for item in "${CONFIG_ITEMS[@]}"; do
        local src="$REPO_CONFIG_DIR/$item"
        local dst="$CONFIG_HOME/$item"
        [[ -e "$src" ]] || continue
        mkdir -p "$(dirname "$dst")"
        if [[ -d "$src" ]]; then
            rm -rf "$dst"
            cp -a "$src" "$dst"
        else
            cp -a "$src" "$dst"
        fi
    done

    # Deploy default wallpaper to both $HOME/Pictures/Wallpapers/default.png and localized XDG Pictures dir
    mkdir -p "$std_wall_dir"
    cp -f "$REPO_WALLPAPER" "$std_wall_dir/default.png"
    if [[ "$xdg_wall_dir" != "$std_wall_dir" ]]; then
        mkdir -p "$xdg_wall_dir"
        cp -f "$REPO_WALLPAPER" "$xdg_wall_dir/default.png"
    fi

    # Expand __HOME__ placeholder across deployed text files safely via python3
    TARGET_HOME="$TARGET_HOME" CONFIG_HOME="$CONFIG_HOME" python3 - <<'PY'
import os, pathlib

target_home = os.environ["TARGET_HOME"]
config_home = pathlib.Path(os.environ["CONFIG_HOME"])

items = [
    "hypr", "quickshell/ii", "illogical-impulse", "matugen", "kitty",
    "fuzzel", "wlogout", "gtk-3.0", "gtk-4.0", "Kvantum",
    "fontconfig", "starship.toml", "cava", "fish", "kdeglobals"
]

for item in items:
    base = config_home / item
    if not base.exists():
        continue
    files = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "__HOME__" in text:
            f.write_text(text.replace("__HOME__", target_home), encoding="utf-8")
PY

    # Enforce executable permissions on scripts
    find "$CONFIG_HOME/hypr" -type f \( -name "*.sh" -o -name "aegis-*.py" \) ! -name "aegis-glassctl.py" -exec chmod +x {} + 2>/dev/null || true
    find "$CONFIG_HOME/quickshell/ii" -type f \( -name "*.sh" -o -name "nexus-settings.py" \) -exec chmod +x {} + 2>/dev/null || true
    if [[ -f "$CONFIG_HOME/matugen/templates/kde/kde-material-you-colors-wrapper.sh" ]]; then
        chmod +x "$CONFIG_HOME/matugen/templates/kde/kde-material-you-colors-wrapper.sh"
    fi

    log "Deployed all Eclipse Hyprland configurations to $CONFIG_HOME"
    log "Default wallpaper installed to $std_wall_dir/default.png"
}

main() {
    log "Starting Eclipse Hyprland & Quickshell installer..."
    log "Target HOME: $TARGET_HOME | Target CONFIG: $CONFIG_HOME"

    if [[ "$SKIP_PACKAGES" -eq 0 ]]; then
        install_system_packages
    else
        log "Skipping system package installation (--skip-packages)."
    fi

    if [[ "$NO_BACKUP" -eq 0 ]]; then
        backup_existing_configs
    else
        log "Skipping pre-install backup (--no-backup)."
    fi

    deploy_configs_and_wallpaper

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "Dry run finished successfully (0 files modified)."
    else
        log "Installation complete! Reload Hyprland ('hyprctl reload') and restart Quickshell ('qs -c ii') to apply."
    fi
}

main
