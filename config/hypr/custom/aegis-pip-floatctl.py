#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json
import shutil
import subprocess
import sys

BASE = Path.home() / ".config/hypr/custom"
RULES = BASE / "rules.lua"
STATE = BASE / "aegis-pip-float.json"
BEGIN = "-- AEGIS PICTURE-IN-PICTURE BEGIN"
END = "-- AEGIS PICTURE-IN-PICTURE END"
RULE = 'name = "aegis-opaque-zen-picture-in-picture"'

def read_state():
    if not STATE.exists():
        return {"enabled": False}
    data = json.loads(STATE.read_text())
    return {"enabled": data.get("enabled") is True}

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "get":
        print(json.dumps(read_state()))
        return
    if action != "apply" or len(sys.argv) != 3 or sys.argv[2] not in ("true", "false"):
        raise RuntimeError("Kullanım: get veya apply true|false")

    enabled = sys.argv[2] == "true"
    source = RULES.read_text()
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise RuntimeError("PiP kural işaretçileri eksik veya yinelenmiş.")

    start = source.index(BEGIN)
    finish = source.index(END, start) + len(END)
    block = source[start:finish]
    if RULE not in block:
        raise RuntimeError("PiP opaklık kuralı bulunamadı.")

    lines = block.splitlines()
    lines = [line for line in lines if "float = true," not in line]
    if enabled:
        for i, line in enumerate(lines):
            if RULE in line:
                lines.insert(i + 1, "    float = true,")
                break
    updated = source[:start] + "\n".join(lines) + source[finish:]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = RULES.with_name(RULES.name + ".backup-pipctl-" + stamp)
    shutil.copy2(RULES, backup)
    old_state = STATE.read_bytes() if STATE.exists() else None

    try:
        RULES.write_text(updated)
        STATE.write_text(json.dumps({"enabled": enabled}, indent=2) + "\n")
        reload_result = subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        check = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True)
        errors = (check.stdout + check.stderr).strip()
        if reload_result.returncode or check.returncode or errors not in ("", "[]", "No config errors found."):
            raise RuntimeError(errors or reload_result.stderr or "Hyprland yeniden yüklenemedi.")
    except Exception as exc:
        shutil.copy2(backup, RULES)
        if old_state is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_bytes(old_state)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        raise RuntimeError(f"{exc}; önceki kurallar geri yüklendi. Yedek: {backup}") from exc

    print("PiP yüzer pencere ayarı uygulandı: " + ("açık" if enabled else "kapalı"))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("HATA:", exc, file=sys.stderr)
        sys.exit(1)
