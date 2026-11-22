#!/usr/bin/env python3
"""Apply and restore Pulsar's temporary Hyprland game profile."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PROFILE = {
    "animations.enabled": "0",
    "decoration.shadow.enabled": "0",
    "decoration.blur.enabled": "0",
    "general.gaps_in": "0",
    "general.gaps_out": "0",
    "general.border_size": "1",
    "decoration.rounding": "0",
    "general.allow_tearing": "1",
}


def run(args: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def option_value(key: str) -> str:
    result = run(["hyprctl", "-j", "getoption", key])
    if result.returncode != 0:
        raise RuntimeError(f"getoption failed for {key}: {(result.stderr or result.stdout).strip()}")
    raw = result.stdout.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for candidate in ("value", "bool", "int", "float", "str", "string", "css"):
                if candidate in data:
                    value = data[candidate]
                    if isinstance(value, bool):
                        return "1" if value else "0"
                    if isinstance(value, (int, float, str)):
                        return str(value)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"(?m)^\s*(?:bool|int|float|str|value):\s*(.*?)\s*$", raw)
    if match:
        return match.group(1)
    raise RuntimeError(f"could not parse getoption output for {key}: {raw[:200]}")


def _lua_value(key: str, value: str) -> str:
    if key in {"animations.enabled", "decoration.shadow.enabled", "decoration.blur.enabled", "general.allow_tearing"}:
        return "true" if value.lower() in {"1", "true"} else "false"
    if key in {"general.gaps_in", "general.gaps_out"} and " " in value.strip():
        parts = [float(part) if "." in part else int(part) for part in value.split()]
        if len(parts) == 1:
            return str(parts[0])
        if len(parts) == 4:
            top, right, bottom, left = parts
            return f"{{ top = {top}, right = {right}, bottom = {bottom}, left = {left} }}"
        raise RuntimeError(f"unsupported saved gap value for {key}: {value}")
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError as error:
        raise RuntimeError(f"unsupported saved value for {key}: {value}") from error


def apply(values: dict[str, str]) -> None:
    entries = ", ".join(f'["{key}"] = {_lua_value(key, value)}' for key, value in values.items())
    result = run(["hyprctl", "eval", f"hl.config({{ {entries} }})"])
    if result.returncode != 0 or result.stdout.strip().lower() != "ok":
        raise RuntimeError(f"Hyprland rejected profile update: {(result.stderr or result.stdout).strip()}")


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"enter", "restore"}:
        print("usage: pulsar_game_mode.py enter|restore STATE_FILE", file=sys.stderr)
        return 2
    action, filename = sys.argv[1], Path(sys.argv[2])
    lock_path = filename.with_name(filename.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "enter":
            if filename.exists():
                print("Pulsar profile is already active")
                return 0
            snapshot = {key: option_value(key) for key in PROFILE}
            atomic_write(filename, {"version": 1, "options": snapshot})
            try:
                apply(PROFILE)
            except Exception:
                try:
                    apply(snapshot)
                    filename.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
            print("Pulsar game profile applied")
            return 0
        if not filename.exists():
            print("No saved game profile")
            return 0
        data = json.loads(filename.read_text(encoding="utf-8"))
        snapshot = data.get("options")
        if not isinstance(snapshot, dict) or set(snapshot) != set(PROFILE):
            raise RuntimeError("saved game profile is incomplete; keeping it for recovery")
        apply({key: str(snapshot[key]) for key in PROFILE})
        filename.unlink()
        print("Previous Hyprland values restored")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Pulsar Game Mode: {error}", file=sys.stderr)
        raise SystemExit(1)
