"""NEXUS adapter for the existing exact-window opacity rule helper."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import uuid


class WindowRuleAdapterError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WindowRulePaths:
    helper: Path
    rules: Path
    state: Path


def _validate_rules(value) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise WindowRuleAdapterError("window_rules_invalid", "The saved window rule list is invalid.")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"class", "title"}:
            raise WindowRuleAdapterError("window_rules_invalid", "The saved window rule list is invalid.")
        window_class = item.get("class")
        title = item.get("title")
        if (
            not isinstance(window_class, str)
            or not isinstance(title, str)
            or not window_class.strip()
            or not title.strip()
            or "\x00" in window_class
            or "\x00" in title
            or len(window_class) > 1024
            or len(title) > 2048
        ):
            raise WindowRuleAdapterError("window_rules_invalid", "The saved window rule list is invalid.")
        pair = (window_class, title)
        if pair in seen:
            raise WindowRuleAdapterError("window_rules_invalid", "The saved window rule list contains a duplicate.")
        seen.add(pair)
        rows.append({"class": window_class, "title": title})
    return rows


def _require_regular(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", f"The {label} is unavailable.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise WindowRuleAdapterError("window_rules_unavailable", f"The {label} is not a regular file.")


def _load_helper(paths: WindowRulePaths):
    _require_regular(paths.helper, "existing window rule helper")
    try:
        module_name = f"nexus_existing_window_rules_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, paths.helper)
        if spec is None or spec.loader is None:
            raise ImportError("helper loader unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if (
            not callable(getattr(module, "read_state", None))
            or not callable(getattr(module, "save", None))
            or not callable(getattr(module, "make_block", None))
            or not isinstance(getattr(module, "BEGIN", None), str)
            or not isinstance(getattr(module, "END", None), str)
        ):
            raise ImportError("helper interface unavailable")
        module.RULES = paths.rules
        module.STATE = paths.state
        return module
    except Exception as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", "The existing window rule helper could not be loaded.") from exc


def _read_from_helper(paths: WindowRulePaths, module=None) -> list[dict[str, str]]:
    _require_regular(paths.rules, "managed Hyprland rules file")
    try:
        state_info = paths.state.lstat()
    except FileNotFoundError:
        state_info = None
    except OSError as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", "The custom window rule state is unavailable.") from exc
    if state_info is not None and not stat.S_ISREG(state_info.st_mode):
        raise WindowRuleAdapterError("window_rules_unavailable", "The custom window rule state is not a regular file.")
    helper = module or _load_helper(paths)
    try:
        rules = _validate_rules(helper.read_state())
        begin = helper.BEGIN
        end = helper.END
        source = paths.rules.read_text(encoding="utf-8")
        if not begin or not end or source.count(begin) != 1 or source.count(end) != 1:
            raise WindowRuleAdapterError("window_rules_conflict", "The managed Hyprland window rule block is missing or ambiguous.")
        start = source.index(begin)
        finish = source.index(end, start) + len(end)
        if start < 0 or finish < len(end) or source[start:finish] != helper.make_block(rules):
            raise WindowRuleAdapterError("window_rules_conflict", "The saved window rule list does not match the managed Hyprland rules.")
        return rules
    except WindowRuleAdapterError:
        raise
    except Exception as exc:
        raise WindowRuleAdapterError("window_rules_invalid", "The saved window rule list could not be read safely.") from exc


def read_window_rules(paths: WindowRulePaths) -> list[dict[str, str]]:
    return _read_from_helper(paths)


def validate_window_rules(value) -> list[dict[str, str]]:
    return _validate_rules(value)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", "The managed window rule files could not be read safely.") from exc


def _optional_state_sha256(path: Path) -> str | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", "The custom window rule state could not be read safely.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise WindowRuleAdapterError("window_rules_unavailable", "The custom window rule state is not a regular file.")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise WindowRuleAdapterError("window_rules_unavailable", "The custom window rule state could not be read safely.") from exc


def _private_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise OSError("private recovery path is not a real directory")
        os.chmod(path, 0o700, follow_symlinks=False)
    except OSError as exc:
        raise WindowRuleAdapterError("window_rule_recovery_unavailable", "Private window rule recovery storage could not be prepared.") from exc


def _atomic_private_json(path: Path, payload: dict) -> None:
    transaction_dir = path.parent
    recovery_root = transaction_dir.parent.parent
    _private_dir(recovery_root)
    _private_dir(recovery_root / "window-rule-undo")
    _private_dir(transaction_dir)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = None
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        os.chmod(path, 0o600, follow_symlinks=False)
        parent_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        temp.unlink(missing_ok=True)
        raise WindowRuleAdapterError("window_rule_recovery_unavailable", "Private window rule recovery data could not be saved.") from exc


def _transaction_path(state_root: Path, transaction_id: str) -> Path:
    if not isinstance(transaction_id, str) or not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise WindowRuleAdapterError("window_rule_undo_invalid", "The saved window rule recovery identifier is invalid.")
    return state_root / "window-rule-undo" / transaction_id / "transaction.json"


def _read_transaction(path: Path) -> dict:
    try:
        _require_regular(path, "window rule recovery record")
        transaction = json.loads(path.read_text(encoding="utf-8"))
    except WindowRuleAdapterError:
        raise
    except (OSError, ValueError) as exc:
        raise WindowRuleAdapterError("window_rule_undo_invalid", "The saved window rule recovery data is unavailable.") from exc
    if not isinstance(transaction, dict) or transaction.get("schema") != "nexus-window-rules-undo-v1":
        raise WindowRuleAdapterError("window_rule_undo_invalid", "The saved window rule recovery data is invalid.")
    try:
        transaction["before"] = _validate_rules(transaction.get("before"))
        transaction["after"] = _validate_rules(transaction.get("after"))
    except WindowRuleAdapterError as exc:
        raise WindowRuleAdapterError("window_rule_undo_invalid", "The saved window rule recovery data is invalid.") from exc
    return transaction


def _run_save(module, items: list[dict[str, str]]) -> None:
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            module.save(items)
    except Exception as exc:
        raise WindowRuleAdapterError("window_rule_apply_failed", "The existing helper could not apply the window rules; its rollback path was checked.") from exc


def apply_window_rules(
    paths: WindowRulePaths,
    state_root: Path,
    desired,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    desired_rules = _validate_rules(desired)
    module = _load_helper(paths)
    before = _read_from_helper(paths, module)
    if before == desired_rules:
        return {"status": "no_changes", "changedCount": 0, "runtimeVerified": False}
    if dry_run:
        return {"status": "dry_run", "changedCount": len(set(map(tuple, before)) ^ set(map(tuple, desired_rules))), "runtimeVerified": False}
    if not confirm_risk:
        raise WindowRuleAdapterError("risk_confirmation_required", "This change reloads Hyprland window rules and requires confirmation.")

    rules_hash = _sha256(paths.rules)
    state_hash = _optional_state_sha256(paths.state)
    if _read_from_helper(paths, module) != before or _sha256(paths.rules) != rules_hash or _optional_state_sha256(paths.state) != state_hash:
        raise WindowRuleAdapterError("window_rules_changed", "The window rules changed while NEXUS was preparing the update.")

    transaction_id = uuid.uuid4().hex
    transaction_file = _transaction_path(state_root, transaction_id)
    transaction = {
        "schema": "nexus-window-rules-undo-v1",
        "id": transaction_id,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "before": before,
        "after": desired_rules,
        "rulesBeforeSha256": rules_hash,
        "stateBeforeSha256": state_hash,
    }
    _atomic_private_json(transaction_file, transaction)

    try:
        _run_save(module, desired_rules)
        current = _read_from_helper(paths, module)
        if current != desired_rules:
            raise WindowRuleAdapterError("window_rules_verify_failed", "The saved window rules did not match the requested change.")
    except Exception as exc:
        try:
            current = _read_from_helper(paths, module)
            if current != before:
                _run_save(module, before)
                if _read_from_helper(paths, module) != before:
                    raise RuntimeError("rollback state mismatch")
        except Exception as rollback_exc:
            transaction["status"] = "manual-recovery-required"
            _atomic_private_json(transaction_file, transaction)
            raise WindowRuleAdapterError("window_rules_rollback_failed", "The rule update failed and the prior window rules could not be verified; manual recovery is required.") from rollback_exc
        transaction["status"] = "failed-rolled-back"
        _atomic_private_json(transaction_file, transaction)
        if isinstance(exc, WindowRuleAdapterError):
            raise exc
        raise WindowRuleAdapterError("window_rule_apply_failed", "The existing helper could not apply the window rules; the previous list was restored.") from exc

    transaction["status"] = "complete"
    transaction["rulesAfterSha256"] = _sha256(paths.rules)
    transaction["stateAfterSha256"] = _optional_state_sha256(paths.state)
    try:
        _atomic_private_json(transaction_file, transaction)
    except WindowRuleAdapterError as exc:
        try:
            _run_save(module, before)
            if _read_from_helper(paths, module) != before:
                raise RuntimeError("rollback state mismatch")
        except Exception as rollback_exc:
            raise WindowRuleAdapterError("window_rules_rollback_failed", "The recovery record could not be finalized and the previous window rules could not be verified; manual recovery is required.") from rollback_exc
        raise WindowRuleAdapterError("window_rule_recovery_unavailable", "The recovery record could not be finalized, so the previous window rules were restored.") from exc
    return {
        "status": "applied",
        "changedCount": len(set(map(tuple, before)) ^ set(map(tuple, desired_rules))),
        "transactionId": transaction_id,
        "runtimeVerified": False,
        "runtimeStatus": "hyprland-reload-and-config-error-check-passed; matching-window-effect-unverified",
    }


def undo_window_rules(
    paths: WindowRulePaths,
    state_root: Path,
    transaction_id: str,
    confirm_risk: bool,
    dry_run: bool = False,
) -> dict:
    transaction_file = _transaction_path(state_root, transaction_id)
    transaction = _read_transaction(transaction_file)
    if transaction.get("id") != transaction_id or transaction.get("status") != "complete" or transaction.get("undone"):
        raise WindowRuleAdapterError("window_rule_undo_invalid", "The saved window rule recovery data is invalid or already used.")
    current = read_window_rules(paths)
    if current != transaction["after"]:
        raise WindowRuleAdapterError("undo_conflict", "Window rules changed after this NEXUS action, so undo was stopped.")
    if current == transaction["before"]:
        raise WindowRuleAdapterError("undo_conflict", "The window rule state no longer matches this NEXUS action.")
    if dry_run:
        return {"status": "dry_run", "changedCount": len(set(map(tuple, current)) ^ set(map(tuple, transaction["before"]))), "runtimeVerified": False}
    if not confirm_risk:
        raise WindowRuleAdapterError("risk_confirmation_required", "Undo reloads Hyprland window rules and requires confirmation.")

    module = _load_helper(paths)
    _run_save(module, transaction["before"])
    restored = _read_from_helper(paths, module)
    if restored != transaction["before"]:
        raise WindowRuleAdapterError("window_rule_undo_failed", "The previous window rule state could not be verified after reload.")
    transaction["undone"] = True
    transaction["undoneAt"] = datetime.now(timezone.utc).isoformat()
    _atomic_private_json(transaction_file, transaction)
    return {
        "status": "undo_written",
        "changedCount": len(set(map(tuple, current)) ^ set(map(tuple, transaction["before"]))),
        "runtimeVerified": False,
        "runtimeStatus": "hyprland-reload-and-config-error-check-passed; matching-window-effect-unverified",
    }
