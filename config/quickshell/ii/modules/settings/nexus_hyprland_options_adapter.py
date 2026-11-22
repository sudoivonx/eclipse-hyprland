"""Transactional NEXUS adapter for three verified Hyprland window options."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid


INT_MIN = -(2 ** 31)
INT_MAX = (2 ** 31) - 1

OPTION_SPECS = {
    "hyprland.general.gaps_in": {
        "option": "general:gaps_in",
        "lua_key": "gaps_in",
        "minimum": INT_MIN,
        "maximum": INT_MAX,
    },
    "hyprland.general.gaps_out": {
        "option": "general:gaps_out",
        "lua_key": "gaps_out",
        "minimum": INT_MIN,
        "maximum": INT_MAX,
    },
    "hyprland.decoration.rounding": {
        "option": "decoration:rounding",
        "lua_key": "rounding",
        "minimum": 0,
        "maximum": 100,
    },
}

_ASSIGNMENT = re.compile(
    r"^(?P<prefix>[ \t]*(?P<key>gaps_in|gaps_out|rounding)[ \t]*=[ \t]*)"
    r"(?P<value>-?[0-9]+)(?P<suffix>[ \t]*,?[ \t]*(?:--[^\r\n]*)?)$"
)
_ASSIGNMENT_START = re.compile(
    r"^[ \t]*(?:gaps_in|gaps_out|rounding|\[[ \t]*[\"'](?:gaps_in|gaps_out|rounding)[\"'][ \t]*\])[ \t]*="
)
_CSS_NUMBER = re.compile(r"[ \t,]+")


class HyprlandOptionsError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HyprlandOptionsPaths:
    source: Path
    hyprctl: str = "hyprctl"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def option_metadata() -> dict[str, dict[str, int]]:
    return {
        setting_id: {"minimum": spec["minimum"], "maximum": spec["maximum"]}
        for setting_id, spec in OPTION_SPECS.items()
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix=".nexus-options-", dir=path.parent)
    temp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise HyprlandOptionsError("unsafe_state_directory", "The Hyprland recovery directory is not owned by this user.")


def _read_regular_source(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        if path.is_symlink():
            raise HyprlandOptionsError("source_unsupported", "The Hyprland settings source is a symbolic link; NEXUS stopped safely.")
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            raise HyprlandOptionsError("source_unsupported", "The Hyprland settings source is not a regular file owned by this user.")
        raw = path.read_bytes()
    except HyprlandOptionsError:
        raise
    except OSError as exc:
        raise HyprlandOptionsError("source_unavailable", "The Hyprland settings source could not be read.") from exc
    return raw, st


def _validate_value(setting_id: str, value: object) -> int:
    spec = OPTION_SPECS.get(setting_id)
    if spec is None:
        raise HyprlandOptionsError("setting_unsupported", "This Hyprland setting is not supported by the safe adapter.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise HyprlandOptionsError("value_invalid", "Hyprland window settings must be whole numbers.")
    if value < spec["minimum"] or value > spec["maximum"]:
        if setting_id.endswith("rounding"):
            raise HyprlandOptionsError("value_out_of_range", "Corner rounding must be between 0 and 100.")
        raise HyprlandOptionsError("value_out_of_range", "The gap value is outside Hyprland's supported integer range.")
    return value


def _parse_source(raw: bytes) -> dict[str, int]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HyprlandOptionsError("source_unsupported", "The Hyprland settings source is not valid UTF-8.") from exc

    found: dict[str, list[tuple[int, int, int]]] = {spec["lua_key"]: [] for spec in OPTION_SPECS.values()}
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith("\n") else line
        if _ASSIGNMENT_START.match(body):
            match = _ASSIGNMENT.fullmatch(body)
            if not match:
                raise HyprlandOptionsError(
                    "source_conflict",
                    "NEXUS only manages a single literal integer assignment for each target option.",
                )
            key = match.group("key")
            found[key].append((offset, offset + len(match.group("prefix")), int(match.group("value"))))
        offset += len(line)

    values: dict[str, int] = {}
    for setting_id, spec in OPTION_SPECS.items():
        matches = found[spec["lua_key"]]
        if len(matches) != 1:
            raise HyprlandOptionsError(
                "source_conflict",
                "NEXUS requires exactly one literal integer assignment for each managed option in the target Lua file.",
            )
        value = _validate_value(setting_id, matches[0][2])
        values[setting_id] = value
    return values


def _replace_source_values(raw: bytes, values: dict[str, int]) -> bytes:
    _parse_source(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HyprlandOptionsError("source_unsupported", "The Hyprland settings source is not valid UTF-8.") from exc
    replacements = {OPTION_SPECS[key]["lua_key"]: _validate_value(key, value) for key, value in values.items()}
    output: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines(keepends=True):
        body = line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith("\n") else line
        match = _ASSIGNMENT.fullmatch(body)
        if match and match.group("key") in replacements:
            key = match.group("key")
            output.append(match.group("prefix") + str(replacements[key]) + match.group("suffix") + ("\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""))
            seen.add(key)
        else:
            output.append(line)
    if seen != set(replacements):
        raise HyprlandOptionsError("source_conflict", "A managed Lua assignment changed while the update was prepared.")
    return "".join(output).encode("utf-8")


def _run_hyprctl(paths: HyprlandOptionsPaths, args: list[str], timeout: float = 5.0) -> str:
    try:
        result = subprocess.run([paths.hyprctl, *args], capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HyprlandOptionsError("hyprland_unavailable", "Hyprland could not be reached from this settings process.") from exc
    if result.returncode != 0:
        raise HyprlandOptionsError("hyprland_unavailable", "Hyprland did not accept the settings request.")
    return result.stdout.strip()


def _parse_css_uniform(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    parts: list[int] | None = None
    if isinstance(value, str):
        pieces = [part for part in _CSS_NUMBER.split(value.strip()) if part]
        if pieces and all(re.fullmatch(r"-?[0-9]+", part) for part in pieces):
            parts = [int(part) for part in pieces]
    elif isinstance(value, (list, tuple)):
        if value and all(isinstance(part, int) and not isinstance(part, bool) for part in value):
            parts = list(value)
    elif isinstance(value, dict):
        allowed = {"top", "right", "bottom", "left"}
        if value and set(value).issubset(allowed) and all(isinstance(part, int) and not isinstance(part, bool) for part in value.values()):
            parts = list(value.values())
    if parts and len(parts) in (1, 2, 3, 4) and len(set(parts)) == 1:
        return parts[0]
    raise HyprlandOptionsError(
        "asymmetric_gaps_unsupported",
        "The current gap layout is not a uniform integer. NEXUS left it unchanged.",
    )


def _read_live_value(paths: HyprlandOptionsPaths, setting_id: str) -> int:
    spec = OPTION_SPECS[setting_id]
    raw = _run_hyprctl(paths, ["-j", "getoption", spec["option"]])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HyprlandOptionsError("hyprland_response_invalid", "Hyprland returned an unreadable setting response.") from exc
    if not isinstance(data, dict) or data.get("set") is not True:
        raise HyprlandOptionsError("hyprland_option_unset", "Hyprland has not confirmed this option as set.")
    if setting_id.endswith("rounding"):
        value = data.get("int")
        if isinstance(value, bool) or not isinstance(value, int):
            raise HyprlandOptionsError("hyprland_response_invalid", "Hyprland returned an unsupported rounding value.")
    else:
        value = _parse_css_uniform(data.get("css", data.get("int")))
    return _validate_value(setting_id, value)


def _read_live(paths: HyprlandOptionsPaths) -> dict[str, int]:
    return {setting_id: _read_live_value(paths, setting_id) for setting_id in OPTION_SPECS}


def read_options(paths: HyprlandOptionsPaths) -> dict[str, int]:
    raw, _ = _read_regular_source(paths.source)
    source_values = _parse_source(raw)
    live_values = _read_live(paths)
    if source_values != live_values:
        raise HyprlandOptionsError("source_runtime_conflict", "Hyprland's live values differ from the persistent source; NEXUS stopped to protect external edits.")
    return source_values


def _eval_values(paths: HyprlandOptionsPaths, values: dict[str, int]) -> None:
    assignments = ", ".join(
        f'[{json.dumps(OPTION_SPECS[key]["option"].replace(":", "."))}] = {_validate_value(key, value)}'
        for key, value in values.items()
    )
    expression = f"hl.config({{ {assignments} }})"
    _run_hyprctl(paths, ["eval", expression])


def _live_matches(paths: HyprlandOptionsPaths, expected: dict[str, int], timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            actual = _read_live(paths)
            if all(actual[key] == value for key, value in expected.items()):
                return True
        except HyprlandOptionsError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def _xattrs(path: Path) -> dict[str, bytes]:
    try:
        names = os.listxattr(path, follow_symlinks=False)
        return {name: os.getxattr(path, name, follow_symlinks=False) for name in names}
    except (AttributeError, OSError) as exc:
        raise HyprlandOptionsError("metadata_read_failed", "File metadata could not be preserved safely.") from exc


def _atomic_source_replace(path: Path, before_hash: str, replacement: bytes) -> str:
    current, st = _read_regular_source(path)
    if sha256_bytes(current) != before_hash:
        raise HyprlandOptionsError("source_changed", "The Hyprland settings file changed during the update; no newer edit was overwritten.")
    attrs = _xattrs(path)
    fd, name = tempfile.mkstemp(prefix=".nexus-hyprland-options-", dir=path.parent)
    temp = Path(name)
    try:
        try:
            os.fchown(fd, st.st_uid, st.st_gid)
        except OSError as exc:
            raise HyprlandOptionsError("metadata_write_failed", "The original file owner could not be preserved.") from exc
        os.fchmod(fd, stat.S_IMODE(st.st_mode))
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        # Restore ACLs after chmod, since chmod can update the ACL mask.
        for attr, value in attrs.items():
            try:
                os.setxattr(temp, attr, value, follow_symlinks=False)
            except OSError as exc:
                raise HyprlandOptionsError("metadata_write_failed", "The original ACL or extended attributes could not be preserved.") from exc
        metadata_fd = os.open(temp, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.fsync(metadata_fd)
        finally:
            os.close(metadata_fd)
        latest, _ = _read_regular_source(path)
        if sha256_bytes(latest) != before_hash:
            raise HyprlandOptionsError("source_changed", "The Hyprland settings file changed during the update; no newer edit was overwritten.")
        os.replace(temp, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return sha256_bytes(replacement)


def _transaction_dir(state: Path, transaction_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", transaction_id):
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery ID is invalid.")
    return state / "hyprland-options-undo" / transaction_id


def validate_apply(paths: HyprlandOptionsPaths, desired: dict[str, int]) -> dict:
    if not isinstance(desired, dict) or not desired or not set(desired).issubset(OPTION_SPECS):
        raise HyprlandOptionsError("setting_unsupported", "Choose one or more supported Hyprland window settings.")
    normalized = {key: _validate_value(key, value) for key, value in desired.items()}
    before, _ = _read_regular_source(paths.source)
    source_values = _parse_source(before)
    live_values = _read_live(paths)
    if source_values != live_values:
        raise HyprlandOptionsError("source_runtime_conflict", "Hyprland's live values differ from the persistent source; NEXUS stopped to protect external edits.")
    changed = {key: value for key, value in normalized.items() if live_values[key] != value}
    return {"changed": changed, "beforeValues": live_values, "sourceSha256": sha256_bytes(before)}


def apply_options(paths: HyprlandOptionsPaths, state: Path, desired: dict[str, int], dry_run: bool = False) -> dict:
    plan = validate_apply(paths, desired)
    changed = plan["changed"]
    if not changed:
        return {"status": "unchanged", "changedCount": 0, "runtimeVerified": True}
    if dry_run:
        return {"status": "dry_run", "changedCount": len(changed), "runtimeVerified": False}

    before_raw, _ = _read_regular_source(paths.source)
    before_values = plan["beforeValues"]
    before_hash = plan["sourceSha256"]
    after_raw = _replace_source_values(before_raw, changed)
    after_hash = sha256_bytes(after_raw)
    transaction_id = uuid.uuid4().hex
    _ensure_private_dir(state)
    folder = _transaction_dir(state, transaction_id)
    _ensure_private_dir(folder.parent)
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    snapshot = folder / "before.lua"
    fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(before_raw)
        stream.flush()
        os.fsync(stream.fileno())
    transaction = {
        "schema": "nexus-hyprland-options-undo-v1",
        "id": transaction_id,
        "sourcePath": str(paths.source),
        "snapshot": snapshot.name,
        "beforeSha256": before_hash,
        "afterSha256": after_hash,
        "beforeValues": before_values,
        "afterValues": {**before_values, **changed},
        "status": "pending",
        "undone": False,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    manifest = folder / "transaction.json"
    _atomic_json(manifest, transaction)

    disk_changed = False
    failure: HyprlandOptionsError | None = None
    try:
        _eval_values(paths, changed)
        if not _live_matches(paths, changed):
            raise HyprlandOptionsError("runtime_apply_failed", "Hyprland did not confirm the requested live value.")
        _atomic_source_replace(paths.source, before_hash, after_raw)
        disk_changed = True
        if not _live_matches(paths, transaction["afterValues"]):
            raise HyprlandOptionsError("runtime_verify_failed", "The saved value did not become the verified live Hyprland value.")
        transaction["status"] = "complete"
        transaction["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _atomic_json(manifest, transaction)
        return {"status": "applied", "changedCount": len(changed), "transactionId": transaction_id, "runtimeVerified": True}
    except HyprlandOptionsError as exc:
        failure = exc
    except OSError as exc:
        failure = HyprlandOptionsError("source_write_failed", "The Hyprland settings update could not be saved.")
        failure.__cause__ = exc

    rollback_errors: list[str] = []
    current_is_applied = False
    try:
        current_after_failure, _ = _read_regular_source(paths.source)
        current_is_applied = sha256_bytes(current_after_failure) == after_hash
    except Exception:
        pass
    if disk_changed or current_is_applied:
        try:
            _atomic_source_replace(paths.source, after_hash, before_raw)
        except Exception:
            rollback_errors.append("source")
    try:
        _eval_values(paths, before_values)
        if not _live_matches(paths, before_values):
            rollback_errors.append("runtime")
    except Exception:
        rollback_errors.append("runtime")
    transaction["status"] = "rollback_failed" if rollback_errors else "rolled_back"
    transaction["rollbackErrors"] = rollback_errors
    try:
        _atomic_json(manifest, transaction)
    except Exception:
        rollback_errors.append("journal")
    if rollback_errors:
        raise HyprlandOptionsError("rollback_incomplete", "The update failed and safe rollback could not be fully verified; manual recovery is required.") from failure
    raise failure or HyprlandOptionsError("operation_failed", "The Hyprland settings update failed and was rolled back.")


def undo_options(paths: HyprlandOptionsPaths, state: Path, transaction_id: str, dry_run: bool = False) -> dict:
    folder = _transaction_dir(state, transaction_id)
    manifest = folder / "transaction.json"
    try:
        transaction = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery information is unavailable.") from exc
    if not isinstance(transaction, dict):
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery information is invalid.")
    if transaction.get("schema") != "nexus-hyprland-options-undo-v1" or transaction.get("status") != "complete" or transaction.get("undone"):
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery information is invalid or already used.")
    if transaction.get("sourcePath") != str(paths.source):
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery information targets a different settings file.")
    if transaction.get("snapshot") != "before.lua":
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland recovery information is invalid.")
    snapshot = folder / "before.lua"
    try:
        before_raw = snapshot.read_bytes()
        current_raw, _ = _read_regular_source(paths.source)
    except OSError as exc:
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland source snapshot is unavailable.") from exc
    if sha256_bytes(before_raw) != transaction.get("beforeSha256") or sha256_bytes(current_raw) != transaction.get("afterSha256"):
        raise HyprlandOptionsError("undo_conflict", "The Hyprland settings file changed after this NEXUS action; Undo stopped to protect newer edits.")
    before_values = transaction.get("beforeValues")
    after_values = transaction.get("afterValues")
    if not isinstance(before_values, dict) or not isinstance(after_values, dict):
        raise HyprlandOptionsError("undo_invalid", "The saved Hyprland value snapshot is invalid.")
    before_values = {key: _validate_value(key, value) for key, value in before_values.items()}
    after_values = {key: _validate_value(key, value) for key, value in after_values.items()}
    live_values = _read_live(paths)
    if live_values != after_values:
        raise HyprlandOptionsError("undo_conflict", "Hyprland's live values changed after this NEXUS action; Undo stopped to protect newer settings.")
    if dry_run:
        return {"status": "dry_run", "runtimeVerified": False}

    try:
        _atomic_source_replace(paths.source, transaction["afterSha256"], before_raw)
        _eval_values(paths, before_values)
        if not _live_matches(paths, before_values):
            raise HyprlandOptionsError("undo_verify_failed", "Hyprland did not confirm the restored values.")
    except Exception as exc:
        rollback_errors: list[str] = []
        try:
            latest, _ = _read_regular_source(paths.source)
            if sha256_bytes(latest) == transaction["beforeSha256"]:
                _atomic_source_replace(paths.source, transaction["beforeSha256"], current_raw)
            elif sha256_bytes(latest) != transaction["afterSha256"]:
                rollback_errors.append("source")
        except Exception:
            rollback_errors.append("source")
        try:
            _eval_values(paths, after_values)
            if not _live_matches(paths, after_values):
                rollback_errors.append("runtime")
        except Exception:
            rollback_errors.append("runtime")
        if rollback_errors:
            raise HyprlandOptionsError("undo_rollback_failed", "Undo failed and recovery could not be fully verified; manual recovery is required.") from exc
        if isinstance(exc, HyprlandOptionsError):
            raise exc
        raise HyprlandOptionsError("undo_failed", "The Hyprland settings could not be restored; the action remains available to retry.") from exc

    transaction["undone"] = True
    transaction["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_json(manifest, transaction)
    return {"status": "undone", "runtimeVerified": True}
