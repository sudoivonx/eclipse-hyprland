#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys

BASE = Path.home() / ".config/hypr/custom"
RULES = BASE / "rules.lua"
STATE = BASE / "aegis-custom-opacity.json"
BEGIN = "-- AEGIS CUSTOM OPACITY BEGIN"
END = "-- AEGIS CUSTOM OPACITY END"
RULES_END = "-- AEGIS WINDOW GLASS RULES END"


def read_state():
    if not STATE.exists():
        return []
    data = json.loads(STATE.read_text())
    if not isinstance(data, list):
        raise RuntimeError("Özel seçim kayıt dosyasının biçimi geçersiz.")
    return data


def window_list():
    result = subprocess.run(
        ["hyprctl", "clients", "-j"],
        check=True, capture_output=True, text=True
    )
    windows = json.loads(result.stdout)
    return [
        {
            "class": w.get("class") or "",
            "title": w.get("title") or "",
            "initialClass": w.get("initialClass") or "",
            "initialTitle": w.get("initialTitle") or "",
            "address": w.get("address") or "",
            "fullscreen": bool(w.get("fullscreen")),
        }
        for w in windows
        if w.get("class") and w.get("title")
    ]


def lua_string(value):
    return json.dumps(value, ensure_ascii=False)


def make_block(items):
    out = [
        BEGIN,
        "-- Yalnızca Aegis özel pencere seçimleri tarafından yönetilir.",
        'local aegisCustomOpaqueOpacity = "1.0 override 1.0 override 1.0 override"',
    ]
    for item in items:
        cls = item["class"]
        title = item["title"]
        digest = hashlib.sha1(
            (cls + "\0" + title).encode("utf-8")
        ).hexdigest()[:12]
        class_pattern = "^" + re.escape(cls) + "$"
        title_pattern = "^" + re.escape(title) + "$"
        out.extend([
            "hl.window_rule({",
            f'    name = "aegis-custom-opaque-{digest}",',
            "    match = { "
            f"class = {lua_string(class_pattern)}, "
            f"title = {lua_string(title_pattern)} "
            "},",
            "    opacity = aegisCustomOpaqueOpacity,",
            "})",
            "",
        ])
    out.append(END)
    return "\n".join(out)


def save(items):
    source = RULES.read_text()
    if source.count(BEGIN) > 1 or source.count(END) > 1:
        raise RuntimeError("Özel kural işaretçileri yinelenmiş.")
    if source.count(BEGIN) != source.count(END):
        raise RuntimeError("Özel kural işaretçileri eşleşmiyor.")

    block = make_block(items)
    if BEGIN in source:
        start = source.index(BEGIN)
        finish = source.index(END, start) + len(END)
        updated = source[:start] + block + source[finish:]
    else:
        if source.count(RULES_END) != 1:
            raise RuntimeError("Hyprland kural bölümünün sonu bulunamadı.")
        updated = source.replace(RULES_END, block + "\n\n" + RULES_END, 1)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = RULES.with_name(RULES.name + ".backup-custom-opacity-" + stamp)
    shutil.copy2(RULES, backup)
    old_state = STATE.read_bytes() if STATE.exists() else None

    try:
        RULES.write_text(updated)
        STATE.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n")
        reload_result = subprocess.run(
            ["hyprctl", "reload"], capture_output=True, text=True
        )
        check = subprocess.run(
            ["hyprctl", "configerrors"], capture_output=True, text=True
        )
        errors = (check.stdout + check.stderr).strip()
        if reload_result.returncode or check.returncode or errors not in (
            "", "[]", "No config errors found."
        ):
            raise RuntimeError(
                errors or reload_result.stderr or "Hyprland yeniden yüklenemedi."
            )
    except Exception as exc:
        shutil.copy2(backup, RULES)
        if old_state is None:
            STATE.unlink(missing_ok=True)
        else:
            STATE.write_bytes(old_state)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        raise RuntimeError(
            f"{exc}; önceki kurallar geri yüklendi. Yedek: {backup}"
        ) from exc

    print("Özel seçimler kaydedildi; Hyprland yapılandırması hatasız.")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "windows":
        print(json.dumps(window_list(), ensure_ascii=False))
        return

    if action == "get":
        print(json.dumps(read_state(), ensure_ascii=False))
        return

    items = read_state()

    if action == "add":
        if len(sys.argv) != 4:
            raise RuntimeError("Kullanım: add SINIF BAŞLIK")
        cls, title = sys.argv[2], sys.argv[3]
        if not cls.strip() or not title.strip():
            raise RuntimeError("Pencere sınıfı ve başlığı boş olamaz.")
        if any(x["class"] == cls and x["title"] == title for x in items):
            print("Bu pencere zaten özel listeye eklenmiş.")
            return
        items.append({"class": cls, "title": title})
        save(items)
        return

    if action == "remove":
        if len(sys.argv) != 3:
            raise RuntimeError("Kullanım: remove SIRA")
        index = int(sys.argv[2])
        if index < 0 or index >= len(items):
            raise RuntimeError("Seçim sırası geçersiz.")
        items.pop(index)
        save(items)
        return

    if action == "clear":
        save([])
        print("Yalnızca özel pencere seçimleri temizlendi.")
        return

    raise RuntimeError("Komutlar: windows, get, add, remove, clear")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("HATA:", exc, file=sys.stderr)
        sys.exit(1)
