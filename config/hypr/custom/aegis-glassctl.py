#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json
import re
import shutil
import subprocess
import sys

GENERAL = Path.home() / ".config/hypr/custom/general.lua"
BEGIN = "-- AEGIS ACRYLIC GLASS BEGIN"
END = "-- AEGIS ACRYLIC GLASS END"

def region_of(source):
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise RuntimeError("Acrylic bölüm işaretçileri eksik veya yinelenmiş.")
    start = source.index(BEGIN)
    finish = source.index(END, start) + len(END)
    return start, finish, source[start:finish]

def number(region, key, default):
    m = re.search(rf"\b{re.escape(key)}\s*=\s*(\d+(?:\.\d+)?)", region)
    return float(m.group(1)) if m else default

def boolean_value(region, key, default):
    match = re.search(
        rf"\b{re.escape(key)}\s*=\s*(true|false)\b",
        region
    )
    return (match.group(1) == "true") if match else default

def get_state(source):
    _, _, block = region_of(source)
    return {
        "size": int(round(number(block, "size", 12))),
        "passes": int(round(number(block, "passes", 3))),
        "clarity": number(block, "clarity", 0.65),
        "enabled": boolean_value(block, "enabled", True),
    }

def make_block(size, clarity, passes, enabled):
    return (
        f"{BEGIN}\n"
        "-- Aegis Gelişmiş Ayarlar tarafından yönetilen Acrylic cam profili.\n"
        "hl.config({\n"
        "    decoration = {\n"
        "        blur = {\n"
        f"            enabled = {'true' if enabled else 'false'},\n"
        '            variant = "acrylic",\n'
        f"            size = {size},\n"
        f"            passes = {passes},\n"
        "            ignore_opacity = true,\n"
        "            acrylic = {\n"
        f"                clarity = {clarity:.2f},\n"
        "            },\n"
        "        },\n"
        "    },\n"
        "})\n"
        f"{END}"
    )

def apply(size, clarity, enabled=True, passes=None):
    if not 4 <= size <= 24:
        raise RuntimeError("Bulanıklık boyutu 4–24 arasında olmalı.")
    if not 0.0 <= clarity <= 1.0:
        raise RuntimeError("Acrylic netliği 0–1 arasında olmalı.")
    if not isinstance(enabled, bool):
        raise RuntimeError("Cam etkin durumu true veya false olmalı.")

    source = GENERAL.read_text()
    start, finish, block = region_of(source)
    current = get_state(source)
    if passes is None:
        passes = current['passes']
    if not isinstance(passes, int) or not 1 <= passes <= 6:
        raise RuntimeError("Bulanıklık geçiş sayısı 1–6 arasında olmalı.")
    updated_block = make_block(size, clarity, passes, enabled)
    updated = source[:start] + updated_block + source[finish:]

    backup = GENERAL.with_name(
        GENERAL.name + ".backup-glassctl-" +
        datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    shutil.copy2(GENERAL, backup)

    try:
        GENERAL.write_text(updated)
        reload_result = subprocess.run(
            ["hyprctl", "reload"], capture_output=True, text=True
        )
        check = subprocess.run(
            ["hyprctl", "configerrors"], capture_output=True, text=True
        )
        errors = (check.stdout + check.stderr).strip()

        if reload_result.returncode != 0:
            raise RuntimeError(
                reload_result.stderr or reload_result.stdout or "Hyprland yeniden yüklenemedi."
            )
        if check.returncode != 0 or errors not in ("", "[]", "No config errors found."):
            raise RuntimeError(errors or "Hyprland yapılandırma kontrolü başarısız.")

    except Exception as exc:
        shutil.copy2(backup, GENERAL)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        raise RuntimeError(
            f"{exc}. Eski ayarlar geri yüklendi; yedek: {backup}"
        ) from exc

    print(f"Cam efekti: {'Açık' if enabled else 'Kapalı'}")
    print(f"Cam bulanıklığı boyutu: {size}")
    print(f"Acrylic netliği: %{clarity * 100:.0f}")
    print(f"Bulanıklık geçişi: {passes}")
    print("Hyprland yapılandırma kontrolü başarılı.")

def main():
    if not GENERAL.is_file():
        raise RuntimeError("general.lua bulunamadı.")
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "get":
        print(json.dumps(get_state(GENERAL.read_text())))
        return

    if action != "apply" or len(sys.argv) not in (4, 5, 6):
        raise RuntimeError(
            "Kullanım: get veya apply BOYUT NETLIK_0_1 [true|false] [GEÇİŞ]"
        )

    state = get_state(GENERAL.read_text())

    if len(sys.argv) >= 5:
        raw_enabled = sys.argv[4].lower()
        if raw_enabled not in ("true", "false"):
            raise RuntimeError("Cam durumu true veya false olmalı.")
        enabled = raw_enabled == "true"
    else:
        enabled = state["enabled"]

    if len(sys.argv) == 6:
        try:
            passes = int(float(sys.argv[5]))
        except ValueError:
            raise RuntimeError("Geçiş sayısı tam sayı olmalı.")
    else:
        passes = state["passes"]

    apply(int(float(sys.argv[2])), float(sys.argv[3]), enabled, passes)
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("HATA:", exc, file=sys.stderr)
        sys.exit(1)
