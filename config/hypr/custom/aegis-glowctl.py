#!/usr/bin/env python3
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path.home() / ".config/hypr/custom"
CONFIG = BASE / "glow.lua"
STATE_FILE = BASE / "glow-settings.json"


def atomic_write(path, content):
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=".aegis-glow-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate(state):
    color = state.get("color")
    enabled = state.get("enabled")
    alpha = state.get("alpha")
    size = state.get("size")

    if not isinstance(color, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", color):
        raise ValueError("Glow rengi geçersiz.")
    if not isinstance(enabled, bool):
        raise ValueError("Glow aç/kapat değeri geçersiz.")
    if not isinstance(alpha, int) or isinstance(alpha, bool) or not 0 <= alpha <= 255:
        raise ValueError("Glow parlaklık değeri geçersiz.")
    if not isinstance(size, int) or isinstance(size, bool) or not 10 <= size <= 80:
        raise ValueError("Glow boyutu 10-80 arasında olmalı.")

    return {
        "color": color.lower(),
        "enabled": enabled,
        "alpha": alpha,
        "size": size,
    }


def from_config():
    source = CONFIG.read_text(encoding="utf-8")
    color = re.search(
        r'local\s+aegis_glow_rgb\s*=\s*"([0-9a-fA-F]{6})"',
        source,
    )
    shadow = re.search(
        r"shadow\s*=\s*\{\s*enabled\s*=\s*(true|false)\s*,\s*range\s*=\s*(\d+)",
        source,
        re.S,
    )
    alpha = re.search(
        r'color\s*=\s*"rgba\("\s*\.\.\s*aegis_glow_rgb\s*\.\.\s*"([0-9a-fA-F]{2})\)"',
        source,
    )

    if not color or not shadow or not alpha:
        raise ValueError("glow.lua içinden mevcut değerler okunamadı.")

    return validate({
        "color": color.group(1),
        "enabled": shadow.group(1) == "true",
        "size": int(shadow.group(2)),
        "alpha": int(alpha.group(1), 16),
    })


def read_state():
    if STATE_FILE.exists():
        return validate(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return from_config()


def render(state):
    color = state["color"]
    alpha = f'{state["alpha"]:02X}'
    enabled = "true" if state["enabled"] else "false"
    size = state["size"]

    return (
        f'local aegis_glow_rgb = "{color}"\n\n'
        "hl.config({\n"
        "    general = {\n"
        "        col = {\n"
        '            active_border = "rgba(" .. aegis_glow_rgb .. "F2)",\n'
        "        },\n"
        "    },\n"
        "    decoration = {\n"
        "        glow = {\n"
        "            enabled = false,\n"
        "        },\n"
        "        shadow = {\n"
        f"            enabled = {enabled},\n"
        f"            range = {size},\n"
        "            render_power = 2,\n"
        "            sharp = false,\n"
        f'            color = "rgba(" .. aegis_glow_rgb .. "{alpha})",\n'
        '            color_inactive = "rgba(" .. aegis_glow_rgb .. "00)",\n'
        "            offset = { 0, 0 },\n"
        "            scale = 1.0,\n"
        "        },\n"
        "    },\n"
        "})\n"
    )


def reload_hyprland():
    result = subprocess.run(
        ["hyprctl", "reload"], capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Hyprland yeniden yüklenemedi.").strip())

    errors = subprocess.run(
        ["hyprctl", "configerrors"], capture_output=True, text=True, timeout=10
    )
    if errors.returncode != 0:
        raise RuntimeError("Hyprland yapılandırma hataları kontrol edilemedi.")

    output = errors.stdout.strip()
    if output not in ("", "[]"):
        raise RuntimeError("Hyprland yapılandırma hatası: " + output)


def commit(state):
    state = validate(state)
    old_config = CONFIG.read_text(encoding="utf-8")
    old_json = STATE_FILE.read_text(encoding="utf-8") if STATE_FILE.exists() else None

    try:
        atomic_write(STATE_FILE, json.dumps(state, indent=2) + "\n")
        atomic_write(CONFIG, render(state))
        reload_hyprland()
    except Exception:
        atomic_write(CONFIG, old_config)
        if old_json is None:
            STATE_FILE.unlink(missing_ok=True)
        else:
            atomic_write(STATE_FILE, old_json)
        try:
            subprocess.run(["hyprctl", "reload"], capture_output=True, text=True, timeout=15)
        except Exception:
            pass
        raise


def main():
    if len(sys.argv) < 2:
        raise ValueError("İşlem belirtilmedi.")

    action = sys.argv[1]
    state = read_state()

    if action == "get":
        if not STATE_FILE.exists():
            atomic_write(STATE_FILE, json.dumps(state, indent=2) + "\n")
        print(json.dumps({
            "enabled": state["enabled"],
            "brightness": round(state["alpha"] * 100.0 / 255.0, 6),
            "size": state["size"],
            "color": state["color"],
        }))
        return

    if action == "apply":
        if len(sys.argv) != 5 or sys.argv[2] not in ("true", "false"):
            raise ValueError("Glow ayarları eksik veya hatalı.")

        brightness = float(sys.argv[3])
        size = float(sys.argv[4])
        if not math.isfinite(brightness) or not 0 <= brightness <= 100:
            raise ValueError("Parlaklık 0-100 arasında olmalı.")
        if not math.isfinite(size) or not 10 <= size <= 80:
            raise ValueError("Boyut 10-80 arasında olmalı.")

        state["enabled"] = sys.argv[2] == "true"
        state["alpha"] = int(round(brightness * 255.0 / 100.0))
        state["size"] = int(round(size))
        commit(state)
        print("Glow ayarları uygulandı.")
        return

    if action == "color":
        if len(sys.argv) != 3 or not re.fullmatch(r"[0-9a-fA-F]{6}", sys.argv[2]):
            raise ValueError("Renk 6 haneli RGB kodu olmalı.")
        state["color"] = sys.argv[2].lower()
        commit(state)
        print("Glow ve aktif pencere kenarı rengi güncellendi.")
        return

    raise ValueError("Bilinmeyen işlem: " + action)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Aegis Glow hatası: " + str(exc), file=sys.stderr)
        sys.exit(1)
