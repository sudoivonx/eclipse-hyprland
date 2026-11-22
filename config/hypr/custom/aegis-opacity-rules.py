#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json, shutil, subprocess, sys

BASE = Path.home() / ".config/hypr/custom"
RULES = BASE / "rules.lua"
STATE = BASE / "aegis-opacity-rules.json"
BEGIN = "-- AEGIS OPACITY OPTIONS BEGIN"
END = "-- AEGIS OPACITY OPTIONS END"

DEFAULTS = {
    "blender": True, "davinci": True, "vlc": True,
    "photo_viewers": True, "games": True,
    "media_content": True, "fullscreen": True,
}

def read_state():
    if not STATE.exists():
        return DEFAULTS.copy()
    data = json.loads(STATE.read_text())
    return {k: bool(data.get(k, DEFAULTS[k])) for k in DEFAULTS}

def make_rules(s):
    out = [BEGIN, "-- Aegis Gelişmiş Ayarlar tarafından yönetilir.",
           'local aegisOpaqueOpacity = "1.0 override 1.0 override 1.0 override"']
    def add(name, match, enabled):
        if enabled:
            out.extend([
                "hl.window_rule({",
                f'    name = "aegis-opaque-{name}",',
                f"    match = {{ {match} }},",
                "    opacity = aegisOpaqueOpacity,",
                "})",
                ""
            ])
    add("blender", r'class = "^(blender|Blender|org\\.blender\\.Blender)$"', s["blender"])
    add("davinci-resolve", r'class = "^(resolve|davinci-resolve)$"', s["davinci"])
    add("vlc", r'class = "^(vlc|org\\.videolan\\.VLC)$"', s["vlc"])
    add("photo-viewers", r'class = "^(eog|loupe|org\\.gnome\\.Loupe|imv|swayimg|gwenview|org\\.kde\\.gwenview)$"', s["photo_viewers"])
    if s["games"]:
        add("game-content", 'content = "game"', True)
        add("steam-games", r'class = "^steam_app.*$"', True)
    if s["media_content"]:
        add("photo-content", 'content = "photo"', True)
        add("video-content", 'content = "video"', True)
    add("fullscreen", "fullscreen = true", s["fullscreen"])
    out.append(END)
    return "\n".join(out)

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "get":
        print(json.dumps(read_state()))
        return
    if action != "apply" or len(sys.argv) != 9:
        raise RuntimeError("Kullanım: get veya apply BLENDER DAVINCI VLC FOTO OYUN MEDYA TAM_EKRAN")
    state = {}
    for key, raw in zip(DEFAULTS, sys.argv[2:]):
        if raw.lower() not in ("true", "false"):
            raise RuntimeError(f"{key}: true/false bekleniyor")
        state[key] = raw.lower() == "true"

    source = RULES.read_text()
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise RuntimeError("Yönetilen opaklık işaretçileri eksik veya yinelenmiş.")
    start = source.index(BEGIN)
    finish = source.index(END, start) + len(END)
    updated = source[:start] + make_rules(state) + source[finish:]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = RULES.with_name(RULES.name + ".backup-opacityctl-" + stamp)
    state_backup = None
    shutil.copy2(RULES, backup)
    if STATE.exists():
        state_backup = STATE.with_name(STATE.name + ".backup-" + stamp)
        shutil.copy2(STATE, state_backup)
    old_state = STATE.read_bytes() if STATE.exists() else None
    try:
        RULES.write_text(updated)
        STATE.write_text(json.dumps(state, indent=2) + "\n")
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
    print("Opaklık istisnaları uygulandı; yapılandırma hatası yok.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("HATA:", e, file=sys.stderr)
        sys.exit(1)
