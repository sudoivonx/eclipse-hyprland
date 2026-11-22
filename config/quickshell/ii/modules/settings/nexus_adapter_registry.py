"""Layer 6 Open Adapter Registry & Capability Verification for NEXUS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
import configparser
from dataclasses import dataclass, field, replace
import datetime as dt
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import tomllib
from typing import Any, Callable, Iterable, Mapping, Sequence
import uuid

import nexus_app_customization_adapter as app_customization_adapter
import nexus_cursor_adapter as cursor_adapter
import nexus_desktop_appearance_adapter as desktop_appearance_adapter
import nexus_hyprland_godmode_adapter as hyprland_godmode_adapter
import nexus_hyprland_options_adapter as hyprland_options_adapter
import nexus_motion_profile_adapter as motion_adapter
import nexus_window_glow_adapter as window_glow_adapter
import nexus_window_rule_adapter as window_rule_adapter


_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))

DEFAULT_CONFIG = _CONFIG_HOME / "illogical-impulse/config.json"
DEFAULT_CONFIG_QML = _CONFIG_HOME / "quickshell/ii/modules/common/Config.qml"
DEFAULT_STATE = _STATE_HOME / "aegis/nexus"
DEFAULT_CURSOR_SEARCH_PATHS: tuple[Path, ...] = (
    _DATA_HOME / "icons",
    Path.home() / ".icons",
    Path("/usr/share/icons"),
    Path("/usr/share/pixmaps"),
)

_HYPRLAND_MANAGED_KEYS = frozenset(
    {
        "general.gaps_in",
        "general.gaps_out",
        "decoration.rounding",
    }
)
_TXN_ID_RE = re.compile(r"^[0-9a-f]{32}$|^\d{8}T\d{6}-[0-9a-f]{8}$")


class AdapterRegistryError(Exception):
    """Structured error raised by Layer 6 adapters and registry operations."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AdapterContext:
    """Explicit path and runtime injection context for safe isolation."""

    config_path: Path = DEFAULT_CONFIG
    config_qml_path: Path | None = DEFAULT_CONFIG_QML
    state_root: Path = DEFAULT_STATE
    config_home: Path = _CONFIG_HOME
    data_home: Path = _DATA_HOME
    cursor_paths: cursor_adapter.CursorPaths | None = None
    cursor_search_paths: tuple[Path, ...] = DEFAULT_CURSOR_SEARCH_PATHS
    window_rule_paths: window_rule_adapter.WindowRulePaths | None = None
    window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None
    motion_profile_paths: motion_adapter.MotionProfilePaths | None = None
    hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None
    hypr_custom_dir: Path | None = None
    hypr_main_dir: Path | None = None
    game_mode_helper: Path | None = None
    game_mode_detector: Path | None = None
    game_mode_state_file: Path | None = None
    matugen_config: Path | None = None
    matugen_colors: Path | None = None
    gtk3_ini: Path | None = None
    gtk4_ini: Path | None = None
    kdeglobals: Path | None = None
    kde_material_you_conf: Path | None = None
    translations_dirs: tuple[Path, ...] = ()
    desktop_entry_dirs: tuple[Path, ...] = ()
    hyprctl: str = "hyprctl"
    enable_live_hyprctl: bool = False
    hyprctl_runner: Callable[[list[str]], Any] | None = None
    allow_script_execution: bool = False

    def effective_hypr_custom_dir(self) -> Path:
        return self.hypr_custom_dir or (self.config_home / "hypr/custom")

    def effective_hypr_main_dir(self) -> Path:
        return self.hypr_main_dir or (self.config_home / "hypr/hyprland")

    def effective_cursor_paths(self) -> cursor_adapter.CursorPaths:
        if self.cursor_paths is not None:
            return self.cursor_paths
        return cursor_adapter.CursorPaths(
            env=self.config_home / "environment.d/90-cursor.conf",
            hypr_env=self.effective_hypr_main_dir() / "env.lua",
            gtk3=self.gtk3_ini or (self.config_home / "gtk-3.0/settings.ini"),
            gtk4=self.gtk4_ini or (self.config_home / "gtk-4.0/settings.ini"),
        )

    def effective_window_rule_paths(self) -> window_rule_adapter.WindowRulePaths:
        if self.window_rule_paths is not None:
            return self.window_rule_paths
        custom = self.effective_hypr_custom_dir()
        return window_rule_adapter.WindowRulePaths(
            helper=custom / "aegis-custom-opacity.py",
            rules=custom / "rules.lua",
            state=custom / "aegis-custom-opacity.json",
        )

    def effective_window_glow_paths(self) -> window_glow_adapter.WindowGlowPaths:
        if self.window_glow_paths is not None:
            return self.window_glow_paths
        custom = self.effective_hypr_custom_dir()
        return window_glow_adapter.WindowGlowPaths(
            helper=custom / "aegis-glowctl.py",
            state=custom / "glow-settings.json",
            config=custom / "glow.lua",
        )

    def effective_motion_profile_paths(self) -> motion_adapter.MotionProfilePaths:
        if self.motion_profile_paths is not None:
            return self.motion_profile_paths
        custom = self.effective_hypr_custom_dir()
        return motion_adapter.MotionProfilePaths(
            helper=custom / "aegis-motion-profile.py",
        )

    def effective_hyprland_options_paths(self) -> hyprland_options_adapter.HyprlandOptionsPaths:
        if self.hyprland_options_paths is not None:
            return self.hyprland_options_paths
        return hyprland_options_adapter.HyprlandOptionsPaths(
            source=self.effective_hypr_main_dir() / "general.lua",
            hyprctl=self.hyprctl,
        )

    def effective_desktop_appearance_paths(self) -> desktop_appearance_adapter.DesktopAppearancePaths:
        is_live = self.enable_live_hyprctl
        icon_paths = tuple(self.cursor_search_paths) if self.cursor_search_paths else (self.data_home / "icons",)
        theme_paths = (
            (self.data_home / "themes", Path.home() / ".themes", Path("/usr/share/themes"))
            if is_live
            else (self.data_home / "themes",)
        )
        color_scheme_paths = (
            (self.data_home / "color-schemes", Path("/usr/share/color-schemes"))
            if is_live
            else (self.data_home / "color-schemes",)
        )
        sound_paths = (
            (self.data_home / "sounds", Path("/usr/share/sounds"))
            if is_live
            else (self.data_home / "sounds",)
        )
        return desktop_appearance_adapter.DesktopAppearancePaths(
            gtk3=self.gtk3_ini or (self.config_home / "gtk-3.0/settings.ini"),
            gtk4=self.gtk4_ini or (self.config_home / "gtk-4.0/settings.ini"),
            kdeglobals=self.kdeglobals or (self.config_home / "kdeglobals"),
            icon_search_paths=icon_paths,
            theme_search_paths=theme_paths,
            color_scheme_search_paths=color_scheme_paths,
            sound_search_paths=sound_paths,
            allow_live_sync=is_live,
        )

    def effective_app_customization_paths(self) -> app_customization_adapter.AppCustomizationPaths:
        dirs = tuple(self.desktop_entry_dirs) if self.desktop_entry_dirs else (self.data_home / "applications",)
        return app_customization_adapter.AppCustomizationPaths(
            mimeapps_list=self.config_home / "mimeapps.list",
            user_applications_dir=self.data_home / "applications",
            desktop_entry_dirs=dirs,
            config_home=self.config_home,
        )

    def effective_hyprland_godmode_paths(self) -> hyprland_godmode_adapter.HyprlandGodModePaths:
        main_dir = self.effective_hypr_main_dir()
        return hyprland_godmode_adapter.HyprlandGodModePaths(
            main_general=main_dir / "general.lua",
            main_colors=main_dir / "colors.lua",
            custom_dir=self.effective_hypr_custom_dir(),
            hyprctl=self.hyprctl,
            allow_live_hyprctl=self.enable_live_hyprctl,
            hyprctl_runner=self.hyprctl_runner,
        )

    @classmethod
    def from_defaults(
        cls,
        *,
        enable_live_hyprctl: bool = False,
        **overrides: Any,
    ) -> "AdapterContext":
        config_home = Path(overrides.get("config_home", _CONFIG_HOME))
        state_home = Path(overrides.get("state_home", _STATE_HOME))
        data_home = Path(overrides.get("data_home", _DATA_HOME))
        quickshell_root = Path(
            overrides.get("quickshell_root", config_home / "quickshell/ii")
        )
        base = cls(
            config_path=config_home / "illogical-impulse/config.json",
            config_qml_path=quickshell_root / "modules/common/Config.qml",
            state_root=state_home / "aegis/nexus",
            config_home=config_home,
            data_home=data_home,
            cursor_search_paths=(
                data_home / "icons",
                Path.home() / ".icons",
                Path("/usr/share/icons"),
                Path("/usr/share/pixmaps"),
            ),
            hypr_custom_dir=config_home / "hypr/custom",
            hypr_main_dir=config_home / "hypr/hyprland",
            game_mode_helper=quickshell_root / "scripts/game-mode/pulsar_game_mode.py",
            game_mode_detector=quickshell_root / "scripts/game-mode/pulsar_game_detector.py",
            game_mode_state_file=state_home / "quickshell/user/game-mode.json",
            matugen_config=config_home / "matugen/config.toml",
            matugen_colors=state_home / "quickshell/user/generated/colors.json",
            gtk3_ini=config_home / "gtk-3.0/settings.ini",
            gtk4_ini=config_home / "gtk-4.0/settings.ini",
            kdeglobals=config_home / "kdeglobals",
            kde_material_you_conf=config_home / "kde-material-you-colors/config.conf",
            translations_dirs=(quickshell_root / "translations",),
            desktop_entry_dirs=(
                data_home / "applications",
                Path("/usr/share/applications"),
            ),
            enable_live_hyprctl=enable_live_hyprctl,
        )
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields}
        return replace(base, **filtered)

    @classmethod
    def default_live(cls, **overrides: Any) -> "AdapterContext":
        overrides.setdefault("enable_live_hyprctl", True)
        return cls.from_defaults(**overrides)

    @classmethod
    def isolated(cls, root: Path, **overrides: Any) -> "AdapterContext":
        root_path = Path(root)
        config_home = Path(overrides.pop("config_home", root_path / ".config"))
        state_home = Path(overrides.pop("state_home", root_path / ".local/state"))
        data_home = Path(overrides.pop("data_home", root_path / ".local/share"))
        quickshell_root = Path(
            overrides.pop("quickshell_root", config_home / "quickshell/ii")
        )
        hypr_custom_dir = Path(
            overrides.pop("hypr_custom_dir", config_home / "hypr/custom")
        )
        hypr_main_dir = Path(
            overrides.pop("hypr_main_dir", config_home / "hypr/hyprland")
        )
        gtk3_ini = Path(overrides.pop("gtk3_ini", config_home / "gtk-3.0/settings.ini"))
        gtk4_ini = Path(overrides.pop("gtk4_ini", config_home / "gtk-4.0/settings.ini"))
        base = cls(
            config_path=config_home / "illogical-impulse/config.json",
            config_qml_path=quickshell_root / "modules/common/Config.qml",
            state_root=state_home / "aegis/nexus",
            config_home=config_home,
            data_home=data_home,
            cursor_paths=cursor_adapter.CursorPaths(
                env=config_home / "environment.d/90-cursor.conf",
                hypr_env=hypr_main_dir / "env.lua",
                gtk3=gtk3_ini,
                gtk4=gtk4_ini,
            ),
            cursor_search_paths=(data_home / "icons",),
            window_rule_paths=window_rule_adapter.WindowRulePaths(
                helper=hypr_custom_dir / "aegis-custom-opacity.py",
                rules=hypr_custom_dir / "rules.lua",
                state=hypr_custom_dir / "aegis-custom-opacity.json",
            ),
            window_glow_paths=window_glow_adapter.WindowGlowPaths(
                helper=hypr_custom_dir / "aegis-glowctl.py",
                state=hypr_custom_dir / "glow-settings.json",
                config=hypr_custom_dir / "glow.lua",
            ),
            motion_profile_paths=motion_adapter.MotionProfilePaths(
                helper=hypr_custom_dir / "aegis-motion-profile.py",
            ),
            hyprland_options_paths=hyprland_options_adapter.HyprlandOptionsPaths(
                source=hypr_main_dir / "general.lua",
                hyprctl=str(overrides.get("hyprctl", "hyprctl")),
            ),
            hypr_custom_dir=hypr_custom_dir,
            hypr_main_dir=hypr_main_dir,
            game_mode_helper=quickshell_root / "scripts/game-mode/pulsar_game_mode.py",
            game_mode_detector=quickshell_root / "scripts/game-mode/pulsar_game_detector.py",
            game_mode_state_file=state_home / "quickshell/user/game-mode.json",
            matugen_config=config_home / "matugen/config.toml",
            matugen_colors=state_home / "quickshell/user/generated/colors.json",
            gtk3_ini=gtk3_ini,
            gtk4_ini=gtk4_ini,
            kdeglobals=config_home / "kdeglobals",
            kde_material_you_conf=config_home / "kde-material-you-colors/config.conf",
            translations_dirs=(quickshell_root / "translations",),
            desktop_entry_dirs=(data_home / "applications",),
            enable_live_hyprctl=False,
            allow_script_execution=False,
        )
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields}
        return replace(base, **filtered)


@dataclass(frozen=True)
class AdapterCapabilities:
    read: bool
    apply: bool
    dry_run: bool
    rollback: bool
    runtime_verify: bool

    @property
    def dryRun(self) -> bool:
        return self.dry_run

    @property
    def runtimeVerify(self) -> bool:
        return self.runtime_verify

    @classmethod
    def from_any(cls, raw: "AdapterCapabilities | Mapping[str, Any]") -> "AdapterCapabilities":
        if isinstance(raw, cls):
            return raw
        return cls(
            read=bool(raw.get("read", False)),
            apply=bool(raw.get("apply", False)),
            dry_run=bool(raw.get("dry_run", raw.get("dryRun", False))),
            rollback=bool(raw.get("rollback", False)),
            runtime_verify=bool(raw.get("runtime_verify", raw.get("runtimeVerify", False))),
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "read": self.read,
            "apply": self.apply,
            "dryRun": self.dry_run,
            "rollback": self.rollback,
            "runtimeVerify": self.runtime_verify,
        }


class AdapterDescriptor:
    def __init__(
        self,
        adapter_id: str | None = None,
        display_name: str | None = None,
        source_kind: str | None = None,
        supported_domains: Iterable[str] = (),
        read_only: bool | None = None,
        capabilities: AdapterCapabilities | Mapping[str, Any] | None = None,
        *,
        adapterId: str | None = None,
        displayName: str | None = None,
        sourceKind: str | None = None,
        supportedDomains: Iterable[str] | None = None,
        readOnly: bool | None = None,
    ) -> None:
        self.adapter_id = str(adapter_id if adapter_id is not None else (adapterId or ""))
        self.display_name = str(display_name if display_name is not None else (displayName or self.adapter_id))
        self.source_kind = str(source_kind if source_kind is not None else (sourceKind or self.adapter_id))
        doms = supportedDomains if supportedDomains is not None else supported_domains
        self.supported_domains = tuple(str(d) for d in doms)
        self.read_only = bool(read_only if read_only is not None else (readOnly if readOnly is not None else False))
        self.capabilities = AdapterCapabilities.from_any(capabilities or {})

    @property
    def adapterId(self) -> str:
        return self.adapter_id

    @property
    def displayName(self) -> str:
        return self.display_name

    @property
    def sourceKind(self) -> str:
        return self.source_kind

    @property
    def supportedDomains(self) -> tuple[str, ...]:
        return self.supported_domains

    @property
    def readOnly(self) -> bool:
        return self.read_only

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapterId": self.adapter_id,
            "displayName": self.display_name,
            "sourceKind": self.source_kind,
            "supportedDomains": list(self.supported_domains),
            "readOnly": self.read_only,
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True)
class CapabilityProbeResult:
    readable: bool
    applicable: bool
    verified: bool
    verified_read: bool
    verified_apply: bool
    manageable: bool
    runtime_verified: bool
    reason: str
    verification_reason: str
    adapter_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def verifiedRead(self) -> bool:
        return self.verified_read

    @property
    def verifiedApply(self) -> bool:
        return self.verified_apply

    @property
    def runtimeVerified(self) -> bool:
        return self.runtime_verified

    @property
    def verificationReason(self) -> str:
        return self.verification_reason

    @property
    def adapterId(self) -> str:
        return self.adapter_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "readable": self.readable,
            "applicable": self.applicable,
            "verified": self.verified,
            "verifiedRead": self.verified_read,
            "verifiedApply": self.verified_apply,
            "manageable": self.manageable,
            "runtimeVerified": self.runtime_verified,
            "reason": self.reason,
            "verificationReason": self.verification_reason,
            "adapterId": self.adapter_id,
            "details": dict(self.details),
        }


def make_probe_result(
    *,
    verified_read: bool,
    verified_apply: bool,
    reason: str,
    verification_reason: str | None = None,
    runtime_verified: bool = False,
    adapter_id: str = "",
    details: dict[str, Any] | None = None,
) -> CapabilityProbeResult:
    """Construct a fail-closed CapabilityProbeResult with unified aliases."""
    manageable = bool(verified_read and verified_apply)
    msg = verification_reason or reason
    return CapabilityProbeResult(
        readable=bool(verified_read),
        applicable=bool(verified_apply),
        verified=manageable,
        verified_read=bool(verified_read),
        verified_apply=bool(verified_apply),
        manageable=manageable,
        runtime_verified=bool(runtime_verified and manageable),
        reason=reason,
        verification_reason=msg,
        adapter_id=adapter_id,
        details=dict(details or {}),
    )


class AdapterInterface(ABC):
    """Explicit Layer 6 adapter contract."""

    @property
    @abstractmethod
    def descriptor(self) -> AdapterDescriptor:
        ...

    @abstractmethod
    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        ...

    @abstractmethod
    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        ...

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        raise AdapterRegistryError(
            "undo_unsupported",
            f"{self.descriptor.adapter_id} does not support undo.",
        )


class BaseAdapter(AdapterInterface):
    """Shared safety helpers for built-in and custom adapters."""

    def _require_writable_adapter(self) -> None:
        if self.descriptor.read_only or not self.descriptor.capabilities.apply:
            raise AdapterRegistryError(
                "read_only_adapter",
                f"Adapter '{self.descriptor.adapter_id}' is read-only and cannot apply changes.",
            )

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        self._require_writable_adapter()
        raise AdapterRegistryError(
            "validate_not_implemented",
            f"Adapter '{self.descriptor.adapter_id}' does not implement validate_change.",
        )

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        self._require_writable_adapter()
        raise AdapterRegistryError(
            "apply_not_implemented",
            f"Adapter '{self.descriptor.adapter_id}' does not implement apply_change.",
        )

    @staticmethod
    def _is_sensitive(setting_spec: dict[str, Any] | None) -> bool:
        return bool(setting_spec and setting_spec.get("sensitive"))

    @staticmethod
    def _check_regular_file(path: Path) -> tuple[bool, os.stat_result | None, str]:
        try:
            st = path.lstat()
        except FileNotFoundError:
            return False, None, "file_missing"
        except OSError:
            return False, None, "file_unreadable"
        if not stat.S_ISREG(st.st_mode):
            return False, st, "file_not_regular"
        return True, st, "ok"


# ---------------------------------------------------------------------------
# Pure-Python helpers (JSON atomic write, xattrs, Lua hl.config parsing)
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _xattr_snapshot(path: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError as exc:
        if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
            return result
        raise AdapterRegistryError(
            "metadata_read_failed", "File metadata could not be read safely."
        ) from exc
    for name in names:
        try:
            result[name] = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            raise AdapterRegistryError(
                "metadata_read_failed", "File metadata could not be read safely."
            ) from exc
    return result


def _apply_xattrs(source_attrs: dict[str, bytes], target: Path) -> None:
    try:
        current = {
            name: os.getxattr(target, name, follow_symlinks=False)
            for name in os.listxattr(target, follow_symlinks=False)
        }
    except OSError as exc:
        if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP) and not source_attrs:
            return
        raise AdapterRegistryError(
            "metadata_copy_failed", "File extended attributes could not be preserved."
        ) from exc
    for name in current.keys() - source_attrs.keys():
        if name == "security.selinux":
            continue
        try:
            os.removexattr(target, name, follow_symlinks=False)
        except OSError as exc:
            raise AdapterRegistryError(
                "metadata_copy_failed", "File extended attributes could not be preserved."
            ) from exc
    for name, value in source_attrs.items():
        if current.get(name) == value:
            continue
        try:
            os.setxattr(target, name, value, follow_symlinks=False)
        except OSError as exc:
            raise AdapterRegistryError(
                "metadata_copy_failed", "File extended attributes could not be preserved."
            ) from exc


def _ensure_private_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        st = path.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise AdapterRegistryError(
                "unsafe_state_directory",
                "NEXUS state directory is not owned by the current user.",
            )
    except AdapterRegistryError:
        raise
    except OSError as exc:
        raise AdapterRegistryError(
            "unsafe_state_directory", "NEXUS state directory could not be prepared."
        ) from exc


def _atomic_private_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".nexus-state-", dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(data)
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


def _flatten_json_leaves(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON objects to dotted leaf keys (lists and empty dicts are leaves)."""
    leaves: dict[str, Any] = {}
    for key, val in obj.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict) and val:
            leaves.update(_flatten_json_leaves(val, dotted))
        else:
            leaves[dotted] = val
    return leaves


def _infer_json_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _same_json_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return isinstance(value, bool)
    if isinstance(expected, int) and not isinstance(expected, bool):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(expected, float):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if isinstance(expected, str):
        return isinstance(value, str)
    if isinstance(expected, list):
        return isinstance(value, list)
    if isinstance(expected, dict):
        return isinstance(value, dict)
    return value is None and expected is None


def _is_complex_object_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)


def _human_title_from_id(setting_id: str) -> str:
    leaf = setting_id.split(".")[-1]
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    spaced = spaced.replace("_", " ").replace("-", " ").strip()
    if not spaced:
        return setting_id
    return spaced[0].upper() + spaced[1:].lower()


_QUICKSHELL_PREFIX_MAP: tuple[tuple[str, str, str], ...] = (
    ("appearance.pulsarAudioVisualizer.", "audio", "audio.visualizer"),
    ("appearance.fonts.", "interface", "interface.fonts"),
    ("appearance.wallpaperTheming.", "appearance", "appearance.wallpaper-theming"),
    ("appearance.extraBackgroundTint", "appearance", "appearance.theming"),
    ("appearance.fakeScreenRounding", "quick", "quick.appearance"),
    ("appearance.palette.", "quick", "quick.palette"),
    ("appearance.transparency.", "quick", "quick.transparency"),
    ("background.transitions.", "motion", "motion.transitions"),
    ("background.wallpaperPath", "quick", "quick.wallpaper"),
    ("background.parallax.", "background", "background.parallax"),
    ("background.widgets.clock.", "background", "background.clock"),
    ("background.widgets.weather.", "background", "background.weather"),
    ("background.", "background", "background.general"),
    ("bar.weather.", "services", "services.weather"),
    ("notifications.liquidGlass.", "effects", "effects.liquid-glass"),
    ("notifications.", "interface", "interface.notifications"),
    ("audio.protection.", "general", "general.audio"),
    ("battery.", "general", "general.battery"),
    ("calendar.", "general", "general.calendar"),
    ("conflictKiller.", "general", "general.conflict-killer"),
    ("language.", "general", "general.language"),
    ("media.", "general", "general.media"),
    ("policies.", "general", "general.policies"),
    ("sounds.", "general", "general.sounds"),
    ("time.pomodoro.", "general", "general.pomodoro"),
    ("time.", "general", "general.time"),
    ("workSafety.", "general", "general.work-safety"),
    ("light.", "quick", "quick.light"),
    ("interactions.", "input", "input.interactions"),
    ("cheatsheet.", "interface", "interface.cheatsheet"),
    ("crosshair.", "interface", "interface.crosshair"),
    ("dock.", "interface", "interface.dock"),
    ("launcher.", "interface", "interface.launcher"),
    ("lock.", "interface", "interface.lock"),
    ("osd.", "interface", "interface.osd"),
    ("osk.", "interface", "interface.osk"),
    ("overlay.", "interface", "interface.overlay"),
    ("overview.", "interface", "interface.overview"),
    ("regionSelector.", "interface", "interface.region-selector"),
    ("sidebar.", "interface", "interface.sidebar"),
    ("tray.", "interface", "interface.tray"),
    ("wallpaperSelector.", "interface", "interface.wallpaper-selector"),
    ("panelFamily", "waffles", "waffles.panel-family"),
    ("ai.", "services", "services.ai"),
    ("apps.", "services", "services.apps"),
    ("musicRecognition.", "services", "services.music-recognition"),
    ("networking.", "services", "services.networking"),
    ("resources.", "services", "services.resources"),
    ("screenRecord.", "services", "services.save-paths"),
    ("screenSnip.", "services", "services.save-paths"),
    ("search.", "services", "services.search"),
    ("updates.", "services", "services.updates"),
    ("windows.", "windows", "windows.general"),
    ("gameMode.", "gaming", "gaming.game-mode"),
)


def map_quickshell_namespace(dotted: str) -> tuple[str, str]:
    """Map known Config.qml namespaces to coherent (domain, featureGroup), preserving unknown domains dynamically."""
    parts = [p for p in str(dotted or "").split(".") if p]
    if not parts:
        return "general", "general"
    for prefix, domain, feature_group in _QUICKSHELL_PREFIX_MAP:
        if prefix.endswith("."):
            if dotted.startswith(prefix):
                return domain, feature_group
        elif dotted == prefix or dotted.startswith(prefix + "."):
            return domain, feature_group
    if parts[0] == "bar":
        sub = parts[1] if len(parts) >= 3 else "general"
        return "bar", f"bar.{sub}"
    if parts[0] == "waffles":
        sub = parts[1] if len(parts) >= 3 else "general"
        return "waffles", f"waffles.{sub}"
    default_fg = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return parts[0], default_fg


# ---------------------------------------------------------------------------
# 1. ConfigJsonAdapter (pure stdlib, zero import of nexus-settings.py)
# ---------------------------------------------------------------------------

class ConfigJsonAdapter(BaseAdapter):
    """Transactional atomic JSON adapter for config.json."""

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="config-json",
        display_name="Quickshell Config JSON",
        source_kind="config-json",
        supported_domains=(
            "appearance",
            "bar",
            "background",
            "general",
            "interface",
            "services",
            "audio",
            "windows",
            "ai",
            "dock",
            "launcher",
        ),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True,
            apply=True,
            dry_run=True,
            rollback=True,
            runtime_verify=False,
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    @staticmethod
    def _read_config(path: Path) -> tuple[dict[str, Any], bytes, os.stat_result]:
        try:
            st = path.lstat()
        except FileNotFoundError as exc:
            raise AdapterRegistryError(
                "config_missing", "The configuration JSON file does not exist."
            ) from exc
        except OSError as exc:
            raise AdapterRegistryError(
                "config_unreadable", "The configuration JSON file could not be read."
            ) from exc
        if not stat.S_ISREG(st.st_mode):
            raise AdapterRegistryError(
                "config_not_regular", "The configuration source is not a regular file."
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AdapterRegistryError(
                "config_unreadable", "The configuration JSON file could not be read."
            ) from exc
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AdapterRegistryError(
                "config_invalid", "The configuration source is not valid JSON."
            ) from exc
        if not isinstance(obj, dict):
            raise AdapterRegistryError(
                "config_invalid", "The configuration JSON root must be an object."
            )
        return obj, raw, st

    @staticmethod
    def _get_leaf(obj: dict[str, Any], path: str) -> Any:
        cur: Any = obj
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                raise AdapterRegistryError(
                    "setting_missing_in_config_json",
                    f"Setting '{path}' is missing in config.json.",
                )
            cur = cur[part]
        if isinstance(cur, dict) and cur:
            raise AdapterRegistryError(
                "setting_not_leaf",
                f"Setting '{path}' resolves to a nested object rather than a leaf.",
            )
        return cur

    @staticmethod
    def _set_leaf(obj: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        target: Any = obj
        for part in parts[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                raise AdapterRegistryError(
                    "setting_path_invalid",
                    f"Setting path '{path}' does not match config.json structure.",
                )
            target = child
        if parts[-1] not in target:
            raise AdapterRegistryError(
                "setting_missing_in_config_json",
                f"Setting '{path}' is missing in config.json.",
            )
        target[parts[-1]] = value

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        if not context.config_path.exists():
            return []
        try:
            obj, _, _ = self._read_config(context.config_path)
        except AdapterRegistryError:
            return []
        leaves = _flatten_json_leaves(obj)
        items: list[dict[str, Any]] = []
        for path in sorted(leaves):
            val = leaves[path]
            vtype = _infer_json_value_type(val)
            complex_list = _is_complex_object_list(val)
            domain, feature_group = map_quickshell_namespace(path)
            items.append(
                {
                    "id": path,
                    "title": _human_title_from_id(path),
                    "description": f"Quickshell configuration key {path}.",
                    "valueType": vtype,
                    "source": "illogical-impulse/config.json",
                    "sourceKind": "config-json",
                    "adapter": self.descriptor.adapter_id,
                    "path": path,
                    "controlType": (
                        "ConfigSwitch"
                        if vtype == "boolean"
                        else "ConfigSpinBox"
                        if vtype == "integer"
                        else "ConfigSlider"
                        if vtype == "number"
                        else "list-editor"
                        if vtype == "array"
                        else "MaterialTextArea"
                    ),
                    "risk": "low",
                    "sensitive": False,
                    "applyMethod": "Quickshell watches the config file; runtime effect is not independently verified",
                    "profileSupported": not complex_list,
                    "resetSupported": not complex_list,
                    "keywords": sorted({p.lower() for p in path.split(".")}),
                    "semantics": {
                        "domainHints": [domain],
                        "featureGroup": feature_group,
                        "componentHint": "modules/common/Config.qml",
                        "targetApp": "quickshell",
                        "tags": ["config-json"] + (["complex-object-list"] if complex_list else []),
                    },
                }
            )
        return items

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        setting_path = str(setting_spec.get("path") or setting_spec.get("id") or "")
        if not setting_path:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="setting_path_missing",
                adapter_id=self.descriptor.adapter_id,
            )
        try:
            obj, _, st = self._read_config(context.config_path)
            val = self._get_leaf(obj, setting_path)
        except AdapterRegistryError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                adapter_id=self.descriptor.adapter_id,
            )

        if _is_complex_object_list(val):
            return make_probe_result(
                verified_read=True,
                verified_apply=False,
                reason="schema_complex_editor_required",
                verification_reason="Complex object list (list<var>) requires a dedicated schema editor.",
                adapter_id=self.descriptor.adapter_id,
                details={"valueType": "array", "complexList": True},
            )

        writable = (
            st.st_uid == os.getuid()
            and os.access(context.config_path, os.W_OK)
            and os.access(context.config_path.parent, os.W_OK)
        )
        if not writable:
            return make_probe_result(
                verified_read=True,
                verified_apply=False,
                reason="config_not_writable",
                verification_reason="config.json or its parent directory is not writable.",
                adapter_id=self.descriptor.adapter_id,
            )

        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"valueType": _infer_json_value_type(val)},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        obj, _, _ = self._read_config(context.config_path)
        if setting_spec is None:
            return {"values": _flatten_json_leaves(obj), "runtimeVerified": False}
        setting_path = str(setting_spec.get("path") or setting_spec.get("id") or "")
        val = self._get_leaf(obj, setting_path)
        if self._is_sensitive(setting_spec):
            return {"redacted": True, "hasValue": bool(val), "runtimeVerified": False}
        return {"path": setting_path, "value": val, "runtimeVerified": False}

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        setting_path = str(setting_spec.get("path") or setting_spec.get("id") or "")
        if not setting_path:
            raise AdapterRegistryError("setting_path_missing", "Setting path is required.")
        obj, raw, st = self._read_config(context.config_path)
        current = self._get_leaf(obj, setting_path)
        if _is_complex_object_list(current):
            raise AdapterRegistryError(
                "schema_complex_editor_required",
                "Complex object-list settings are not editable by ConfigJsonAdapter.",
            )
        if not _same_json_type(desired_value, current):
            raise AdapterRegistryError(
                "value_type_mismatch",
                f"Desired value type does not match existing type for '{setting_path}'.",
            )
        if isinstance(desired_value, float) and not math.isfinite(desired_value):
            raise AdapterRegistryError("value_invalid", "Numeric value must be finite.")
        if not (
            st.st_uid == os.getuid()
            and os.access(context.config_path, os.W_OK)
            and os.access(context.config_path.parent, os.W_OK)
        ):
            raise AdapterRegistryError(
                "config_not_writable", "config.json is not writable."
            )
        return {
            "valid": True,
            "path": setting_path,
            "changed": current != desired_value,
            "beforeSha256": _sha256_bytes(raw),
        }

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        setting_path = str(setting_spec.get("path") or setting_spec.get("id") or "")
        plan = self.validate_change(setting_spec, desired_value, context)
        if not plan["changed"]:
            return {"status": "no_changes", "changedCount": 0, "runtimeVerified": False}
        if dry_run:
            return {"status": "dry_run", "changedCount": 1, "runtimeVerified": False}
        if setting_spec.get("risk") == "confirmation-required" and not confirm_risk:
            raise AdapterRegistryError(
                "risk_confirmation_required",
                f"Setting '{setting_path}' requires risk confirmation before applying.",
            )

        obj, original_raw, original_stat = self._read_config(context.config_path)
        before_hash = _sha256_bytes(original_raw)
        if before_hash != plan["beforeSha256"]:
            raise AdapterRegistryError(
                "config_changed_concurrently",
                "config.json changed while preparing the update.",
            )

        updated_obj = json.loads(original_raw.decode("utf-8"))
        self._set_leaf(updated_obj, setting_path, desired_value)

        indent = 2
        for line in original_raw.decode("utf-8").splitlines()[1:]:
            match = re.match(r'^(\s+)["\w]', line)
            if match:
                indent = len(match.group(1))
                break
        newline = "\r\n" if b"\r\n" in original_raw else "\n"
        suffix = newline if original_raw.endswith((b"\n", b"\r")) else ""
        candidate = (
            (json.dumps(updated_obj, ensure_ascii=False, indent=indent) + suffix)
            .replace("\n", newline)
            .encode("utf-8")
        )
        json.loads(candidate.decode("utf-8"))
        after_hash = _sha256_bytes(candidate)
        if after_hash == before_hash:
            return {"status": "no_changes", "changedCount": 0, "runtimeVerified": False}

        undo_root = context.state_root / "undo"
        _ensure_private_dir(context.state_root)
        _ensure_private_dir(undo_root)
        txn_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        txn_dir = undo_root / txn_id
        _ensure_private_dir(txn_dir)
        snapshot = txn_dir / "config.json"

        source_attrs = _xattr_snapshot(context.config_path)
        shutil.copy2(context.config_path, snapshot, follow_symlinks=False)
        os.chown(snapshot, original_stat.st_uid, original_stat.st_gid)
        os.chmod(snapshot, stat.S_IMODE(original_stat.st_mode))
        _apply_xattrs(source_attrs, snapshot)

        index_path = undo_root / "index.json"
        index_rows: list[dict[str, Any]] = []
        if index_path.exists():
            try:
                loaded_idx = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(loaded_idx, dict) and isinstance(loaded_idx.get("transactions"), list):
                    index_rows = loaded_idx["transactions"]
            except (OSError, UnicodeError, json.JSONDecodeError):
                index_rows = []
        row = {
            "id": txn_id,
            "action": f"set:{setting_path}",
            "changedIds": [str(setting_spec.get("id") or setting_path)],
            "beforeSha256": before_hash,
            "afterSha256": after_hash,
            "status": "pending",
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        index_rows.append(row)
        _atomic_private_json(index_path, {"schema": "nexus-undo-v1", "transactions": index_rows[-20:]})

        temp: Path | None = None
        try:
            current_raw = context.config_path.read_bytes()
            if _sha256_bytes(current_raw) != before_hash:
                raise AdapterRegistryError(
                    "config_changed_concurrently",
                    "config.json changed while preparing the update.",
                )
            fd, temp_name = tempfile.mkstemp(
                prefix=".nexus-config-", dir=context.config_path.parent
            )
            temp = Path(temp_name)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(temp, original_stat.st_uid, original_stat.st_gid)
            shutil.copystat(context.config_path, temp, follow_symlinks=False)
            os.utime(
                temp,
                ns=(original_stat.st_atime_ns, time.time_ns()),
                follow_symlinks=False,
            )
            _apply_xattrs(source_attrs, temp)
            os.replace(temp, context.config_path)
            temp = None
            parent_fd = os.open(
                context.config_path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            row["status"] = "complete"
            _atomic_private_json(
                index_path, {"schema": "nexus-undo-v1", "transactions": index_rows[-20:]}
            )
        except Exception:
            if temp is not None:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
            current_hash = (
                _sha256_bytes(context.config_path.read_bytes())
                if context.config_path.exists()
                else ""
            )
            if current_hash == before_hash:
                index_rows = [r for r in index_rows if r.get("id") != txn_id]
                _atomic_private_json(
                    index_path, {"schema": "nexus-undo-v1", "transactions": index_rows[-20:]}
                )
                shutil.rmtree(txn_dir, ignore_errors=True)
            raise

        return {
            "status": "written_to_config",
            "changedCount": 1,
            "transactionId": txn_id,
            "undoId": txn_id,
            "runtimeVerified": False,
            "runtimeStatus": "pending-existing-application-reload",
        }

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(transaction_id, str) or not _TXN_ID_RE.fullmatch(transaction_id):
            raise AdapterRegistryError("undo_snapshot_invalid", "Invalid undo transaction ID.")
        undo_root = context.state_root / "undo"
        index_path = undo_root / "index.json"
        if not index_path.is_file():
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo index is unavailable.")
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo index is invalid.") from exc
        rows = index_data.get("transactions") if isinstance(index_data, dict) else None
        if not isinstance(rows, list):
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo index is invalid.")
        row = next((r for r in rows if isinstance(r, dict) and r.get("id") == transaction_id), None)
        if row is None or row.get("status") != "complete" or row.get("undone"):
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo transaction is unavailable.")

        _, current_raw, current_stat = self._read_config(context.config_path)
        if _sha256_bytes(current_raw) != row.get("afterSha256"):
            raise AdapterRegistryError(
                "undo_conflict",
                "config.json changed after this action; undo was stopped.",
            )
        snapshot = undo_root / transaction_id / "config.json"
        if not snapshot.is_file():
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo snapshot file is missing.")
        snapshot_raw = snapshot.read_bytes()
        if _sha256_bytes(snapshot_raw) != row.get("beforeSha256"):
            raise AdapterRegistryError("undo_snapshot_invalid", "Undo snapshot failed checksum check.")
        if dry_run:
            return {"status": "dry_run", "changedCount": len(row.get("changedIds", [])), "runtimeVerified": False}

        snap_attrs = _xattr_snapshot(snapshot)
        snap_stat = snapshot.stat()
        fd, temp_name = tempfile.mkstemp(prefix=".nexus-restore-", dir=context.config_path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "wb", closefd=True) as stream:
                stream.write(snapshot_raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(temp, snap_stat.st_uid, snap_stat.st_gid)
            shutil.copystat(snapshot, temp, follow_symlinks=False)
            _apply_xattrs(snap_attrs, temp)
            os.replace(temp, context.config_path)
            parent_fd = os.open(
                context.config_path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        except Exception:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise
        row["undone"] = True
        row["undoneAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _atomic_private_json(index_path, {"schema": "nexus-undo-v1", "transactions": rows[-20:]})
        return {
            "status": "undo_written_to_config",
            "transactionId": transaction_id,
            "runtimeVerified": False,
        }


# ---------------------------------------------------------------------------
# 2-6. Wrappers for the 5 Existing NEXUS Adapters
# ---------------------------------------------------------------------------

class CursorAdapterWrapper(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="cursor-adapter",
        display_name="Cursor Theme & Size Adapter",
        source_kind="cursor-adapter",
        supported_domains=("input", "pointer", "appearance", "cursor"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True, apply=True, dry_run=True, rollback=True, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        themes = cursor_adapter.discover_themes(context.cursor_search_paths)
        return [
            {
                "id": "cursor.theme",
                "title": "Cursor theme",
                "description": "Choose an installed pointer theme synchronized across environment.d, Hyprland, and GTK.",
                "valueType": "string",
                "source": "environment.d/90-cursor.conf, Hyprland env.lua, GTK 3/4 settings.ini",
                "sourceKind": "cursor-adapter",
                "adapter": "cursor-adapter",
                "path": "cursor.theme",
                "controlType": "combo",
                "risk": "reversible",
                "sensitive": False,
                "applyMethod": "Saved to the canonical environment file and synchronized to Hyprland and GTK settings.",
                "profileSupported": True,
                "resetSupported": True,
                "choices": themes,
                "keywords": ["cursor", "pointer", "theme", "imlec", "imleç"],
                "semantics": {
                    "domainHints": ["input", "pointer", "appearance"],
                    "featureGroup": "cursor-appearance",
                    "componentHint": "modules/settings/CursorConfig.qml",
                    "targetApp": None,
                    "tags": ["mirror-synced", "cursor", "gtk", "hyprland"],
                },
            },
            {
                "id": "cursor.size",
                "title": "Cursor size",
                "description": "Pointer size synchronized across environment.d, Hyprland, and GTK.",
                "valueType": "integer",
                "source": "environment.d/90-cursor.conf, Hyprland env.lua, GTK 3/4 settings.ini",
                "sourceKind": "cursor-adapter",
                "adapter": "cursor-adapter",
                "path": "cursor.size",
                "controlType": "number",
                "risk": "reversible",
                "sensitive": False,
                "applyMethod": "Saved to the canonical environment file and synchronized to Hyprland and GTK settings.",
                "profileSupported": True,
                "resetSupported": True,
                "limits": {
                    "minimum": cursor_adapter.MIN_CURSOR_SIZE,
                    "maximum": cursor_adapter.MAX_CURSOR_SIZE,
                },
                "keywords": ["cursor", "pointer", "size", "imlec", "imleç"],
                "semantics": {
                    "domainHints": ["input", "pointer", "appearance"],
                    "featureGroup": "cursor-appearance",
                    "componentHint": "modules/settings/CursorConfig.qml",
                    "targetApp": None,
                    "tags": ["mirror-synced", "cursor", "gtk", "hyprland"],
                },
            },
        ]

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        paths = context.effective_cursor_paths()
        themes = cursor_adapter.discover_themes(context.cursor_search_paths)
        try:
            state = cursor_adapter.read_cursor_state(paths)
        except cursor_adapter.CursorAdapterError as exc:
            diag = cursor_adapter.cursor_mirror_diagnostic(paths, context.cursor_search_paths)
            is_conflict = diag.get("conflictingMirrorCount", 0) > 0 or (
                "differ" in str(exc).lower()
            )
            reason = "cursor_state_conflict" if is_conflict else "cursor_state_unavailable"
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=reason,
                verification_reason=str(exc),
                runtime_verified=False,
                adapter_id=self.descriptor.adapter_id,
                details={
                    **diag,
                    "installedThemeCount": len(themes),
                },
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={
                "installedThemeCount": len(themes),
                "reconciliationAvailable": False,
                "mirrorsMatch": True,
                "size": state["size"],
            },
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_cursor_paths()
        try:
            state = cursor_adapter.read_cursor_state(paths)
        except cursor_adapter.CursorAdapterError as exc:
            raise AdapterRegistryError("cursor_state_conflict", str(exc)) from exc
        themes = cursor_adapter.discover_themes(context.cursor_search_paths)
        if setting_spec and setting_spec.get("id") == "cursor.theme":
            return {"value": state["theme"], "themes": themes, "runtimeVerified": False}
        if setting_spec and setting_spec.get("id") == "cursor.size":
            return {"value": state["size"], "runtimeVerified": False}
        return {**state, "themes": themes, "runtimeVerified": False}

    def _resolve_target_pair(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> tuple[str, int]:
        paths = context.effective_cursor_paths()
        try:
            current = cursor_adapter.read_cursor_state(paths)
        except cursor_adapter.CursorAdapterError as exc:
            raise AdapterRegistryError("cursor_state_conflict", str(exc)) from exc
        if isinstance(desired_value, dict):
            theme = desired_value.get("theme", current["theme"])
            size = desired_value.get("size", current["size"])
            return theme, size
        sid = str(setting_spec.get("id") or setting_spec.get("path") or "")
        if sid.endswith("theme"):
            return desired_value, current["size"]
        if sid.endswith("size"):
            return current["theme"], desired_value
        raise AdapterRegistryError(
            "cursor_value_invalid",
            "Cursor update requires either a theme/size dict or a cursor.theme / cursor.size setting.",
        )

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        paths = context.effective_cursor_paths()
        theme, size = self._resolve_target_pair(setting_spec, desired_value, context)
        try:
            res = cursor_adapter.apply_cursor_state(
                paths,
                context.state_root,
                theme,
                size,
                dry_run=True,
                search_paths=context.cursor_search_paths,
            )
            return {"valid": True, **res}
        except cursor_adapter.CursorAdapterError as exc:
            raise AdapterRegistryError("cursor_state_conflict", str(exc)) from exc

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_cursor_paths()
        theme, size = self._resolve_target_pair(setting_spec, desired_value, context)
        try:
            return cursor_adapter.apply_cursor_state(
                paths,
                context.state_root,
                theme,
                size,
                dry_run=dry_run,
                search_paths=context.cursor_search_paths,
            )
        except cursor_adapter.CursorAdapterError as exc:
            raise AdapterRegistryError("cursor_state_conflict", str(exc)) from exc

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_cursor_paths()
        if dry_run:
            return {"status": "dry_run", "runtimeVerified": False}
        try:
            return cursor_adapter.undo_cursor_state(paths, context.state_root, transaction_id)
        except cursor_adapter.CursorAdapterError as exc:
            raise AdapterRegistryError("cursor_undo_failed", str(exc)) from exc


class WindowRuleAdapterWrapper(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="window-rule-adapter",
        display_name="Custom Window Rules Adapter",
        source_kind="window-rule-adapter",
        supported_domains=("windows", "apps", "window-rules"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True, apply=True, dry_run=True, rollback=True, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        return [
            {
                "id": "integration.custom-window-rules",
                "title": "Custom window rules",
                "description": "Manage exact-match Hyprland window opacity rules via nexus_window_rule_adapter.",
                "valueType": "array",
                "source": "custom/rules.lua, custom/aegis-custom-opacity.py",
                "sourceKind": "window-rule-adapter",
                "adapter": "window-rule-adapter",
                "path": "windowRules.customOpacity",
                "controlType": "custom-editor",
                "risk": "confirmation-required",
                "sensitive": True,
                "applyMethod": "Validated and applied through nexus_window_rule_adapter with Hyprland reload.",
                "profileSupported": True,
                "resetSupported": True,
                "keywords": ["window", "rules", "opacity", "class", "title", "aegis"],
                "semantics": {
                    "domainHints": ["windows", "apps", "window-rules"],
                    "featureGroup": "per-app-window-rules",
                    "componentHint": "modules/settings/AdvancedConfig.qml",
                    "targetApp": "per-window",
                    "tags": ["app-targeting", "rules.lua", "sensitive"],
                },
            }
        ]

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        paths = context.effective_window_rule_paths()
        try:
            rules = window_rule_adapter.read_window_rules(paths)
        except window_rule_adapter.WindowRuleAdapterError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                adapter_id=self.descriptor.adapter_id,
            )
        # Redacted: NEVER expose class or title strings in probe details.
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"ruleCount": len(rules), "redacted": True},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_window_rule_paths()
        try:
            rules = window_rule_adapter.read_window_rules(paths)
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc
        return {"ruleCount": len(rules), "redacted": True, "runtimeVerified": False}

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        paths = context.effective_window_rule_paths()
        try:
            normalized = window_rule_adapter.validate_window_rules(desired_value)
            res = window_rule_adapter.apply_window_rules(
                paths, context.state_root, normalized, confirm_risk=False, dry_run=True
            )
            return {"valid": True, "ruleCount": len(normalized), **res}
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_window_rule_paths()
        try:
            return window_rule_adapter.apply_window_rules(
                paths,
                context.state_root,
                desired_value,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_window_rule_paths()
        try:
            return window_rule_adapter.undo_window_rules(
                paths,
                context.state_root,
                transaction_id,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


class WindowGlowAdapterWrapper(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="window-glow-adapter",
        display_name="Window Glow Adapter",
        source_kind="window-glow-adapter",
        supported_domains=("windows", "effects", "glow"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True, apply=True, dry_run=True, rollback=True, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        return [
            {
                "id": "integration.window-glow",
                "title": "Window glow",
                "description": "Manage Hyprland window glow/shadow profile via nexus_window_glow_adapter.",
                "valueType": "object",
                "source": "custom/glow.lua, custom/glow-settings.json, custom/aegis-glowctl.py",
                "sourceKind": "window-glow-adapter",
                "adapter": "window-glow-adapter",
                "path": "windowGlow.settings",
                "controlType": "custom-editor",
                "risk": "confirmation-required",
                "sensitive": False,
                "applyMethod": "Validated and committed through nexus_window_glow_adapter with Hyprland reload.",
                "profileSupported": True,
                "resetSupported": True,
                "keywords": ["window", "glow", "shadow", "aegis"],
                "semantics": {
                    "domainHints": ["windows", "effects", "glow"],
                    "featureGroup": "window-glow",
                    "componentHint": "modules/settings/AdvancedConfig.qml",
                    "targetApp": None,
                    "tags": ["hyprland-reload", "aegis"],
                },
            }
        ]

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        paths = context.effective_window_glow_paths()
        try:
            summary = window_glow_adapter.read_window_glow(paths)
        except window_glow_adapter.WindowGlowAdapterError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                adapter_id=self.descriptor.adapter_id,
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"fieldCount": summary.get("fieldCount", 0), "redacted": True},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_window_glow_paths()
        try:
            return window_glow_adapter.read_window_glow(paths)
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        paths = context.effective_window_glow_paths()
        try:
            res = window_glow_adapter.apply_window_glow(
                paths, context.state_root, desired_value, confirm_risk=False, dry_run=True
            )
            return {"valid": True, **res}
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_window_glow_paths()
        try:
            return window_glow_adapter.apply_window_glow(
                paths,
                context.state_root,
                desired_value,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_window_glow_paths()
        try:
            return window_glow_adapter.undo_window_glow(
                paths,
                context.state_root,
                transaction_id,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


class MotionProfileAdapterWrapper(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="motion-profile-adapter",
        display_name="Motion Profile Adapter",
        source_kind="motion-profile-adapter",
        supported_domains=("motion", "animations", "effects"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True, apply=True, dry_run=True, rollback=True, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        return [
            {
                "id": "integration.motion-profile",
                "title": "Motion profile",
                "description": "Manage Hyprland motion animation profile (off, light, full).",
                "valueType": "string",
                "source": "custom/general.lua, custom/aegis-motion-profile.py",
                "sourceKind": "motion-profile-adapter",
                "adapter": "motion-profile-adapter",
                "path": "motionProfile",
                "controlType": "combo",
                "risk": "confirmation-required",
                "sensitive": False,
                "applyMethod": "Applied via nexus_motion_profile_adapter with helper SHA-256 verification.",
                "profileSupported": True,
                "resetSupported": True,
                "choices": ["off", "light", "full"],
                "keywords": ["motion", "animation", "profile", "wobble", "aegis"],
                "semantics": {
                    "domainHints": ["motion", "animations"],
                    "featureGroup": "motion-animations",
                    "componentHint": "modules/settings/AdvancedConfig.qml",
                    "targetApp": None,
                    "tags": ["animations", "profile"],
                },
            }
        ]

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        paths = context.effective_motion_profile_paths()
        ok, _, reason = self._check_regular_file(paths.helper)
        if not ok:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="motion_helper_unavailable",
                verification_reason=f"Motion profile helper unavailable ({reason}).",
                adapter_id=self.descriptor.adapter_id,
            )
        try:
            # Safe read-only "get" invocation only (never "apply").
            profile = motion_adapter.read_motion_profile(paths)
        except motion_adapter.MotionProfileAdapterError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                adapter_id=self.descriptor.adapter_id,
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"profile": profile, "choices": ["off", "light", "full"]},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_motion_profile_paths()
        try:
            profile = motion_adapter.read_motion_profile(paths)
        except motion_adapter.MotionProfileAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc
        return {"profile": profile, "choices": ["off", "light", "full"], "runtimeVerified": False}

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        paths = context.effective_motion_profile_paths()
        try:
            profile = motion_adapter.validate_motion_profile(desired_value)
            res = motion_adapter.apply_motion_profile(
                paths, context.state_root, profile, confirm_risk=False, dry_run=True
            )
            return {"valid": True, "profile": profile, **res}
        except motion_adapter.MotionProfileAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_motion_profile_paths()
        try:
            return motion_adapter.apply_motion_profile(
                paths,
                context.state_root,
                desired_value,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_motion_profile_paths()
        try:
            return motion_adapter.undo_motion_profile(
                paths,
                context.state_root,
                transaction_id,
                confirm_risk=confirm_risk,
                dry_run=dry_run,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


class HyprlandOptionsAdapterWrapper(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="hyprland-options-adapter",
        display_name="Hyprland Window Options Adapter",
        source_kind="hyprland-options-adapter",
        supported_domains=("windows", "layout", "hyprland"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True, apply=True, dry_run=True, rollback=True, runtime_verify=True
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    @contextmanager
    def _with_hyprctl_runner(self, context: AdapterContext):
        runner = context.hyprctl_runner
        if runner is None:
            yield
            return
        original_run = hyprland_options_adapter.subprocess.run

        def _wrapped_run(cmd, *args, **kwargs):
            res = runner(list(cmd))
            if isinstance(res, subprocess.CompletedProcess):
                return res
            if isinstance(res, tuple) and len(res) == 3:
                rc, stdout, stderr = res
                return subprocess.CompletedProcess(cmd, int(rc), str(stdout), str(stderr))
            raise AdapterRegistryError(
                "hyprctl_runner_invalid",
                "Injected hyprctl_runner returned an unsupported result.",
            )

        hyprland_options_adapter.subprocess.run = _wrapped_run
        try:
            yield
        finally:
            hyprland_options_adapter.subprocess.run = original_run

    @staticmethod
    def _can_query_hyprctl(
        paths: hyprland_options_adapter.HyprlandOptionsPaths, context: AdapterContext
    ) -> bool:
        return bool(
            context.enable_live_hyprctl
            or context.hyprctl_runner is not None
            or paths.hyprctl != "hyprctl"
        )

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        limits = hyprland_options_adapter.option_metadata()
        titles = {
            "hyprland.general.gaps_in": "Window gap inside",
            "hyprland.general.gaps_out": "Window gap outside",
            "hyprland.decoration.rounding": "Window corner rounding",
        }
        descriptions = {
            "hyprland.general.gaps_in": "Inner gap between tiled windows in Hyprland.",
            "hyprland.general.gaps_out": "Outer gap between tiled windows and monitor edges in Hyprland.",
            "hyprland.decoration.rounding": "Window corner radius in Hyprland decoration.",
        }
        results: list[dict[str, Any]] = []
        for setting_id, spec in sorted(hyprland_options_adapter.OPTION_SPECS.items()):
            results.append(
                {
                    "id": setting_id,
                    "title": titles.get(setting_id, _human_title_from_id(setting_id)),
                    "description": descriptions.get(setting_id, ""),
                    "valueType": "integer",
                    "source": "hyprland/general.lua",
                    "sourceKind": "hyprland-options-adapter",
                    "adapter": "hyprland-options-adapter",
                    "path": spec["option"],
                    "controlType": "ConfigSpinBox",
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": "Live Hyprland eval with atomic Lua persistence and live readback verification.",
                    "profileSupported": True,
                    "resetSupported": True,
                    "limits": limits.get(setting_id),
                    "keywords": sorted(
                        set(setting_id.split(".") + [spec["lua_key"], "hyprland", "windows"])
                    ),
                    "semantics": {
                        "domainHints": ["windows", "layout", "hyprland"],
                        "featureGroup": "window-geometry",
                        "componentHint": "modules/settings/AdvancedConfig.qml",
                        "targetApp": None,
                        "tags": ["live-verified", "hyprctl", "lua"],
                    },
                }
            )
        return results

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        paths = context.effective_hyprland_options_paths()
        setting_id = str(setting_spec.get("id") or "")
        if setting_id and setting_id not in hyprland_options_adapter.OPTION_SPECS:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="setting_unsupported",
                verification_reason=f"Setting '{setting_id}' is not managed by hyprland-options-adapter.",
                adapter_id=self.descriptor.adapter_id,
            )

        try:
            raw, _ = hyprland_options_adapter._read_regular_source(paths.source)
            source_values = hyprland_options_adapter._parse_source(raw)
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                adapter_id=self.descriptor.adapter_id,
            )

        if not self._can_query_hyprctl(paths, context):
            detail_val = source_values.get(setting_id) if setting_id else source_values
            return make_probe_result(
                verified_read=True,
                verified_apply=False,
                reason="live_hyprctl_disabled",
                verification_reason="Live Hyprland IPC probing is disabled in this context.",
                runtime_verified=False,
                adapter_id=self.descriptor.adapter_id,
                details={"sourceValue": detail_val, "liveProbeDisabled": True},
            )

        try:
            with self._with_hyprctl_runner(context):
                values = hyprland_options_adapter.read_options(paths)
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            return make_probe_result(
                verified_read=True,
                verified_apply=False,
                reason=exc.code,
                verification_reason=str(exc),
                runtime_verified=False,
                adapter_id=self.descriptor.adapter_id,
                details={"sourceValues": source_values},
            )

        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            verification_reason="ok",
            runtime_verified=True,
            adapter_id=self.descriptor.adapter_id,
            details={
                "value": values.get(setting_id) if setting_id else values,
                "limits": hyprland_options_adapter.option_metadata().get(setting_id),
            },
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_hyprland_options_paths()
        if not self._can_query_hyprctl(paths, context):
            try:
                raw, _ = hyprland_options_adapter._read_regular_source(paths.source)
                values = hyprland_options_adapter._parse_source(raw)
            except hyprland_options_adapter.HyprlandOptionsError as exc:
                raise AdapterRegistryError(exc.code, str(exc)) from exc
            if setting_spec and setting_spec.get("id") in values:
                return {
                    "value": values[setting_spec["id"]],
                    "runtimeVerified": False,
                }
            return {"values": values, "runtimeVerified": False}

        try:
            with self._with_hyprctl_runner(context):
                values = hyprland_options_adapter.read_options(paths)
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc
        if setting_spec and setting_spec.get("id") in values:
            return {"value": values[setting_spec["id"]], "runtimeVerified": True}
        return {"values": values, "runtimeVerified": True}

    def _desired_map(
        self, setting_spec: dict[str, Any], desired_value: Any
    ) -> dict[str, int]:
        if isinstance(desired_value, dict):
            return desired_value
        setting_id = str(setting_spec.get("id") or "")
        if not setting_id:
            raise AdapterRegistryError(
                "setting_unsupported", "Hyprland option ID is required."
            )
        return {setting_id: desired_value}

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        paths = context.effective_hyprland_options_paths()
        if not self._can_query_hyprctl(paths, context):
            raise AdapterRegistryError(
                "hyprland_unavailable",
                "Live Hyprland IPC is disabled in this context.",
            )
        desired_map = self._desired_map(setting_spec, desired_value)
        try:
            with self._with_hyprctl_runner(context):
                plan = hyprland_options_adapter.validate_apply(paths, desired_map)
                return {"valid": True, **plan}
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_hyprland_options_paths()
        if not self._can_query_hyprctl(paths, context):
            raise AdapterRegistryError(
                "hyprland_unavailable",
                "Live Hyprland IPC is disabled in this context.",
            )
        desired_map = self._desired_map(setting_spec, desired_value)
        try:
            with self._with_hyprctl_runner(context):
                return hyprland_options_adapter.apply_options(
                    paths, context.state_root, desired_map, dry_run=dry_run
                )
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def undo_change(
        self,
        transaction_id: str,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        paths = context.effective_hyprland_options_paths()
        if not self._can_query_hyprctl(paths, context):
            raise AdapterRegistryError(
                "hyprland_unavailable",
                "Live Hyprland IPC is disabled in this context.",
            )
        try:
            with self._with_hyprctl_runner(context):
                return hyprland_options_adapter.undo_options(
                    paths, context.state_root, transaction_id, dry_run=dry_run
                )
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


# ---------------------------------------------------------------------------
# 7. AegisScriptReviewAdapter (Read-only static/file probing ONLY)
# ---------------------------------------------------------------------------

class AegisScriptReviewAdapter(BaseAdapter):
    """Read-only capability & health probe for unadapted script-backed integrations."""

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="script-backed",
        display_name="Unadapted Aegis/Pulsar Script Review Adapter",
        source_kind="script-backed",
        supported_domains=("effects", "windows", "gaming", "integrations"),
        read_only=True,
        capabilities=AdapterCapabilities(
            read=True, apply=False, dry_run=False, rollback=False, runtime_verify=False
        ),
    )

    _SPECS: dict[str, dict[str, Any]] = {
        "integration.acrylic-blur": {
            "title": "Acrylic blur",
            "helper": "aegis-glassctl.py",
            "target": "general.lua",
            "begin": "-- AEGIS ACRYLIC GLASS BEGIN",
            "end": "-- AEGIS ACRYLIC GLASS END",
            "blocker": "aegis-glassctl.py writes custom/general.lua non-atomically without a shared lock against aegis-window-effects.py and aegis-motion-profile.py, and executes hyprctl reload.",
            "domains": ["effects", "windows"],
            "featureGroup": "window-blur-effects",
        },
        "integration.window-effects": {
            "title": "Window opacity and depth",
            "helper": "aegis-window-effects.py",
            "target": "general.lua",
            "begin": "-- AEGIS WINDOW EFFECTS BEGIN",
            "end": "-- AEGIS WINDOW EFFECTS END",
            "blocker": "aegis-window-effects.py writes custom/general.lua non-atomically without a shared lock against aegis-glassctl.py and would overwrite live wobble settings.",
            "domains": ["effects", "windows"],
            "featureGroup": "window-blur-effects",
        },
        "integration.opacity-rules": {
            "title": "Opaque window exceptions",
            "helper": "aegis-opacity-rules.py",
            "target": "rules.lua",
            "state_json": "aegis-opacity-rules.json",
            "begin": "-- AEGIS OPACITY OPTIONS BEGIN",
            "end": "-- AEGIS OPACITY OPTIONS END",
            "blocker": "aegis-opacity-rules.py shares custom/rules.lua with aegis-pip-floatctl.py and aegis-custom-opacity.py without a shared lock.",
            "domains": ["windows", "apps"],
            "featureGroup": "per-app-window-rules",
        },
        "integration.picture-in-picture": {
            "title": "Picture in picture",
            "helper": "aegis-pip-floatctl.py",
            "target": "rules.lua",
            "state_json": "aegis-pip-float.json",
            "begin": "-- AEGIS PICTURE-IN-PICTURE BEGIN",
            "end": "-- AEGIS PICTURE-IN-PICTURE END",
            "blocker": "aegis-pip-floatctl.py shares custom/rules.lua with aegis-opacity-rules.py and aegis-custom-opacity.py without a shared lock.",
            "domains": ["windows", "apps"],
            "featureGroup": "per-app-window-rules",
        },
        "integration.game-mode": {
            "title": "Pulsar Game Mode",
            "helper": "pulsar_game_mode.py",
            "target": "game-mode",
            "blocker": "pulsar_game_mode.py only supports enter/restore without a status subcommand and mutates live Hyprland options competing with hyprland-options-adapter.",
            "domains": ["gaming", "performance"],
            "featureGroup": "game-mode",
        },
    }

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        custom = context.effective_hypr_custom_dir()
        results: list[dict[str, Any]] = []
        for setting_id, spec in sorted(self._SPECS.items()):
            helper_path = (
                context.game_mode_helper
                if setting_id == "integration.game-mode"
                else custom / spec["helper"]
            )
            results.append(
                {
                    "id": setting_id,
                    "title": spec["title"],
                    "description": spec["blocker"],
                    "valueType": "unknown",
                    "source": str(helper_path or spec["helper"]),
                    "sourceKind": "script-backed",
                    "adapter": "script-backed",
                    "path": None,
                    "controlType": "readonly-info",
                    "risk": "review-required",
                    "sensitive": False,
                    "applyMethod": spec["blocker"],
                    "profileSupported": False,
                    "resetSupported": False,
                    "keywords": sorted(
                        set(setting_id.replace(".", "-").split("-") + ["aegis", "review"])
                    ),
                    "semantics": {
                        "domainHints": list(spec["domains"]),
                        "featureGroup": spec["featureGroup"],
                        "componentHint": "modules/settings/AdvancedConfig.qml",
                        "targetApp": "steam" if setting_id == "integration.game-mode" else None,
                        "tags": ["script-backed", "adapter-review-required"],
                    },
                }
            )
        return results

    @staticmethod
    def _extract_region(text: str, begin: str, end: str) -> str | None:
        if text.count(begin) != 1 or text.count(end) != 1:
            return None
        start = text.index(begin)
        finish = text.index(end, start) + len(end)
        if finish <= start:
            return None
        return text[start:finish]

    def _probe_one(
        self, setting_id: str, context: AdapterContext
    ) -> tuple[bool, dict[str, Any]]:
        spec = self._SPECS.get(setting_id)
        if spec is None:
            return False, {"error": "unknown_script_integration"}
        custom = context.effective_hypr_custom_dir()
        if setting_id == "integration.game-mode":
            helper = context.game_mode_helper
            detector = context.game_mode_detector
            ok_helper = bool(helper and self._check_regular_file(helper)[0])
            ok_detector = bool(detector and self._check_regular_file(detector)[0])
            state_active = False
            state_valid = True
            if context.game_mode_state_file and context.game_mode_state_file.exists():
                ok_state, _, _ = self._check_regular_file(context.game_mode_state_file)
                if not ok_state:
                    state_valid = False
                else:
                    try:
                        parsed = json.loads(
                            context.game_mode_state_file.read_text(encoding="utf-8")
                        )
                        state_valid = isinstance(parsed, dict)
                        state_active = state_valid
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        state_valid = False
            readable = ok_helper and ok_detector and state_valid
            return readable, {
                "helperPresent": ok_helper,
                "detectorPresent": ok_detector,
                "gameModeActive": state_active,
                "noStatusSubcommand": True,
            }

        helper_path = custom / spec["helper"]
        target_path = custom / spec["target"]
        ok_helper, _, _ = self._check_regular_file(helper_path)
        ok_target, _, _ = self._check_regular_file(target_path)
        if not (ok_helper and ok_target):
            return False, {
                "helperPresent": ok_helper,
                "targetPresent": ok_target,
            }
        try:
            source = target_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False, {"helperPresent": ok_helper, "targetReadable": False}

        region = self._extract_region(source, spec["begin"], spec["end"])
        if region is None:
            return False, {
                "helperPresent": ok_helper,
                "targetReadable": True,
                "markersValid": False,
            }

        details: dict[str, Any] = {
            "helperPresent": ok_helper,
            "targetReadable": True,
            "markersValid": True,
        }
        if setting_id == "integration.acrylic-blur":
            size_m = re.search(r"\bsize\s*=\s*(\d+(?:\.\d+)?)", region)
            passes_m = re.search(r"\bpasses\s*=\s*(\d+(?:\.\d+)?)", region)
            clarity_m = re.search(r"\bclarity\s*=\s*(\d+(?:\.\d+)?)", region)
            enabled_m = re.search(r"\benabled\s*=\s*(true|false)\b", region)
            details["parsedState"] = {
                "size": int(round(float(size_m.group(1)))) if size_m else 12,
                "passes": int(round(float(passes_m.group(1)))) if passes_m else 3,
                "clarity": float(clarity_m.group(1)) if clarity_m else 0.65,
                "enabled": (enabled_m.group(1) == "true") if enabled_m else True,
            }
            return True, details

        if setting_id == "integration.window-effects":
            active_m = re.findall(r"\bactive_opacity\s*=\s*(\d+(?:\.\d+)?)", region)
            inactive_m = re.findall(r"\binactive_opacity\s*=\s*(\d+(?:\.\d+)?)", region)
            depth_m = re.search(r"\bdim_inactive\s*=\s*(true|false)\b", region)
            wobble_present = "wobble" in region
            details["wobbleDriftDetected"] = wobble_present
            details["parsedState"] = {
                "activeOpacity": round(float(active_m[-1]) * 100, 1) if active_m else 80.0,
                "inactiveOpacity": round(float(inactive_m[-1]) * 100, 1) if inactive_m else 80.0,
                "depth": (depth_m.group(1) == "true") if depth_m else False,
            }
            return True, details

        if setting_id == "integration.opacity-rules":
            state_path = custom / spec["state_json"]
            if state_path.exists():
                ok_state, _, _ = self._check_regular_file(state_path)
                if not ok_state:
                    return False, {**details, "stateReadable": False}
                try:
                    parsed = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(parsed, dict):
                        return False, {**details, "stateValid": False}
                    details["parsedState"] = parsed
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return False, {**details, "stateValid": False}
            return True, details

        if setting_id == "integration.picture-in-picture":
            rule_present = 'name = "aegis-opaque-zen-picture-in-picture"' in region
            state_path = custom / spec["state_json"]
            if state_path.exists():
                ok_state, _, _ = self._check_regular_file(state_path)
                if not ok_state:
                    return False, {**details, "stateReadable": False}
                try:
                    parsed = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(parsed, dict):
                        return False, {**details, "stateValid": False}
                    details["parsedState"] = {"enabled": parsed.get("enabled") is True}
                except (OSError, UnicodeError, json.JSONDecodeError):
                    return False, {**details, "stateValid": False}
            details["pipRulePresent"] = rule_present
            return rule_present, details

        return False, details

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        setting_id = str(setting_spec.get("id") or "")
        spec = self._SPECS.get(setting_id)
        if spec is None:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="adapter_review_required",
                verification_reason="Unknown script-backed integration.",
                adapter_id=self.descriptor.adapter_id,
            )
        readable, details = self._probe_one(setting_id, context)
        blocker = spec["blocker"]
        return make_probe_result(
            verified_read=readable,
            verified_apply=False,  # Always False for unadapted script-backed helpers
            reason="adapter_review_required",
            verification_reason=f"adapter_review_required: {blocker}",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details=details,
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if setting_spec is None:
            states = {}
            for sid in sorted(self._SPECS):
                ok, details = self._probe_one(sid, context)
                states[sid] = {"readable": ok, **details}
            return {"integrations": states, "runtimeVerified": False}
        sid = str(setting_spec.get("id") or "")
        ok, details = self._probe_one(sid, context)
        return {"id": sid, "readable": ok, **details, "runtimeVerified": False}


# ---------------------------------------------------------------------------
# 8. HyprlandLuaReadOnlyAdapter
# ---------------------------------------------------------------------------

def _strip_lua_comments(text: str) -> str:
    """Remove Lua block (--[[...]]) and line (--) comments while preserving strings."""
    out: list[str] = []
    i = 0
    n = len(text)
    quote: str | None = None
    while i < n:
        ch = text[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith("--[[", i):
            end = text.find("]]", i + 4)
            if end == -1:
                break
            out.append(" " * (end + 2 - i))
            i = end + 2
            continue
        if text.startswith("--", i):
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level_lua_entries(body: str) -> list[str]:
    entries: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if quote is not None:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(body[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch in "{([":
            depth += 1
            buf.append(ch)
        elif ch in "})]":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in ",\n" and depth == 0:
            item = "".join(buf).strip()
            if item:
                entries.append(item)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        entries.append(tail)
    return entries


def _parse_lua_table(body: str, prefix: str = "") -> list[tuple[str, Any, str]]:
    """Parse nested `key = value` and `["key"] = value` pairs in an `hl.config({...})` table."""
    results: list[tuple[str, Any, str]] = []
    for entry in _split_top_level_lua_entries(body):
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$', entry, re.DOTALL)
        if m:
            key = m.group(1)
            val_raw = m.group(2).strip().rstrip(",").strip()
        else:
            m_br = re.match(r'^\[\s*["\']([A-Za-z0-9_.:-]+)["\']\s*\]\s*=\s*(.+)$', entry, re.DOTALL)
            if not m_br:
                continue
            key = m_br.group(1).replace(":", ".")
            val_raw = m_br.group(2).strip().rstrip(",").strip()
        dotted = f"{prefix}.{key}" if prefix else key
        if val_raw.startswith("{") and val_raw.endswith("}"):
            inner = val_raw[1:-1]
            nested = _parse_lua_table(inner, dotted)
            if nested:
                results.extend(nested)
            else:
                results.append((dotted, val_raw, "array"))
        elif val_raw == "true":
            results.append((dotted, True, "boolean"))
        elif val_raw == "false":
            results.append((dotted, False, "boolean"))
        elif re.fullmatch(r"-?\d+", val_raw):
            results.append((dotted, int(val_raw), "integer"))
        elif re.fullmatch(r"-?\d+\.\d+", val_raw):
            results.append((dotted, float(val_raw), "number"))
        elif (val_raw.startswith('"') and val_raw.endswith('"')) or (
            val_raw.startswith("'") and val_raw.endswith("'")
        ):
            results.append((dotted, val_raw[1:-1], "string"))
        else:
            results.append((dotted, val_raw, "unknown"))
    return results


def parse_hl_config_blocks(lua_text: str) -> list[tuple[str, Any, str]]:
    """Extract dotted `hl.config({...})` keys from a Lua configuration file."""
    cleaned = _strip_lua_comments(lua_text)
    results: list[tuple[str, Any, str]] = []
    idx = 0
    while True:
        match = re.search(r"\bhl\.config\s*\(\s*\{", cleaned[idx:])
        if not match:
            break
        brace_start = idx + match.end() - 1
        depth = 0
        quote: str | None = None
        i = brace_start
        n = len(cleaned)
        end_brace = -1
        while i < n:
            ch = cleaned[i]
            if quote is not None:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end_brace = i
                    break
            i += 1
        if end_brace == -1:
            break
        table_body = cleaned[brace_start + 1 : end_brace]
        results.extend(_parse_lua_table(table_body))
        idx = end_brace + 1
    return results


class HyprlandLuaReadOnlyAdapter(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="hyprland-lua-readonly",
        display_name="Hyprland Lua Read-Only Adapter",
        source_kind="hyprland-lua-readonly",
        supported_domains=("windows", "input", "hyprland", "appearance", "gestures"),
        read_only=True,
        capabilities=AdapterCapabilities(
            read=True, apply=False, dry_run=False, rollback=False, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def _scan_lua_files(self, context: AdapterContext) -> list[dict[str, Any]]:
        main_dir = context.effective_hypr_main_dir()
        candidates_by_id: dict[str, dict[str, Any]] = {}
        target_files = [
            main_dir / "general.lua",
            main_dir / "colors.lua",
            main_dir / "shellOverrides/main.lua",
        ]
        for path in target_files:
            ok, _, _ = self._check_regular_file(path)
            if not ok:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for dotted, value, vtype in parse_hl_config_blocks(text):
                if dotted in _HYPRLAND_MANAGED_KEYS:
                    continue
                # Skip shadow entries managed by window-glow-adapter or blur entries managed by acrylic-blur
                setting_id = f"hyprland.{dotted}"
                section = dotted.split(".")[0]
                candidates_by_id[setting_id] = {
                    "id": setting_id,
                    "title": _human_title_from_id(setting_id),
                    "description": f"Hyprland Lua configuration key '{dotted}' in {path.name}.",
                    "valueType": vtype,
                    "source": str(path),
                    "sourceKind": "hyprland-lua-readonly",
                    "adapter": "hyprland-lua-readonly",
                    "path": dotted.replace(".", ":", 1),
                    "controlType": "readonly-info",
                    "risk": "review-required",
                    "sensitive": False,
                    "applyMethod": "Read-only Lua configuration option without a verified NEXUS transactional writer.",
                    "profileSupported": False,
                    "resetSupported": False,
                    "keywords": sorted(set(dotted.split(".") + ["hyprland", "lua"])),
                    "semantics": {
                        "domainHints": ["hyprland", section],
                        "featureGroup": f"hyprland-{section}",
                        "componentHint": None,
                        "targetApp": None,
                        "tags": ["hyprland-lua", "readonly"],
                    },
                    "_currentValue": value,
                }
        return [candidates_by_id[k] for k in sorted(candidates_by_id)]

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        items = self._scan_lua_files(context)
        for item in items:
            item.pop("_currentValue", None)
        return items

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        items = {row["id"]: row for row in self._scan_lua_files(context)}
        sid = str(setting_spec.get("id") or "")
        matched = items.get(sid)
        readable = matched is not None
        if not readable and setting_spec.get("source"):
            p = Path(str(setting_spec["source"]))
            ok, _, _ = self._check_regular_file(p)
            readable = ok
        return make_probe_result(
            verified_read=readable,
            verified_apply=False,
            reason="no_verified_apply_adapter",
            verification_reason="no_verified_apply_adapter: Read-only Hyprland Lua option.",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"valueType": matched.get("valueType") if matched else "unknown"},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        items = {row["id"]: row for row in self._scan_lua_files(context)}
        if setting_spec is None:
            return {
                "options": {k: v.get("_currentValue") for k, v in items.items()},
                "runtimeVerified": False,
            }
        sid = str(setting_spec.get("id") or "")
        if sid not in items:
            raise AdapterRegistryError("setting_missing", f"Hyprland Lua key '{sid}' not found.")
        return {"id": sid, "value": items[sid].get("_currentValue"), "runtimeVerified": False}


# ---------------------------------------------------------------------------
# 9. SystemThemeAppearanceAdapter (Read-only theme/GTK/KDE/Matugen/Locale)
# ---------------------------------------------------------------------------

class SystemThemeAppearanceAdapter(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="system-theme-readonly",
        display_name="System Theme & Appearance Read-Only Adapter",
        source_kind="system-theme-readonly",
        supported_domains=("appearance", "colors", "theming", "localization"),
        read_only=True,
        capabilities=AdapterCapabilities(
            read=True, apply=False, dry_run=False, rollback=False, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    @staticmethod
    def _parse_ini(path: Path | None) -> configparser.ConfigParser | None:
        if path is None or not path.exists():
            return None
        try:
            st = path.lstat()
            if not stat.S_ISREG(st.st_mode):
                return None
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str  # preserve case
            with path.open("r", encoding="utf-8") as handle:
                parser.read_file(handle)
            return parser
        except (OSError, UnicodeError, configparser.Error):
            return None

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        # Matugen config
        if context.matugen_config and context.matugen_config.is_file():
            try:
                data = tomllib.loads(context.matugen_config.read_text(encoding="utf-8"))
                templates = sorted((data.get("templates") or {}).keys())
                if templates:
                    results.append(
                        {
                            "id": "theme.matugen.templates",
                            "title": "Matugen color templates",
                            "description": "Read-only Matugen color generation targets.",
                            "valueType": "array",
                            "source": str(context.matugen_config),
                            "sourceKind": "system-theme-readonly",
                            "adapter": "system-theme-readonly",
                            "path": "templates",
                            "controlType": "readonly-info",
                            "risk": "review-required",
                            "sensitive": False,
                            "applyMethod": "Generated by Matugen and switchwall.sh.",
                            "profileSupported": False,
                            "resetSupported": False,
                            "choices": templates,
                            "keywords": ["matugen", "theme", "colors", "templates"],
                            "semantics": {
                                "domainHints": ["appearance", "colors", "theming"],
                                "featureGroup": "material-theming",
                                "componentHint": None,
                                "targetApp": None,
                                "tags": ["matugen", "generated"],
                            },
                        }
                    )
            except (OSError, UnicodeError, tomllib.TOMLDecodeError):
                pass

        # GTK3/4 non-cursor settings
        gtk_map = {
            "gtk-theme-name": ("theme.gtk3.themeName", "GTK theme", "string"),
            "gtk-icon-theme-name": ("theme.gtk3.iconThemeName", "GTK icon theme", "string"),
            "gtk-font-name": ("theme.gtk3.fontName", "GTK font", "string"),
            "gtk-application-prefer-dark-theme": ("theme.gtk3.preferDarkTheme", "GTK prefer dark theme", "boolean"),
        }
        gtk3 = self._parse_ini(context.gtk3_ini)
        if gtk3 and gtk3.has_section("Settings"):
            for ini_key, (sid, title, vtype) in gtk_map.items():
                if gtk3.has_option("Settings", ini_key):
                    results.append(
                        {
                            "id": sid,
                            "title": title,
                            "description": f"GTK3 setting '{ini_key}' from settings.ini (read-only).",
                            "valueType": vtype,
                            "source": str(context.gtk3_ini),
                            "sourceKind": "system-theme-readonly",
                            "adapter": "system-theme-readonly",
                            "path": f"Settings.{ini_key}",
                            "controlType": "readonly-info",
                            "risk": "review-required",
                            "sensitive": False,
                            "applyMethod": "Externally managed by GTK / theme scripts.",
                            "profileSupported": False,
                            "resetSupported": False,
                            "keywords": ["gtk", "gtk3", "theme", "appearance"],
                            "semantics": {
                                "domainHints": ["appearance", "desktop-toolkit"],
                                "featureGroup": "toolkit-theme",
                                "componentHint": None,
                                "targetApp": "gtk",
                                "tags": ["gtk3", "readonly"],
                            },
                        }
                    )

        # KDE globals
        kde = self._parse_ini(context.kdeglobals)
        if kde:
            kde_entries = (
                ("General", "ColorScheme", "theme.kde.colorScheme", "KDE color scheme", "string"),
                ("Icons", "Theme", "theme.kde.iconTheme", "KDE icon theme", "string"),
                ("KDE", "widgetStyle", "theme.kde.widgetStyle", "KDE widget style", "string"),
            )
            for section, key, sid, title, vtype in kde_entries:
                if kde.has_option(section, key):
                    results.append(
                        {
                            "id": sid,
                            "title": title,
                            "description": f"KDE global setting [{section}] {key} (read-only).",
                            "valueType": vtype,
                            "source": str(context.kdeglobals),
                            "sourceKind": "system-theme-readonly",
                            "adapter": "system-theme-readonly",
                            "path": f"{section}.{key}",
                            "controlType": "readonly-info",
                            "risk": "review-required",
                            "sensitive": False,
                            "applyMethod": "Externally managed by KDE / Matugen scripts.",
                            "profileSupported": False,
                            "resetSupported": False,
                            "keywords": ["kde", "qt", "theme", "appearance"],
                            "semantics": {
                                "domainHints": ["appearance", "desktop-toolkit"],
                                "featureGroup": "toolkit-theme",
                                "componentHint": None,
                                "targetApp": "kde",
                                "tags": ["kdeglobals", "readonly"],
                            },
                        }
                    )

        return sorted(results, key=lambda r: r["id"])

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        src = setting_spec.get("source")
        readable = False
        if src:
            ok, _, _ = self._check_regular_file(Path(str(src)))
            readable = ok
        return make_probe_result(
            verified_read=readable,
            verified_apply=False,
            reason="no_verified_apply_adapter",
            verification_reason="no_verified_apply_adapter: System theme source is read-only.",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        locales: set[str] = set()
        for tdir in context.translations_dirs:
            if tdir.is_dir():
                for child in sorted(tdir.glob("*.json")):
                    locales.add(child.stem)
        return {
            "discoveredCount": len(self.discover_settings(context)),
            "locales": sorted(locales),
            "runtimeVerified": False,
        }


# ---------------------------------------------------------------------------
# 10. AppDiscoveryAdapter (Read-only .desktop & game detector probe)
# ---------------------------------------------------------------------------

class AppDiscoveryAdapter(BaseAdapter):
    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="app-discovery-readonly",
        display_name="Application Discovery Read-Only Adapter",
        source_kind="app-discovery-readonly",
        supported_domains=("apps", "launcher", "dock", "gaming"),
        read_only=True,
        capabilities=AdapterCapabilities(
            read=True, apply=False, dry_run=False, rollback=False, runtime_verify=False
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        # Do not invent fake per-app settings; expose app-discovery telemetry/status only if detector present.
        return []

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        detector_ok = bool(
            context.game_mode_detector and self._check_regular_file(context.game_mode_detector)[0]
        )
        dirs_ok = any(Path(d).is_dir() for d in context.desktop_entry_dirs)
        return make_probe_result(
            verified_read=detector_ok or dirs_ok,
            verified_apply=False,
            reason="no_verified_apply_adapter",
            verification_reason="no_verified_apply_adapter: Application discovery is read-only.",
            runtime_verified=False,
            adapter_id=self.descriptor.adapter_id,
            details={"detectorAvailable": detector_ok, "desktopDirsAvailable": dirs_ok},
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        desktop_count = 0
        for base in context.desktop_entry_dirs:
            if base.is_dir():
                desktop_count += sum(1 for _ in base.glob("*.desktop"))
        return {"desktopEntryCount": desktop_count, "runtimeVerified": False}


# ---------------------------------------------------------------------------
# Built-in Adapter 11: DesktopAppearanceAdapterWrapper
# ---------------------------------------------------------------------------

class DesktopAppearanceAdapterWrapper(BaseAdapter):
    """Transactional Layer 6 adapter for system icon themes, GTK 3/4, KDE/Qt, and sound themes."""

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="desktop-appearance-adapter",
        display_name="Desktop Appearance & System Icons Adapter",
        source_kind="desktop-appearance-adapter",
        supported_domains=("appearance",),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True,
            apply=True,
            dry_run=True,
            rollback=True,
            runtime_verify=False,
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        paths = context.effective_desktop_appearance_paths()
        items: list[dict[str, Any]] = []
        for sid, spec in desktop_appearance_adapter.SETTING_SPECS.items():
            if not desktop_appearance_adapter.setting_available(sid, paths):
                continue
            choices = desktop_appearance_adapter.choices_for_setting(sid, paths)
            items.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "description": spec["description"],
                    "valueType": spec["valueType"],
                    "source": "GTK 3/4 settings.ini & kdeglobals",
                    "sourceKind": "desktop-appearance-adapter",
                    "adapter": "desktop-appearance-adapter",
                    "path": sid,
                    "controlType": spec["controlType"],
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": "Synchronized atomically across GTK 3, GTK 4, kdeglobals, and gsettings.",
                    "profileSupported": True,
                    "resetSupported": True,
                    "choices": choices,
                    "keywords": list(spec.get("keywords") or []),
                    "semantics": {
                        "domainHints": ["appearance"],
                        "featureGroup": spec["featureGroup"],
                        "componentHint": "modules/settings/AppearanceConfig.qml",
                        "targetApp": None,
                        "tags": ["desktop-appearance", "cross-toolkit"],
                    },
                }
            )
        return items

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_desktop_appearance_paths()
        if sid not in desktop_appearance_adapter.SETTING_SPECS:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="setting_unsupported",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        if not desktop_appearance_adapter.setting_available(sid, paths):
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="source_unavailable",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        try:
            desktop_appearance_adapter.read_setting(sid, paths)
        except desktop_appearance_adapter.DesktopAppearanceError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=f"{exc.code}: {exc}",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            runtime_verified=False,
            adapter_id=self._DESCRIPTOR.adapter_id,
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_desktop_appearance_paths()
        if setting_spec and setting_spec.get("id"):
            sid = str(setting_spec["id"])
            val = desktop_appearance_adapter.read_setting(sid, paths)
            return {"value": val, "settingId": sid, "runtimeVerified": False}
        return {"values": desktop_appearance_adapter.read_all_settings(paths), "runtimeVerified": False}

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        sid = str(setting_spec.get("id") or "")
        try:
            validated = desktop_appearance_adapter.validate_setting_value(sid, desired_value)
            return {"valid": True, "normalizedValue": validated}
        except desktop_appearance_adapter.DesktopAppearanceError as exc:
            return {"valid": False, "code": exc.code, "message": str(exc)}

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        _ = confirm_risk
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_desktop_appearance_paths()
        try:
            return desktop_appearance_adapter.apply_setting(
                paths, context.state_root, sid, desired_value, dry_run=dry_run
            )
        except desktop_appearance_adapter.DesktopAppearanceError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def rollback_change(
        self, transaction_id: str, context: AdapterContext, *, confirm_risk: bool = False
    ) -> dict[str, Any]:
        _ = confirm_risk
        paths = context.effective_desktop_appearance_paths()
        try:
            return desktop_appearance_adapter.undo_transaction(paths, context.state_root, transaction_id)
        except desktop_appearance_adapter.DesktopAppearanceError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


# ---------------------------------------------------------------------------
# Built-in Adapter 12: AppCustomizationAdapterWrapper
# ---------------------------------------------------------------------------

class AppCustomizationAdapterWrapper(BaseAdapter):
    """Transactional Layer 6 adapter for default apps, per-app .desktop icon overrides, and launcher visibility."""

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="app-customization-adapter",
        display_name="Applications & Desktop Icon Customization Adapter",
        source_kind="app-customization-adapter",
        supported_domains=("apps",),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True,
            apply=True,
            dry_run=True,
            rollback=True,
            runtime_verify=False,
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        paths = context.effective_app_customization_paths()
        items: list[dict[str, Any]] = []
        for sid, spec in app_customization_adapter.DEFAULT_APP_SPECS.items():
            if not app_customization_adapter.setting_available(sid, paths):
                continue
            choices = app_customization_adapter.choices_for_default_app(sid, paths)
            items.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "description": spec["description"],
                    "valueType": "string",
                    "source": str(paths.mimeapps_list),
                    "sourceKind": "app-customization-adapter",
                    "adapter": "app-customization-adapter",
                    "path": sid,
                    "controlType": "StyledComboBox" if choices else "MaterialTextField",
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": "Written atomically to ~/.config/mimeapps.list [Default Applications].",
                    "profileSupported": True,
                    "resetSupported": True,
                    "choices": choices or None,
                    "keywords": list(spec.get("keywords") or []),
                    "semantics": {
                        "domainHints": ["apps"],
                        "featureGroup": "defaults",
                        "componentHint": "modules/settings/DynamicCategoryConfig.qml",
                        "targetApp": None,
                        "tags": ["default-apps", "xdg-mime"],
                    },
                }
            )
        for sid, spec in app_customization_adapter.DESKTOP_OVERRIDE_SPECS.items():
            if not app_customization_adapter.setting_available(sid, paths):
                continue
            items.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "description": spec["description"],
                    "valueType": spec["valueType"],
                    "source": str(paths.user_applications_dir),
                    "sourceKind": "app-customization-adapter",
                    "adapter": "app-customization-adapter",
                    "path": sid,
                    "controlType": spec["controlType"],
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": "Writes XDG user .desktop overrides in ~/.local/share/applications/.",
                    "profileSupported": True,
                    "resetSupported": True,
                    "keywords": list(spec.get("keywords") or []),
                    "semantics": {
                        "domainHints": ["apps"],
                        "featureGroup": spec["featureGroup"],
                        "componentHint": "modules/settings/DynamicCategoryConfig.qml",
                        "targetApp": None,
                        "tags": ["desktop-icons", "app-overrides"],
                    },
                }
            )
        return items

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_app_customization_paths()
        if sid not in app_customization_adapter.ALL_SETTING_IDS:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="setting_unsupported",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        if not app_customization_adapter.setting_available(sid, paths):
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="source_unavailable",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        try:
            app_customization_adapter.read_setting(sid, paths, context.state_root)
        except app_customization_adapter.AppCustomizationError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=f"{exc.code}: {exc}",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            runtime_verified=False,
            adapter_id=self._DESCRIPTOR.adapter_id,
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_app_customization_paths()
        if setting_spec and setting_spec.get("id"):
            sid = str(setting_spec["id"])
            val = app_customization_adapter.read_setting(sid, paths, context.state_root)
            return {"value": val, "settingId": sid, "runtimeVerified": False}
        return {
            "values": app_customization_adapter.read_all_settings(paths, context.state_root),
            "runtimeVerified": False,
        }

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        sid = str(setting_spec.get("id") or "")
        try:
            validated = app_customization_adapter.validate_setting_value(sid, desired_value)
            return {"valid": True, "normalizedValue": validated}
        except app_customization_adapter.AppCustomizationError as exc:
            return {"valid": False, "code": exc.code, "message": str(exc)}

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        _ = confirm_risk
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_app_customization_paths()
        try:
            return app_customization_adapter.apply_setting(
                paths, context.state_root, sid, desired_value, dry_run=dry_run
            )
        except app_customization_adapter.AppCustomizationError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def rollback_change(
        self, transaction_id: str, context: AdapterContext, *, confirm_risk: bool = False
    ) -> dict[str, Any]:
        _ = confirm_risk
        paths = context.effective_app_customization_paths()
        try:
            return app_customization_adapter.undo_transaction(paths, context.state_root, transaction_id)
        except app_customization_adapter.AppCustomizationError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


# ---------------------------------------------------------------------------
# Built-in Adapter 13: HyprlandGodModeAdapterWrapper
# ---------------------------------------------------------------------------

class HyprlandGodModeAdapterWrapper(BaseAdapter):
    """Transactional Layer 6 adapter for simplified Hyprland controls persisted in custom/*.lua with live eval."""

    _DESCRIPTOR = AdapterDescriptor(
        adapter_id="hyprland-godmode-adapter",
        display_name="Hyprland Simplified Controls Adapter",
        source_kind="hyprland-godmode-adapter",
        supported_domains=("hyprland", "windows", "effects", "motion", "input"),
        read_only=False,
        capabilities=AdapterCapabilities(
            read=True,
            apply=True,
            dry_run=True,
            rollback=True,
            runtime_verify=True,
        ),
    )

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self._DESCRIPTOR

    def discover_settings(self, context: AdapterContext) -> list[dict[str, Any]]:
        paths = context.effective_hyprland_godmode_paths()
        items: list[dict[str, Any]] = []
        for sid, spec in hyprland_godmode_adapter.OPTION_SPECS.items():
            if not hyprland_godmode_adapter.setting_available(sid, paths):
                continue
            vt = spec["valueType"]
            choices = list(spec["choices"]) if spec.get("choices") else None
            ctrl = (
                "ConfigSwitch" if vt == "boolean"
                else "StyledComboBox" if choices
                else "ConfigSpinBox" if vt == "integer"
                else "StyledSlider" if vt == "number"
                else "MaterialTextField"
            )
            is_post_glow = hyprland_godmode_adapter.is_post_glow_shadow_setting(sid)
            items.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "description": spec["description"],
                    "valueType": vt,
                    "source": (
                        f"Hyprland custom/nexus-post-glow.lua; live {spec['option']}"
                        if is_post_glow
                        else f"Hyprland custom/general.lua; live {spec['option']}"
                    ),
                    "sourceKind": "hyprland-godmode-adapter",
                    "adapter": "hyprland-godmode-adapter",
                    "path": sid,
                    "controlType": ctrl,
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": (
                        "Persisted in ~/.config/hypr/custom/nexus-post-glow.lua (post-glow) and applied live via hyprctl eval."
                        if is_post_glow
                        else "Persisted in ~/.config/hypr/custom/general.lua and applied live via hyprctl eval."
                    ),
                    "profileSupported": True,
                    "resetSupported": True,
                    "choices": choices,
                    "limits": dict(spec["limits"]) if spec.get("limits") else None,
                    "keywords": list(spec.get("keywords") or []),
                    "semantics": {
                        "domainHints": ["hyprland"],
                        "featureGroup": spec["featureGroup"],
                        "componentHint": "modules/settings/DynamicCategoryConfig.qml",
                        "targetApp": None,
                        "tags": ["hyprland", "live-eval", "god-menu"],
                    },
                }
            )
        for sid, spec in hyprland_godmode_adapter.CUSTOM_LIST_SPECS.items():
            if not hyprland_godmode_adapter.setting_available(sid, paths):
                continue
            items.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "description": spec["description"],
                    "valueType": spec["valueType"],
                    "source": "~/.config/hypr/custom/",
                    "sourceKind": "hyprland-godmode-adapter",
                    "adapter": "hyprland-godmode-adapter",
                    "path": sid,
                    "controlType": spec["controlType"],
                    "risk": "reversible",
                    "sensitive": False,
                    "applyMethod": "Persisted in managed NEXUS block inside ~/.config/hypr/custom/*.lua.",
                    "profileSupported": True,
                    "resetSupported": True,
                    "keywords": list(spec.get("keywords") or []),
                    "semantics": {
                        "domainHints": ["hyprland"],
                        "featureGroup": spec["featureGroup"],
                        "componentHint": "modules/settings/DynamicCategoryConfig.qml",
                        "targetApp": None,
                        "tags": ["hyprland", "custom-lua", "god-menu"],
                    },
                }
            )
        return items

    def probe_capabilities(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_hyprland_godmode_paths()
        if sid not in hyprland_godmode_adapter.ALL_SETTING_IDS:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="setting_unsupported",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        if not hyprland_godmode_adapter.setting_available(sid, paths):
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="source_unavailable",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        # Never call live hyprctl during offline probe_capabilities (keeps isolated tests subprocess-free).
        offline_paths = replace(paths, allow_live_hyprctl=False)
        try:
            hyprland_godmode_adapter.read_setting(sid, offline_paths)
        except hyprland_godmode_adapter.HyprlandGodModeError as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason=exc.code,
                verification_reason=f"{exc.code}: {exc}",
                adapter_id=self._DESCRIPTOR.adapter_id,
            )
        return make_probe_result(
            verified_read=True,
            verified_apply=True,
            reason="ok",
            runtime_verified=bool(paths.allow_live_hyprctl and sid in hyprland_godmode_adapter.OPTION_SPECS),
            adapter_id=self._DESCRIPTOR.adapter_id,
        )

    def read_state(
        self, context: AdapterContext, setting_spec: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        paths = context.effective_hyprland_godmode_paths()
        if setting_spec and setting_spec.get("id"):
            sid = str(setting_spec["id"])
            val = hyprland_godmode_adapter.read_setting(sid, paths)
            return {"value": val, "settingId": sid, "runtimeVerified": bool(paths.allow_live_hyprctl and sid in hyprland_godmode_adapter.OPTION_SPECS)}
        return {
            "values": hyprland_godmode_adapter.read_all_settings(paths),
            "runtimeVerified": False,
        }

    def validate_change(
        self, setting_spec: dict[str, Any], desired_value: Any, context: AdapterContext
    ) -> dict[str, Any]:
        sid = str(setting_spec.get("id") or "")
        try:
            validated = hyprland_godmode_adapter.validate_setting_value(sid, desired_value)
            return {"valid": True, "normalizedValue": validated}
        except hyprland_godmode_adapter.HyprlandGodModeError as exc:
            return {"valid": False, "code": exc.code, "message": str(exc)}

    def apply_change(
        self,
        setting_spec: dict[str, Any],
        desired_value: Any,
        context: AdapterContext,
        *,
        confirm_risk: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        _ = confirm_risk
        sid = str(setting_spec.get("id") or "")
        paths = context.effective_hyprland_godmode_paths()
        try:
            return hyprland_godmode_adapter.apply_setting(
                paths, context.state_root, sid, desired_value, dry_run=dry_run
            )
        except hyprland_godmode_adapter.HyprlandGodModeError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc

    def rollback_change(
        self, transaction_id: str, context: AdapterContext, *, confirm_risk: bool = False
    ) -> dict[str, Any]:
        _ = confirm_risk
        paths = context.effective_hyprland_godmode_paths()
        try:
            return hyprland_godmode_adapter.undo_transaction(paths, context.state_root, transaction_id)
        except hyprland_godmode_adapter.HyprlandGodModeError as exc:
            raise AdapterRegistryError(exc.code, str(exc)) from exc


# ---------------------------------------------------------------------------
# AdapterRegistry & Default Factory
# ---------------------------------------------------------------------------

class AdapterRegistry:
    """Open Layer 6 registry holding built-in and dynamically registered adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterInterface] = {}

    @classmethod
    def default(cls, context: AdapterContext | None = None) -> "AdapterRegistry":
        return create_default_registry(context)

    def register(self, adapter: AdapterInterface, *, replace: bool = False) -> None:
        if not isinstance(adapter, AdapterInterface):
            raise AdapterRegistryError(
                "invalid_adapter", "Registered object must implement AdapterInterface."
            )
        adapter_id = adapter.descriptor.adapter_id
        if not adapter_id:
            raise AdapterRegistryError(
                "invalid_adapter", "Adapter descriptor must provide a non-empty adapter_id."
            )
        if adapter_id in self._adapters and not replace:
            raise AdapterRegistryError(
                "adapter_already_registered",
                f"Adapter '{adapter_id}' is already registered.",
            )
        self._adapters[adapter_id] = adapter

    def unregister(self, adapter_id: str) -> bool:
        return self._adapters.pop(adapter_id, None) is not None

    def get(self, adapter_id: str) -> AdapterInterface | None:
        return self._adapters.get(adapter_id)

    def all_adapters(self) -> list[AdapterInterface]:
        return [self._adapters[k] for k in sorted(self._adapters)]

    def resolve(self, setting_spec: dict[str, Any]) -> AdapterInterface | None:
        explicit = setting_spec.get("adapter")
        if isinstance(explicit, str) and explicit in self._adapters:
            return self._adapters[explicit]
        source_kind = setting_spec.get("sourceKind")
        if isinstance(source_kind, str) and source_kind in self._adapters:
            return self._adapters[source_kind]
        return None

    def list_descriptors(self) -> list[dict[str, Any]]:
        return [adapter.descriptor.to_dict() for adapter in self.all_adapters()]

    def probe_setting(
        self, setting_spec: dict[str, Any], context: AdapterContext
    ) -> CapabilityProbeResult:
        adapter = self.resolve(setting_spec)
        if adapter is None:
            requested = setting_spec.get("adapter") or setting_spec.get("sourceKind") or "none"
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="adapter_not_registered",
                verification_reason=f"adapter_not_registered: No adapter registered for '{requested}'.",
                runtime_verified=False,
                adapter_id="",
            )
        try:
            return adapter.probe_capabilities(setting_spec, context)
        except Exception as exc:
            return make_probe_result(
                verified_read=False,
                verified_apply=False,
                reason="adapter_probe_failed",
                verification_reason=f"adapter_probe_failed: {exc}",
                runtime_verified=False,
                adapter_id=adapter.descriptor.adapter_id,
            )

    def discover_all(
        self, context: AdapterContext
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        discovered: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for adapter in self.all_adapters():
            aid = adapter.descriptor.adapter_id
            try:
                items = adapter.discover_settings(context)
                if not isinstance(items, list):
                    raise TypeError("discover_settings must return a list")
                for item in items:
                    if isinstance(item, dict):
                        item.setdefault("adapter", aid)
                        item.setdefault("sourceKind", adapter.descriptor.source_kind)
                        discovered.append(item)
            except Exception as exc:
                diagnostics.append(
                    {
                        "adapterId": aid,
                        "stage": "discover_settings",
                        "error": str(exc),
                    }
                )
        return discovered, diagnostics


BUILTIN_ADAPTER_IDS: frozenset[str] = frozenset(
    {
        "config-json",
        "cursor-adapter",
        "window-rule-adapter",
        "window-glow-adapter",
        "motion-profile-adapter",
        "hyprland-options-adapter",
        "desktop-appearance-adapter",
        "app-customization-adapter",
        "hyprland-godmode-adapter",
        "script-backed",
        "hyprland-lua-readonly",
        "system-theme-readonly",
        "app-discovery-readonly",
    }
)


def create_default_registry(context: AdapterContext | None = None) -> AdapterRegistry:
    """Create a registry populated with all built-in Layer 6 adapters."""
    _ = context  # Context is passed per-operation; parameter kept for API ergonomics.
    registry = AdapterRegistry()
    for adapter in (
        ConfigJsonAdapter(),
        CursorAdapterWrapper(),
        WindowRuleAdapterWrapper(),
        WindowGlowAdapterWrapper(),
        MotionProfileAdapterWrapper(),
        HyprlandOptionsAdapterWrapper(),
        DesktopAppearanceAdapterWrapper(),
        AppCustomizationAdapterWrapper(),
        HyprlandGodModeAdapterWrapper(),
        AegisScriptReviewAdapter(),
        HyprlandLuaReadOnlyAdapter(),
        SystemThemeAppearanceAdapter(),
        AppDiscoveryAdapter(),
    ):
        registry.register(adapter)
    return registry


def get_default_registry(context: AdapterContext | None = None) -> AdapterRegistry:
    """Alias for `create_default_registry`."""
    return create_default_registry(context)

