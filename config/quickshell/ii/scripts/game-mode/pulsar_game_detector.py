#!/usr/bin/env python3
"""Recognize fullscreen windows launched by a Steam game process."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Callable

NON_GAME_STEAM_APP_IDS = frozenset({"228980", "1493710", "4183110"})
STEAM_LAUNCH_RE = re.compile(r"(?:^|\s)SteamLaunch\s+AppId=(\d+)(?:\s|$)")


def read_process(pid: int) -> tuple[int, str] | None:
    """Return a process's parent PID and flattened argv from procfs."""
    proc = Path("/proc") / str(pid)
    try:
        stat = (proc / "stat").read_text(encoding="utf-8")
        close = stat.rfind(")")
        if close < 0:
            return None
        fields = stat[close + 1 :].split()
        if len(fields) < 2:
            return None
        parent_pid = int(fields[1])
        argv = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        return parent_pid, argv
    except (OSError, ValueError):
        return None


def steam_app_for_process(pid: int, process_reader: Callable[[int], tuple[int, str] | None] = read_process) -> str | None:
    """Walk parents to Steam's per-app launch wrapper, if present."""
    seen: set[int] = set()
    current = pid
    for _ in range(24):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        record = process_reader(current)
        if record is None:
            break
        parent_pid, argv = record
        match = STEAM_LAUNCH_RE.search(argv)
        if match:
            return match.group(1)
        current = parent_pid
    return None


def detect_game_addresses(
    windows: list[dict], process_reader: Callable[[int], tuple[int, str] | None] = read_process
) -> list[str]:
    addresses: list[str] = []
    for window in windows:
        if not isinstance(window, dict) or not window.get("address"):
            continue
        try:
            pid = int(window.get("pid", 0))
        except (TypeError, ValueError):
            continue
        app_id = steam_app_for_process(pid, process_reader)
        if app_id and app_id not in NON_GAME_STEAM_APP_IDS:
            addresses.append(str(window["address"]))
    return addresses


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: pulsar_game_detector.py WINDOWS_JSON", file=sys.stderr)
        return 2
    try:
        windows = json.loads(sys.argv[1])
        if not isinstance(windows, list):
            raise ValueError("window data must be a JSON array")
        json.dump(detect_game_addresses(windows), sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    except (json.JSONDecodeError, ValueError) as error:
        print(f"Pulsar game detector: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
