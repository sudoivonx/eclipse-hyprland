#!/usr/bin/env python3
"""Verified NEXUS backup listing and guarded configuration restoration."""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid


CONFIG_ROOTS = (
    ".config/environment.d/90-cursor.conf",
    ".config/gtk-3.0",
    ".config/gtk-4.0",
    ".config/hypr",
    ".config/illogical-impulse",
    ".config/kde-material-you-colors",
    ".config/kdeglobals",
    ".config/matugen",
    ".config/quickshell/ii",
    ".local/share/icons/march-7th-honkai-cursors",
    ".local/state/aegis/nexus",
    ".local/state/quickshell/states.json",
    ".local/state/quickshell/user/generated",
)
WORKING_SCHEMA = "nexus-working-backup-v1"
SAFETY_SCHEMA = "nexus-safety-backup-v1"
BACKUP_NAME = re.compile(r"^nexus-(?:working|safety)-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}[+-]\d{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class BackupRecoveryPaths:
    home: Path
    backup_root: Path
    workspace_root: Path | None = None
    config_roots: tuple[str, ...] = CONFIG_ROOTS


DEFAULT_PATHS = BackupRecoveryPaths(
    home=Path.home(),
    backup_root=Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "aegis-backups",
    workspace_root=None,
)


class BackupRecoveryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _safe_id(backup_id: str) -> bool:
    return isinstance(backup_id, str) and BACKUP_NAME.fullmatch(backup_id) is not None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_member_name(value: str) -> PurePosixPath:
    while value.startswith("./"):
        value = value[2:]
    value = value.rstrip("/")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise BackupRecoveryError("backup_path_invalid", "The backup contains an unsafe path.")
    return path


def _within(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest contains an invalid path.")
    try:
        return _normalize_member_name(value)
    except BackupRecoveryError as exc:
        raise BackupRecoveryError("backup_path_invalid", "The backup contains an unsafe path.") from exc


def _entry_type(mode: int) -> str:
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def _file_entry(path: Path, root_name: str, relative: str) -> dict:
    st = path.lstat()
    kind = _entry_type(st.st_mode)
    row = {
        "root": root_name,
        "relativePath": relative,
        "path": str(path),
        "type": kind,
        "mode": stat.S_IMODE(st.st_mode),
        "uid": st.st_uid,
        "gid": st.st_gid,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size if kind == "file" else 0,
        "sha256": _sha256(path) if kind == "file" else None,
        "symlinkTarget": os.readlink(path) if kind == "symlink" else None,
    }
    try:
        attrs = {}
        for name in os.listxattr(path, follow_symlinks=False):
            try:
                attrs[name] = hashlib.sha256(os.getxattr(path, name, follow_symlinks=False)).hexdigest()
            except OSError:
                attrs[name] = "unreadable"
        row["xattrSha256"] = attrs
        row["xattrStatus"] = "captured"
    except OSError:
        row["xattrSha256"] = {}
        row["xattrStatus"] = "unavailable"
    return row


def _walk_root(home: Path, relative_root: str, *, include_cache: bool = False) -> list[dict]:
    root_rel = _safe_relative(relative_root)
    root = home.joinpath(*root_rel.parts)
    if not root.exists() and not root.is_symlink():
        return []
    if root.is_symlink():
        raise BackupRecoveryError("restore_target_unsafe", "A managed configuration root is a symbolic link.")
    rows = [_file_entry(root, "config", str(root_rel))]
    if root.is_dir():
        excluded = set() if include_cache else {"__pycache__"}
        for parent, dirs, files in os.walk(root, topdown=True, followlinks=False):
            parent_path = Path(parent)
            parent_rel = parent_path.relative_to(home)
            keep = []
            for name in sorted(dirs):
                if name in excluded:
                    continue
                path = parent_path / name
                relative = str(PurePosixPath(*parent_rel.parts, name))
                rows.append(_file_entry(path, "config", relative))
                if not path.is_symlink():
                    keep.append(name)
            dirs[:] = keep
            for name in sorted(files):
                if name in excluded:
                    continue
                path = parent_path / name
                rows.append(_file_entry(path, "config", str(PurePosixPath(*parent_rel.parts, name))))
    return rows


def _current_entries(paths: BackupRecoveryPaths) -> list[dict]:
    rows = []
    for root in paths.config_roots:
        rows.extend(_walk_root(paths.home, root))
    return sorted(rows, key=lambda row: row["relativePath"])


def _assert_private(path: Path, *, directory: bool) -> None:
    try:
        st = path.lstat()
    except OSError as exc:
        raise BackupRecoveryError("backup_unavailable", "The selected backup could not be opened.") from exc
    if stat.S_ISLNK(st.st_mode) or (directory and not stat.S_ISDIR(st.st_mode)) or (not directory and not stat.S_ISREG(st.st_mode)):
        raise BackupRecoveryError("backup_path_invalid", "The backup contains an unexpected filesystem object.")
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise BackupRecoveryError("backup_permissions_unsafe", "The backup permissions are not restricted to this user.")


def _backup_dir(paths: BackupRecoveryPaths, backup_id: str) -> Path:
    if not _safe_id(backup_id):
        raise BackupRecoveryError("backup_id_invalid", "Choose a valid NEXUS backup.")
    root = paths.backup_root
    _assert_private(root, directory=True)
    candidate = root / backup_id
    _assert_private(candidate, directory=True)
    if candidate.parent.resolve() != root.resolve():
        raise BackupRecoveryError("backup_path_invalid", "The selected backup is outside the NEXUS backup folder.")
    return candidate


def _read_manifest(paths: BackupRecoveryPaths, backup_id: str) -> tuple[Path, dict]:
    backup_dir = _backup_dir(paths, backup_id)
    manifest_path = backup_dir / "MANIFEST.json"
    sums_path = backup_dir / "SHA256SUMS"
    _assert_private(manifest_path, directory=False)
    _assert_private(sums_path, directory=False)
    if manifest_path.stat().st_size > 16 * 1024 * 1024 or sums_path.stat().st_size > 16 * 1024:
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest is too large.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest could not be read.") from exc
    expected_schema = SAFETY_SCHEMA if backup_id.startswith("nexus-safety-") else WORKING_SCHEMA
    if not isinstance(manifest, dict) or manifest.get("schema") != expected_schema:
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest has an unsupported format.")
    if manifest.get("backup_directory") != str(backup_dir):
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest does not match its folder.")
    source_roots = manifest.get("source_roots")
    if not isinstance(source_roots, dict) or source_roots.get("config") != list(paths.config_roots):
        raise BackupRecoveryError("backup_roots_unsupported", "The backup contains an unsupported configuration scope.")
    if expected_schema == WORKING_SCHEMA:
        workspace = source_roots.get("workspace")
        if not isinstance(workspace, str) or not Path(workspace).is_absolute():
            raise BackupRecoveryError("backup_manifest_invalid", "The workspace archive source is invalid.")
    if not isinstance(manifest.get("entries"), list) or not isinstance(manifest.get("archives"), list):
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest is incomplete.")
    return backup_dir, manifest


def _validate_manifest_entries(paths: BackupRecoveryPaths, manifest: dict) -> dict[str, dict[str, dict]]:
    grouped: dict[str, dict[str, dict]] = {"config": {}, "workspace": {}}
    roots = [PurePosixPath(root) for root in paths.config_roots]
    workspace_path = Path(manifest["source_roots"].get("workspace", "/"))
    workspace_prefix = PurePosixPath(workspace_path.name)
    for row in manifest["entries"]:
        if not isinstance(row, dict) or row.get("root") not in grouped:
            raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest has an invalid file record.")
        root_name = row["root"]
        rel = _safe_relative(row.get("relativePath"))
        if any(part == "__pycache__" for part in rel.parts):
            raise BackupRecoveryError("backup_path_invalid", "The backup includes an excluded cache path.")
        if root_name == "config":
            if not any(_within(rel, root) for root in roots):
                raise BackupRecoveryError("backup_roots_unsupported", "The backup contains a path outside managed configuration roots.")
            expected_path = paths.home.joinpath(*rel.parts)
        else:
            if not _within(rel, workspace_prefix):
                raise BackupRecoveryError("backup_path_invalid", "The workspace archive contains an unexpected path.")
            suffix = rel.parts[1:]
            expected_path = workspace_path.joinpath(*suffix)
        if row.get("path") != str(expected_path):
            raise BackupRecoveryError("backup_manifest_invalid", "A backup path does not match its declared source root.")
        if rel.as_posix() in grouped[root_name]:
            raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest contains duplicate paths.")
        kind = row.get("type")
        if kind not in ("directory", "file", "symlink"):
            raise BackupRecoveryError("backup_member_unsupported", "The backup contains an unsupported file type.")
        if not isinstance(row.get("mode"), int) or not isinstance(row.get("uid"), int) or not isinstance(row.get("gid"), int):
            raise BackupRecoveryError("backup_manifest_invalid", "The backup file metadata is incomplete.")
        if row["uid"] != os.getuid() or row["gid"] != os.getgid():
            raise BackupRecoveryError("backup_owner_unsupported", "The backup contains files owned by another user or group.")
        if kind == "file" and (not isinstance(row.get("sha256"), str) or not SHA256_RE.fullmatch(row["sha256"]) or not isinstance(row.get("size"), int)):
            raise BackupRecoveryError("backup_manifest_invalid", "The backup file checksum is invalid.")
        if kind == "symlink":
            target = row.get("symlinkTarget")
            if not isinstance(target, str) or target.startswith("/"):
                raise BackupRecoveryError("backup_path_invalid", "The backup contains an unsafe symbolic link.")
            resolved = posixpath.normpath(posixpath.join(str(rel.parent), target))
            if resolved == ".." or resolved.startswith("../"):
                raise BackupRecoveryError("backup_path_invalid", "The backup contains a symbolic link outside the home folder.")
        grouped[root_name][rel.as_posix()] = row
    expected_count = manifest.get("entry_count")
    if expected_count is not None and expected_count != len(manifest["entries"]):
        raise BackupRecoveryError("backup_manifest_invalid", "The backup manifest file count does not match.")
    return grouped


def _verify_archive(archive_path: Path, expected: dict[str, dict], *, allow_missing=False) -> int:
    _assert_private(archive_path, directory=False)
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            seen: dict[str, tarfile.TarInfo] = {}
            symlinks: set[str] = set()
            for member in members:
                rel = _normalize_member_name(member.name)
                name = rel.as_posix()
                if name in seen:
                    raise BackupRecoveryError("backup_manifest_invalid", "The archive contains duplicate paths.")
                row = expected.get(name)
                if row is None:
                    raise BackupRecoveryError("backup_path_invalid", "The archive contains a path absent from its manifest.")
                if member.isdir():
                    kind = "directory"
                elif member.isfile():
                    kind = "file"
                elif member.issym():
                    kind = "symlink"
                    symlinks.add(name)
                else:
                    raise BackupRecoveryError("backup_member_unsupported", "The archive contains a link or special file type.")
                if kind != row["type"] or member.mode & 0o7777 != row["mode"] or member.uid != row["uid"] or member.gid != row["gid"]:
                    raise BackupRecoveryError("backup_manifest_invalid", "Archive metadata does not match the manifest.")
                if kind == "file":
                    if member.size != row["size"]:
                        raise BackupRecoveryError("backup_manifest_invalid", "An archived file size does not match the manifest.")
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise BackupRecoveryError("backup_archive_invalid", "An archived file could not be read.")
                    digest = hashlib.sha256()
                    size = 0
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                        size += len(chunk)
                    if size != row["size"] or digest.hexdigest() != row["sha256"]:
                        raise BackupRecoveryError("backup_content_mismatch", "An archived file does not match its recorded checksum.")
                elif kind == "symlink" and member.linkname != row["symlinkTarget"]:
                    raise BackupRecoveryError("backup_manifest_invalid", "A symbolic link does not match the manifest.")
                seen[name] = member
            if not allow_missing and set(seen) != set(expected):
                raise BackupRecoveryError("backup_manifest_invalid", "The archive file list differs from the manifest.")
            for name in seen:
                parent = PurePosixPath(name).parent
                while str(parent) not in (".", ""):
                    if parent.as_posix() in symlinks:
                        raise BackupRecoveryError("backup_path_invalid", "The archive contains a path through a symbolic link.")
                    parent = parent.parent
            return len(members)
    except BackupRecoveryError:
        raise
    except (OSError, tarfile.TarError, EOFError) as exc:
        raise BackupRecoveryError("backup_archive_invalid", "The backup archive could not be read.") from exc


def verify_backup(paths: BackupRecoveryPaths, backup_id: str) -> dict:
    backup_dir, manifest = _read_manifest(paths, backup_id)
    grouped = _validate_manifest_entries(paths, manifest)
    archives = manifest["archives"]
    expected_names = ["configuration.tar"]
    if manifest["schema"] == WORKING_SCHEMA:
        expected_names.append("workspace.tar")
    archive_map = {}
    for item in archives:
        if not isinstance(item, dict) or item.get("name") not in expected_names or item["name"] in archive_map:
            raise BackupRecoveryError("backup_manifest_invalid", "The backup archive list is invalid.")
        if not isinstance(item.get("sha256"), str) or not SHA256_RE.fullmatch(item["sha256"]):
            raise BackupRecoveryError("backup_manifest_invalid", "The backup archive checksum is invalid.")
        archive_map[item["name"]] = item
    if set(archive_map) != set(expected_names):
        raise BackupRecoveryError("backup_manifest_invalid", "A required backup archive is missing.")
    manifest_hash = _sha256(backup_dir / "MANIFEST.json")
    sums = {}
    try:
        for line in (backup_dir / "SHA256SUMS").read_text(encoding="ascii").splitlines():
            parts = line.split()
            if len(parts) != 2 or not SHA256_RE.fullmatch(parts[0]) or "/" in parts[1] or "\\" in parts[1]:
                raise ValueError
            if parts[1] in sums:
                raise ValueError
            sums[parts[1]] = parts[0]
    except (OSError, UnicodeError, ValueError) as exc:
        raise BackupRecoveryError("backup_checksums_invalid", "The backup checksum list is invalid.") from exc
    expected_sums = {name: row["sha256"] for name, row in archive_map.items()}
    expected_sums["MANIFEST.json"] = manifest_hash
    if sums != expected_sums:
        raise BackupRecoveryError("backup_checksum_mismatch", "The backup checksum list does not match its manifest.")
    for name, row in archive_map.items():
        archive_path = backup_dir / name
        _assert_private(archive_path, directory=False)
        if archive_path.stat().st_size != row.get("bytes") or _sha256(archive_path) != row["sha256"]:
            raise BackupRecoveryError("backup_checksum_mismatch", "A backup archive checksum does not match.")
    config_count = _verify_archive(backup_dir / "configuration.tar", grouped["config"])
    if manifest["schema"] == WORKING_SCHEMA:
        if not isinstance(manifest["source_roots"].get("workspace"), str):
            raise BackupRecoveryError("backup_manifest_invalid", "The workspace archive root is missing.")
        workspace_count = _verify_archive(backup_dir / "workspace.tar", grouped["workspace"])
    else:
        workspace_count = 0
    files = [row for row in grouped["config"].values() if row["type"] == "file"]
    return {
        "status": "verified",
        "backupId": backup_id,
        "createdAt": backup_id.removeprefix("nexus-working-").removeprefix("nexus-safety-"),
        "fileCount": len(files),
        "entryCount": len(grouped["config"]) + len(grouped["workspace"]),
        "bytes": sum(row["size"] for row in files),
        "archiveCount": 1 + (1 if manifest["schema"] == WORKING_SCHEMA else 0),
        "configurationArchiveEntries": config_count,
        "workspaceArchiveEntries": workspace_count,
        "restoreSupported": True,
    }


def list_backups(paths: BackupRecoveryPaths = DEFAULT_PATHS) -> dict:
    if not paths.backup_root.exists():
        return {"status": "ok", "backups": []}
    _assert_private(paths.backup_root, directory=True)
    rows = []
    for child in sorted(paths.backup_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not child.is_dir() or child.is_symlink() or not _safe_id(child.name):
            continue
        try:
            result = verify_backup(paths, child.name)
            rows.append({key: result[key] for key in ("backupId", "createdAt", "fileCount", "bytes", "archiveCount", "status", "restoreSupported")})
        except BackupRecoveryError as exc:
            rows.append({"backupId": child.name, "createdAt": child.name, "fileCount": 0, "bytes": 0, "archiveCount": 0, "status": "invalid", "restoreSupported": False, "errorCode": exc.code})
    return {"status": "ok", "backups": rows}


def _file_state(row: dict) -> tuple:
    if row["type"] == "file":
        return ("file", row.get("sha256"), row.get("mode"), row.get("size"), row.get("xattrSha256", {}))
    return (row["type"], row.get("symlinkTarget"), row.get("mode"))


def preview_restore(paths: BackupRecoveryPaths, backup_id: str) -> dict:
    verified = verify_backup(paths, backup_id)
    _, manifest = _read_manifest(paths, backup_id)
    grouped = _validate_manifest_entries(paths, manifest)
    expected = {path: row for path, row in grouped["config"].items()}
    current_rows = _current_entries(paths)
    current = {row["relativePath"]: row for row in current_rows}
    expected_files = {path: row for path, row in expected.items() if row["type"] != "directory"}
    current_files = {path: row for path, row in current.items() if row["type"] != "directory"}
    added = sum(path not in current_files for path in expected_files)
    removed = sum(path not in expected_files for path in current_files)
    replaced = sum(path in current_files and _file_state(expected_files[path]) != _file_state(current_files[path]) for path in expected_files)
    return {
        "status": "dry_run",
        "backupId": backup_id,
        "fileCount": verified["fileCount"],
        "addedCount": added,
        "replacedCount": replaced,
        "removedCount": removed,
        "cacheDirectoriesPreserved": True,
        "requiresConfirmation": True,
    }


def _check_restore_targets(paths: BackupRecoveryPaths, backup_root: Path) -> None:
    if paths.home.is_symlink() or paths.home.resolve() != paths.home:
        raise BackupRecoveryError("restore_target_unsafe", "The home directory path is not safe for restore.")
    backup_device = backup_root.stat().st_dev
    for rel_text in paths.config_roots:
        rel = _safe_relative(rel_text)
        current = paths.home
        for part in rel.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise BackupRecoveryError("restore_target_unsafe", "A managed configuration parent is a symbolic link.")
            if current.exists() and not current.is_dir():
                raise BackupRecoveryError("restore_target_unsafe", "A managed configuration parent is not a directory.")
        parent = paths.home.joinpath(*rel.parts[:-1])
        if not parent.is_dir() or parent.stat().st_dev != backup_device:
            raise BackupRecoveryError("restore_filesystem_unsupported", "A managed configuration root is on a different filesystem or has no safe parent.")
        target = paths.home.joinpath(*rel.parts)
        if target.is_symlink():
            raise BackupRecoveryError("restore_target_unsafe", "A managed configuration root is a symbolic link.")


def _write_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix=".nexus-backup-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _create_safety_backup(paths: BackupRecoveryPaths) -> str:
    backup_root = paths.backup_root
    if backup_root.exists():
        _assert_private(backup_root, directory=True)
    else:
        backup_root.mkdir(parents=True, mode=0o700)
    now = dt.datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d_%H-%M-%S%z")
    backup_id = f"nexus-safety-{stamp}"
    final_dir = backup_root / backup_id
    partial_dir = backup_root / f".{backup_id}.partial"
    if final_dir.exists() or partial_dir.exists():
        raise BackupRecoveryError("safety_backup_collision", "A safety backup with this timestamp already exists.")
    partial_dir.mkdir(mode=0o700)
    os.chmod(partial_dir, 0o700)
    try:
        before = _current_entries(paths)
        existing_roots = [root for root in paths.config_roots if (paths.home / root).exists() or (paths.home / root).is_symlink()]
        if not existing_roots:
            raise BackupRecoveryError("safety_backup_empty", "No managed configuration roots are available for a safety backup.")
        archive_path = partial_dir / "configuration.tar"
        args = ["tar", "--acls", "--xattrs", "--numeric-owner", "--sort=name", "-cpf", str(archive_path), "-C", str(paths.home), "--exclude=*/__pycache__", "--exclude=*/__pycache__/*", *existing_roots]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.chmod(archive_path, 0o600)
        member_count = len(subprocess.run(["tar", "-tf", str(archive_path)], check=True, capture_output=True, text=True).stdout.splitlines())
        if member_count != len(before):
            raise BackupRecoveryError("safety_backup_manifest_mismatch", "The safety backup archive and file list do not match.")
        subprocess.run(["tar", "--compare", "--acls", "--xattrs", "-f", str(archive_path), "-C", str(paths.home)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        after = _current_entries(paths)
        if before != after:
            raise BackupRecoveryError("safety_backup_source_changed", "Configuration files changed while the safety backup was being created.")
        archive_row = {"name": archive_path.name, "sha256": _sha256(archive_path), "bytes": archive_path.stat().st_size, "entryCount": member_count}
        manifest = {
            "schema": SAFETY_SCHEMA,
            "backup_directory": str(final_dir),
            "created_local": now.isoformat(),
            "source_roots": {"config": list(paths.config_roots)},
            "excluded": ["__pycache__ directories", "workspace sources and VCS metadata", "private user data outside approved roots"],
            "missing_roots": [str(paths.home / root) for root in paths.config_roots if not (paths.home / root).exists()],
            "entry_count": len(before),
            "regular_file_count": sum(row["type"] == "file" for row in before),
            "regular_file_bytes": sum(row["size"] for row in before if row["type"] == "file"),
            "archives": [archive_row],
            "entries": before,
        }
        manifest_path = partial_dir / "MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        sums_path = partial_dir / "SHA256SUMS"
        sums_path.write_text(f"{archive_row['sha256']}  configuration.tar\n{_sha256(manifest_path)}  MANIFEST.json\n", encoding="ascii")
        os.chmod(sums_path, 0o600)
        partial_dir.rename(final_dir)
        verify_backup(paths, backup_id)
        return backup_id
    except Exception:
        shutil.rmtree(partial_dir, ignore_errors=True)
        shutil.rmtree(final_dir, ignore_errors=True)
        raise


def _remove_path(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _preserve_caches(paths: BackupRecoveryPaths, stage: Path, manifest: dict) -> None:
    directory_rows = {row["relativePath"]: row for row in manifest["entries"] if row["root"] == "config" and row["type"] == "directory"}
    for rel_text in paths.config_roots:
        live_root = paths.home / rel_text
        stage_root = stage / rel_text
        if not live_root.is_dir() or live_root.is_symlink() or not stage_root.is_dir() or stage_root.is_symlink():
            continue
        for parent, dirs, _ in os.walk(live_root, topdown=True, followlinks=False):
            parent_path = Path(parent)
            keep = []
            for name in sorted(dirs):
                source = parent_path / name
                if name == "__pycache__":
                    rel = source.relative_to(paths.home)
                    target = stage / rel
                    if target.exists() or target.is_symlink():
                        raise BackupRecoveryError("restore_cache_conflict", "A preserved cache path conflicts with the backup.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)
                elif not source.is_symlink():
                    keep.append(name)
            dirs[:] = keep
    for rel_text, row in directory_rows.items():
        path = stage / rel_text
        if path.is_dir() and not path.is_symlink():
            current = path.stat()
            os.utime(path, ns=(current.st_atime_ns, row["mtime_ns"]))


def _rollback_roots(steps: list[dict]) -> list[str]:
    errors = []
    for step in reversed(steps):
        dest = Path(step["target"])
        rollback = Path(step["rollback"])
        try:
            if rollback.exists() or rollback.is_symlink():
                _remove_path(dest)
                os.replace(rollback, dest)
            elif not step["hadOriginal"] and (dest.exists() or dest.is_symlink()) and step.get("installAttempted"):
                _remove_path(dest)
            elif step["hadOriginal"] and step.get("originalMoved") and not dest.exists() and not dest.is_symlink():
                errors.append(str(dest))
        except OSError:
            errors.append(str(dest))
    return errors


def restore_backup(paths: BackupRecoveryPaths, backup_id: str, *, confirm_risk: bool = False, dry_run: bool = False) -> dict:
    plan = preview_restore(paths, backup_id)
    if dry_run:
        return plan
    if not confirm_risk:
        raise BackupRecoveryError("confirmation_required", "Restoring a backup requires explicit risk confirmation.")
    backup_dir, manifest = _read_manifest(paths, backup_id)
    _check_restore_targets(paths, paths.backup_root)
    stage = paths.backup_root / f".nexus-restore-stage-{uuid.uuid4().hex}"
    stage.mkdir(mode=0o700)
    os.chmod(stage, 0o700)
    try:
        subprocess.run(["tar", "-xpf", str(backup_dir / "configuration.tar"), "--acls", "--xattrs", "--numeric-owner", "-C", str(stage)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        subprocess.run(["tar", "--compare", "--acls", "--xattrs", "-f", str(backup_dir / "configuration.tar"), "-C", str(stage)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _preserve_caches(paths, stage, manifest)
        subprocess.run(["tar", "--compare", "--acls", "--xattrs", "-f", str(backup_dir / "configuration.tar"), "-C", str(stage)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _check_restore_targets(paths, paths.backup_root)
        safety_id = _create_safety_backup(paths)
        transaction = uuid.uuid4().hex
        steps = []
        try:
            for root in paths.config_roots:
                dest = paths.home / root
                staged = stage / root
                rollback = dest.parent / f".{dest.name}.nexus-rollback-{transaction}"
                if rollback.exists() or rollback.is_symlink():
                    raise BackupRecoveryError("restore_target_conflict", "A restore rollback path already exists.")
                step = {"target": str(dest), "rollback": str(rollback), "hadOriginal": dest.exists() or dest.is_symlink(), "originalMoved": False, "installAttempted": False}
                steps.append(step)
                if step["hadOriginal"]:
                    os.replace(dest, rollback)
                    step["originalMoved"] = True
                if staged.exists() or staged.is_symlink():
                    step["installAttempted"] = True
                    os.replace(staged, dest)
            subprocess.run(["tar", "--compare", "--acls", "--xattrs", "-f", str(backup_dir / "configuration.tar"), "-C", str(paths.home)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as exc:
            rollback_errors = _rollback_roots(steps)
            try:
                safety_dir = paths.backup_root / safety_id
                subprocess.run(["tar", "--compare", "--acls", "--xattrs", "-f", str(safety_dir / "configuration.tar"), "-C", str(paths.home)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except Exception:
                rollback_errors.append("safety-archive-compare")
            if rollback_errors:
                raise BackupRecoveryError("restore_rollback_failed", f"Restore failed and rollback could not be verified. Keep safety backup {safety_id} for recovery.") from exc
            raise BackupRecoveryError("restore_failed_rolled_back", f"Restore failed; the previous configuration was restored. Safety backup: {safety_id}.") from exc
        for step in steps:
            _remove_path(Path(step["rollback"]))
        return {
            "status": "restored",
            "backupId": backup_id,
            "safetyBackupId": safety_id,
            "addedCount": plan["addedCount"],
            "replacedCount": plan["replacedCount"],
            "removedCount": plan["removedCount"],
            "cacheDirectoriesPreserved": True,
            "runtimeVerified": False,
            "runtimeStatus": "configuration-restored; application-reload-not-issued",
        }
    except BackupRecoveryError:
        raise
    except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
        raise BackupRecoveryError("backup_restore_failed", "The backup could not be restored safely; no success was reported.") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
