"""Guarded NEXUS adapter for the existing Aegis motion-profile helper."""
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
import sys
import tempfile
import uuid


MOTION_PROFILES = frozenset({"off", "light", "full"})
TRANSACTION_SCHEMA = "nexus-motion-profile-transaction-v1"
TRANSACTION_RE = re.compile(r"\d{8}T\d{6}-[a-f0-9]{8}")


class MotionProfileAdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MotionProfilePaths:
    helper: Path
    python: Path = Path(sys.executable)


def validate_motion_profile(value) -> str:
    if not isinstance(value, str) or value not in MOTION_PROFILES:
        raise MotionProfileAdapterError(
            "motion_profile_invalid", "The selected motion profile is not supported."
        )
    return value


def _require_helper(paths: MotionProfilePaths) -> Path:
    try:
        info = paths.helper.lstat()
    except OSError as exc:
        raise MotionProfileAdapterError(
            "motion_helper_unavailable", "The existing motion profile helper is unavailable."
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise MotionProfileAdapterError(
            "motion_helper_invalid", "The existing motion profile helper is not a regular file."
        )
    return paths.helper


def _helper_hash(paths: MotionProfilePaths) -> str:
    helper = _require_helper(paths)
    try:
        return hashlib.sha256(helper.read_bytes()).hexdigest()
    except OSError as exc:
        raise MotionProfileAdapterError(
            "motion_helper_unavailable", "The existing motion profile helper could not be read."
        ) from exc


def _invoke(paths: MotionProfilePaths, action: str, profile: str | None = None) -> str:
    helper = _require_helper(paths)
    command = [str(paths.python), str(helper), action]
    if profile is not None:
        command.append(validate_motion_profile(profile))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MotionProfileAdapterError(
            "motion_helper_timeout", "The motion profile action timed out."
        ) from exc
    except OSError as exc:
        raise MotionProfileAdapterError(
            "motion_helper_unavailable", "The motion profile action could not be started."
        ) from exc
    if result.returncode != 0:
        raise MotionProfileAdapterError(
            "motion_helper_failed", "The existing motion profile helper reported a failure."
        )
    return result.stdout


def read_motion_profile(paths: MotionProfilePaths) -> str:
    output = _invoke(paths, "get")
    try:
        payload = json.loads(output)
    except (TypeError, ValueError) as exc:
        raise MotionProfileAdapterError(
            "motion_status_invalid", "The motion profile helper returned invalid status data."
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"profile"}:
        raise MotionProfileAdapterError(
            "motion_status_invalid", "The motion profile helper returned unexpected status data."
        )
    return validate_motion_profile(payload["profile"])


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise OSError("not a directory")
        if info.st_uid != os.getuid():
            raise OSError("wrong owner")
        if info.st_mode & 0o077:
            os.chmod(path, 0o700)
    except OSError as exc:
        raise MotionProfileAdapterError(
            "motion_state_unavailable", "The private motion profile recovery folder is unavailable."
        ) from exc


def _atomic_json(path: Path, payload: dict) -> None:
    _private_directory(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=".nexus-motion-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _transaction_path(state_root: Path, transaction_id: str) -> Path:
    if not isinstance(transaction_id, str) or not TRANSACTION_RE.fullmatch(transaction_id):
        raise MotionProfileAdapterError(
            "motion_undo_invalid", "The saved motion profile recovery information is unavailable."
        )
    return state_root / "motion-profile-undo" / f"{transaction_id}.json"


def _load_transaction(state_root: Path, transaction_id: str) -> tuple[Path, dict]:
    path = _transaction_path(state_root, transaction_id)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OSError("unsafe transaction file")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MotionProfileAdapterError(
            "motion_undo_invalid", "The saved motion profile recovery information is unavailable."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != TRANSACTION_SCHEMA
        or payload.get("transactionId") != transaction_id
        or payload.get("status") != "complete"
    ):
        raise MotionProfileAdapterError(
            "motion_undo_invalid", "The saved motion profile recovery information is invalid."
        )
    try:
        validate_motion_profile(payload.get("beforeProfile"))
        validate_motion_profile(payload.get("afterProfile"))
    except MotionProfileAdapterError as exc:
        raise MotionProfileAdapterError(
            "motion_undo_invalid", "The saved motion profile recovery information is invalid."
        ) from exc
    return path, payload


def _apply_and_verify(paths: MotionProfilePaths, target: str) -> None:
    _invoke(paths, "apply", target)
    if read_motion_profile(paths) != target:
        raise MotionProfileAdapterError(
            "motion_profile_verify_failed", "The requested motion profile could not be verified."
        )


def apply_motion_profile(
    paths: MotionProfilePaths,
    state_root: Path,
    desired: str,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    desired = validate_motion_profile(desired)
    before = read_motion_profile(paths)
    if before == desired:
        return {"status": "no_changes", "changedCount": 0, "runtimeVerified": False}
    _helper_sha256 = _helper_hash(paths)
    if not dry_run and not confirm_risk:
        raise MotionProfileAdapterError(
            "risk_confirmation_required", "Changing the motion profile reloads Hyprland and requires confirmation."
        )
    if dry_run:
        return {"status": "dry_run", "changedCount": 1, "runtimeVerified": False}

    transaction_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S-") + uuid.uuid4().hex[:8]
    transaction = {
        "schema": TRANSACTION_SCHEMA,
        "transactionId": transaction_id,
        "status": "pending",
        "helperSha256": _helper_sha256,
        "beforeProfile": before,
        "afterProfile": desired,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    path = _transaction_path(state_root, transaction_id)
    _private_directory(state_root)
    _atomic_json(path, transaction)
    try:
        if _helper_hash(paths) != _helper_sha256:
            raise MotionProfileAdapterError(
                "motion_helper_changed", "The motion profile helper changed before the action could be applied."
            )
        _apply_and_verify(paths, desired)
        if _helper_hash(paths) != _helper_sha256:
            raise MotionProfileAdapterError(
                "motion_helper_changed", "The motion profile helper changed while the action was running."
            )
        transaction["status"] = "complete"
        _atomic_json(path, transaction)
    except Exception as exc:
        try:
            if _helper_hash(paths) != _helper_sha256:
                raise MotionProfileAdapterError(
                    "motion_helper_changed", "The motion profile helper changed; its previous state cannot be safely restored."
                )
            _apply_and_verify(paths, before)
            transaction["status"] = "rolled-back"
            _atomic_json(path, transaction)
        except Exception as rollback_exc:
            transaction["status"] = "rollback-failed"
            try:
                _atomic_json(path, transaction)
            except Exception:
                pass
            raise MotionProfileAdapterError(
                "motion_profile_rollback_failed",
                "The motion profile action failed and its saved state could not be restored.",
            ) from rollback_exc
        if isinstance(exc, MotionProfileAdapterError) and exc.code == "motion_profile_rollback_failed":
            raise exc
        raise MotionProfileAdapterError(
            "motion_profile_apply_failed", "The motion profile action failed; its previous state was restored."
        ) from exc
    return {
        "status": "written_to_config",
        "changedCount": 1,
        "transactionId": transaction_id,
        "runtimeVerified": False,
        "runtimeStatus": "hyprland-reload-and-config-error-check-passed; visual-motion-effect-unverified",
    }


def undo_motion_profile(
    paths: MotionProfilePaths,
    state_root: Path,
    transaction_id: str,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    path, transaction = _load_transaction(state_root, transaction_id)
    if _helper_hash(paths) != transaction.get("helperSha256"):
        raise MotionProfileAdapterError(
            "undo_conflict", "The motion profile helper changed after this NEXUS action, so undo was stopped."
        )
    before = transaction["beforeProfile"]
    after = transaction["afterProfile"]
    current = read_motion_profile(paths)
    if current != after:
        raise MotionProfileAdapterError(
            "undo_conflict", "The motion profile changed after this NEXUS action, so undo was stopped."
        )
    if not dry_run and not confirm_risk:
        raise MotionProfileAdapterError(
            "risk_confirmation_required", "Undo reloads Hyprland motion settings and requires confirmation."
        )
    if dry_run:
        return {"status": "dry_run", "changedCount": 1, "runtimeVerified": False}
    try:
        if _helper_hash(paths) != transaction.get("helperSha256"):
            raise MotionProfileAdapterError(
                "undo_conflict", "The motion profile helper changed before undo could be applied."
            )
        _apply_and_verify(paths, before)
        if _helper_hash(paths) != transaction.get("helperSha256"):
            raise MotionProfileAdapterError(
                "undo_conflict", "The motion profile helper changed while undo was running."
            )
        transaction["status"] = "undone"
        transaction["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _atomic_json(path, transaction)
    except Exception as exc:
        try:
            if _helper_hash(paths) != transaction.get("helperSha256"):
                raise MotionProfileAdapterError(
                    "undo_conflict", "The motion profile helper changed; the previous applied state cannot be safely restored."
                )
            _apply_and_verify(paths, after)
            transaction["status"] = "complete"
            transaction.pop("undoneAt", None)
            _atomic_json(path, transaction)
        except Exception as rollback_exc:
            transaction["status"] = "rollback-failed"
            try:
                _atomic_json(path, transaction)
            except Exception:
                pass
            raise MotionProfileAdapterError(
                "motion_profile_rollback_failed",
                "Undo failed and the motion profile could not be restored.",
            ) from rollback_exc
        if isinstance(exc, MotionProfileAdapterError) and exc.code == "motion_profile_rollback_failed":
            raise exc
        raise MotionProfileAdapterError(
            "motion_profile_undo_failed", "Undo failed; the motion profile was restored to its previous state."
        ) from exc
    return {
        "status": "undo_written_to_config",
        "changedCount": 1,
        "runtimeVerified": False,
        "runtimeStatus": "hyprland-reload-and-config-error-check-passed; visual-motion-effect-unverified",
    }
