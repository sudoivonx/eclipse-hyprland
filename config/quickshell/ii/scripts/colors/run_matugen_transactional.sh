#!/usr/bin/env bash

# Render every Matugen template to a staging directory first. Publish the new
# set only after Matugen succeeds; roll back already-published files if a
# filesystem error interrupts the commit.

set -u

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 MATUGEN_CONFIG MATUGEN_ARGUMENTS..." >&2
    exit 2
fi

config_path="$1"
shift
cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/pulsar"
mkdir -p "$cache_root" || exit 1
stage_dir="$(mktemp -d "$cache_root/matugen.XXXXXX")" || exit 1
trap 'rm -rf -- "$stage_dir"' EXIT

if ! python3 - "$config_path" "$stage_dir" <<'PY'
import json
import os
import re
import sys
import tomllib
from pathlib import Path

config_path = Path(sys.argv[1]).expanduser().resolve()
stage_dir = Path(sys.argv[2]).resolve()
source = config_path.read_text()
config = tomllib.loads(source)
outputs = []
for section in config.get("templates", {}).values():
    output = section.get("output_path")
    if output is None:
        continue
    destination = Path(os.path.expandvars(os.path.expanduser(output)))
    if not destination.is_absolute():
        destination = (config_path.parent / destination).resolve()
    outputs.append(destination)

if not outputs:
    raise SystemExit("Matugen config has no template output_path entries")
if len(set(outputs)) != len(outputs):
    raise SystemExit("Matugen config contains duplicate template output paths")

matches = list(re.finditer(r"(?m)^(\s*output_path\s*=\s*)(['\"])(.*?)\2\s*$", source))
if len(matches) != len(outputs):
    raise SystemExit("Could not safely map every Matugen output path")

staged = []
for index, (destination, match) in enumerate(zip(outputs, matches)):
    stage_path = stage_dir / "rendered" / f"{index:03d}-{destination.name}"
    stage_path.parent.mkdir(parents=True, exist_ok=True)
    staged.append({"destination": str(destination), "stage": str(stage_path)})

rewritten = source
for index in range(len(matches) - 1, -1, -1):
    match = matches[index]
    replacement = f'{match.group(1)}"{staged[index]["stage"]}"'
    rewritten = rewritten[:match.start()] + replacement + rewritten[match.end():]
(stage_dir / "config.toml").write_text(rewritten)
(stage_dir / "manifest.json").write_text(json.dumps(staged))
PY
then
    echo "Pulsar: could not prepare Matugen staging configuration." >&2
    exit 1
fi

if ! matugen --config "$stage_dir/config.toml" "$@"; then
    echo "Pulsar: Matugen failed; existing generated files were kept." >&2
    exit 1
fi

if ! python3 - "$stage_dir" <<'PY'
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

stage_dir = Path(sys.argv[1])
manifest = json.loads((stage_dir / "manifest.json").read_text())
for item in manifest:
    stage = Path(item["stage"])
    if not stage.is_file() or stage.stat().st_size == 0:
        raise SystemExit(f"Matugen did not produce a valid template: {stage.name}")

# GTK remains on the standard Matugen surfaces by default. When opted in,
# gently blend each GTK accent into the window and common container surfaces.
if os.environ.get("PULSAR_GTK_WINDOW_TINT", "false").lower() == "true":
    import re

    tint_color = None
    for item in manifest:
        if Path(item["destination"]).name == "colors.json":
            try:
                tint_color = json.loads(Path(item["stage"]).read_text()).get("source_color")
            except (OSError, json.JSONDecodeError):
                tint_color = None
            break

    tint_strength = {
        "window_bg_color": 0.32,
        "headerbar_bg_color": 0.27,
        "card_bg_color": 0.25,
        "sidebar_bg_color": 0.24,
        "secondary_sidebar_bg_color": 0.22,
        "view_bg_color": 0.18,
        "overview_bg_color": 0.18,
        "popover_bg_color": 0.25,
        "dialog_bg_color": 0.25,
    }

    def mix_hex(base, accent, amount):
        base_rgb = tuple(int(base[i:i + 2], 16) for i in (1, 3, 5))
        accent_rgb = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
        mixed = tuple(round(b * (1 - amount) + a * amount) for b, a in zip(base_rgb, accent_rgb))
        return "#" + "".join(f"{channel:02x}" for channel in mixed)

    for item in manifest:
        destination = Path(item["destination"])
        if destination.name != "gtk.css" or destination.parent.name not in {"gtk-3.0", "gtk-4.0"}:
            continue
        stage = Path(item["stage"])
        lines = stage.read_text().splitlines(keepends=True)
        accent = None
        output = []
        for line in lines:
            accent_match = re.search(r"@define-color\s+accent_color\s+(#[0-9a-fA-F]{6})\s*;", line)
            if accent_match:
                accent = accent_match.group(1)
            background_match = re.search(r"(@define-color\s+)([a-z_]+)(\s+)(#[0-9a-fA-F]{6})(\s*;)", line)
            selected_color = tint_color or accent
            if selected_color and background_match and background_match.group(2) in tint_strength:
                color_name = background_match.group(2)
                tinted = mix_hex(background_match.group(4), selected_color, tint_strength[color_name])
                line = line[:background_match.start(4)] + tinted + line[background_match.end(4):]
            output.append(line)
        stage.write_text("".join(output))

committed = []
unchanged_count = 0
changed_count = 0
try:
    for index, item in enumerate(manifest):
        destination = Path(item["destination"])
        stage = Path(item["stage"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = stage_dir / f"backup-{index:03d}"
        existed = destination.exists()
        if existed and stage.read_bytes() == destination.read_bytes():
            unchanged_count += 1
            continue
        if existed:
            shutil.copy2(destination, backup)

        fd, temporary = tempfile.mkstemp(prefix=".pulsar-matugen-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(stage, temporary)
            shutil.copystat(destination if existed else stage, temporary)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        committed.append((destination, backup if existed else None))
        changed_count += 1
except Exception:
    for destination, backup in reversed(committed):
        if backup is None:
            destination.unlink(missing_ok=True)
            continue
        fd, temporary = tempfile.mkstemp(prefix=".pulsar-rollback-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(backup, temporary)
            shutil.copystat(backup, temporary)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    raise

print(f"Pulsar: Matugen outputs: {changed_count} updated, {unchanged_count} unchanged.")
PY
then
    echo "Pulsar: template publishing failed; prior outputs were restored." >&2
    exit 1
fi
