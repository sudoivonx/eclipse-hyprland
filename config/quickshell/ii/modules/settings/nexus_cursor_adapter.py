"""Persistent cursor preference adapter used by NEXUS.

The environment.d file is authoritative. Hyprland and GTK files are mirrors;
the adapter refuses writes when they disagree instead of silently repairing
unknown edits.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


MIN_CURSOR_SIZE = 8
MAX_CURSOR_SIZE = 128
_THEME_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TRANSACTION_ID = re.compile(r"^[a-f0-9]{32}$")
_KEY_PATTERNS = {
    "env": {
        "theme": re.compile(r"^(\s*XCURSOR_THEME\s*=\s*)([^\r\n]*)(\s*)$", re.MULTILINE),
        "size": re.compile(r"^(\s*XCURSOR_SIZE\s*=\s*)([^\r\n]*)(\s*)$", re.MULTILINE),
    },
    "hypr": {
        "theme": re.compile(r'^(\s*hl\.env\(\s*"XCURSOR_THEME"\s*,\s*")([^"\r\n]*)("\s*\)\s*)$', re.MULTILINE),
        "size": re.compile(r'^(\s*hl\.env\(\s*"XCURSOR_SIZE"\s*,\s*")([^"\r\n]*)("\s*\)\s*)$', re.MULTILINE),
    },
    "gtk": {
        "theme": re.compile(r"^(\s*gtk-cursor-theme-name\s*=\s*)([^\r\n]*)(\s*)$", re.MULTILINE),
        "size": re.compile(r"^(\s*gtk-cursor-theme-size\s*=\s*)([^\r\n]*)(\s*)$", re.MULTILINE),
    },
}


class CursorAdapterError(Exception):
    """A cursor operation could not be completed safely."""


@dataclass(frozen=True)
class CursorPaths:
    env: Path
    hypr_env: Path
    gtk3: Path
    gtk4: Path


def _target_specs(paths: CursorPaths):
    return (
        ("env", paths.env, _KEY_PATTERNS["env"]),
        ("hypr", paths.hypr_env, _KEY_PATTERNS["hypr"]),
        ("gtk3", paths.gtk3, _KEY_PATTERNS["gtk"]),
        ("gtk4", paths.gtk4, _KEY_PATTERNS["gtk"]),
    )


def _read_regular(path: Path) -> tuple[str, os.stat_result, dict[str, bytes]]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise CursorAdapterError("A cursor settings target is not a regular file.")
        text = path.read_text(encoding="utf-8")
        attrs = {}
        try:
            for name in os.listxattr(path, follow_symlinks=False):
                attrs[name] = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            if exc.errno not in (errno.ENOTSUP, errno.EOPNOTSUPP):
                raise
        return text, info, attrs
    except CursorAdapterError:
        raise
    except (OSError, UnicodeError) as exc:
        raise CursorAdapterError("A cursor settings target could not be read safely.") from exc


def _one_value(text: str, pattern: re.Pattern, label: str) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise CursorAdapterError(f"Expected exactly one {label} setting in every cursor target.")
    return matches[0].group(2).strip()


def _parse_size(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise CursorAdapterError("The saved cursor size is not a valid integer.")
    size = int(value)
    if not MIN_CURSOR_SIZE <= size <= MAX_CURSOR_SIZE:
        raise CursorAdapterError("The saved cursor size is outside the supported range.")
    return size


def read_cursor_state(paths: CursorPaths) -> dict:
    """Read the canonical state after confirming every persisted mirror agrees."""
    observed = []
    for kind, path, patterns in _target_specs(paths):
        text, _, _ = _read_regular(path)
        observed.append(
            {
                "theme": _one_value(text, patterns["theme"], "cursor theme"),
                "size": _parse_size(_one_value(text, patterns["size"], "cursor size")),
            }
        )
    canonical = observed[0]
    if not _THEME_NAME.fullmatch(canonical["theme"]):
        raise CursorAdapterError("The saved cursor theme name is invalid.")
    if any(item != canonical for item in observed[1:]):
        raise CursorAdapterError("Cursor settings differ between the canonical file and its mirrors.")
    return dict(canonical)


def cursor_mirror_diagnostic(
    paths: CursorPaths,
    search_paths: Sequence[Path] | None = None,
) -> dict:
    """Return conflict metadata without exposing saved cursor values."""
    observed = {}
    try:
        for kind, path, patterns in _target_specs(paths):
            text, _, _ = _read_regular(path)
            theme = _one_value(text, patterns["theme"], "cursor theme")
            size = _parse_size(_one_value(text, patterns["size"], "cursor size"))
            observed[kind] = {"theme": theme, "size": size}
    except CursorAdapterError:
        return {
            "canonicalPairConsistent": False,
            "mirrorsMatch": False,
            "reconciliationAvailable": False,
            "conflictingMirrorCount": 0,
        }

    canonical = observed["env"]
    canonical_pair_consistent = canonical == observed["hypr"]
    source_valid = canonical_pair_consistent and bool(_THEME_NAME.fullmatch(canonical["theme"]))
    if source_valid:
        try:
            _validated_theme(canonical["theme"], search_paths)
        except CursorAdapterError:
            source_valid = False
    mirror_states = (observed["gtk3"], observed["gtk4"])
    conflicting_mirrors = sum(state != canonical for state in mirror_states)
    return {
        "canonicalPairConsistent": canonical_pair_consistent,
        "mirrorsMatch": canonical_pair_consistent and conflicting_mirrors == 0,
        "reconciliationAvailable": source_valid,
        "conflictingMirrorCount": conflicting_mirrors if canonical_pair_consistent else 0,
    }


def reconcile_cursor_mirrors(
    paths: CursorPaths,
    state_root: Path,
    *,
    source: str,
    dry_run: bool = False,
    search_paths: Sequence[Path] | None = None,
) -> dict:
    """Repair only GTK mirrors from the explicitly selected canonical pair."""
    if source != "environment.d+hyprland":
        raise CursorAdapterError("Choose the supported environment.d + Hyprland source group.")

    env_text, env_info, env_attrs = _read_regular(paths.env)
    env_snapshot = {
        "kind": "env",
        "path": paths.env,
        "bytes": env_text.encode("utf-8"),
        "stat": env_info,
        "xattrs": env_attrs,
    }
    env_state = {
        "theme": _one_value(env_text, _KEY_PATTERNS["env"]["theme"], "cursor theme"),
        "size": _parse_size(_one_value(env_text, _KEY_PATTERNS["env"]["size"], "cursor size")),
    }
    hypr_text, hypr_info, hypr_attrs = _read_regular(paths.hypr_env)
    hypr_snapshot = {
        "kind": "hypr",
        "path": paths.hypr_env,
        "bytes": hypr_text.encode("utf-8"),
        "stat": hypr_info,
        "xattrs": hypr_attrs,
    }
    hypr_state = {
        "theme": _one_value(hypr_text, _KEY_PATTERNS["hypr"]["theme"], "cursor theme"),
        "size": _parse_size(_one_value(hypr_text, _KEY_PATTERNS["hypr"]["size"], "cursor size")),
    }
    if env_state != hypr_state:
        raise CursorAdapterError("The selected environment.d + Hyprland source group is internally inconsistent.")
    _validated_theme(env_state["theme"], search_paths)

    snapshots = []
    for kind, path, patterns in _target_specs(paths)[2:]:
        text, info, attrs = _read_regular(path)
        updated = _replace_value(text, patterns["theme"], env_state["theme"], "cursor theme")
        updated = _replace_value(updated, patterns["size"], str(env_state["size"]), "cursor size")
        encoded = updated.encode("utf-8")
        original = text.encode("utf-8")
        if encoded != original:
            snapshots.append({
                "kind": kind,
                "path": path,
                "text": text,
                "bytes": original,
                "updated": encoded,
                "stat": info,
                "xattrs": attrs,
            })

    if not snapshots:
        return {
            "status": "no_changes",
            "changedMirrorCount": 0,
            "source": "environment.d+Hyprland",
            "runtimeVerified": False,
        }
    if dry_run:
        return {
            "status": "dry_run",
            "changedMirrorCount": len(snapshots),
            "source": "environment.d+Hyprland",
            "runtimeVerified": False,
        }

    transaction_id = uuid.uuid4().hex
    transaction_dir = Path(state_root) / "cursor-undo" / transaction_id
    _ensure_private_dir(transaction_dir.parent)
    _ensure_private_dir(transaction_dir)
    metadata = []
    changed = []
    try:
        for index, snapshot in enumerate(snapshots):
            snapshot_name = f"{index}.before"
            snapshot_path = transaction_dir / snapshot_name
            snapshot_path.write_bytes(snapshot["bytes"])
            os.chmod(snapshot_path, 0o600)
            metadata.append({
                "kind": snapshot["kind"],
                "path": str(snapshot["path"]),
                "snapshot": snapshot_name,
                "beforeSha256": _file_hash(snapshot["bytes"]),
                "afterSha256": _file_hash(snapshot["updated"]),
                "mode": stat.S_IMODE(snapshot["stat"].st_mode),
                "uid": snapshot["stat"].st_uid,
                "gid": snapshot["stat"].st_gid,
                "xattrs": {key: value.hex() for key, value in snapshot["xattrs"].items()},
            })
        transaction = {
            "schema": "nexus-cursor-undo-v1",
            "transactionId": transaction_id,
            "action": "mirror-reconciliation",
            "source": "environment.d+Hyprland",
            "before": dict(env_state),
            "after": dict(env_state),
            "files": metadata,
            "undone": False,
        }
        for snapshot in snapshots:
            _assert_snapshot_unchanged(env_snapshot)
            _assert_snapshot_unchanged(hypr_snapshot)
            _assert_snapshot_unchanged(snapshot)
            for applied in changed:
                _assert_applied_unchanged(applied)
            changed.append(snapshot)
            _atomic_replace(snapshot["path"], snapshot["updated"], snapshot["stat"], snapshot["xattrs"])
        _assert_snapshot_unchanged(env_snapshot)
        _assert_snapshot_unchanged(hypr_snapshot)
        for applied in changed:
            _assert_applied_unchanged(applied)
        _atomic_json(transaction_dir / "transaction.json", transaction)
    except Exception as exc:
        rollback_errors = _rollback_snapshots(changed)
        if not rollback_errors:
            shutil.rmtree(transaction_dir, ignore_errors=True)
        detail = "Cursor mirrors were restored after the failed write." if not rollback_errors else "Cursor mirror rollback was incomplete; manual recovery is required."
        raise CursorAdapterError(detail) from exc
    return {
        "status": "written_to_config",
        "transactionId": transaction_id,
        "changedMirrorCount": len(snapshots),
        "source": "environment.d+Hyprland",
        "runtimeVerified": False,
    }


def discover_themes(search_paths: Sequence[Path]) -> list[str]:
    """Return installed cursor theme names that contain metadata and assets."""
    found = set()
    for base in search_paths:
        try:
            children = list(Path(base).iterdir())
        except OSError:
            continue
        for candidate in children:
            name = candidate.name
            if not _THEME_NAME.fullmatch(name) or not candidate.is_dir():
                continue
            metadata = candidate / "index.theme"
            cursor_dir = candidate / "cursors"
            if not metadata.is_file() or not cursor_dir.is_dir():
                continue
            try:
                metadata_text = metadata.read_text(encoding="utf-8")
                has_theme_section = re.search(r"^\[Icon Theme\]\s*$", metadata_text, re.MULTILINE)
                has_name = re.search(r"^Name\s*=\s*.+$", metadata_text, re.MULTILINE)
                has_assets = any(item.is_file() for item in cursor_dir.iterdir())
            except (OSError, UnicodeError):
                continue
            if has_theme_section and has_name and has_assets:
                found.add(name)
    return sorted(found, key=str.casefold)


def _validated_theme(theme: str, search_paths: Sequence[Path] | None) -> str:
    if not isinstance(theme, str) or not _THEME_NAME.fullmatch(theme):
        raise CursorAdapterError("The cursor theme name is invalid.")
    paths = search_paths or _default_search_paths()
    if theme not in discover_themes(paths):
        raise CursorAdapterError("The selected cursor theme is not installed or is incomplete.")
    return theme


def _default_search_paths() -> list[Path]:
    home = Path.home()
    return [home / ".local/share/icons", home / ".icons", Path("/usr/share/icons"), Path("/usr/share/pixmaps")]


def _replace_value(text: str, pattern: re.Pattern, value: str, label: str) -> str:
    if len(list(pattern.finditer(text))) != 1:
        raise CursorAdapterError(f"Expected exactly one {label} setting before update.")
    return pattern.sub(lambda match: match.group(1) + value + match.group(3), text, count=1)


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_snapshot_unchanged(snapshot: dict) -> None:
    """Stop before replacing a target edited after it was snapshotted."""
    text, info, attrs = _read_regular(snapshot["path"])
    original_info = snapshot["stat"]
    unchanged_metadata = (
        info.st_dev == original_info.st_dev
        and info.st_ino == original_info.st_ino
        and info.st_mode == original_info.st_mode
        and info.st_uid == original_info.st_uid
        and info.st_gid == original_info.st_gid
        and info.st_mtime_ns == original_info.st_mtime_ns
    )
    if text.encode("utf-8") != snapshot["bytes"] or not unchanged_metadata or attrs != snapshot["xattrs"]:
        raise CursorAdapterError("Cursor settings changed during this operation; the newer edit was kept.")


def _assert_applied_unchanged(snapshot: dict) -> None:
    """Detect external edits to an already replaced target before continuing."""
    text, info, attrs = _read_regular(snapshot["path"])
    original_info = snapshot["stat"]
    unchanged_metadata = (
        info.st_mode == original_info.st_mode
        and info.st_uid == original_info.st_uid
        and info.st_gid == original_info.st_gid
    )
    if text.encode("utf-8") != snapshot["updated"] or not unchanged_metadata or attrs != snapshot["xattrs"]:
        raise CursorAdapterError("Cursor settings changed during this operation; the newer edit was kept.")


def _rollback_snapshots(changed: list[dict]) -> list[str]:
    errors = []
    for snapshot in reversed(changed):
        try:
            text, current_info, current_attrs = _read_regular(snapshot["path"])
            current_bytes = text.encode("utf-8")
            original_info = snapshot["stat"]
            current_is_original = (
                current_bytes == snapshot["bytes"]
                and current_info.st_mode == original_info.st_mode
                and current_info.st_uid == original_info.st_uid
                and current_info.st_gid == original_info.st_gid
                and current_attrs == snapshot["xattrs"]
            )
            if current_is_original:
                continue
            current_is_ours = (
                current_bytes == snapshot["updated"]
                and current_info.st_mode == original_info.st_mode
                and current_info.st_uid == original_info.st_uid
                and current_info.st_gid == original_info.st_gid
                and current_attrs == snapshot["xattrs"]
            )
            if not current_is_ours:
                errors.append(snapshot["kind"])
                continue
            _atomic_replace(snapshot["path"], snapshot["bytes"], original_info, snapshot["xattrs"])
        except Exception:
            errors.append(snapshot["kind"])
    return errors


def _private_undo_directory(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(info.st_mode) and not (stat.S_IMODE(info.st_mode) & 0o077)


def _read_undo_snapshot(transaction_dir: Path, name: object, index: int) -> bytes:
    expected = f"{index}.before"
    if (
        name != expected
        or not _private_undo_directory(transaction_dir.parent)
        or not _private_undo_directory(transaction_dir)
    ):
        raise CursorAdapterError("The cursor undo snapshot path is invalid.")
    path = transaction_dir / expected
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise CursorAdapterError("The cursor undo snapshot is not a private regular file.")
        return path.read_bytes()
    except CursorAdapterError:
        raise
    except OSError as exc:
        raise CursorAdapterError("The cursor undo snapshot is unavailable.") from exc


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _set_xattrs(source_attrs: dict[str, bytes], path: Path) -> None:
    try:
        current = {
            name: os.getxattr(path, name, follow_symlinks=False)
            for name in os.listxattr(path, follow_symlinks=False)
        }
    except OSError as exc:
        if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP) and not source_attrs:
            return
        raise CursorAdapterError("Extended file attributes could not be preserved.") from exc
    for name in current.keys() - source_attrs.keys():
        # The temporary file inherits its SELinux label from the parent. Do
        # not try to remove a system label that the unprivileged user cannot
        # set or clear.
        if name == "security.selinux":
            continue
        try:
            os.removexattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise CursorAdapterError("An extended file attribute could not be removed safely.") from exc
    for name, value in source_attrs.items():
        if current.get(name) == value:
            continue
        try:
            os.setxattr(path, name, value, follow_symlinks=False)
        except OSError as exc:
            raise CursorAdapterError("An extended file attribute could not be preserved.") from exc


def _atomic_replace(path: Path, data: bytes, info: os.stat_result, attrs: dict[str, bytes]) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.nexus-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, info.st_uid, info.st_gid)
        os.chmod(temporary, stat.S_IMODE(info.st_mode))
        _set_xattrs(attrs, temporary)
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, payload: dict) -> None:
    _ensure_private_dir(path.parent)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _read_targets(paths: CursorPaths):
    state = read_cursor_state(paths)
    snapshots = []
    rendered = []
    for kind, path, patterns in _target_specs(paths):
        text, info, attrs = _read_regular(path)
        changed = _replace_value(text, patterns["theme"], state["theme"], "cursor theme")
        changed = _replace_value(changed, patterns["size"], str(state["size"]), "cursor size")
        snapshots.append({"kind": kind, "path": path, "text": text, "bytes": text.encode("utf-8"), "stat": info, "xattrs": attrs})
        rendered.append(changed)
    return state, snapshots, rendered


def apply_cursor_state(
    paths: CursorPaths,
    state_root: Path,
    theme: str,
    size: int,
    dry_run: bool = False,
    search_paths: Sequence[Path] | None = None,
) -> dict:
    """Persist a cursor preference across the canonical file and all mirrors."""
    selected_theme = _validated_theme(theme, search_paths)
    if isinstance(size, bool) or not isinstance(size, int) or not MIN_CURSOR_SIZE <= size <= MAX_CURSOR_SIZE:
        raise CursorAdapterError(f"Cursor size must be an integer from {MIN_CURSOR_SIZE} to {MAX_CURSOR_SIZE}.")
    current, snapshots, _ = _read_targets(paths)
    requested = {"theme": selected_theme, "size": size}
    if current == requested:
        return {"status": "no_changes", "runtimeVerified": False}
    if dry_run:
        return {"status": "dry_run", "changedCount": len(snapshots), "runtimeVerified": False}

    rendered = []
    for kind, path, patterns in _target_specs(paths):
        original = next(item["text"] for item in snapshots if item["kind"] == kind)
        updated = _replace_value(original, patterns["theme"], selected_theme, "cursor theme")
        updated = _replace_value(updated, patterns["size"], str(size), "cursor size")
        rendered.append(updated.encode("utf-8"))

    transaction_id = uuid.uuid4().hex
    undo_root = Path(state_root) / "cursor-undo"
    transaction_dir = undo_root / transaction_id
    changed_snapshots = []
    metadata = []
    try:
        _ensure_private_dir(undo_root)
        _ensure_private_dir(transaction_dir)
        for i, snapshot in enumerate(snapshots):
            name = f"{i}.before"
            snapshot["updated"] = rendered[i]
            stored = transaction_dir / name
            stored.write_bytes(snapshot["bytes"])
            os.chmod(stored, 0o600)
            metadata.append(
                {
                    "kind": snapshot["kind"],
                    "path": str(snapshot["path"]),
                    "snapshot": name,
                    "beforeSha256": _file_hash(snapshot["bytes"]),
                    "afterSha256": _file_hash(rendered[i]),
                    "mode": stat.S_IMODE(snapshot["stat"].st_mode),
                    "uid": snapshot["stat"].st_uid,
                    "gid": snapshot["stat"].st_gid,
                    "xattrs": {key: value.hex() for key, value in snapshot["xattrs"].items()},
                }
            )
        transaction = {
            "schema": "nexus-cursor-undo-v1",
            "transactionId": transaction_id,
            "before": current,
            "after": requested,
            "files": metadata,
            "undone": False,
        }
        for i, snapshot in enumerate(snapshots):
            _assert_snapshot_unchanged(snapshot)
            for applied in changed_snapshots:
                _assert_applied_unchanged(applied)
            changed_snapshots.append(snapshot)
            _atomic_replace(snapshot["path"], rendered[i], snapshot["stat"], snapshot["xattrs"])
        for applied in changed_snapshots:
            _assert_applied_unchanged(applied)
        _atomic_json(transaction_dir / "transaction.json", transaction)
    except Exception as exc:
        rollback_errors = _rollback_snapshots(changed_snapshots)
        if not rollback_errors:
            shutil.rmtree(transaction_dir, ignore_errors=True)
        detail = "Cursor files were restored after the failed write." if not rollback_errors else "Cursor rollback was incomplete; manual recovery is required."
        raise CursorAdapterError(detail) from exc
    return {"status": "written_to_config", "transactionId": transaction_id, "runtimeVerified": False}


def undo_cursor_state(paths: CursorPaths, state_root: Path, transaction_id: str) -> dict:
    """Undo a cursor transaction only if none of its target files changed later."""
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise CursorAdapterError("The cursor transaction identifier is invalid.")
    transaction_dir = Path(state_root) / "cursor-undo" / transaction_id
    if not _private_undo_directory(transaction_dir.parent) or not _private_undo_directory(transaction_dir):
        raise CursorAdapterError("The cursor undo transaction directory is invalid.")
    transaction_path = transaction_dir / "transaction.json"
    try:
        transaction_info = transaction_path.lstat()
        if not stat.S_ISREG(transaction_info.st_mode) or stat.S_IMODE(transaction_info.st_mode) & 0o077:
            raise CursorAdapterError("The cursor undo transaction record is not a private regular file.")
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
    except CursorAdapterError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CursorAdapterError("The cursor undo record is unavailable or invalid.") from exc
    if transaction.get("schema") != "nexus-cursor-undo-v1" or transaction.get("undone"):
        raise CursorAdapterError("The cursor transaction is not available for undo.")

    targets = {str(p): p for _, p, _ in _target_specs(paths)}
    files = transaction.get("files")
    if not isinstance(files, list) or not files:
        raise CursorAdapterError("The cursor undo record is incomplete.")
    recorded_targets = [row.get("path") if isinstance(row, dict) else None for row in files]
    if len(set(recorded_targets)) != len(recorded_targets):
        raise CursorAdapterError("The cursor undo record contains duplicate targets.")
    if transaction.get("action") == "mirror-reconciliation":
        if transaction.get("source") != "environment.d+Hyprland" or not set(recorded_targets).issubset({str(paths.gtk3), str(paths.gtk4)}) or len(files) > 2:
            raise CursorAdapterError("The cursor reconciliation undo record contains an unexpected target.")
    elif set(recorded_targets) != set(targets) or len(files) != len(targets):
        raise CursorAdapterError("The cursor undo record is incomplete or contains an unexpected target.")
    prepared = []
    for index, row in enumerate(files):
        path = Path(row.get("path", ""))
        if str(path) not in targets:
            raise CursorAdapterError("The cursor undo record contains an unexpected target.")
        current, info, attrs = _read_regular(path)
        current_bytes = current.encode("utf-8")
        if _file_hash(current_bytes) != row.get("afterSha256"):
            raise CursorAdapterError("Cursor settings changed after this NEXUS action; undo was stopped.")
        before = _read_undo_snapshot(transaction_dir, row.get("snapshot"), index)
        if _file_hash(before) != row.get("beforeSha256"):
            raise CursorAdapterError("The cursor undo snapshot failed its integrity check.")
        original_attrs = {key: bytes.fromhex(value) for key, value in row.get("xattrs", {}).items()}
        prepared.append((path, before, info, attrs, current_bytes, original_attrs))

    restored = []
    try:
        for item in prepared:
            path, before, info, _, current_bytes, original_attrs = item
            _atomic_replace(path, before, info, original_attrs)
            restored.append(item)
        transaction["undone"] = True
        _atomic_json(transaction_dir / "transaction.json", transaction)
    except Exception as exc:
        rollback_errors = []
        for path, _, info, current_attrs, current_bytes, _ in reversed(restored):
            try:
                _atomic_replace(path, current_bytes, info, current_attrs)
            except Exception:
                rollback_errors.append(str(path))
        detail = "Cursor undo was rolled back." if not rollback_errors else "Cursor undo rollback was incomplete; manual recovery is required."
        raise CursorAdapterError(detail) from exc
    return {"status": "undo_written_to_config", "transactionId": transaction_id, "runtimeVerified": False}
