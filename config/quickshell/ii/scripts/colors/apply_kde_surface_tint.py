#!/usr/bin/env python3
"""Apply an optional, restrained Matugen tint to generated KDE app surfaces."""
import json
import os
import re
from pathlib import Path

home = Path.home()
config_path = home / ".config/illogical-impulse/config.json"
palette_path = home / ".local/state/quickshell/user/generated/colors.json"
try:
    config = json.loads(config_path.read_text())
    configured_enabled = config.get("appearance", {}).get("wallpaperTheming", {}).get("tintAppWindowSurfaces", False)
    override = os.environ.get("PULSAR_TINT_APP_WINDOW_SURFACES")
    enabled = configured_enabled if override is None else override.strip().lower() == "true"
    palette = json.loads(palette_path.read_text())
    color = palette.get("source_color", "").strip()
except (OSError, json.JSONDecodeError, AttributeError):
    raise SystemExit(0)

if not enabled or not re.fullmatch(r"#?[0-9a-fA-F]{6}", color):
    raise SystemExit(0)
color = color.lstrip("#")
tint = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
sections = {
    "[Colors:Button]", "[Colors:Complementary]", "[Colors:Header]",
    "[Colors:Header][Inactive]", "[Colors:Tooltip]", "[Colors:View]",
    "[Colors:Window]",
}
strengths = {"BackgroundNormal": 0.28, "BackgroundAlternate": 0.22}
pattern = re.compile(r"^(BackgroundNormal|BackgroundAlternate)=(#[0-9a-fA-F]{6})$")
files = list((home / ".local/share/color-schemes").glob("MaterialYou*.colors"))
files.append(home / ".config/kdeglobals")
for path in files:
    if not path.is_file():
        continue
    current_section = ""
    output = []
    changed = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped
        match = pattern.match(stripped)
        if current_section in sections and match:
            key, value = match.groups()
            amount = strengths[key]
            base = tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
            mixed = tuple(round(b * (1 - amount) + t * amount) for b, t in zip(base, tint))
            prefix = line[:len(line) - len(line.lstrip())]
            line = prefix + key + "=" + "#" + "".join(f"{c:02x}" for c in mixed)
            changed = True
        output.append(line)
    if changed:
        path.write_text("\n".join(output) + "\n")
