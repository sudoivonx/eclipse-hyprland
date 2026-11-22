#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json
import re
import shutil
import subprocess
import sys

F = Path.home() / ".config/hypr/custom/general.lua"
BEGIN = "-- AEGIS MOTION PROFILE BEGIN"
END = "-- AEGIS MOTION PROFILE END"

# None: kapalı; tuple: (speed, bezier, style)
LEAVES = {
    "windowsIn": (3.0, "aegisSpatialPop", "popin 86%"),
    "fadeIn": (2.8, "aegisSmoothOut", None),
    "windowsOut": (2.2, "aegisSmoothIn", "popin 92%"),
    "fadeOut": (2.0, "aegisSmoothIn", None),
    "workspaces": (5.5, "aegisSmoothOut", "slidefade 22%"),
    "windowsMove": (3.2, "aegisSmoothOut", "slide"),
    "specialWorkspaceIn": (3.0, "aegisSmoothOut", "slidevert"),
    "specialWorkspaceOut": (2.2, "aegisSmoothIn", "slidevert"),
    "border": (8.0, "aegisSmoothOut", None),
    "layersIn": (2.8, "aegisSpatialPop", "popin 94%"),
    "layersOut": (2.2, "aegisSmoothIn", "popin 96%"),
    "fadeLayersIn": (2.6, "aegisSmoothOut", None),
    "fadeLayersOut": (2.0, "aegisSmoothIn", None),
    "fadeSwitch": (2.8, "aegisSmoothOut", None),
    "fadeShadow": (2.8, "aegisSmoothOut", None),
    "fadeDim": (2.8, "aegisSmoothOut", None),
    "fadeGlow": (2.8, "aegisSmoothOut", None),
    "fadePopupsIn": (2.4, "aegisSmoothOut", None),
    "fadePopupsOut": (2.0, "aegisSmoothIn", None),
}

LIGHT = {
    "windowsIn": (2.0, "aegisSpatialPop", "popin 96%"),
    "fadeIn": (2.0, "aegisSmoothOut", None),
    "windowsOut": (1.8, "aegisSmoothIn", "popin 98%"),
    "fadeOut": (1.8, "aegisSmoothIn", None),
    "workspaces": (3.5, "aegisSmoothOut", "slidefade 12%"),
    "windowsMove": (2.5, "aegisSmoothOut", "slide"),
    "specialWorkspaceIn": (2.2, "aegisSmoothOut", "slidevert"),
    "specialWorkspaceOut": (1.8, "aegisSmoothIn", "slidevert"),
    "border": (6.0, "aegisSmoothOut", None),
    "layersIn": (2.0, "aegisSpatialPop", "popin 96%"),
    "layersOut": (1.8, "aegisSmoothIn", "popin 98%"),
    "fadeLayersIn": (2.0, "aegisSmoothOut", None),
    "fadeLayersOut": (1.8, "aegisSmoothIn", None),
    "fadeSwitch": (2.0, "aegisSmoothOut", None),
    "fadeShadow": (2.0, "aegisSmoothOut", None),
    "fadeDim": (2.0, "aegisSmoothOut", None),
    "fadeGlow": (2.0, "aegisSmoothOut", None),
    "fadePopupsIn": (1.8, "aegisSmoothOut", None),
    "fadePopupsOut": (1.6, "aegisSmoothIn", None),
}

PROFILES = {
    "off": ({}, False, 0.45),
    "light": (LIGHT, True, 0.25),
    "full": (LEAVES, True, 0.45),
}

def read_profile(source):
    if source.count(BEGIN) != source.count(END) or source.count(BEGIN) > 1:
        raise RuntimeError("Profil işaretçileri tutarsız.")
    if BEGIN not in source:
        return "full"
    start = source.index(BEGIN)
    stop = source.index(END, start)
    match = re.search(
        r"(?m)^-- AEGIS MOTION PROFILE NAME: (off|light|full)$",
        source[start:stop],
    )
    if not match:
        raise RuntimeError("Kayıtlı profil okunamadı.")
    return match.group(1)

def make_block(profile):
    animations, wobble_enabled, intensity = PROFILES[profile]
    lines = [
        BEGIN,
        f"-- AEGIS MOTION PROFILE NAME: {profile}",
        "-- Gelişmiş menü tarafından yönetilen geçici profiller.",
    ]

    for leaf in LEAVES:
        setting = animations.get(leaf)
        if setting is None:
            lines.append(
                f'hl.animation({{ leaf = "{leaf}", enabled = false }})'
            )
            continue

        speed, bezier, style = setting
        fields = [
            f'leaf = "{leaf}"',
            "enabled = true",
            f"speed = {speed}",
            f'bezier = "{bezier}"',
        ]
        if style is not None:
            fields.append(f'style = "{style}"')
        lines.append("hl.animation({ " + ", ".join(fields) + " })")

    lines.extend([
        "hl.config({",
        "    decoration = {",
        "        wobble = {",
        f"            enabled = {'true' if wobble_enabled else 'false'},",
        "            mesh = 16,",
        f"            intensity = {intensity},",
        "            stiffness = 220,",
        "            damping = 18,",
        "        },",
        "    },",
        "})",
        END,
    ])
    return "\n".join(lines)

def errors():
    r = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    clean = r.returncode == 0 and (
        out in ("", "[]") or "no config errors found" in out.lower()
    )
    return clean, out

def main():
    if not F.is_file():
        raise RuntimeError("general.lua bulunamadı.")
    source = F.read_text()
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "get":
        print(json.dumps({"profile": read_profile(source)}))
        return
    if action != "apply" or len(sys.argv) != 3:
        raise RuntimeError("Kullanım: get veya apply off|light|full")

    profile = sys.argv[2].lower()
    if profile not in PROFILES:
        raise RuntimeError("Bilinmeyen profil.")

    clean, current_errors = errors()
    if not clean:
        raise RuntimeError(
            "Mevcut yapılandırma temiz değil; değişiklik yapılmadı. "
            + current_errors
        )

    previous = read_profile(source)
    block = make_block(profile)

    if BEGIN in source:
        start = source.index(BEGIN)
        stop = source.index(END, start) + len(END)
        updated = source[:start] + block + source[stop:]
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        updated = source.rstrip() + "\n\n" + block + "\n"

    backup = F.with_name(
        F.name + ".backup-motion-profile-" +
        datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    shutil.copy2(F, backup)

    try:
        F.write_text(updated)
        reload_result = subprocess.run(
            ["hyprctl", "reload"], capture_output=True, text=True
        )
        clean, current_errors = errors()

        if reload_result.returncode != 0:
            raise RuntimeError(
                reload_result.stderr or reload_result.stdout or "Reload başarısız."
            )
        if not clean:
            raise RuntimeError(current_errors or "Kontrol başarısız.")

    except Exception as exc:
        shutil.copy2(backup, F)
        subprocess.run(["hyprctl", "reload"], capture_output=True, text=True)
        raise RuntimeError(
            f"Profil uygulanamadı; önceki dosya geri yüklendi.\n{exc}"
        )

    print(f"Profil uygulandı: {profile} (önceki: {previous})")
    print("Yedek:", backup)
    print("Yapılandırma hatası yok.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("HATA:", exc, file=sys.stderr)
        sys.exit(1)
