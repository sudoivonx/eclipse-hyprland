"""Transactional NEXUS adapter for default applications, per-app .desktop icon overrides, and app visibility."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any, Mapping, Sequence
import uuid


class AppCustomizationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AppCustomizationPaths:
    mimeapps_list: Path
    user_applications_dir: Path
    desktop_entry_dirs: tuple[Path, ...]
    config_home: Path


DEFAULT_APP_SPECS: dict[str, dict[str, Any]] = {
    "apps.defaults.browser": {
        "title": "Default web browser",
        "description": "Sets the default desktop web browser in mimeapps.list for HTTP, HTTPS, and HTML links.",
        "mimes": ("x-scheme-handler/http", "x-scheme-handler/https", "text/html"),
        "categories": ("WebBrowser",),
        "keywords": ["browser", "web", "tarayici", "http", "https", "default", "app", "uygulama"],
    },
    "apps.defaults.fileManager": {
        "title": "Default file manager",
        "description": "Sets the default file manager for opening folders (inode/directory) in mimeapps.list.",
        "mimes": ("inode/directory",),
        "categories": ("FileManager",),
        "keywords": ["file", "manager", "dosya", "yoneticisi", "dolphin", "nautilus", "thunar", "default"],
    },
    "apps.defaults.textEditor": {
        "title": "Default text editor",
        "description": "Sets the default plain text editor (text/plain) in mimeapps.list.",
        "mimes": ("text/plain",),
        "categories": ("TextEditor",),
        "keywords": ["text", "editor", "metin", "duzenleyici", "code", "default"],
    },
    "apps.defaults.imageViewer": {
        "title": "Default image viewer",
        "description": "Sets the default application for opening PNG, JPEG, and WebP images.",
        "mimes": ("image/png", "image/jpeg", "image/webp"),
        "categories": ("Viewer", "Graphics"),
        "keywords": ["image", "photo", "resim", "fotograf", "viewer", "default"],
    },
    "apps.defaults.pdfViewer": {
        "title": "Default PDF viewer",
        "description": "Sets the default application for opening PDF documents.",
        "mimes": ("application/pdf",),
        "categories": ("Office", "Viewer"),
        "keywords": ["pdf", "document", "belge", "viewer", "default"],
    },
    "apps.defaults.videoPlayer": {
        "title": "Default video player",
        "description": "Sets the default media player for MP4 and Matroska video files.",
        "mimes": ("video/mp4", "video/x-matroska"),
        "categories": ("Video", "Player"),
        "keywords": ["video", "player", "media", "oynatici", "mpv", "vlc", "default"],
    },
    "apps.defaults.audioPlayer": {
        "title": "Default audio player",
        "description": "Sets the default audio player for MP3 and FLAC files.",
        "mimes": ("audio/mpeg", "audio/flac"),
        "categories": ("Audio", "Music", "Player"),
        "keywords": ["audio", "music", "muzik", "ses", "player", "default"],
    },
}

DESKTOP_OVERRIDE_SPECS: dict[str, dict[str, Any]] = {
    "apps.icons.overrides": {
        "title": "Application & Hyprland icon overrides",
        "description": "Custom per-application icons ('appId=iconNameOrPath') written to ~/.local/share/applications/*.desktop so launchers, dock, and Hyprland workspace icons update everywhere.",
        "valueType": "array",
        "controlType": "array",
        "featureGroup": "app-icons",
        "keywords": ["icon", "icons", "ikon", "simge", "app", "application", "uygulama", "hyprland", "desktop", "launcher", "dock", "override"],
    },
    "apps.visibility.hiddenApps": {
        "title": "Hidden launcher applications",
        "description": "Applications marked NoDisplay=true in ~/.local/share/applications/*.desktop to hide clutter from app launchers.",
        "valueType": "array",
        "controlType": "array",
        "featureGroup": "app-icons",
        "keywords": ["hide", "hidden", "gizle", "app", "launcher", "desktop", "nodisplay", "uygulama"],
    },
}

ALL_SETTING_IDS: tuple[str, ...] = tuple(DEFAULT_APP_SPECS.keys()) + tuple(DESKTOP_OVERRIDE_SPECS.keys())

_DESKTOP_ID_RE = re.compile(r"^[A-Za-z0-9._@+ -]{1,160}$")
_DESKTOP_FILE_RE = re.compile(r"^[A-Za-z0-9._@+ -]{1,180}\.desktop$")
_ICON_VALUE_RE = re.compile(r"^[^\r\n\x00]{1,512}$")
_SECTION_RE = re.compile(r"^\s*\[([^\r\n]+)\]\s*$")
_KV_RE = re.compile(r"^([ \t]*)([^=\r\n#]+?)([ \t]*=[ \t]*)(.*)$")
_TXN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise AppCustomizationError("unsafe_state_directory", "NEXUS state directory is not owned by this user.")


@contextmanager
def _state_lock(state_root: Path):
    locks_dir = state_root / "locks"
    _ensure_private_dir(locks_dir)
    lock_file = locks_dir / "app-customization.lock"
    fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _is_user_regular_file(path: Path) -> bool:
    try:
        if path.is_symlink() or not path.exists():
            return False
        st = path.stat()
        return stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
    except OSError:
        return False


def _atomic_write_text(path: Path, text: str, default_mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    orig_stat = path.stat() if path.exists() and not path.is_symlink() else None
    fd, tmp_name = tempfile.mkstemp(prefix=f".nexus-{path.name}-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        mode = stat.S_IMODE(orig_stat.st_mode) if orig_stat is not None else default_mode
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
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
            tmp.unlink()
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    _atomic_write_text(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        default_mode=0o600,
    )


def _read_ini_key(text: str, section: str, key: str) -> str | None:
    current: str | None = None
    for line in text.splitlines():
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            current = m_sec.group(1).strip()
            continue
        if current != section:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m_kv = _KV_RE.match(line)
        if m_kv and m_kv.group(2).strip() == key:
            return m_kv.group(4).strip()
    return None


def _set_ini_key(text: str, section: str, key: str, value: str | None) -> str:
    """Set or remove (if value is None) a key inside an INI/Desktop Entry section, preserving all other lines."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    current: str | None = None
    section_found = False
    key_handled = False
    insert_idx: int | None = None

    for line in lines:
        m_sec = _SECTION_RE.match(line.rstrip("\r\n"))
        if m_sec:
            if current == section and not key_handled and insert_idx is None:
                insert_idx = len(out)
            current = m_sec.group(1).strip()
            if current == section:
                section_found = True
            out.append(line)
            continue

        if current == section and not key_handled:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                m_kv = _KV_RE.match(line.rstrip("\r\n"))
                if m_kv and m_kv.group(2).strip() == key:
                    key_handled = True
                    if value is not None:
                        eol = "\r\n" if line.endswith("\r\n") else "\n"
                        out.append(f"{m_kv.group(1)}{key}={value}{eol}")
                    continue
        out.append(line)

    if not key_handled and value is not None:
        if section_found:
            idx = insert_idx if insert_idx is not None else len(out)
            if idx > 0 and not out[idx - 1].endswith("\n"):
                out[idx - 1] += "\n"
            out.insert(idx, f"{key}={value}\n")
        else:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            if out and out[-1].strip() != "":
                out.append("\n")
            out.append(f"[{section}]\n{key}={value}\n")
    return "".join(out)


def _parse_desktop_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    name = _read_ini_key(text, "Desktop Entry", "Name")
    if not name:
        return None
    entry_type = (_read_ini_key(text, "Desktop Entry", "Type") or "").strip()
    if entry_type and entry_type != "Application":
        return None
    if (_read_ini_key(text, "Desktop Entry", "Hidden") or "").lower() == "true":
        return None
    icon = (_read_ini_key(text, "Desktop Entry", "Icon") or "").strip()
    exec_cmd = (_read_ini_key(text, "Desktop Entry", "Exec") or "").strip()
    cats_raw = _read_ini_key(text, "Desktop Entry", "Categories") or ""
    mimes_raw = _read_ini_key(text, "Desktop Entry", "MimeType") or ""
    no_display = (_read_ini_key(text, "Desktop Entry", "NoDisplay") or "").lower() == "true"
    return {
        "id": path.stem,
        "desktopFile": path.name,
        "name": name.strip(),
        "icon": icon,
        "exec": exec_cmd,
        "categories": [c.strip() for c in cats_raw.split(";") if c.strip()],
        "mimeTypes": [m.strip() for m in mimes_raw.split(";") if m.strip()],
        "noDisplay": no_display,
        "path": str(path),
    }


def _override_registry_path(state_root: Path) -> Path:
    return state_root / "app-desktop-overrides.json"


def _load_override_registry(state_root: Path) -> dict[str, Any]:
    path = _override_registry_path(state_root)
    if not path.is_file():
        return {"schema": "nexus-app-overrides-v1", "icons": {}, "hidden": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("icons", {})
            data.setdefault("hidden", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"schema": "nexus-app-overrides-v1", "icons": {}, "hidden": {}}


def _save_override_registry(state_root: Path, data: Mapping[str, Any]) -> None:
    _atomic_json(_override_registry_path(state_root), data)


def _find_desktop_files(paths: AppCustomizationPaths, app_id: str) -> tuple[Path | None, Path | None]:
    """Return (user_override_path_if_exists, system_or_fallback_path_if_exists)."""
    clean_id = app_id[:-8] if app_id.endswith(".desktop") else app_id
    filename = f"{clean_id}.desktop"
    user_candidate = paths.user_applications_dir / filename
    user_path = user_candidate if user_candidate.is_file() and not user_candidate.is_symlink() else None
    sys_path: Path | None = None
    for base in paths.desktop_entry_dirs:
        base_p = Path(base)
        if base_p.resolve() == paths.user_applications_dir.resolve() if paths.user_applications_dir.exists() and base_p.exists() else base_p == paths.user_applications_dir:
            continue
        cand = base_p / filename
        if cand.is_file():
            sys_path = cand
            break
    return user_path, sys_path


def list_installed_apps(paths: AppCustomizationPaths, state_root: Path | None = None) -> list[dict[str, Any]]:
    """Return merged list of installed .desktop applications with system vs user icon override metadata."""
    system_apps: dict[str, dict[str, Any]] = {}
    user_apps: dict[str, dict[str, Any]] = {}
    user_dir_resolved = paths.user_applications_dir.resolve() if paths.user_applications_dir.exists() else paths.user_applications_dir

    for base in paths.desktop_entry_dirs:
        base_p = Path(base)
        if not base_p.is_dir():
            continue
        is_user = base_p.resolve() == user_dir_resolved
        for entry in sorted(base_p.glob("*.desktop")):
            parsed = _parse_desktop_file(entry)
            if parsed is None:
                continue
            if is_user:
                user_apps[parsed["id"]] = parsed
            elif parsed["id"] not in system_apps:
                system_apps[parsed["id"]] = parsed

    if paths.user_applications_dir.is_dir():
        for entry in sorted(paths.user_applications_dir.glob("*.desktop")):
            parsed = _parse_desktop_file(entry)
            if parsed is not None:
                user_apps[parsed["id"]] = parsed

    reg = _load_override_registry(state_root) if state_root is not None else {"icons": {}, "hidden": {}}
    managed_icons = reg.get("icons") or {}
    managed_hidden = reg.get("hidden") or {}

    all_ids = sorted(set(system_apps) | set(user_apps), key=str.casefold)
    rows: list[dict[str, Any]] = []
    for app_id in all_ids:
        u = user_apps.get(app_id)
        s = system_apps.get(app_id)
        active = u or s
        if active is None:
            continue
        sys_icon = s["icon"] if s else active["icon"]
        has_override = bool(u and ((s and u["icon"] != s["icon"]) or app_id in managed_icons))
        hidden_by_nexus = bool(app_id in managed_hidden and active["noDisplay"])
        rows.append(
            {
                "id": app_id,
                "desktopFile": active["desktopFile"],
                "name": active["name"],
                "icon": active["icon"],
                "systemIcon": sys_icon,
                "hasIconOverride": has_override,
                "noDisplay": bool(active["noDisplay"]),
                "hiddenByNexus": hidden_by_nexus,
                "categories": active["categories"],
                "mimeTypes": active["mimeTypes"],
                "exec": active["exec"],
            }
        )
    return rows


def _has_desktop_config_environment(paths: AppCustomizationPaths) -> bool:
    """True when the config_home looks like a desktop profile (not a config.json-only minimal test sandbox)."""
    return (
        _is_user_regular_file(paths.mimeapps_list)
        or _is_user_regular_file(paths.config_home / "gtk-3.0/settings.ini")
        or (paths.config_home / "hypr/hyprland").is_dir()
    )


def setting_available(setting_id: str, paths: AppCustomizationPaths) -> bool:
    if setting_id in DEFAULT_APP_SPECS:
        return _is_user_regular_file(paths.mimeapps_list)
    if setting_id in DESKTOP_OVERRIDE_SPECS:
        if not _has_desktop_config_environment(paths):
            return False
        # Require at least one discoverable desktop entry dir with .desktop files or existing user dir
        for d in paths.desktop_entry_dirs:
            p = Path(d)
            if p.is_dir() and any(p.glob("*.desktop")):
                return True
        return paths.user_applications_dir.is_dir()
    return False


def choices_for_default_app(setting_id: str, paths: AppCustomizationPaths) -> list[str]:
    spec = DEFAULT_APP_SPECS.get(setting_id)
    if spec is None:
        return []
    mimes = set(spec["mimes"])
    cats = set(spec["categories"])
    apps = list_installed_apps(paths)
    matched: list[str] = []
    for app in apps:
        if app["noDisplay"]:
            continue
        if (mimes & set(app["mimeTypes"])) or (cats & set(app["categories"])):
            matched.append(app["desktopFile"])
    return sorted(set(matched), key=str.casefold)


def read_setting(setting_id: str, paths: AppCustomizationPaths, state_root: Path) -> Any:
    if setting_id in DEFAULT_APP_SPECS:
        if not _is_user_regular_file(paths.mimeapps_list):
            raise AppCustomizationError("source_unavailable", "mimeapps.list is unavailable.")
        text = paths.mimeapps_list.read_text(encoding="utf-8")
        spec = DEFAULT_APP_SPECS[setting_id]
        for mime in spec["mimes"]:
            val = _read_ini_key(text, "Default Applications", mime)
            if val:
                return val.split(";")[0].strip()
        return ""

    if setting_id == "apps.icons.overrides":
        if not setting_available(setting_id, paths):
            raise AppCustomizationError("source_unavailable", "Desktop application directories are unavailable.")
        reg = _load_override_registry(state_root)
        icons_map = reg.get("icons") or {}
        out: list[str] = []
        for app_id in sorted(icons_map):
            user_path, _ = _find_desktop_files(paths, app_id)
            if user_path is not None:
                parsed = _parse_desktop_file(user_path)
                if parsed and parsed["icon"]:
                    out.append(f"{app_id}={parsed['icon']}")
        return out

    if setting_id == "apps.visibility.hiddenApps":
        if not setting_available(setting_id, paths):
            raise AppCustomizationError("source_unavailable", "Desktop application directories are unavailable.")
        reg = _load_override_registry(state_root)
        hidden_map = reg.get("hidden") or {}
        out_hidden: list[str] = []
        for app_id in sorted(hidden_map):
            user_path, _ = _find_desktop_files(paths, app_id)
            if user_path is not None:
                text = user_path.read_text(encoding="utf-8", errors="replace")
                if (_read_ini_key(text, "Desktop Entry", "NoDisplay") or "").lower() == "true":
                    out_hidden.append(app_id)
        return out_hidden

    raise AppCustomizationError("setting_unsupported", f"Unsupported application setting: {setting_id}")


def read_all_settings(paths: AppCustomizationPaths, state_root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sid in ALL_SETTING_IDS:
        if setting_available(sid, paths):
            try:
                out[sid] = read_setting(sid, paths, state_root)
            except AppCustomizationError:
                pass
    return out


def _validate_default_app(value: Any) -> str:
    if not isinstance(value, str):
        raise AppCustomizationError("value_invalid", "Default application must be a .desktop identifier string.")
    cleaned = value.strip()
    if not cleaned:
        return ""
    if not cleaned.endswith(".desktop"):
        cleaned = f"{cleaned}.desktop"
    if not _DESKTOP_FILE_RE.fullmatch(cleaned) or "/" in cleaned or ".." in cleaned:
        raise AppCustomizationError("value_invalid", "Default application must be a valid .desktop filename.")
    return cleaned


def _validate_icon_override_pair(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or "=" not in raw:
        raise AppCustomizationError("value_invalid", "Icon override entries must use the format 'appId=iconNameOrPath'.")
    app_part, icon_part = raw.split("=", 1)
    app_id = app_part.strip()
    if app_id.endswith(".desktop"):
        app_id = app_id[:-8]
    icon_val = icon_part.strip()
    if not app_id or not _DESKTOP_ID_RE.fullmatch(app_id) or ".." in app_id or "/" in app_id:
        raise AppCustomizationError("value_invalid", f"Invalid application identifier: {app_part!r}")
    if not icon_val or not _ICON_VALUE_RE.fullmatch(icon_val):
        raise AppCustomizationError("value_invalid", f"Invalid icon name or path for {app_id}.")
    return app_id, icon_val


def _validate_app_id(raw: str) -> str:
    if not isinstance(raw, str):
        raise AppCustomizationError("value_invalid", "Application identifier must be a string.")
    app_id = raw.strip()
    if app_id.endswith(".desktop"):
        app_id = app_id[:-8]
    if not app_id or not _DESKTOP_ID_RE.fullmatch(app_id) or ".." in app_id or "/" in app_id:
        raise AppCustomizationError("value_invalid", f"Invalid application identifier: {raw!r}")
    return app_id


def validate_setting_value(setting_id: str, value: Any) -> Any:
    if setting_id in DEFAULT_APP_SPECS:
        return _validate_default_app(value)
    if setting_id == "apps.icons.overrides":
        if not isinstance(value, list):
            raise AppCustomizationError("value_invalid", "apps.icons.overrides must be a list of 'appId=icon' strings.")
        seen: dict[str, str] = {}
        for item in value:
            app_id, icon_val = _validate_icon_override_pair(item)
            seen[app_id] = icon_val
        return [f"{k}={seen[k]}" for k in sorted(seen)]
    if setting_id == "apps.visibility.hiddenApps":
        if not isinstance(value, list):
            raise AppCustomizationError("value_invalid", "apps.visibility.hiddenApps must be a list of application IDs.")
        seen_ids = sorted({_validate_app_id(item) for item in value})
        return seen_ids
    raise AppCustomizationError("setting_unsupported", f"Unsupported application setting: {setting_id}")


def _snapshot_file(path: Path, txn_dir: Path, name: str) -> dict[str, Any]:
    if path.is_file() and not path.is_symlink():
        raw = path.read_bytes()
        snap = txn_dir / name
        snap.write_bytes(raw)
        os.chmod(snap, 0o600)
        return {
            "path": str(path),
            "existed": True,
            "snapshot": name,
            "beforeSha256": _sha256_bytes(raw),
        }
    return {
        "path": str(path),
        "existed": False,
        "snapshot": None,
        "beforeSha256": None,
    }


def _finalize_file_meta(entry: dict[str, Any]) -> dict[str, Any]:
    p = Path(entry["path"])
    if p.is_file() and not p.is_symlink():
        entry["existsAfter"] = True
        entry["afterSha256"] = _sha256_bytes(p.read_bytes())
    else:
        entry["existsAfter"] = False
        entry["afterSha256"] = None
    return entry


def _apply_desktop_key_override(
    paths: AppCustomizationPaths,
    app_id: str,
    key: str,
    value: str | None,
    reg_bucket: dict[str, Any],
    txn_dir: Path,
    file_snapshots: dict[str, dict[str, Any]],
) -> None:
    user_path, sys_path = _find_desktop_files(paths, app_id)
    target = paths.user_applications_dir / f"{app_id}.desktop"
    if target.is_symlink():
        raise AppCustomizationError("source_unsupported", f"Refusing to modify symbolic link: {target.name}")
    target_key = str(target)

    if target_key not in file_snapshots:
        file_snapshots[target_key] = _snapshot_file(target, txn_dir, f"desktop-{len(file_snapshots)}.before")

    if value is not None:
        if user_path is not None:
            base_text = user_path.read_text(encoding="utf-8", errors="replace")
            if app_id not in reg_bucket:
                reg_bucket[app_id] = {
                    "createdUserFile": False,
                    "originalValue": _read_ini_key(base_text, "Desktop Entry", key),
                }
        elif sys_path is not None:
            base_text = sys_path.read_text(encoding="utf-8", errors="replace")
            if app_id not in reg_bucket:
                reg_bucket[app_id] = {
                    "createdUserFile": True,
                    "originalValue": _read_ini_key(base_text, "Desktop Entry", key),
                }
        else:
            raise AppCustomizationError("app_not_found", f"No installed .desktop entry was found for '{app_id}'.")
        updated = _set_ini_key(base_text, "Desktop Entry", key, value)
        _atomic_write_text(target, updated, default_mode=0o644)
    else:
        info = reg_bucket.pop(app_id, None)
        if user_path is None:
            return
        if info and info.get("createdUserFile") and sys_path is not None:
            # Remove the NEXUS-created override if no other managed override references it
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        else:
            orig_val = info.get("originalValue") if isinstance(info, dict) else None
            if orig_val is None and sys_path is not None:
                orig_val = _read_ini_key(sys_path.read_text(encoding="utf-8", errors="replace"), "Desktop Entry", key)
            base_text = user_path.read_text(encoding="utf-8", errors="replace")
            updated = _set_ini_key(base_text, "Desktop Entry", key, orig_val)
            _atomic_write_text(target, updated, default_mode=0o644)


def apply_setting(
    paths: AppCustomizationPaths,
    state_root: Path,
    setting_id: str,
    value: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    validated = validate_setting_value(setting_id, value)
    if not setting_available(setting_id, paths):
        raise AppCustomizationError("source_unavailable", f"Target files for {setting_id} are unavailable.")

    current = read_setting(setting_id, paths, state_root)
    if current == validated:
        return {
            "status": "no_changes",
            "settingId": setting_id,
            "value": validated,
            "runtimeVerified": False,
        }

    if dry_run:
        # Verify all referenced apps exist when changing overrides
        if setting_id == "apps.icons.overrides":
            for pair in validated:
                aid, _ = _validate_icon_override_pair(pair)
                u, s = _find_desktop_files(paths, aid)
                if u is None and s is None:
                    raise AppCustomizationError("app_not_found", f"No installed .desktop entry was found for '{aid}'.")
        elif setting_id == "apps.visibility.hiddenApps":
            for aid in validated:
                u, s = _find_desktop_files(paths, aid)
                if u is None and s is None:
                    raise AppCustomizationError("app_not_found", f"No installed .desktop entry was found for '{aid}'.")
        return {
            "status": "dry_run",
            "settingId": setting_id,
            "value": validated,
            "runtimeVerified": False,
        }

    with _state_lock(state_root):
        txn_id = uuid.uuid4().hex
        txn_dir = state_root / "app-customization-transactions" / txn_id
        _ensure_private_dir(txn_dir)
        file_snapshots: dict[str, dict[str, Any]] = {}

        if setting_id in DEFAULT_APP_SPECS:
            target = paths.mimeapps_list
            file_snapshots[str(target)] = _snapshot_file(target, txn_dir, "mimeapps.before")
            text = target.read_text(encoding="utf-8")
            spec = DEFAULT_APP_SPECS[setting_id]
            updated = text
            for mime in spec["mimes"]:
                updated = _set_ini_key(updated, "Default Applications", mime, validated or None)
            _atomic_write_text(target, updated, default_mode=0o644)
        else:
            reg_path = _override_registry_path(state_root)
            file_snapshots[str(reg_path)] = _snapshot_file(reg_path, txn_dir, "registry.before")
            reg = _load_override_registry(state_root)
            try:
                if setting_id == "apps.icons.overrides":
                    desired_map = dict(_validate_icon_override_pair(item) for item in validated)
                    prev_ids = set((reg.get("icons") or {}).keys())
                    for removed_id in sorted(prev_ids - set(desired_map)):
                        # Only delete file if not also tracked in hidden
                        if removed_id in (reg.get("hidden") or {}):
                            reg["icons"][removed_id]["createdUserFile"] = False
                        _apply_desktop_key_override(paths, removed_id, "Icon", None, reg["icons"], txn_dir, file_snapshots)
                    for app_id, icon_val in sorted(desired_map.items()):
                        _apply_desktop_key_override(paths, app_id, "Icon", icon_val, reg["icons"], txn_dir, file_snapshots)
                elif setting_id == "apps.visibility.hiddenApps":
                    desired_set = set(validated)
                    prev_ids = set((reg.get("hidden") or {}).keys())
                    for removed_id in sorted(prev_ids - desired_set):
                        if removed_id in (reg.get("icons") or {}):
                            reg["hidden"][removed_id]["createdUserFile"] = False
                        _apply_desktop_key_override(paths, removed_id, "NoDisplay", None, reg["hidden"], txn_dir, file_snapshots)
                    for app_id in sorted(desired_set):
                        _apply_desktop_key_override(paths, app_id, "NoDisplay", "true", reg["hidden"], txn_dir, file_snapshots)
                _save_override_registry(state_root, reg)
            except Exception:
                # Roll back any files modified during this transaction
                for snap_info in file_snapshots.values():
                    p = Path(snap_info["path"])
                    if snap_info["existed"] and snap_info["snapshot"]:
                        try:
                            _atomic_write_text(p, (txn_dir / snap_info["snapshot"]).read_text(encoding="utf-8"))
                        except Exception:
                            pass
                    elif not snap_info["existed"]:
                        try:
                            p.unlink()
                        except FileNotFoundError:
                            pass
                raise

        finalized = [_finalize_file_meta(info) for info in file_snapshots.values()]
        meta = {
            "schema": "nexus-app-customization-txn-v1",
            "transactionId": txn_id,
            "settingId": setting_id,
            "previousValue": current,
            "newValue": validated,
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "files": finalized,
            "undone": False,
        }
        _atomic_json(txn_dir / "meta.json", meta)

    return {
        "status": "written_to_config",
        "settingId": setting_id,
        "value": validated,
        "previousValue": current,
        "transactionId": txn_id,
        "runtimeVerified": False,
        "runtimeStatus": "xdg-desktop-entries-updated",
    }


def set_app_icon(
    paths: AppCustomizationPaths,
    state_root: Path,
    app_id: str,
    icon_name_or_path: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_id = _validate_app_id(app_id)
    icon_val = str(icon_name_or_path or "").strip()
    if not icon_val or not _ICON_VALUE_RE.fullmatch(icon_val):
        raise AppCustomizationError("value_invalid", "Icon name or path must be a non-empty single-line value.")
    current_list = read_setting("apps.icons.overrides", paths, state_root)
    cur_map = dict(_validate_icon_override_pair(item) for item in current_list)
    cur_map[clean_id] = icon_val
    new_list = [f"{k}={cur_map[k]}" for k in sorted(cur_map)]
    return apply_setting(paths, state_root, "apps.icons.overrides", new_list, dry_run=dry_run)


def reset_app_icon(
    paths: AppCustomizationPaths,
    state_root: Path,
    app_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_id = _validate_app_id(app_id)
    current_list = read_setting("apps.icons.overrides", paths, state_root)
    cur_map = dict(_validate_icon_override_pair(item) for item in current_list)
    if clean_id not in cur_map:
        return {
            "status": "no_changes",
            "settingId": "apps.icons.overrides",
            "appId": clean_id,
            "runtimeVerified": False,
        }
    cur_map.pop(clean_id, None)
    new_list = [f"{k}={cur_map[k]}" for k in sorted(cur_map)]
    res = apply_setting(paths, state_root, "apps.icons.overrides", new_list, dry_run=dry_run)
    res["appId"] = clean_id
    return res


def set_app_hidden(
    paths: AppCustomizationPaths,
    state_root: Path,
    app_id: str,
    hidden: bool,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_id = _validate_app_id(app_id)
    current_list = read_setting("apps.visibility.hiddenApps", paths, state_root)
    cur_set = set(current_list)
    if hidden:
        cur_set.add(clean_id)
    else:
        cur_set.discard(clean_id)
    new_list = sorted(cur_set, key=str.casefold)
    res = apply_setting(paths, state_root, "apps.visibility.hiddenApps", new_list, dry_run=dry_run)
    res["appId"] = clean_id
    res["hidden"] = bool(hidden)
    return res


def undo_transaction(
    paths: AppCustomizationPaths,
    state_root: Path,
    transaction_id: str,
) -> dict[str, Any]:
    _ = paths
    if not _TXN_ID_RE.fullmatch(transaction_id or ""):
        raise AppCustomizationError("undo_snapshot_invalid", "Invalid application customization transaction ID.")
    with _state_lock(state_root):
        txn_dir = state_root / "app-customization-transactions" / transaction_id
        meta_path = txn_dir / "meta.json"
        if not meta_path.is_file():
            raise AppCustomizationError("undo_snapshot_invalid", "The saved application customization snapshot is missing.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("undone"):
            raise AppCustomizationError("undo_already_done", "This application customization change was already undone.")

        files_meta = meta.get("files") or []
        for entry in files_meta:
            p = Path(entry["path"])
            if entry.get("existsAfter"):
                if not p.is_file() or _sha256_bytes(p.read_bytes()) != entry.get("afterSha256"):
                    raise AppCustomizationError("undo_conflict", f"{p.name} changed externally after NEXUS updated it.")
            else:
                if p.exists():
                    raise AppCustomizationError("undo_conflict", f"{p.name} was recreated externally after NEXUS removed it.")

        for entry in files_meta:
            p = Path(entry["path"])
            if entry.get("existed"):
                snap = txn_dir / entry["snapshot"]
                raw = snap.read_bytes()
                if _sha256_bytes(raw) != entry.get("beforeSha256"):
                    raise AppCustomizationError("undo_snapshot_invalid", f"Backup checksum mismatch for {p.name}.")
                _atomic_write_text(p, raw.decode("utf-8"))
            else:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass

        meta["undone"] = True
        meta["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _atomic_json(meta_path, meta)

    return {
        "status": "undo_written_to_config",
        "settingId": meta.get("settingId"),
        "restoredValue": meta.get("previousValue"),
        "transactionId": transaction_id,
        "runtimeVerified": False,
    }
