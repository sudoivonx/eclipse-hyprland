#!/usr/bin/env bash
set -euo pipefail

picked="$(hyprpicker --format=hex --no-fancy 2>/dev/null | tr -d '[:space:]' || true)"
picked="${picked#\#}"
picked="${picked,,}"

if [[ ! "$picked" =~ ^[0-9a-f]{6}$ ]]; then
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "Aegis Glow" "Renk seçilemedi; tekrar deneyebilirsin." || true
    fi
    exit 1
fi

python3 "$HOME/.config/hypr/custom/aegis-glowctl.py" color "$picked"

if command -v notify-send >/dev/null 2>&1; then
    notify-send "Aegis Glow" "Yeni renk: #$picked" || true
fi
