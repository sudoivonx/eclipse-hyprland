"""Transactional NEXUS adapter for unified desktop appearance, icon themes, GTK 3/4, and KDE/Qt settings."""
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
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Mapping, Sequence
import uuid


class DesktopAppearanceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DesktopAppearancePaths:
    gtk3: Path
    gtk4: Path
    kdeglobals: Path
    icon_search_paths: tuple[Path, ...] = ()
    theme_search_paths: tuple[Path, ...] = ()
    color_scheme_search_paths: tuple[Path, ...] = ()
    sound_search_paths: tuple[Path, ...] = ()
    allow_live_sync: bool = False


SETTING_SPECS: dict[str, dict[str, Any]] = {
    "desktop.icons.theme": {
        "title": "System icon theme",
        "description": "Synchronizes the icon theme across GTK 3, GTK 4, Qt/KDE applications, and desktop portals.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4", "kdeglobals"),
        "gtk_key": "gtk-icon-theme-name",
        "kde_section": "Icons",
        "kde_key": "Theme",
        "gsettings": ("org.gnome.desktop.interface", "icon-theme"),
        "keywords": ["icon", "icons", "icon theme", "ikon", "simge", "tema", "gtk", "kde", "qt", "desktop"],
    },
    "desktop.gtk.theme": {
        "title": "GTK application theme",
        "description": "Controls the visual widget theme used by GTK applications.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3",),
        "gtk_key": "gtk-theme-name",
        "gsettings": ("org.gnome.desktop.interface", "gtk-theme"),
        "keywords": ["gtk", "theme", "tema", "applications", "uygulama", "appearance"],
    },
    "desktop.gtk.preferDark": {
        "title": "Prefer dark theme (GTK 3 & 4)",
        "description": "Requests dark mode across GTK 3, GTK 4, and libadwaita applications.",
        "valueType": "boolean",
        "controlType": "ConfigSwitch",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4"),
        "gtk_key": "gtk-application-prefer-dark-theme",
        "gsettings_color_scheme": True,
        "keywords": ["dark", "theme", "karanlik", "koyu", "gtk", "mode"],
    },
    "desktop.gtk.font": {
        "title": "GTK interface font",
        "description": "Default UI font family and size for GTK 3 and GTK 4 applications (e.g. 'Google Sans Flex, Medium 11').",
        "valueType": "string",
        "controlType": "MaterialTextField",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4"),
        "gtk_key": "gtk-font-name",
        "gsettings": ("org.gnome.desktop.interface", "font-name"),
        "keywords": ["font", "yazi tipi", "gtk", "interface", "typography"],
    },
    "desktop.gtk.animations": {
        "title": "GTK interface animations",
        "description": "Enables or disables toolkit transitions and animations inside GTK 3 and GTK 4 apps.",
        "valueType": "boolean",
        "controlType": "ConfigSwitch",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4"),
        "gtk_key": "gtk-enable-animations",
        "gsettings": ("org.gnome.desktop.interface", "enable-animations"),
        "keywords": ["gtk", "animations", "animasyon", "motion", "performance"],
    },
    "desktop.gtk.decorationLayout": {
        "title": "Window header button layout",
        "description": "Controls minimize, maximize, and close button placement on GTK client-side window headers.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4"),
        "gtk_key": "gtk-decoration-layout",
        "choices": [
            "icon:minimize,maximize,close",
            ":minimize,maximize,close",
            "close,minimize,maximize:",
            "menu:minimize,maximize,close",
            "icon:close",
            ":close",
        ],
        "keywords": ["window", "buttons", "titlebar", "close", "minimize", "maximize", "decoration", "gtk"],
    },
    "desktop.kde.colorScheme": {
        "title": "Qt / KDE color scheme",
        "description": "Selects the active color scheme in kdeglobals for Qt and KDE applications.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("kdeglobals",),
        "kde_section": "General",
        "kde_key": "ColorScheme",
        "keywords": ["kde", "qt", "color", "scheme", "renk", "tema", "palette"],
    },
    "desktop.kde.widgetStyle": {
        "title": "Qt / KDE widget style",
        "description": "Selects the Qt widget style engine (e.g. Darkly, Breeze, Fusion) in kdeglobals.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("kdeglobals",),
        "kde_section": "KDE",
        "kde_key": "widgetStyle",
        "default_choices": ["Darkly", "Breeze", "Fusion", "kvantum", "kvantum-dark", "Oxygen"],
        "keywords": ["kde", "qt", "widget", "style", "darkly", "breeze", "fusion"],
    },
    "desktop.sound.theme": {
        "title": "System sound theme",
        "description": "Synchronizes the desktop event sound theme across GTK 3, GTK 4, and KDE.",
        "valueType": "string",
        "controlType": "StyledComboBox",
        "featureGroup": "desktop-appearance",
        "targets": ("gtk3", "gtk4", "kdeglobals"),
        "gtk_key": "gtk-sound-theme-name",
        "kde_section": "Sounds",
        "kde_key": "Theme",
        "gsettings": ("org.gnome.desktop.sound", "theme-name"),
        "keywords": ["sound", "audio", "ses", "theme", "freedesktop", "notification"],
    },
}

_SECTION_RE = re.compile(r"^\s*\[([^\r\n]+)\]\s*$")
_KV_RE = re.compile(r"^([ \t]*)([^=\r\n#;]+?)([ \t]*=[ \t]*)(.*)$")
_TXN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SAFE_NAME_RE = re.compile(r"^[^\r\n\x00]{1,128}$")
_DECORATION_RE = re.compile(r"^[a-zA-Z,:_ -]{1,96}$")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise DesktopAppearanceError("unsafe_state_directory", "NEXUS state directory is not owned by this user.")


@contextmanager
def _state_lock(state_root: Path):
    locks_dir = state_root / "locks"
    _ensure_private_dir(locks_dir)
    lock_file = locks_dir / "desktop-appearance.lock"
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


def _read_text_safe(path: Path) -> str:
    if not _is_user_regular_file(path):
        raise DesktopAppearanceError("source_unavailable", f"Config file is unavailable or unsafe: {path.name}")
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DesktopAppearanceError("source_unreadable", f"Could not read UTF-8 config file: {path.name}") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    orig_stat = path.stat() if path.exists() and not path.is_symlink() else None
    attrs: dict[str, bytes] = {}
    if orig_stat is not None:
        try:
            for name in os.listxattr(path, follow_symlinks=False):
                attrs[name] = os.getxattr(path, name, follow_symlinks=False)
        except OSError:
            attrs = {}
    fd, tmp_name = tempfile.mkstemp(prefix=f".nexus-{path.name}-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        mode = stat.S_IMODE(orig_stat.st_mode) if orig_stat is not None else 0o644
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        for name, val in attrs.items():
            try:
                os.setxattr(tmp, name, val, follow_symlinks=False)
            except OSError:
                pass
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
    fd, tmp_name = tempfile.mkstemp(prefix=".nexus-da-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
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


def _read_ini_key(text: str, section: str, key: str) -> str | None:
    current_section: str | None = None
    for line in text.splitlines():
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            current_section = m_sec.group(1).strip()
            continue
        if current_section != section:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        m_kv = _KV_RE.match(line)
        if m_kv and m_kv.group(2).strip() == key:
            return m_kv.group(4).strip()
    return None


def _set_ini_key(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    current_section: str | None = None
    section_found = False
    key_updated = False
    insert_index: int | None = None

    for line in lines:
        m_sec = _SECTION_RE.match(line.rstrip("\r\n"))
        if m_sec:
            if current_section == section and not key_updated and insert_index is None:
                insert_index = len(out)
            current_section = m_sec.group(1).strip()
            if current_section == section:
                section_found = True
            out.append(line)
            continue

        if current_section == section and not key_updated:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith(";"):
                m_kv = _KV_RE.match(line.rstrip("\r\n"))
                if m_kv and m_kv.group(2).strip() == key:
                    eol = "\r\n" if line.endswith("\r\n") else "\n"
                    out.append(f"{m_kv.group(1)}{key}={value}{eol}")
                    key_updated = True
                    continue
        out.append(line)

    if not key_updated:
        if section_found:
            idx = insert_index if insert_index is not None else len(out)
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


def _index_theme_has_icon_directories(index_theme: Path) -> bool:
    """Return True if index.theme declares a non-empty Directories= entry under [Icon Theme]."""
    try:
        text = index_theme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    dirs_val = _read_ini_key(text, "Icon Theme", "Directories")
    return bool(dirs_val and dirs_val.strip())


def _is_cursor_only_icon_theme(theme_dir: Path) -> bool:
    """Return True if an icon theme directory only contains cursors (not app/desktop icons)."""
    has_cursor_content = (theme_dir / "cursor.theme").is_file()
    has_non_cursor_dir = False
    try:
        for child in theme_dir.iterdir():
            lower_name = child.name.lower()
            if child.is_dir():
                if lower_name == "cursors" or lower_name.startswith("cursors_") or lower_name.startswith("cursors-"):
                    has_cursor_content = True
                else:
                    has_non_cursor_dir = True
    except OSError:
        return False
    if not has_cursor_content:
        return False
    if not has_non_cursor_dir:
        return True
    # Even if extra non-icon folders exist alongside cursors, cursor-only themes omit Directories= in index.theme.
    index_theme = theme_dir / "index.theme"
    if index_theme.is_file() and not _index_theme_has_icon_directories(index_theme):
        return True
    return False


def scan_icon_themes(search_paths: Sequence[Path]) -> list[str]:
    found: set[str] = set()
    for base in search_paths:
        p = Path(base)
        if not p.is_dir():
            continue
        try:
            for entry in p.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name in ("default", "hicolor", "locolor"):
                    continue
                if not (entry / "index.theme").is_file():
                    continue
                if _is_cursor_only_icon_theme(entry):
                    continue
                found.add(entry.name)
        except OSError:
            continue
    return sorted(found, key=str.casefold)


def scan_gtk_themes(search_paths: Sequence[Path]) -> list[str]:
    found: set[str] = set()
    for base in search_paths:
        p = Path(base)
        if not p.is_dir():
            continue
        try:
            for entry in p.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name in ("Default", "Emacs"):
                    continue
                if (entry / "gtk-3.0").is_dir() or (entry / "gtk-4.0").is_dir() or (entry / "index.theme").is_file():
                    found.add(entry.name)
        except OSError:
            continue
    return sorted(found, key=str.casefold)


def scan_kde_color_schemes(search_paths: Sequence[Path]) -> list[str]:
    found: set[str] = set()
    for base in search_paths:
        p = Path(base)
        if not p.is_dir():
            continue
        try:
            for f in p.glob("*.colors"):
                if f.is_file():
                    found.add(f.stem)
        except OSError:
            continue
    return sorted(found, key=str.casefold)


def scan_sound_themes(search_paths: Sequence[Path]) -> list[str]:
    found: set[str] = {"freedesktop"}
    for base in search_paths:
        p = Path(base)
        if not p.is_dir():
            continue
        try:
            for entry in p.iterdir():
                if entry.is_dir() and (entry / "index.theme").is_file():
                    found.add(entry.name)
        except OSError:
            continue
    return sorted(found, key=str.casefold)


def _target_paths_for_setting(setting_id: str, paths: DesktopAppearancePaths) -> list[tuple[str, Path]]:
    spec = SETTING_SPECS.get(setting_id)
    if spec is None:
        return []
    mapping = {"gtk3": paths.gtk3, "gtk4": paths.gtk4, "kdeglobals": paths.kdeglobals}
    return [(t, mapping[t]) for t in spec["targets"] if t in mapping]


def setting_available(setting_id: str, paths: DesktopAppearancePaths) -> bool:
    """A setting is verified only when at least its primary backing config file exists as a user-owned regular file."""
    targets = _target_paths_for_setting(setting_id, paths)
    if not targets:
        return False
    # Primary target must exist as a regular user-owned file (e.g. gtk-3.0/settings.ini or kdeglobals)
    primary_kind, primary_path = targets[0]
    if _is_user_regular_file(primary_path):
        return True
    # For multi-target settings (like desktop.icons.theme), kdeglobals alone is also sufficient
    if setting_id in ("desktop.icons.theme", "desktop.sound.theme"):
        return any(_is_user_regular_file(p) for _, p in targets)
    return False


def choices_for_setting(setting_id: str, paths: DesktopAppearancePaths) -> list[str] | None:
    spec = SETTING_SPECS.get(setting_id)
    if spec is None:
        return None
    if setting_id == "desktop.icons.theme":
        return scan_icon_themes(paths.icon_search_paths) or None
    if setting_id == "desktop.gtk.theme":
        return scan_gtk_themes(paths.theme_search_paths) or None
    if setting_id == "desktop.kde.colorScheme":
        return scan_kde_color_schemes(paths.color_scheme_search_paths) or None
    if setting_id == "desktop.kde.widgetStyle":
        return list(spec.get("default_choices") or [])
    if setting_id == "desktop.sound.theme":
        return scan_sound_themes(paths.sound_search_paths)
    if "choices" in spec:
        return list(spec["choices"])
    return None


def validate_setting_value(setting_id: str, value: Any) -> Any:
    spec = SETTING_SPECS.get(setting_id)
    if spec is None:
        raise DesktopAppearanceError("setting_unsupported", f"Unsupported desktop appearance setting: {setting_id}")
    vtype = spec["valueType"]
    if vtype == "boolean":
        if not isinstance(value, bool):
            raise DesktopAppearanceError("value_invalid", f"{setting_id} must be a boolean.")
        return value
    if not isinstance(value, str):
        raise DesktopAppearanceError("value_invalid", f"{setting_id} must be a string.")
    cleaned = value.strip()
    if not cleaned or not _SAFE_NAME_RE.fullmatch(cleaned):
        raise DesktopAppearanceError("value_invalid", f"{setting_id} must be a non-empty single-line string.")
    if setting_id == "desktop.gtk.decorationLayout" and not _DECORATION_RE.fullmatch(cleaned):
        raise DesktopAppearanceError("value_invalid", "Window button layout contains unsupported characters.")
    return cleaned


def read_setting(setting_id: str, paths: DesktopAppearancePaths) -> Any:
    spec = SETTING_SPECS.get(setting_id)
    if spec is None:
        raise DesktopAppearanceError("setting_unsupported", f"Unsupported desktop appearance setting: {setting_id}")
    if not setting_available(setting_id, paths):
        raise DesktopAppearanceError("source_unavailable", f"Backing desktop config files for {setting_id} are not available.")

    vtype = spec["valueType"]
    raw_val: str | None = None
    for kind, target in _target_paths_for_setting(setting_id, paths):
        if not _is_user_regular_file(target):
            continue
        text = _read_text_safe(target)
        if kind in ("gtk3", "gtk4") and "gtk_key" in spec:
            raw_val = _read_ini_key(text, "Settings", spec["gtk_key"])
        elif kind == "kdeglobals" and "kde_section" in spec and "kde_key" in spec:
            raw_val = _read_ini_key(text, spec["kde_section"], spec["kde_key"])
        if raw_val is not None:
            break

    if vtype == "boolean":
        if raw_val is None:
            return True if setting_id == "desktop.gtk.animations" else False
        return raw_val.lower() in ("1", "true", "yes", "on")
    return raw_val or ""


def read_all_settings(paths: DesktopAppearancePaths) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for sid, spec in SETTING_SPECS.items():
        if setting_available(sid, paths):
            try:
                val = read_setting(sid, paths)
                if spec["valueType"] == "string" and val == "":
                    continue
                out[sid] = val
            except DesktopAppearanceError:
                pass
    return out


def _sync_gsettings_best_effort(setting_id: str, value: Any) -> bool:
    spec = SETTING_SPECS.get(setting_id) or {}
    if not shutil.which("gsettings"):
        return False
    try:
        if spec.get("gsettings_color_scheme"):
            scheme = "prefer-dark" if value else "default"
            res = subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", scheme],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            return res.returncode == 0
        gs = spec.get("gsettings")
        if gs:
            schema, key = gs
            str_val = "true" if value is True else "false" if value is False else str(value)
            res = subprocess.run(
                ["gsettings", "set", schema, key, str_val],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def apply_setting(
    paths: DesktopAppearancePaths,
    state_root: Path,
    setting_id: str,
    value: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    validated = validate_setting_value(setting_id, value)
    if not setting_available(setting_id, paths):
        raise DesktopAppearanceError("source_unavailable", f"Backing desktop config files for {setting_id} are not available.")

    spec = SETTING_SPECS[setting_id]
    current = read_setting(setting_id, paths)

    # Build planned file updates across all existing targets so cross-toolkit drift is reconciled.
    plans: list[tuple[str, Path, bytes, bytes]] = []
    str_val = "true" if validated is True else "false" if validated is False else str(validated)

    for kind, target in _target_paths_for_setting(setting_id, paths):
        if not _is_user_regular_file(target):
            continue
        before_bytes = target.read_bytes()
        before_text = before_bytes.decode("utf-8")
        if kind in ("gtk3", "gtk4") and "gtk_key" in spec:
            after_text = _set_ini_key(before_text, "Settings", spec["gtk_key"], str_val)
        elif kind == "kdeglobals" and "kde_section" in spec and "kde_key" in spec:
            after_text = _set_ini_key(before_text, spec["kde_section"], spec["kde_key"], str_val)
        else:
            continue
        after_bytes = after_text.encode("utf-8")
        if after_bytes != before_bytes:
            plans.append((kind, target, before_bytes, after_bytes))

    if current == validated and not plans:
        return {
            "status": "no_changes",
            "settingId": setting_id,
            "value": validated,
            "runtimeVerified": False,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "settingId": setting_id,
            "value": validated,
            "targets": [str(p[1]) for p in plans],
            "runtimeVerified": False,
        }

    with _state_lock(state_root):
        txn_id = uuid.uuid4().hex
        txn_dir = state_root / "desktop-appearance-transactions" / txn_id
        _ensure_private_dir(txn_dir)
        files_meta: list[dict[str, Any]] = []
        for kind, target, before_bytes, after_bytes in plans:
            snap = txn_dir / f"{kind}.before"
            snap.write_bytes(before_bytes)
            os.chmod(snap, 0o600)
            files_meta.append(
                {
                    "kind": kind,
                    "path": str(target),
                    "snapshot": snap.name,
                    "beforeSha256": _sha256_bytes(before_bytes),
                    "afterSha256": _sha256_bytes(after_bytes),
                }
            )
        meta = {
            "schema": "nexus-desktop-appearance-txn-v1",
            "transactionId": txn_id,
            "settingId": setting_id,
            "previousValue": current,
            "newValue": validated,
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "files": files_meta,
            "undone": False,
        }
        _atomic_json(txn_dir / "meta.json", meta)

        written: list[tuple[Path, bytes]] = []
        try:
            for _, target, before_bytes, after_bytes in plans:
                _atomic_write_text(target, after_bytes.decode("utf-8"))
                written.append((target, before_bytes))
        except Exception as exc:
            for target, before_bytes in reversed(written):
                try:
                    _atomic_write_text(target, before_bytes.decode("utf-8"))
                except Exception:
                    pass
            raise DesktopAppearanceError("write_failed", f"Failed to update {setting_id}; previous files were restored.") from exc

        gsettings_synced = False
        if paths.allow_live_sync:
            gsettings_synced = _sync_gsettings_best_effort(setting_id, validated)

    return {
        "status": "written_to_config",
        "settingId": setting_id,
        "value": validated,
        "previousValue": current,
        "transactionId": txn_id,
        "gsettingsSynced": gsettings_synced,
        "runtimeVerified": False,
        "runtimeStatus": "gsettings-and-ini-synced" if gsettings_synced else "ini-written-pending-app-reload",
    }


def undo_transaction(
    paths: DesktopAppearancePaths,
    state_root: Path,
    transaction_id: str,
) -> dict[str, Any]:
    if not _TXN_ID_RE.fullmatch(transaction_id or ""):
        raise DesktopAppearanceError("undo_snapshot_invalid", "Invalid desktop appearance transaction identifier.")
    with _state_lock(state_root):
        txn_dir = state_root / "desktop-appearance-transactions" / transaction_id
        meta_path = txn_dir / "meta.json"
        if not meta_path.is_file():
            raise DesktopAppearanceError("undo_snapshot_invalid", "The saved desktop appearance snapshot is missing.")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("undone"):
            raise DesktopAppearanceError("undo_already_done", "This desktop appearance change was already undone.")

        files_meta = meta.get("files") or []
        restores: list[tuple[Path, bytes]] = []
        for entry in files_meta:
            target = Path(entry["path"])
            snap = txn_dir / entry["snapshot"]
            if not snap.is_file():
                raise DesktopAppearanceError("undo_snapshot_invalid", "A desktop appearance backup file is missing.")
            before_bytes = snap.read_bytes()
            if _sha256_bytes(before_bytes) != entry["beforeSha256"]:
                raise DesktopAppearanceError("undo_snapshot_invalid", "A desktop appearance backup file failed checksum verification.")
            if not target.is_file() or _sha256_bytes(target.read_bytes()) != entry["afterSha256"]:
                raise DesktopAppearanceError("undo_conflict", f"{target.name} changed externally after NEXUS updated it.")
            restores.append((target, before_bytes))

        for target, before_bytes in restores:
            _atomic_write_text(target, before_bytes.decode("utf-8"))

        prev_val = meta.get("previousValue")
        if paths.allow_live_sync and "settingId" in meta and (isinstance(prev_val, bool) or (isinstance(prev_val, str) and prev_val.strip())):
            _sync_gsettings_best_effort(meta["settingId"], prev_val)

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
