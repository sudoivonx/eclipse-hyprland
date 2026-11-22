"""Guarded adapter for the existing Aegis window glow helper."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
import uuid
import datetime as dt
from dataclasses import dataclass
from pathlib import Path


_TRANSACTION_ID = re.compile(r"^[a-f0-9]{32}$")
_STATE_KEYS = {"color", "enabled", "alpha", "size"}
_RUNTIME_STATUS = "hyprland-reload-and-config-error-check-passed; visual-glow-effect-unverified"


class WindowGlowAdapterError(Exception):
    """A window glow operation could not be completed safely."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WindowGlowPaths:
    helper: Path
    state: Path
    config: Path


def _load_helper(paths: WindowGlowPaths):
    try:
        helper_path = Path(paths.helper)
        info = helper_path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise WindowGlowAdapterError("window_glow_unavailable", "The existing glow helper is not a regular file.")
        module_name = f"nexus_window_glow_helper_{hashlib.sha256(str(helper_path.resolve()).encode()).hexdigest()[:16]}"
        spec = importlib.util.spec_from_file_location(module_name, helper_path)
        if spec is None or spec.loader is None:
            raise WindowGlowAdapterError("window_glow_unavailable", "The existing glow helper could not be loaded.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.CONFIG = Path(paths.config)
        module.STATE_FILE = Path(paths.state)
        for name in ("read_state", "validate", "render", "commit"):
            if not callable(getattr(module, name, None)):
                raise WindowGlowAdapterError("window_glow_unavailable", "The existing glow helper does not provide the required operations.")
        return module
    except WindowGlowAdapterError:
        raise
    except Exception as exc:
        raise WindowGlowAdapterError("window_glow_unavailable", "The existing glow helper could not be loaded safely.") from exc


def _validate_state(module, value) -> dict:
    if not isinstance(value, dict) or set(value) != _STATE_KEYS:
        raise WindowGlowAdapterError("window_glow_invalid", "The saved glow settings have an unexpected structure.")
    try:
        checked = module.validate(value)
    except Exception as exc:
        raise WindowGlowAdapterError("window_glow_invalid", "The saved glow settings failed the existing helper's validation.") from exc
    if not isinstance(checked, dict) or set(checked) != _STATE_KEYS:
        raise WindowGlowAdapterError("window_glow_invalid", "The existing helper returned an unexpected glow state.")
    return checked


def _read_regular(path: Path, label: str) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise WindowGlowAdapterError("window_glow_unavailable", f"The {label} is not a regular file.")
        return path.read_bytes()
    except WindowGlowAdapterError:
        raise
    except OSError as exc:
        raise WindowGlowAdapterError("window_glow_unavailable", f"The {label} could not be read safely.") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_sources(paths: WindowGlowPaths, module=None) -> tuple[dict, dict[str, str], object]:
    module = module or _load_helper(paths)
    state_raw = _read_regular(Path(paths.state), "saved glow state")
    config_raw = _read_regular(Path(paths.config), "generated glow configuration")
    try:
        stored = json.loads(state_raw.decode("utf-8"))
        helper_state = _validate_state(module, module.read_state())
        stored_state = _validate_state(module, stored)
        rendered = module.render(helper_state)
        rendered_raw = rendered.encode("utf-8") if isinstance(rendered, str) else bytes(rendered)
    except WindowGlowAdapterError:
        raise
    except Exception as exc:
        raise WindowGlowAdapterError("window_glow_invalid", "The saved glow state could not be read or validated.") from exc
    if helper_state != stored_state or rendered_raw != config_raw:
        raise WindowGlowAdapterError("window_glow_conflict", "The glow state file and generated Hyprland settings disagree.")
    return helper_state, {"state": _sha(state_raw), "config": _sha(config_raw)}, module


def read_window_glow(paths: WindowGlowPaths) -> dict:
    state, _, _ = _read_sources(paths)
    return {
        "status": "ok",
        "fieldCount": len(state),
        "runtimeVerified": False,
        "runtimeStatus": "persisted-glow-state-and-generated-config-agree; visual-glow-effect-unverified",
    }


def read_window_glow_state(paths: WindowGlowPaths) -> dict:
    """Read the validated state for private manager storage; callers must not emit it."""
    state, _, _ = _read_sources(paths)
    return state


def _ensure_private_dir(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise OSError("transaction directory is not a directory")
        else:
            path.mkdir(mode=0o700, parents=True)
        os.chmod(path, 0o700)
        if stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise OSError("transaction directory permissions could not be restricted")
    except OSError as exc:
        raise WindowGlowAdapterError("window_glow_recovery_unavailable", "Private glow recovery storage is unavailable.") from exc


def _atomic_private_json(path: Path, payload: dict) -> None:
    _ensure_private_dir(path.parent)
    temp_name = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".window-glow-", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise WindowGlowAdapterError("window_glow_recovery_unavailable", "Private glow recovery data could not be saved.") from exc
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _transaction_path(state_root: Path, transaction_id: str) -> Path:
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise WindowGlowAdapterError("window_glow_undo_invalid", "The glow recovery identifier is invalid.")
    return Path(state_root) / "window-glow-undo" / f"{transaction_id}.json"


def _read_transaction(path: Path) -> dict:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("invalid transaction file permissions")
        transaction = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(transaction, dict) or transaction.get("schema") != "nexus-window-glow-undo-v1":
            raise ValueError("invalid transaction schema")
        if set(transaction.get("before", {})) != _STATE_KEYS or set(transaction.get("after", {})) != _STATE_KEYS:
            raise ValueError("invalid transaction state")
        if set(transaction.get("beforeHashes", {})) != {"state", "config"} or set(transaction.get("afterHashes", {})) != {"state", "config"}:
            raise ValueError("invalid transaction hashes")
        if transaction.get("status") != "complete" or transaction.get("undone") is True:
            raise ValueError("transaction is not available")
        return transaction
    except WindowGlowAdapterError:
        raise
    except Exception as exc:
        raise WindowGlowAdapterError("window_glow_undo_invalid", "The saved glow recovery data is unavailable or invalid.") from exc


def _run_commit(module, desired: dict, paths: WindowGlowPaths, expected: dict, expected_hashes: dict, failure_code: str):
    try:
        module.commit(desired)
    except Exception as exc:
        try:
            current, hashes, _ = _read_sources(paths, module)
            if current != expected or hashes != expected_hashes:
                raise WindowGlowAdapterError("window_glow_rollback_failed", "The glow helper failed and the previous state could not be verified; manual recovery is required.") from exc
        except WindowGlowAdapterError as verify_exc:
            if verify_exc.code == "window_glow_rollback_failed":
                raise
            raise WindowGlowAdapterError("window_glow_rollback_failed", "The glow helper failed and the previous state could not be verified; manual recovery is required.") from exc
        raise WindowGlowAdapterError(failure_code, "The existing glow helper failed; its prior state and generated file were restored.") from exc
    return _read_sources(paths, module)


def apply_window_glow(
    paths: WindowGlowPaths,
    state_root: Path,
    desired,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    module = _load_helper(paths)
    before, before_hashes, _ = _read_sources(paths, module)
    desired_state = _validate_state(module, desired)
    changed = sum(before[key] != desired_state[key] for key in _STATE_KEYS)
    if changed == 0:
        return {"status": "no_changes", "changedCount": 0, "runtimeVerified": False}
    if dry_run:
        return {"status": "dry_run", "changedCount": changed, "runtimeVerified": False}
    if not confirm_risk:
        raise WindowGlowAdapterError("risk_confirmation_required", "Changing window glow settings reloads Hyprland and requires confirmation.")

    transaction_id = uuid.uuid4().hex
    transaction_file = _transaction_path(state_root, transaction_id)
    transaction = {
        "schema": "nexus-window-glow-undo-v1",
        "id": transaction_id,
        "status": "pending",
        "undone": False,
        "before": before,
        "after": desired_state,
        "beforeHashes": before_hashes,
        "afterHashes": {"state": "", "config": ""},
    }
    _atomic_private_json(transaction_file, transaction)
    try:
        after, after_hashes, _ = _run_commit(module, desired_state, paths, before, before_hashes, "window_glow_apply_failed")
        if after != desired_state:
            raise WindowGlowAdapterError("window_glow_verify_failed", "The glow helper did not persist the requested state.")
        transaction["status"] = "complete"
        transaction["afterHashes"] = after_hashes
        _atomic_private_json(transaction_file, transaction)
    except WindowGlowAdapterError as exc:
        try:
            if transaction_file.exists() and transaction.get("status") == "pending":
                if exc.code == "window_glow_apply_failed":
                    transaction_file.unlink()
                else:
                    transaction["status"] = "manual-recovery-required"
                    transaction["failureCode"] = exc.code
                    _atomic_private_json(transaction_file, transaction)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            current, hashes, _ = _read_sources(paths, module)
            if current == desired_state and hashes == transaction.get("afterHashes"):
                _run_commit(module, before, paths, desired_state, hashes, "window_glow_rollback_failed")
            elif current != before or hashes != before_hashes:
                raise WindowGlowAdapterError("window_glow_rollback_failed", "The glow recovery record failed and the prior state could not be restored; manual recovery is required.") from exc
        except WindowGlowAdapterError as recovery_exc:
            raise recovery_exc
        try:
            transaction_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise WindowGlowAdapterError("window_glow_recovery_unavailable", "The glow recovery record could not be finalized; the prior state was restored.") from exc
    return {
        "status": "written",
        "changedCount": changed,
        "transactionId": transaction_id,
        "runtimeVerified": False,
        "runtimeStatus": _RUNTIME_STATUS,
    }


def undo_window_glow(
    paths: WindowGlowPaths,
    state_root: Path,
    transaction_id: str,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    transaction_file = _transaction_path(state_root, transaction_id)
    transaction = _read_transaction(transaction_file)
    if transaction.get("id") != transaction_id:
        raise WindowGlowAdapterError("window_glow_undo_invalid", "The saved glow recovery data is invalid.")
    module = _load_helper(paths)
    try:
        current, current_hashes, _ = _read_sources(paths, module)
    except WindowGlowAdapterError as exc:
        if exc.code == "window_glow_conflict":
            raise WindowGlowAdapterError("undo_conflict", "Glow settings changed after this NEXUS action, so undo was stopped.") from exc
        raise
    if current != transaction["after"] or current_hashes != transaction["afterHashes"]:
        raise WindowGlowAdapterError("undo_conflict", "Glow settings changed after this NEXUS action, so undo was stopped.")
    changed = sum(transaction["after"][key] != transaction["before"][key] for key in _STATE_KEYS)
    if dry_run:
        return {"status": "dry_run", "changedCount": changed, "runtimeVerified": False}
    if not confirm_risk:
        raise WindowGlowAdapterError("risk_confirmation_required", "Undoing window glow settings reloads Hyprland and requires confirmation.")
    restored, restored_hashes, _ = _run_commit(
        module, transaction["before"], paths,
        transaction["after"], transaction["afterHashes"], "window_glow_undo_failed",
    )
    if restored != transaction["before"]:
        try:
            _run_commit(
                module, transaction["after"], paths, restored, restored_hashes,
                "window_glow_undo_rollback_failed",
            )
        except WindowGlowAdapterError as rollback_exc:
            raise WindowGlowAdapterError("window_glow_undo_rollback_failed", "Glow undo verification failed and the previously applied state could not be restored; manual recovery is required.") from rollback_exc
        raise WindowGlowAdapterError("window_glow_undo_verify_failed", "The starting glow state was not restored; the previous state was re-applied.")
    transaction["undone"] = True
    transaction["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        _atomic_private_json(transaction_file, transaction)
    except WindowGlowAdapterError as record_exc:
        try:
            _run_commit(
                module, transaction["after"], paths, restored, restored_hashes,
                "window_glow_undo_rollback_failed",
            )
        except WindowGlowAdapterError as rollback_exc:
            raise WindowGlowAdapterError("window_glow_undo_rollback_failed", "Glow undo could not be recorded and the previous state could not be re-applied; manual recovery is required.") from rollback_exc
        raise WindowGlowAdapterError("window_glow_undo_record_failed", "Glow undo could not be recorded; the previous state was re-applied so the undo can be retried.") from record_exc
    return {
        "status": "undo_written",
        "changedCount": changed,
        "runtimeVerified": False,
        "runtimeStatus": _RUNTIME_STATUS,
    }
