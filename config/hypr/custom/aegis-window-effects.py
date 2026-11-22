#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json, re, shutil, subprocess, sys

GENERAL = Path.home() / ".config/hypr/custom/general.lua"
BEGIN = "-- AEGIS WINDOW EFFECTS BEGIN"
END = "-- AEGIS WINDOW EFFECTS END"

def managed_region(source):
    if source.count(BEGIN) != source.count(END) or source.count(BEGIN) > 1:
        raise RuntimeError("Yönetilen ayar işaretçileri tutarsız.")
    if BEGIN not in source:
        return None
    start = source.index(BEGIN)
    finish = source.index(END, start) + len(END)
    return start, finish, source[start:finish]

def percent_in(text, key):
    values = re.findall(
        rf"\b{re.escape(key)}\s*=\s*(\d+(?:\.\d+)?)", text
    )
    return round(float(values[-1]) * 100, 1) if values else None

def get_state(source):
    region = managed_region(source)
    managed = region[2] if region else ""
    active = percent_in(managed, "active_opacity")
    inactive = percent_in(managed, "inactive_opacity")
    if active is None:
        active = percent_in(source, "active_opacity")
    if inactive is None:
        inactive = percent_in(source, "inactive_opacity")
    depth = re.search(r"\bdim_inactive\s*=\s*(true|false)", managed)
    return {
        "activeOpacity": active if active is not None else 80.0,
        "inactiveOpacity": inactive if inactive is not None else 80.0,
        "depth": depth.group(1) == "true" if depth else False,
    }

def fmt(value):
    return f"{value / 100:.3f}".rstrip("0").rstrip(".")

def make_block(active, inactive, enabled):
    dim = "true" if enabled else "false"
    return (
        f"{BEGIN}\n"
        "-- Aegis Gelişmiş Ayarlar tarafından yönetilir.\n"
        "hl.config({\n"
        "    decoration = {\n"
        f"        active_opacity = {fmt(active)},\n"
        f"        inactive_opacity = {fmt(inactive)},\n"
        f"        dim_inactive = {dim},\n"
        "        dim_strength = 0.35,\n"
        "    },\n"
        "})\n"
        f"{END}"
    )

def apply(active, inactive, enabled):
    if not 75 <= active <= 100 or not 75 <= inactive <= 100:
        raise RuntimeError("Opaklık değerleri %75–100 arasında olmalı.")
    if enabled not in ("true", "false"):
        raise RuntimeError("Derinlik değeri true veya false olmalı.")

    source = GENERAL.read_text()
    region = managed_region(source)
    block = make_block(active, inactive, enabled == "true")
    if region is None:
        updated = source.rstrip() + "\n\n" + block + "\n"
    else:
        updated = source[:region[0]] + block + source[region[1]:]
        if not updated.endswith("\n"):
            updated += "\n"

    backup = GENERAL.with_name(
        GENERAL.name + ".backup-window-effects-" +
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
            raise RuntimeError(reload_result.stderr or reload_result.stdout or "Reload başarısız.")
        if check.returncode != 0 or errors not in ("", "[]", "No config errors found."):
            raise RuntimeError(errors or "Yapılandırma kontrolü başarısız.")
    except Exception as exc:
        shutil.copy2(backup, GENERAL)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        raise RuntimeError(f"{exc}; önceki dosya geri yüklendi. Yedek: {backup}") from exc

    print(f"Aktif pencere opaklığı: %{active:g}")
    print(f"Pasif pencere opaklığı: %{inactive:g}")
    print("Yapılandırma hatası yok.")

def main():
    source = GENERAL.read_text()
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "get":
        print(json.dumps(get_state(source)))
        return
    if action != "apply" or len(sys.argv) != 5:
        raise RuntimeError("Kullanım: get veya apply AKTIF PASIF TRUE/FALSE")
    apply(float(sys.argv[2]), float(sys.argv[3]), sys.argv[4].lower())

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("HATA:", exc, file=sys.stderr)
        sys.exit(1)
