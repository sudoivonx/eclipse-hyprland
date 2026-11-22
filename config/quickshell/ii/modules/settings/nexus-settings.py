#!/usr/bin/env python3
"""NEXUS manager for config-backed settings and verified Hyprland adapters."""
from __future__ import annotations
import argparse
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
import sys
import tempfile
import time
import unicodedata
import uuid
import nexus_cursor_adapter as cursor_adapter
import nexus_window_rule_adapter as window_rule_adapter
import nexus_window_glow_adapter as window_glow_adapter
import nexus_motion_profile_adapter as motion_adapter
import nexus_hyprland_options_adapter as hyprland_options_adapter
import nexus_desktop_appearance_adapter as desktop_appearance_adapter
import nexus_app_customization_adapter as app_customization_adapter
import nexus_hyprland_godmode_adapter as hyprland_godmode_adapter
import nexus_adapter_registry as adapter_registry
import nexus_backup_recovery as backup_recovery
import nexus_discovery as discovery_layer
import nexus_category_engine as category_engine

DEFAULT_CONFIG = Path.home() / '.config/illogical-impulse/config.json'
DEFAULT_STATE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'aegis/nexus'
DEFAULT_REGISTRY = Path(__file__).with_name('nexus-settings.json')
CONFIG_HOME = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
DEFAULT_CURSOR_PATHS = cursor_adapter.CursorPaths(
    env=CONFIG_HOME / 'environment.d/90-cursor.conf',
    hypr_env=CONFIG_HOME / 'hypr/hyprland/env.lua',
    gtk3=CONFIG_HOME / 'gtk-3.0/settings.ini',
    gtk4=CONFIG_HOME / 'gtk-4.0/settings.ini',
)
DEFAULT_WINDOW_RULE_PATHS = window_rule_adapter.WindowRulePaths(
    helper=CONFIG_HOME / 'hypr/custom/aegis-custom-opacity.py',
    rules=CONFIG_HOME / 'hypr/custom/rules.lua',
    state=CONFIG_HOME / 'hypr/custom/aegis-custom-opacity.json',
)
DEFAULT_WINDOW_GLOW_PATHS = window_glow_adapter.WindowGlowPaths(
    helper=CONFIG_HOME / 'hypr/custom/aegis-glowctl.py',
    state=CONFIG_HOME / 'hypr/custom/glow-settings.json',
    config=CONFIG_HOME / 'hypr/custom/glow.lua',
)
DEFAULT_MOTION_PROFILE_PATHS = motion_adapter.MotionProfilePaths(
    helper=CONFIG_HOME / 'hypr/custom/aegis-motion-profile.py',
)
DEFAULT_HYPRLAND_OPTIONS_PATHS = hyprland_options_adapter.HyprlandOptionsPaths(
    source=CONFIG_HOME / 'hypr/hyprland/general.lua',
)
DEFAULT_BACKUP_RECOVERY_PATHS = backup_recovery.DEFAULT_PATHS
DATA_HOME = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
DEFAULT_CURSOR_SEARCH_PATHS = [
    DATA_HOME / 'icons',
    Path.home() / '.local/share/icons',
    Path.home() / '.icons',
    Path('/usr/share/icons'),
    Path('/usr/share/pixmaps'),
]

class ManagerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def emit(payload: dict, exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    raise SystemExit(exit_code)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode):
        raise ManagerError('unsafe_state_directory', 'NEXUS state directory is not owned by the current user.')


def atomic_private_json(path: Path, payload: dict) -> None:
    ensure_private_dir(path.parent)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    fd, temp_name = tempfile.mkstemp(prefix='.nexus-write-', dir=path.parent)
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass


def load_json(path: Path) -> dict:
    try:
        with path.open('r', encoding='utf-8') as stream:
            result = json.load(stream)
    except FileNotFoundError:
        raise ManagerError('file_missing', 'A required NEXUS file is missing.')
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ManagerError('file_invalid', 'A required NEXUS or settings file could not be read.')
    if not isinstance(result, dict):
        raise ManagerError('json_shape_invalid', 'A JSON file has an unexpected structure.')
    return result


def get_path(obj: dict, path: str):
    value = obj
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            raise ManagerError('setting_missing', 'A registered setting is missing from the current configuration.')
        value = value[part]
    return value


def set_path(obj: dict, path: str, value) -> None:
    parts = path.split('.')
    target = obj
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            raise ManagerError('setting_path_invalid', 'A registered setting path does not match the configuration structure.')
        target = child
    if parts[-1] not in target:
        raise ManagerError('setting_missing', 'A registered setting is missing from the current configuration.')
    target[parts[-1]] = value


def same_json_type(value, expected) -> bool:
    if isinstance(expected, bool): return isinstance(value, bool)
    if isinstance(expected, int) and not isinstance(expected, bool): return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(expected, float): return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    if isinstance(expected, str): return isinstance(value, str)
    if isinstance(expected, list): return isinstance(value, list)
    if isinstance(expected, dict): return isinstance(value, dict)
    return value is None and expected is None


def load_registry(path: Path) -> tuple[dict, dict[str, dict]]:
    catalog = load_json(path)
    if catalog.get('schema') != 'nexus-settings-catalog-v1' or not isinstance(catalog.get('definitions'), list):
        raise ManagerError('catalog_invalid', 'The NEXUS settings catalogue is invalid.')
    definitions: dict[str, dict] = {}
    for row in catalog['definitions']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            raise ManagerError('catalog_invalid', 'The NEXUS settings catalogue contains an invalid definition.')
        if row['id'] in definitions:
            raise ManagerError('catalog_duplicate', 'The NEXUS settings catalogue contains duplicate IDs.')
        definitions[row['id']] = row
    return catalog, definitions


def read_config(path: Path) -> tuple[dict, bytes, os.stat_result]:
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            raise ManagerError('config_not_regular', 'The settings source is not a regular file.')
        raw = path.read_bytes()
    except ManagerError:
        raise
    except OSError:
        raise ManagerError('config_unreadable', 'The current settings source could not be read.')
    try:
        obj = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        raise ManagerError('config_invalid', 'The current settings source is not valid JSON.')
    if not isinstance(obj, dict):
        raise ManagerError('config_invalid', 'The current settings source has an unexpected structure.')
    return obj, raw, st


def baseline_path(state: Path) -> Path: return state / 'initial-state.json'
def profiles_dir(state: Path) -> Path: return state / 'profiles'
def undo_dir(state: Path) -> Path: return state / 'undo'


def baseline_data(state: Path) -> dict:
    data = load_json(baseline_path(state))
    if data.get('schema') != 'nexus-initial-state-v1' or not isinstance(data.get('values'), dict):
        raise ManagerError('baseline_invalid', 'The saved NEXUS starting state is invalid.')
    return data


def create_baseline(config_path: Path, state: Path, definitions: dict[str, dict],
                    cursor_paths: cursor_adapter.CursorPaths | None = None,
                    window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
                    window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
                    motion_paths: motion_adapter.MotionProfilePaths | None = None,
                    hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
                    adapter_context: adapter_registry.AdapterContext | None = None) -> dict:
    ensure_private_dir(state)
    target = baseline_path(state)
    if target.exists():
        existing = baseline_data(state)
        external = existing.setdefault('externalValues', {})
        migrated = False
        if cursor_paths is not None and 'cursor' not in external:
            try:
                external['cursor'] = cursor_adapter.read_cursor_state(cursor_paths)
            except cursor_adapter.CursorAdapterError as exc:
                raise ManagerError('cursor_state_conflict', str(exc)) from exc
            migrated = True
        has_window_rules = any(
            d.get('sourceKind') == 'window-rule-adapter' and d.get('resetSupported') is True
            for d in definitions.values()
        )
        if window_rule_paths is not None and has_window_rules and 'customWindowRules' not in external:
            try:
                external['customWindowRules'] = window_rule_adapter.read_window_rules(window_rule_paths)
            except window_rule_adapter.WindowRuleAdapterError as exc:
                raise ManagerError('window_rules_conflict', str(exc)) from exc
            migrated = True
        has_window_glow = any(
            d.get('sourceKind') == 'window-glow-adapter' and d.get('resetSupported') is True
            for d in definitions.values()
        )
        if window_glow_paths is not None and has_window_glow and 'windowGlow' not in external:
            try:
                external['windowGlow'] = window_glow_adapter.read_window_glow_state(window_glow_paths)
            except window_glow_adapter.WindowGlowAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
            migrated = True
        has_motion = any(
            d.get('sourceKind') == 'motion-profile-adapter' and d.get('resetSupported') is True
            for d in definitions.values()
        )
        if motion_paths is not None and has_motion and 'motionProfile' not in external:
            try:
                external['motionProfile'] = motion_adapter.read_motion_profile(motion_paths)
            except motion_adapter.MotionProfileAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
            migrated = True
        has_hyprland_options = any(
            d.get('sourceKind') == 'hyprland-options-adapter' and d.get('resetSupported') is True
            for d in definitions.values()
        )
        if hyprland_options_paths is not None and has_hyprland_options:
            try:
                current_options = hyprland_options_adapter.read_options(hyprland_options_paths)
            except hyprland_options_adapter.HyprlandOptionsError:
                pass
            else:
                saved_options = external.get('hyprlandOptions')
                if not isinstance(saved_options, dict):
                    saved_options = {}
                    external['hyprlandOptions'] = saved_options
                for ident, value in current_options.items():
                    if ident not in saved_options:
                        saved_options[ident] = value
                        migrated = True
        if adapter_context is not None:
            current_god = read_god_menu_values(adapter_context)
            if current_god:
                saved_god = external.get('godMenuValues')
                if not isinstance(saved_god, dict):
                    saved_god = {}
                    external['godMenuValues'] = saved_god
                for ident, value in current_god.items():
                    if ident not in saved_god:
                        saved_god[ident] = value
                        migrated = True
        if cursor_paths is not None or window_rule_paths is not None or window_glow_paths is not None or motion_paths is not None or hyprland_options_paths is not None:
            unsupported_now = sum(
                1 for definition in definitions.values()
                if definition.get('sourceKind') not in ('config-json', 'cursor-adapter', 'window-rule-adapter', 'window-glow-adapter', 'motion-profile-adapter', 'hyprland-options-adapter')
                or (definition.get('sourceKind') == 'cursor-adapter' and cursor_paths is None)
                or (definition.get('sourceKind') == 'window-rule-adapter' and window_rule_paths is None)
                or (definition.get('sourceKind') == 'window-glow-adapter' and window_glow_paths is None)
                or (definition.get('sourceKind') == 'motion-profile-adapter' and motion_paths is None)
                or (definition.get('sourceKind') == 'hyprland-options-adapter' and (
                    hyprland_options_paths is None
                    or not isinstance(external.get('hyprlandOptions'), dict)
                    or definition.get('id') not in external.get('hyprlandOptions', {})
                ))
            )
            if existing.get('externalDefinitionsNotCaptured') != unsupported_now:
                existing['externalDefinitionsNotCaptured'] = unsupported_now
                migrated = True
        if migrated:
            atomic_private_json(target, existing)
        return {'status':'baseline_exists','captured':len(existing['values']),'externalPending':existing.get('externalDefinitionsNotCaptured',0),'createdAt':existing.get('createdAt')}
    config, raw, _ = read_config(config_path)
    values = {}
    unsupported = 0
    for ident, definition in definitions.items():
        if definition.get('sourceKind') != 'config-json':
            if definition.get('sourceKind') != 'cursor-adapter' or cursor_paths is None:
                unsupported += 1
            continue
        path = definition.get('path')
        if not isinstance(path, str):
            raise ManagerError('catalog_invalid', 'A registered config setting has no value path.')
        values[path] = get_path(config, path)
    external_values = {}
    if cursor_paths is not None:
        try:
            external_values['cursor'] = cursor_adapter.read_cursor_state(cursor_paths)
        except cursor_adapter.CursorAdapterError as exc:
            raise ManagerError('cursor_state_conflict', str(exc)) from exc
    if window_rule_paths is not None and any(
        d.get('sourceKind') == 'window-rule-adapter' and d.get('resetSupported') is True
        for d in definitions.values()
    ):
        try:
            external_values['customWindowRules'] = window_rule_adapter.read_window_rules(window_rule_paths)
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise ManagerError('window_rules_conflict', str(exc)) from exc
    if window_glow_paths is not None and any(
        d.get('sourceKind') == 'window-glow-adapter' and d.get('resetSupported') is True
        for d in definitions.values()
    ):
        try:
            external_values['windowGlow'] = window_glow_adapter.read_window_glow_state(window_glow_paths)
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    if motion_paths is not None and any(
        d.get('sourceKind') == 'motion-profile-adapter' and d.get('resetSupported') is True
        for d in definitions.values()
    ):
        try:
            external_values['motionProfile'] = motion_adapter.read_motion_profile(motion_paths)
        except motion_adapter.MotionProfileAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    if hyprland_options_paths is not None and any(
        d.get('sourceKind') == 'hyprland-options-adapter' and d.get('resetSupported') is True
        for d in definitions.values()
    ):
        try:
            external_values['hyprlandOptions'] = hyprland_options_adapter.read_options(hyprland_options_paths)
        except hyprland_options_adapter.HyprlandOptionsError:
            pass
    if adapter_context is not None:
        god_vals = read_god_menu_values(adapter_context)
        if god_vals:
            external_values['godMenuValues'] = god_vals
    unsupported = sum(
        1 for definition in definitions.values()
        if definition.get('sourceKind') not in ('config-json', 'cursor-adapter', 'window-rule-adapter', 'window-glow-adapter', 'motion-profile-adapter', 'hyprland-options-adapter')
        or (definition.get('sourceKind') == 'cursor-adapter' and cursor_paths is None)
        or (definition.get('sourceKind') == 'window-rule-adapter' and window_rule_paths is None)
        or (definition.get('sourceKind') == 'window-glow-adapter' and window_glow_paths is None)
        or (definition.get('sourceKind') == 'motion-profile-adapter' and motion_paths is None)
        or (definition.get('sourceKind') == 'hyprland-options-adapter' and (
            hyprland_options_paths is None
            or not isinstance(external_values.get('hyprlandOptions'), dict)
            or definition.get('id') not in external_values.get('hyprlandOptions', {})
        ))
    )
    payload = {
        'schema':'nexus-initial-state-v1',
        'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source':'illogical-impulse/config.json',
        'sourceSha256':sha256_bytes(raw),
        'values':values,
        'externalValues':external_values,
        'externalDefinitionsNotCaptured':unsupported,
    }
    atomic_private_json(target, payload)
    os.chmod(target, 0o600)
    return {'status':'baseline_captured','captured':len(values),'externalPending':unsupported,'createdAt':payload['createdAt']}


def profile_slug(name: str, *, lowercase: bool = False) -> tuple[str, str]:
    raw = unicodedata.normalize('NFKC', name)
    if '..' in raw or '/' in raw or '\\' in raw or any(unicodedata.category(c).startswith('C') for c in raw):
        raise ManagerError('profile_name_invalid', 'Choose a profile name of 1 to 64 visible characters.')
    display = raw.strip()
    if not display or len(display) > 64:
        raise ManagerError('profile_name_invalid', 'Choose a profile name of 1 to 64 visible characters.')
    chars=[]
    for c in display:
        if c.isalnum() or c in '-_.': chars.append(c)
        elif c.isspace(): chars.append('-')
        else: chars.append('-')
    slug=re.sub(r'-+','-',''.join(chars)).strip('.-')
    if not slug or slug in {'.','..'}:
        raise ManagerError('profile_name_invalid', 'The profile name cannot be used as a file name.')
    if lowercase:
        slug = slug.lower()
    return slug, display


def profile_file(state: Path, name: str, must_exist: bool = False, *, lowercase: bool = False) -> tuple[Path, str, str]:
    slug, display = profile_slug(name, lowercase=lowercase)
    path = profiles_dir(state) / (slug + '.json')
    if not path.is_file() and not lowercase and slug != slug.lower():
        lower_path = profiles_dir(state) / (slug.lower() + '.json')
        if lower_path.is_file():
            path = lower_path
            slug = slug.lower()
    if must_exist and not path.is_file():
        raise ManagerError('profile_missing', 'That profile does not exist.')
    return path, slug, display


def list_profiles(state: Path, definitions: dict[str, dict] | None = None) -> dict:
    folder = profiles_dir(state)
    if not folder.exists(): return {'status':'ok','profiles':[]}
    rows=[]
    for path in sorted(folder.glob('*.json'), key=lambda p:p.name.casefold()):
        profile=load_json(path)
        external = profile.get('externalValues', {})
        cursor_count = 2 if isinstance(external, dict) and isinstance(external.get('cursor'), dict) else 0
        window_rules = isinstance(external, dict) and 'customWindowRules' in external
        window_glow = isinstance(external, dict) and 'windowGlow' in external
        motion_profile = isinstance(external, dict) and 'motionProfile' in external
        hyprland_options = isinstance(external, dict) and 'hyprlandOptions' in external
        values = profile.get('values', {})
        risky_config = isinstance(values, dict) and any(
            definitions.get(ident, {}).get('risk') == 'confirmation-required'
            for ident in values
        ) if definitions is not None else False
        reloads_hyprland = window_rules or window_glow or motion_profile
        hyprland_option_count = len(external.get('hyprlandOptions', {})) if hyprland_options and isinstance(external.get('hyprlandOptions'), dict) else 0
        god_menu_count = len(external.get('godMenuValues', {})) if isinstance(external, dict) and isinstance(external.get('godMenuValues'), dict) else 0
        rows.append({'name':profile.get('name',path.stem),'id':path.stem,'createdAt':profile.get('createdAt'),'settingCount':len(values)+cursor_count+int(window_rules)+int(window_glow)+int(motion_profile)+hyprland_option_count+god_menu_count,'requiresConfirmation':reloads_hyprland or risky_config,'requiresHyprlandReload':reloads_hyprland})
    return {'status':'ok','profiles':rows}


def safe_definitions(definitions: dict[str, dict], field: str = 'profileSupported') -> dict[str, dict]:
    return {k:v for k,v in definitions.items() if v.get('sourceKind') == 'config-json' and v.get(field) is True}


def save_profile(name: str, config_path: Path, state: Path, definitions: dict[str, dict],
                 cursor_paths: cursor_adapter.CursorPaths | None = None,
                 window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
                 window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
                 motion_paths: motion_adapter.MotionProfilePaths | None = None,
                 hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
                 *,
                 lowercase_slug: bool = False,
                 adapter_context: adapter_registry.AdapterContext | None = None) -> dict:
    path, slug, display = profile_file(state,name,lowercase=lowercase_slug)
    if path.exists(): raise ManagerError('profile_exists','A profile with that name already exists.')
    config, _, _ = read_config(config_path)
    supported=safe_definitions(definitions)
    values={}
    for ident, definition in supported.items():
        setting_path=definition['path']
        values[ident]=get_path(config,setting_path)
    external_values = {}
    if cursor_paths is not None and any(d.get('sourceKind') == 'cursor-adapter' and d.get('profileSupported') is True for d in definitions.values()):
        try:
            external_values['cursor'] = cursor_adapter.read_cursor_state(cursor_paths)
        except cursor_adapter.CursorAdapterError as exc:
            raise ManagerError('cursor_state_conflict', str(exc)) from exc
    if window_rule_paths is not None and any(d.get('sourceKind') == 'window-rule-adapter' and d.get('profileSupported') is True for d in definitions.values()):
        try:
            external_values['customWindowRules'] = window_rule_adapter.read_window_rules(window_rule_paths)
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise ManagerError('window_rules_conflict', str(exc)) from exc
    if window_glow_paths is not None and any(d.get('sourceKind') == 'window-glow-adapter' and d.get('profileSupported') is True for d in definitions.values()):
        try:
            external_values['windowGlow'] = window_glow_adapter.read_window_glow_state(window_glow_paths)
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    if motion_paths is not None and any(d.get('sourceKind') == 'motion-profile-adapter' and d.get('profileSupported') is True for d in definitions.values()):
        try:
            external_values['motionProfile'] = motion_adapter.read_motion_profile(motion_paths)
        except motion_adapter.MotionProfileAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    if hyprland_options_paths is not None and any(d.get('sourceKind') == 'hyprland-options-adapter' and d.get('profileSupported') is True for d in definitions.values()):
        try:
            external_values['hyprlandOptions'] = hyprland_options_adapter.read_options(hyprland_options_paths)
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    if adapter_context is not None:
        god_vals = read_god_menu_values(adapter_context)
        if god_vals:
            external_values['godMenuValues'] = god_vals
    payload={'schema':'nexus-profile-v1','id':slug,'name':display,'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),'source':'illogical-impulse/config.json','values':values,'externalValues':external_values}
    atomic_private_json(path,payload)
    os.chmod(path,0o600)
    return {'status':'profile_saved','name':display,'settingCount':len(values) + (2 if 'cursor' in external_values else 0) + int('customWindowRules' in external_values) + int('windowGlow' in external_values) + int('motionProfile' in external_values) + len(external_values.get('hyprlandOptions', {})) + len(external_values.get('godMenuValues', {}))}


def copy_profile(source_name: str, target_name: str | None, state: Path, *, lowercase_slug: bool = False) -> dict:
    source_path, _, source_display = profile_file(state,source_name,must_exist=True,lowercase=lowercase_slug)
    if target_name is None:
        base_name = source_display + ' copy'
        target_name = base_name
        suffix = 2
        while profile_file(state,target_name,lowercase=lowercase_slug)[0].exists():
            target_name = f'{base_name} {suffix}'
            suffix += 1
    target_path, slug, display = profile_file(state,target_name,lowercase=lowercase_slug)
    if target_path.exists(): raise ManagerError('profile_exists','A profile with that name already exists.')
    source=load_json(source_path)
    payload=dict(source)
    payload.update({'id':slug,'name':display,'createdAt':dt.datetime.now(dt.timezone.utc).isoformat(),'copiedFrom':source.get('id',source_path.stem)})
    atomic_private_json(target_path,payload)
    os.chmod(target_path,0o600)
    external = payload.get('externalValues', {})
    extra = (2 if isinstance(external, dict) and 'cursor' in external else 0) + int(isinstance(external, dict) and 'customWindowRules' in external) + int(isinstance(external, dict) and 'windowGlow' in external) + int(isinstance(external, dict) and 'motionProfile' in external) + (len(external.get('hyprlandOptions', {})) if isinstance(external, dict) and isinstance(external.get('hyprlandOptions'), dict) else 0) + (len(external.get('godMenuValues', {})) if isinstance(external, dict) and isinstance(external.get('godMenuValues'), dict) else 0)
    return {'status':'profile_copied','name':display,'settingCount':len(payload.get('values',{})) + extra}


def delete_profile(name: str, state: Path) -> dict:
    path, _, display=profile_file(state,name,must_exist=True)
    path.unlink()
    return {'status':'profile_deleted','name':display}


def read_undo_index(state: Path) -> list[dict]:
    path=undo_dir(state)/'index.json'
    if not path.exists(): return []
    data=load_json(path)
    rows=data.get('transactions')
    if not isinstance(rows,list): raise ManagerError('undo_index_invalid','The NEXUS undo history is invalid.')
    return rows


def write_undo_index(state: Path, rows: list[dict]) -> None:
    atomic_private_json(undo_dir(state)/'index.json',{'schema':'nexus-undo-v1','transactions':rows[-20:]})


def action_index_path(state: Path) -> Path:
    return undo_dir(state) / 'actions.json'


def read_action_index(state: Path) -> list[dict]:
    path = action_index_path(state)
    if not path.exists():
        return []
    data = load_json(path)
    rows = data.get('actions')
    if data.get('schema') != 'nexus-actions-v1' or not isinstance(rows, list):
        raise ManagerError('action_index_invalid', 'The NEXUS action history is invalid.')
    return rows


def record_action(state: Path, action: str, config_undo_id: str | None = None,
                  cursor_transaction_id: str | None = None,
                  window_rules_transaction_id: str | None = None,
                  window_glow_transaction_id: str | None = None,
                  motion_profile_transaction_id: str | None = None,
                  hyprland_options_transaction_id: str | None = None,
                  requires_confirmation: bool = False,
                  adapter_transactions: list[dict] | None = None) -> dict:
    """Record one user action across NEXUS persistence sources."""
    if not config_undo_id and not cursor_transaction_id and not window_rules_transaction_id and not window_glow_transaction_id and not motion_profile_transaction_id and not hyprland_options_transaction_id and not adapter_transactions:
        raise ManagerError('action_empty', 'There is no persisted change to record.')
    rows = read_action_index(state)
    row = {
        'id': uuid.uuid4().hex,
        'action': action,
        'configUndoId': config_undo_id,
        'cursorTransactionId': cursor_transaction_id,
        'windowRulesTransactionId': window_rules_transaction_id,
        'windowGlowTransactionId': window_glow_transaction_id,
        'motionProfileTransactionId': motion_profile_transaction_id,
        'hyprlandOptionsTransactionId': hyprland_options_transaction_id,
        'adapterTransactions': list(adapter_transactions) if adapter_transactions else None,
        'requiresConfirmation': requires_confirmation,
        'status': 'complete',
        'createdAt': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    rows.append(row)
    atomic_private_json(action_index_path(state), {'schema': 'nexus-actions-v1', 'actions': rows[-20:]})
    return row


def reconcile_pending(config_path: Path, state: Path, rows: list[dict]) -> list[dict]:
    if not any(x.get('status')=='pending' for x in rows): return rows
    current_hash=sha256_file(config_path)
    cleaned=[]
    for item in rows:
        if item.get('status')!='pending': cleaned.append(item); continue
        if current_hash==item.get('afterSha256'):
            item['status']='complete'; cleaned.append(item)
        elif current_hash==item.get('beforeSha256'):
            shutil.rmtree(undo_dir(state)/item.get('id',''),ignore_errors=True)
        else:
            raise ManagerError('undo_pending_conflict','A previous settings update stopped mid-way; manual recovery is required.')
    write_undo_index(state,cleaned)
    return cleaned


def xattr_snapshot(path: Path) -> dict[str, bytes]:
    result={}
    try: names=os.listxattr(path,follow_symlinks=False)
    except OSError as e:
        if e.errno in (errno.ENOTSUP,errno.EOPNOTSUPP): return result
        raise ManagerError('metadata_read_failed','Settings file metadata could not be read.')
    for name in names:
        try: result[name]=os.getxattr(path,name,follow_symlinks=False)
        except OSError: raise ManagerError('metadata_read_failed','Settings file metadata could not be read.')
    return result


def verify_xattrs(source: Path, target: Path) -> None:
    expected=xattr_snapshot(source)
    actual=xattr_snapshot(target)
    if {k:sha256_bytes(v) for k,v in expected.items()} != {k:sha256_bytes(v) for k,v in actual.items()}:
        raise ManagerError('metadata_copy_failed','Settings file ACL or extended attributes could not be preserved.')


def prepare_config_temp(config_path: Path, data: bytes, original_stat: os.stat_result) -> Path:
    fd, temp_name=tempfile.mkstemp(prefix='.nexus-config-',dir=config_path.parent)
    temp=Path(temp_name)
    try:
        with os.fdopen(fd,'wb',closefd=True) as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chown(temp,original_stat.st_uid,original_stat.st_gid)
        shutil.copystat(config_path,temp,follow_symlinks=False)
        os.utime(temp,ns=(original_stat.st_atime_ns,time.time_ns()),follow_symlinks=False)
        verify_xattrs(config_path,temp)
        return temp
    except Exception:
        try: temp.unlink()
        except FileNotFoundError: pass
        raise


def prepare_restore_temp(destination: Path, snapshot: Path) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix='.nexus-restore-', dir=destination.parent)
    temp = Path(temp_name)
    source_stat = snapshot.stat()
    try:
        with os.fdopen(fd, 'wb', closefd=True) as stream:
            stream.write(snapshot.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, source_stat.st_uid, source_stat.st_gid)
        shutil.copystat(snapshot, temp, follow_symlinks=False)
        verify_xattrs(snapshot, temp)
        return temp
    except Exception:
        try: temp.unlink()
        except FileNotFoundError: pass
        raise


def commit_config(config_path: Path, new_obj: dict, original_raw: bytes, original_stat: os.stat_result, state: Path, action: str, changed_ids: list[str], dry_run: bool) -> dict:
    indent=2
    for line in original_raw.decode('utf-8').splitlines()[1:]:
        m=re.match(r'^(\s+)["\w]',line)
        if m:
            indent=len(m.group(1)); break
    newline='\r\n' if b'\r\n' in original_raw else '\n'
    suffix=newline if original_raw.endswith((b'\n',b'\r')) else ''
    candidate=(json.dumps(new_obj,ensure_ascii=False,indent=indent)+suffix).replace('\n',newline).encode('utf-8')
    json.loads(candidate.decode('utf-8'))
    before_hash=sha256_bytes(original_raw); after_hash=sha256_bytes(candidate)
    if before_hash==after_hash:
        return {'status':'no_changes','changedCount':0,'runtimeVerified':False}
    if dry_run:
        return {'status':'dry_run','changedCount':len(changed_ids),'runtimeVerified':False}

    index=reconcile_pending(config_path,state,read_undo_index(state))
    txn_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    folder=undo_dir(state)/txn_id
    ensure_private_dir(folder)
    snapshot=folder/'config.json'
    try:
        shutil.copy2(config_path,snapshot,follow_symlinks=False)
        os.chown(snapshot,original_stat.st_uid,original_stat.st_gid)
        os.chmod(snapshot,stat.S_IMODE(original_stat.st_mode))
        if sha256_file(snapshot)!=before_hash: raise ManagerError('undo_snapshot_failed','Could not verify the pre-change recovery copy.')
        copied_stat=snapshot.stat()
        if (copied_stat.st_uid,copied_stat.st_gid,stat.S_IMODE(copied_stat.st_mode)) != (original_stat.st_uid,original_stat.st_gid,stat.S_IMODE(original_stat.st_mode)):
            raise ManagerError('undo_snapshot_failed','Could not preserve the pre-change file permissions.')
        verify_xattrs(config_path,snapshot)
        row={'id':txn_id,'action':action,'changedIds':changed_ids,'beforeSha256':before_hash,'afterSha256':after_hash,'status':'pending','createdAt':dt.datetime.now(dt.timezone.utc).isoformat()}
        index.append(row); write_undo_index(state,index)
        current_raw=config_path.read_bytes()
        if sha256_bytes(current_raw)!=before_hash: raise ManagerError('config_changed_concurrently','The settings file changed while NEXUS was preparing this update.')
        temp=prepare_config_temp(config_path,candidate,original_stat)
        os.replace(temp,config_path)
        parent_fd=os.open(config_path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
        try: os.fsync(parent_fd)
        finally: os.close(parent_fd)
        row['status']='complete'; write_undo_index(state,index)
    except Exception:
        current_hash=sha256_file(config_path) if config_path.exists() else ''
        if current_hash==before_hash:
            index=[x for x in index if x.get('id')!=txn_id]
            write_undo_index(state,index)
            shutil.rmtree(folder,ignore_errors=True)
        raise
    return {'status':'written_to_config','changedCount':len(changed_ids),'undoId':txn_id,'runtimeVerified':False,'runtimeStatus':'pending-existing-application-reload'}


def _restore_config_transaction(config_path: Path, state: Path, transaction_id: str, mark_undone: bool = True):
    rows = reconcile_pending(config_path, state, read_undo_index(state))
    row = next((item for item in rows if item.get('id') == transaction_id), None)
    if row is None or row.get('status') != 'complete' or row.get('undone'):
        raise ManagerError('undo_snapshot_invalid', 'The saved recovery copy for this change is unavailable.')
    if sha256_file(config_path) != row.get('afterSha256'):
        raise ManagerError('undo_conflict', 'The settings file changed after this NEXUS action, so undo was stopped to protect newer edits.')
    snapshot = undo_dir(state) / row['id'] / 'config.json'
    if not snapshot.is_file() or sha256_file(snapshot) != row.get('beforeSha256'):
        raise ManagerError('undo_snapshot_invalid', 'The saved recovery copy for this change is invalid.')
    temp = prepare_restore_temp(config_path, snapshot)
    os.replace(temp, config_path)
    fd = os.open(config_path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if mark_undone:
        row['undone'] = True
        row['undoneAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_undo_index(state, rows)
    return row, rows


def _mark_config_transaction_undone(state: Path, row: dict, rows: list[dict]) -> None:
    row['undone'] = True
    row['undoneAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_undo_index(state, rows)


def _apply_action(config_path: Path, state: Path, config: dict, raw: bytes, original_stat: os.stat_result,
                  action: str, changed_ids: list[str], dry_run: bool,
                  cursor_paths: cursor_adapter.CursorPaths | None = None,
                  desired_cursor: dict | None = None,
                  search_paths: list[Path] | None = None,
                  window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
                  desired_window_rules: list[dict] | None = None,
                  confirm_risk: bool = False,
                  window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
                  desired_window_glow: dict | None = None,
                  motion_paths: motion_adapter.MotionProfilePaths | None = None,
                  desired_motion_profile: str | None = None,
                  hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
                  desired_hyprland_options: dict | None = None,
                  requires_confirmation: bool = False,
                  adapter_context: adapter_registry.AdapterContext | None = None,
                  desired_god_menu_values: dict | None = None) -> dict:
    cursor_before = None
    cursor_changed = False
    if desired_cursor is not None:
        if cursor_paths is None:
            raise ManagerError('cursor_paths_missing', 'The cursor settings sources are unavailable.')
        try:
            cursor_before = cursor_adapter.read_cursor_state(cursor_paths)
            cursor_adapter.apply_cursor_state(
                cursor_paths, state, desired_cursor.get('theme'), desired_cursor.get('size'),
                dry_run=True, search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
            )
            cursor_changed = cursor_before != desired_cursor
        except cursor_adapter.CursorAdapterError as exc:
            raise ManagerError('cursor_state_conflict', str(exc)) from exc

    window_rules_changed = False
    if desired_window_rules is not None:
        if window_rule_paths is None:
            raise ManagerError('window_rules_paths_missing', 'The custom window rule settings source is unavailable.')
        try:
            current_window_rules = window_rule_adapter.read_window_rules(window_rule_paths)
            window_rule_adapter.apply_window_rules(
                window_rule_paths, state, desired_window_rules,
                confirm_risk=False, dry_run=True,
            )
            window_rules_changed = current_window_rules != desired_window_rules
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
        if window_rules_changed and not dry_run and not confirm_risk:
            raise ManagerError('risk_confirmation_required', 'This change reloads Hyprland window rules and requires confirmation.')

    window_glow_changed = False
    if desired_window_glow is not None:
        if window_glow_paths is None:
            raise ManagerError('window_glow_paths_missing', 'The window glow settings source is unavailable.')
        try:
            current_window_glow = window_glow_adapter.read_window_glow_state(window_glow_paths)
            window_glow_adapter.apply_window_glow(
                window_glow_paths, state, desired_window_glow,
                confirm_risk=False, dry_run=True,
            )
            window_glow_changed = current_window_glow != desired_window_glow
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
        if window_glow_changed and not dry_run and not confirm_risk:
            raise ManagerError('risk_confirmation_required', 'Changing window glow settings reloads Hyprland and requires confirmation.')

    motion_profile_changed = False
    if desired_motion_profile is not None:
        if motion_paths is None:
            raise ManagerError('motion_paths_missing', 'The motion profile settings source is unavailable.')
        try:
            current_motion_profile = motion_adapter.read_motion_profile(motion_paths)
            motion_adapter.validate_motion_profile(desired_motion_profile)
            motion_profile_changed = current_motion_profile != desired_motion_profile
            motion_adapter.apply_motion_profile(
                motion_paths, state, desired_motion_profile,
                confirm_risk=False, dry_run=True,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
        if motion_profile_changed and not dry_run and not confirm_risk:
            raise ManagerError('risk_confirmation_required', 'Changing the motion profile reloads Hyprland and requires confirmation.')

    hyprland_options_changed = False
    if desired_hyprland_options is not None:
        if hyprland_options_paths is None:
            raise ManagerError('hyprland_options_paths_missing', 'The Hyprland window settings source is unavailable.')
        try:
            option_plan = hyprland_options_adapter.validate_apply(hyprland_options_paths, desired_hyprland_options)
            hyprland_options_changed = bool(option_plan['changed'])
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise ManagerError(exc.code, str(exc)) from exc

    god_menu_changes: dict[str, object] = {}
    if desired_god_menu_values and adapter_context is not None:
        current_god = read_god_menu_values(adapter_context)
        reg = adapter_registry.create_default_registry()
        for sid, desired_val in sorted(desired_god_menu_values.items()):
            aid = god_menu_adapter_for_setting(sid)
            if not aid:
                raise ManagerError('setting_unsupported', f'Unsupported God Menu setting: {sid}')
            if sid in current_god and current_god.get(sid) == desired_val:
                continue
            adp = reg.get(aid)
            if adp is None:
                raise ManagerError('adapter_not_registered', f'Adapter unavailable: {aid}')
            v = adp.validate_change({'id': sid}, desired_val, adapter_context)
            if not v.get('valid'):
                raise ManagerError(str(v.get('code') or 'value_invalid'), str(v.get('message') or 'Invalid value.'))
            norm_val = v.get('normalizedValue', desired_val)
            if current_god.get(sid) != norm_val:
                try:
                    adp.apply_change({'id': sid}, norm_val, adapter_context, dry_run=True)
                except adapter_registry.AdapterRegistryError as exc:
                    raise ManagerError(exc.code, str(exc)) from exc
                god_menu_changes[sid] = norm_val

    config_result = commit_config(config_path, config, raw, original_stat, state, action, changed_ids, dry_run)
    if dry_run:
        if cursor_changed or window_rules_changed or window_glow_changed or motion_profile_changed or hyprland_options_changed or god_menu_changes:
            return {'status': 'dry_run', 'changedCount': len(changed_ids) + (2 if cursor_changed else 0) + (1 if window_rules_changed else 0) + (1 if window_glow_changed else 0) + (1 if motion_profile_changed else 0) + len(option_plan['changed'] if desired_hyprland_options is not None else {}) + len(god_menu_changes), 'runtimeVerified': False}
        return config_result

    config_undo_id = config_result.get('undoId')
    cursor_result = None
    if cursor_changed:
        try:
            cursor_result = cursor_adapter.apply_cursor_state(
                cursor_paths, state, desired_cursor['theme'], desired_cursor['size'],
                search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
            )
        except cursor_adapter.CursorAdapterError as exc:
            if config_undo_id:
                _restore_config_transaction(config_path, state, config_undo_id)
            raise ManagerError('cursor_write_failed', str(exc)) from exc

    cursor_transaction_id = cursor_result.get('transactionId') if cursor_result else None
    window_rules_result = None
    if window_rules_changed:
        try:
            window_rules_result = window_rule_adapter.apply_window_rules(
                window_rule_paths, state, desired_window_rules,
                confirm_risk=confirm_risk,
            )
        except window_rule_adapter.WindowRuleAdapterError as exc:
            rollback_errors = []
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            detail = str(exc)
            if rollback_errors:
                detail = 'The window rule update failed and rollback of another setting was incomplete; manual recovery is required.'
            raise ManagerError(exc.code, detail) from exc

    window_rules_transaction_id = window_rules_result.get('transactionId') if window_rules_result else None
    window_glow_result = None
    if window_glow_changed:
        try:
            window_glow_result = window_glow_adapter.apply_window_glow(
                window_glow_paths, state, desired_window_glow,
                confirm_risk=confirm_risk,
            )
        except window_glow_adapter.WindowGlowAdapterError as exc:
            rollback_errors = []
            if window_rules_transaction_id:
                try:
                    window_rule_adapter.undo_window_rules(window_rule_paths, state, window_rules_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-rules')
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            detail = str(exc)
            if rollback_errors:
                detail = 'The window glow update failed and rollback of another setting was incomplete; manual recovery is required.'
            raise ManagerError('window_glow_rollback_failed' if rollback_errors else exc.code, detail) from exc

    window_glow_transaction_id = window_glow_result.get('transactionId') if window_glow_result else None
    motion_profile_result = None
    if motion_profile_changed:
        try:
            motion_profile_result = motion_adapter.apply_motion_profile(
                motion_paths, state, desired_motion_profile,
                confirm_risk=confirm_risk,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            rollback_errors = []
            if window_glow_transaction_id:
                try:
                    window_glow_adapter.undo_window_glow(window_glow_paths, state, window_glow_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-glow')
            if window_rules_transaction_id:
                try:
                    window_rule_adapter.undo_window_rules(window_rule_paths, state, window_rules_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-rules')
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            detail = str(exc)
            if rollback_errors:
                detail = 'The motion profile update failed and rollback of another setting was incomplete; manual recovery is required.'
            raise ManagerError('motion_profile_rollback_failed' if rollback_errors else exc.code, detail) from exc

    motion_profile_transaction_id = motion_profile_result.get('transactionId') if motion_profile_result else None
    hyprland_options_result = None
    if hyprland_options_changed:
        try:
            hyprland_options_result = hyprland_options_adapter.apply_options(
                hyprland_options_paths, state, desired_hyprland_options,
            )
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            rollback_errors = []
            if motion_profile_transaction_id:
                try:
                    motion_adapter.undo_motion_profile(motion_paths, state, motion_profile_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('motion-profile')
            if window_glow_transaction_id:
                try:
                    window_glow_adapter.undo_window_glow(window_glow_paths, state, window_glow_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-glow')
            if window_rules_transaction_id:
                try:
                    window_rule_adapter.undo_window_rules(window_rule_paths, state, window_rules_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-rules')
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            if rollback_errors:
                raise ManagerError('hyprland_options_rollback_failed', 'The Hyprland window settings failed and rollback of another setting was incomplete; manual recovery is required.') from exc
            raise ManagerError(exc.code, str(exc)) from exc

    hyprland_options_transaction_id = hyprland_options_result.get('transactionId') if hyprland_options_result else None
    adapter_txns: list[dict] = []
    if god_menu_changes and adapter_context is not None:
        try:
            adapter_txns = apply_god_menu_values(adapter_context, god_menu_changes)
        except ManagerError as exc:
            rollback_errors = []
            if hyprland_options_transaction_id:
                try:
                    hyprland_options_adapter.undo_options(hyprland_options_paths, state, hyprland_options_transaction_id)
                except Exception:
                    rollback_errors.append('hyprland-options')
            if motion_profile_transaction_id:
                try:
                    motion_adapter.undo_motion_profile(motion_paths, state, motion_profile_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('motion-profile')
            if window_glow_transaction_id:
                try:
                    window_glow_adapter.undo_window_glow(window_glow_paths, state, window_glow_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-glow')
            if window_rules_transaction_id:
                try:
                    window_rule_adapter.undo_window_rules(window_rule_paths, state, window_rules_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-rules')
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            if rollback_errors:
                raise ManagerError('god_menu_rollback_failed', 'Adapter update failed and rollback was incomplete; manual recovery is required.') from exc
            raise

    if config_undo_id or cursor_transaction_id or window_rules_transaction_id or window_glow_transaction_id or motion_profile_transaction_id or hyprland_options_transaction_id or adapter_txns:
        try:
            record_action(
                state, action, config_undo_id=config_undo_id,
                cursor_transaction_id=cursor_transaction_id,
                window_rules_transaction_id=window_rules_transaction_id,
                window_glow_transaction_id=window_glow_transaction_id,
                motion_profile_transaction_id=motion_profile_transaction_id,
                hyprland_options_transaction_id=hyprland_options_transaction_id,
                requires_confirmation=requires_confirmation,
                adapter_transactions=adapter_txns or None,
            )
        except Exception as exc:
            rollback_errors = []
            if adapter_txns and adapter_context is not None:
                try:
                    rollback_adapter_transactions(adapter_context, adapter_txns)
                except Exception:
                    rollback_errors.append('god-menu-adapters')
            if hyprland_options_transaction_id:
                try:
                    hyprland_options_adapter.undo_options(hyprland_options_paths, state, hyprland_options_transaction_id)
                except Exception:
                    rollback_errors.append('hyprland-options')
            if motion_profile_transaction_id:
                try:
                    motion_adapter.undo_motion_profile(motion_paths, state, motion_profile_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('motion-profile')
            if window_glow_transaction_id:
                try:
                    window_glow_adapter.undo_window_glow(window_glow_paths, state, window_glow_transaction_id, confirm_risk=True)
                except Exception:
                    rollback_errors.append('window-glow')
            if window_rules_transaction_id:
                try:
                    window_rule_adapter.undo_window_rules(
                        window_rule_paths, state, window_rules_transaction_id, confirm_risk=True,
                    )
                except Exception:
                    rollback_errors.append('window-rules')
            if cursor_transaction_id:
                try:
                    cursor_adapter.undo_cursor_state(cursor_paths, state, cursor_transaction_id)
                except Exception:
                    rollback_errors.append('cursor')
            if config_undo_id:
                try:
                    _restore_config_transaction(config_path, state, config_undo_id)
                except Exception:
                    rollback_errors.append('config')
            detail = 'The action was rolled back because its recovery record could not be saved.'
            if rollback_errors:
                detail = 'The recovery record failed and rollback was incomplete; manual recovery is required.'
            raise ManagerError('action_record_failed', detail) from exc

    if config_undo_id or cursor_transaction_id or window_rules_transaction_id or motion_profile_transaction_id or window_glow_transaction_id or hyprland_options_transaction_id or adapter_txns:
        only_hyprland_options = bool(hyprland_options_transaction_id) and not any((
            config_undo_id, cursor_transaction_id, window_rules_transaction_id,
            window_glow_transaction_id, motion_profile_transaction_id, adapter_txns,
        ))
        runtime_status = (
            'hyprland-live-values-verified; config-file-auto-reload-may-occur'
            if hyprland_options_transaction_id else
            'hyprland-reload-and-config-error-check-passed; visual-effect-unverified'
            if window_rules_changed or window_glow_changed or motion_profile_changed else 'pending-existing-application-reload'
        )
        return {
            'status': 'written_to_config',
            'changedCount': len(changed_ids) + (2 if cursor_changed else 0) + (1 if window_rules_changed else 0) + (1 if window_glow_changed else 0) + (1 if motion_profile_changed else 0) + (len(option_plan['changed']) if hyprland_options_changed else 0) + len(adapter_txns),
            'undoId': config_undo_id,
            'cursorUndoId': cursor_transaction_id,
            'windowRulesUndoId': window_rules_transaction_id,
            'windowGlowUndoId': window_glow_transaction_id,
            'motionProfileUndoId': motion_profile_transaction_id,
            'hyprlandOptionsUndoId': hyprland_options_transaction_id,
            'adapterTransactions': adapter_txns or None,
            'runtimeVerified': only_hyprland_options,
            'runtimeStatus': runtime_status,
        }
    return config_result


def cursor_status(paths: cursor_adapter.CursorPaths | None = None, search_paths: list[Path] | None = None) -> dict:
    paths = paths or DEFAULT_CURSOR_PATHS
    try:
        current = cursor_adapter.read_cursor_state(paths)
        themes = cursor_adapter.discover_themes(search_paths or DEFAULT_CURSOR_SEARCH_PATHS)
    except cursor_adapter.CursorAdapterError as exc:
        diagnostic = cursor_adapter.cursor_mirror_diagnostic(
            paths,
            search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
        )
        if diagnostic['reconciliationAvailable'] and not diagnostic['mirrorsMatch']:
            return {
                'status': 'conflict',
                'code': 'cursor_state_conflict',
                'message': 'Cursor settings differ between the canonical environment.d + Hyprland files and GTK mirrors.',
                'source': 'environment.d+Hyprland',
                'reconciliationAvailable': True,
                'conflictingMirrorCount': diagnostic['conflictingMirrorCount'],
                'runtimeVerified': False,
            }
        raise ManagerError('cursor_state_conflict', str(exc)) from exc
    return {
        'status': 'ok',
        'current': current,
        'themes': themes,
        'runtimeVerified': False,
        'runtimeStatus': 'not-live-verified',
    }


def reconcile_cursor_setting(state: Path, paths: cursor_adapter.CursorPaths,
                             source: str, confirm_risk: bool,
                             dry_run: bool = False,
                             search_paths: list[Path] | None = None) -> dict:
    if not dry_run and not confirm_risk:
        raise ManagerError('risk_confirmation_required', 'Aligning cursor mirrors requires explicit confirmation.')
    try:
        result = cursor_adapter.reconcile_cursor_mirrors(
            paths,
            state,
            source=source,
            dry_run=dry_run,
            search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
        )
    except cursor_adapter.CursorAdapterError as exc:
        raise ManagerError('cursor_state_conflict', str(exc)) from exc
    if dry_run or not result.get('transactionId'):
        return {**result, 'changedCount': 2 if result.get('changedMirrorCount', 0) else 0}
    try:
        record_action(
            state,
            'cursor-reconcile',
            cursor_transaction_id=result['transactionId'],
            requires_confirmation=True,
        )
    except Exception as exc:
        try:
            cursor_adapter.undo_cursor_state(paths, state, result['transactionId'])
        except cursor_adapter.CursorAdapterError as rollback_exc:
            raise ManagerError('action_record_rollback_failed', 'The mirror repair could not be recorded, and its rollback was incomplete; manual recovery is required.') from rollback_exc
        raise ManagerError('action_record_failed', 'The mirror repair was rolled back because its recovery record could not be saved.') from exc
    return {
        **result,
        'changedCount': 2,
        'cursorUndoId': result['transactionId'],
        'runtimeStatus': 'persisted-mirrors-written; live-cursor-effect-unverified',
    }


def hyprland_options_status(paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None) -> dict:
    try:
        values = hyprland_options_adapter.read_options(paths or DEFAULT_HYPRLAND_OPTIONS_PATHS)
    except hyprland_options_adapter.HyprlandOptionsError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    return {
        'status': 'ok',
        'values': values,
        'limits': hyprland_options_adapter.option_metadata(),
        'runtimeVerified': True,
        'workspaceRulesMayOverrideGaps': True,
    }


def set_hyprland_options(state: Path, definitions: dict[str, dict], values: dict,
                         dry_run: bool = False,
                         paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None) -> dict:
    paths = paths or DEFAULT_HYPRLAND_OPTIONS_PATHS
    supported = {
        ident for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'hyprland-options-adapter'
        and definition.get('profileSupported') is True
        and definition.get('resetSupported') is True
    }
    if not isinstance(values, dict) or not values or not set(values).issubset(supported):
        raise ManagerError('setting_unsupported', 'Choose one or more Hyprland window settings NEXUS can safely manage.')
    try:
        result = hyprland_options_adapter.apply_options(paths, state, values, dry_run=dry_run)
    except hyprland_options_adapter.HyprlandOptionsError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    transaction_id = result.get('transactionId')
    if transaction_id:
        try:
            record_action(state, 'set-hyprland-options', hyprland_options_transaction_id=transaction_id)
        except Exception as exc:
            try:
                hyprland_options_adapter.undo_options(paths, state, transaction_id)
            except Exception as rollback_exc:
                raise ManagerError('action_record_rollback_failed', 'The settings action could not be recorded and its rollback could not be verified; manual recovery is required.') from rollback_exc
            raise ManagerError('action_record_failed', 'The settings action could not be recorded and was rolled back.') from exc
    return result


def window_rule_status(paths: window_rule_adapter.WindowRulePaths | None = None) -> dict:
    try:
        rules = window_rule_adapter.read_window_rules(paths or DEFAULT_WINDOW_RULE_PATHS)
    except window_rule_adapter.WindowRuleAdapterError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    return {
        'status': 'ok',
        'currentCount': len(rules),
        'runtimeVerified': False,
        'runtimeStatus': 'persisted-rule-list-read; live-window-effect-unverified',
    }


def window_glow_status(paths: window_glow_adapter.WindowGlowPaths | None = None) -> dict:
    try:
        return window_glow_adapter.read_window_glow(paths or DEFAULT_WINDOW_GLOW_PATHS)
    except window_glow_adapter.WindowGlowAdapterError as exc:
        raise ManagerError(exc.code, str(exc)) from exc


def motion_profile_status(paths: motion_adapter.MotionProfilePaths | None = None) -> dict:
    try:
        profile = motion_adapter.read_motion_profile(paths or DEFAULT_MOTION_PROFILE_PATHS)
        return {'status': 'ok', 'profile': profile, 'runtimeVerified': False}
    except motion_adapter.MotionProfileAdapterError as exc:
        raise ManagerError(exc.code, str(exc)) from exc


def backup_list(paths: backup_recovery.BackupRecoveryPaths | None = None) -> dict:
    try:
        return backup_recovery.list_backups(paths or DEFAULT_BACKUP_RECOVERY_PATHS)
    except backup_recovery.BackupRecoveryError as exc:
        raise ManagerError(exc.code, str(exc)) from exc


def backup_verify(backup_id: str, paths: backup_recovery.BackupRecoveryPaths | None = None) -> dict:
    try:
        return backup_recovery.verify_backup(paths or DEFAULT_BACKUP_RECOVERY_PATHS, backup_id)
    except backup_recovery.BackupRecoveryError as exc:
        raise ManagerError(exc.code, str(exc)) from exc


def backup_restore(backup_id: str, confirm_risk: bool, dry_run: bool = False,
                   paths: backup_recovery.BackupRecoveryPaths | None = None) -> dict:
    try:
        return backup_recovery.restore_backup(
            paths or DEFAULT_BACKUP_RECOVERY_PATHS,
            backup_id,
            confirm_risk=confirm_risk,
            dry_run=dry_run,
        )
    except backup_recovery.BackupRecoveryError as exc:
        raise ManagerError(exc.code, str(exc)) from exc


def set_cursor_setting(state: Path, paths: cursor_adapter.CursorPaths, theme: str, size: int,
                       dry_run: bool = False, search_paths: list[Path] | None = None) -> dict:
    try:
        current = cursor_adapter.read_cursor_state(paths)
        preflight = cursor_adapter.apply_cursor_state(
            paths, state, theme, size, dry_run=True,
            search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
        )
    except cursor_adapter.CursorAdapterError as exc:
        raise ManagerError('cursor_state_conflict', str(exc)) from exc
    if dry_run:
        return {'status': preflight['status'], 'changedCount': 2 if current != {'theme': theme, 'size': size} else 0, 'runtimeVerified': False}
    if current == {'theme': theme, 'size': size}:
        return {'status': 'no_changes', 'changedCount': 0, 'runtimeVerified': False}
    try:
        result = cursor_adapter.apply_cursor_state(
            paths, state, theme, size, search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS,
        )
        record_action(state, 'cursor-set', cursor_transaction_id=result.get('transactionId'))
    except cursor_adapter.CursorAdapterError as exc:
        raise ManagerError('cursor_write_failed', str(exc)) from exc
    except Exception as exc:
        transaction_id = result.get('transactionId') if 'result' in locals() else None
        if transaction_id:
            try:
                cursor_adapter.undo_cursor_state(paths, state, transaction_id)
            except cursor_adapter.CursorAdapterError as rollback_exc:
                raise ManagerError('action_record_failed', 'The action record failed and cursor rollback was incomplete; manual recovery is required.') from rollback_exc
        raise ManagerError('action_record_failed', 'The action was rolled back because its recovery record could not be saved.') from exc
    return {'status': result['status'], 'changedCount': 2, 'cursorUndoId': result.get('transactionId'), 'runtimeVerified': False, 'runtimeStatus': 'pending-existing-application-reload'}


def reset_values(config_path: Path,state: Path,definitions: dict[str,dict],ids: list[str],dry_run: bool,action: str,
                 cursor_paths: cursor_adapter.CursorPaths | None = None, search_paths: list[Path] | None = None,
                 window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
                 confirm_risk: bool = False,
                 window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
                 motion_paths: motion_adapter.MotionProfilePaths | None = None,
                 hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
                 adapter_context: adapter_registry.AdapterContext | None = None) -> dict:
    baseline=baseline_data(state)
    config,raw,st=read_config(config_path)
    changed=[]
    desired_cursor = None
    cursor_ids = {
        ident: definition.get('path', '').split('.', 1)[-1]
        for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'cursor-adapter'
        and definition.get('resetSupported') is True
        and definition.get('path', '').startswith('cursor.')
        and definition.get('path', '').split('.', 1)[-1] in ('theme', 'size')
    }
    selected_cursor = [ident for ident in ids if ident in cursor_ids and definitions.get(ident, {}).get('sourceKind') == 'cursor-adapter' and definitions.get(ident, {}).get('resetSupported') is True]
    window_rule_ids = {
        ident for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'window-rule-adapter' and definition.get('resetSupported') is True
    }
    selected_window_rules = [ident for ident in ids if ident in window_rule_ids]
    desired_window_rules = None
    if selected_window_rules:
        if window_rule_paths is None:
            raise ManagerError('window_rules_paths_missing', 'The custom window rule settings source is unavailable.')
        starting_rules = baseline.get('externalValues', {}).get('customWindowRules')
        try:
            window_rule_adapter.validate_window_rules(starting_rules)
            current_rules = window_rule_adapter.read_window_rules(window_rule_paths)
        except window_rule_adapter.WindowRuleAdapterError as exc:
            if not isinstance(starting_rules, list):
                raise ManagerError('baseline_value_missing', 'The starting custom window rule state was not captured.') from exc
            raise ManagerError(exc.code, str(exc)) from exc
        if current_rules != starting_rules:
            desired_window_rules = starting_rules
    window_glow_ids = {
        ident for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'window-glow-adapter' and definition.get('resetSupported') is True
    }
    selected_window_glow = [ident for ident in ids if ident in window_glow_ids]
    desired_window_glow = None
    if selected_window_glow:
        if window_glow_paths is None:
            raise ManagerError('window_glow_paths_missing', 'The window glow settings source is unavailable.')
        starting_glow = baseline.get('externalValues', {}).get('windowGlow')
        if not isinstance(starting_glow, dict):
            raise ManagerError('baseline_value_missing', 'The starting window glow state was not captured.')
        try:
            current_glow = window_glow_adapter.read_window_glow_state(window_glow_paths)
            window_glow_adapter.apply_window_glow(
                window_glow_paths, state, starting_glow,
                confirm_risk=False, dry_run=True,
            )
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
        if current_glow != starting_glow:
            desired_window_glow = starting_glow
    if selected_cursor:
        if cursor_paths is None:
            raise ManagerError('cursor_paths_missing', 'The cursor settings sources are unavailable.')
        external = baseline.get('externalValues', {}).get('cursor')
        if not isinstance(external, dict) or not {'theme', 'size'} <= external.keys():
            raise ManagerError('baseline_value_missing', 'The starting cursor state was not captured.')
        try:
            desired_cursor = cursor_adapter.read_cursor_state(cursor_paths)
        except cursor_adapter.CursorAdapterError as exc:
            raise ManagerError('cursor_state_conflict', str(exc)) from exc
        for ident in selected_cursor:
            desired_cursor[cursor_ids[ident]] = external[cursor_ids[ident]]
    motion_profile_ids = {
        ident for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'motion-profile-adapter' and definition.get('resetSupported') is True
    }
    selected_motion_profile = [ident for ident in ids if ident in motion_profile_ids]
    desired_motion_profile = None
    if selected_motion_profile:
        if motion_paths is None:
            raise ManagerError('motion_paths_missing', 'The motion profile settings source is unavailable.')
        starting_motion_profile = baseline.get('externalValues', {}).get('motionProfile')
        try:
            motion_adapter.validate_motion_profile(starting_motion_profile)
            current_motion_profile = motion_adapter.read_motion_profile(motion_paths)
            motion_adapter.apply_motion_profile(
                motion_paths, state, starting_motion_profile,
                confirm_risk=False, dry_run=True,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            if not isinstance(starting_motion_profile, str):
                raise ManagerError('baseline_value_missing', 'The starting motion profile was not captured.') from exc
            raise ManagerError(exc.code, str(exc)) from exc
        if current_motion_profile != starting_motion_profile:
            desired_motion_profile = starting_motion_profile
    hyprland_option_ids = {
        ident for ident, definition in definitions.items()
        if definition.get('sourceKind') == 'hyprland-options-adapter'
        and definition.get('resetSupported') is True
        and isinstance(baseline.get('externalValues', {}).get('hyprlandOptions'), dict)
        and ident in baseline.get('externalValues', {}).get('hyprlandOptions', {})
    }
    requested_hyprland_options = [
        ident for ident in ids
        if definitions.get(ident, {}).get('sourceKind') == 'hyprland-options-adapter'
        and definitions.get(ident, {}).get('resetSupported') is True
    ]
    missing_hyprland_baseline = [ident for ident in requested_hyprland_options if ident not in hyprland_option_ids]
    if missing_hyprland_baseline and action == 'reset-one':
        raise ManagerError('baseline_value_missing', 'The starting Hyprland window value was not captured.')
    selected_hyprland_options = [ident for ident in ids if ident in hyprland_option_ids]
    desired_hyprland_options = None
    if selected_hyprland_options:
        if hyprland_options_paths is None:
            raise ManagerError('hyprland_options_paths_missing', 'The Hyprland window settings source is unavailable.')
        starting_options = baseline.get('externalValues', {}).get('hyprlandOptions')
        if not isinstance(starting_options, dict):
            raise ManagerError('baseline_value_missing', 'The starting Hyprland window values were not captured.')
        desired_hyprland_options = {ident: starting_options[ident] for ident in selected_hyprland_options}
        try:
            option_plan = hyprland_options_adapter.validate_apply(hyprland_options_paths, desired_hyprland_options)
            if not option_plan['changed']:
                desired_hyprland_options = None
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    for ident in ids:
        definition=definitions.get(ident)
        if not definition or definition.get('sourceKind')!='config-json' or definition.get('resetSupported') is not True:
            continue
        path=definition['path']
        if path not in baseline['values']:
            raise ManagerError('baseline_value_missing','The starting value for a supported setting is missing.')
        target=baseline['values'][path]
        current=get_path(config,path)
        if not same_json_type(target,current):
            raise ManagerError('setting_type_mismatch','A setting type changed since the starting state was captured.')
        if current!=target:
            set_path(config,path,target); changed.append(ident)
    desired_god_menu_values: dict[str, object] | None = None
    god_menu_reset_ids: set[str] = set()
    if adapter_context is not None:
        selected_god = [ident for ident in ids if god_menu_adapter_for_setting(ident) is not None]
        if selected_god:
            saved_god = baseline.get('externalValues', {}).get('godMenuValues')
            if not isinstance(saved_god, dict):
                if action == 'reset-one':
                    raise ManagerError('baseline_value_missing', f'The starting value for {selected_god[0]} was not captured.')
            else:
                desired_god_menu_values = {}
                for ident in selected_god:
                    if ident in saved_god:
                        desired_god_menu_values[ident] = saved_god[ident]
                        god_menu_reset_ids.add(ident)
                    elif action == 'reset-one':
                        raise ManagerError('baseline_value_missing', f'The starting value for {ident} was not captured.')
                if not desired_god_menu_values:
                    desired_god_menu_values = None
    risky_config_change = any(
        definitions.get(ident, {}).get('risk') == 'confirmation-required'
        for ident in changed
    )
    if risky_config_change and not dry_run and not confirm_risk:
        raise ManagerError('risk_confirmation_required', 'Resetting these advanced settings requires confirmation.')
    result=_apply_action(config_path,state,config,raw,st,action,changed,dry_run,cursor_paths,desired_cursor,search_paths,window_rule_paths,desired_window_rules,confirm_risk,window_glow_paths,desired_window_glow,motion_paths,desired_motion_profile,hyprland_options_paths,desired_hyprland_options,risky_config_change,adapter_context,desired_god_menu_values)
    supported_ids = sum(
        1 for ident in ids
        if ident in god_menu_reset_ids
        or (
            definitions.get(ident,{}).get('resetSupported') is True
            and (
                definitions.get(ident,{}).get('sourceKind') == 'config-json'
                or (definitions.get(ident,{}).get('sourceKind') == 'cursor-adapter' and ident in cursor_ids)
                or (definitions.get(ident,{}).get('sourceKind') == 'window-rule-adapter' and ident in window_rule_ids and window_rule_paths is not None)
                or (definitions.get(ident,{}).get('sourceKind') == 'window-glow-adapter' and ident in window_glow_ids and window_glow_paths is not None)
                or (definitions.get(ident,{}).get('sourceKind') == 'motion-profile-adapter' and ident in motion_profile_ids and motion_paths is not None)
                or (definitions.get(ident,{}).get('sourceKind') == 'hyprland-options-adapter' and ident in hyprland_option_ids and hyprland_options_paths is not None)
            )
        )
    )
    result['unsupportedCount']=len(ids)-supported_ids
    return result


def load_profile(name: str,config_path: Path,state: Path,definitions: dict[str,dict],dry_run: bool,
                 cursor_paths: cursor_adapter.CursorPaths | None = None, search_paths: list[Path] | None = None,
                 window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
                 confirm_risk: bool = False,
                 window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
                 motion_paths: motion_adapter.MotionProfilePaths | None = None,
                 hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
                 adapter_context: adapter_registry.AdapterContext | None = None) -> dict:
    path,_,_=profile_file(state,name,must_exist=True)
    profile=load_json(path)
    if profile.get('schema')!='nexus-profile-v1' or not isinstance(profile.get('values'),dict):
        raise ManagerError('profile_invalid','The selected profile is invalid.')
    config,raw,st=read_config(config_path)
    supported=safe_definitions(definitions)
    changed=[]
    risky_config_change = False
    for ident,value in profile['values'].items():
        definition=supported.get(ident)
        if definition is None: raise ManagerError('profile_unsupported_setting','The profile contains a setting NEXUS cannot safely apply yet.')
        current=get_path(config,definition['path'])
        if not same_json_type(value,current): raise ManagerError('profile_type_mismatch','A profile setting has a different type from the current configuration.')
        if current!=value:
            set_path(config,definition['path'],value); changed.append(ident)
            risky_config_change = risky_config_change or definition.get('risk') == 'confirmation-required'
    if risky_config_change and not dry_run and not confirm_risk:
        raise ManagerError('risk_confirmation_required', 'Loading this profile changes advanced settings and requires confirmation.')
    desired_cursor = None
    external = profile.get('externalValues', {})
    if not isinstance(external, dict) or set(external) - {'cursor', 'customWindowRules', 'windowGlow', 'motionProfile', 'hyprlandOptions', 'godMenuValues'}:
        raise ManagerError('profile_invalid', 'The selected profile has invalid external settings.')
    cursor_profile = external.get('cursor')
    if cursor_profile is not None:
        cursor_definitions = {ident: definition for ident, definition in definitions.items() if definition.get('sourceKind') == 'cursor-adapter' and definition.get('profileSupported') is True}
        if not cursor_definitions or not isinstance(cursor_profile, dict) or set(cursor_profile) != {'theme', 'size'}:
            raise ManagerError('profile_unsupported_setting', 'The profile contains cursor settings NEXUS cannot safely apply.')
        if cursor_paths is None:
            raise ManagerError('cursor_paths_missing', 'The cursor settings sources are unavailable.')
        try:
            current_cursor = cursor_adapter.read_cursor_state(cursor_paths)
            desired_cursor = {'theme': cursor_profile['theme'], 'size': cursor_profile['size']}
            cursor_adapter.apply_cursor_state(cursor_paths, state, desired_cursor['theme'], desired_cursor['size'], dry_run=True, search_paths=search_paths or DEFAULT_CURSOR_SEARCH_PATHS)
        except cursor_adapter.CursorAdapterError as exc:
            raise ManagerError('cursor_state_conflict', str(exc)) from exc
    desired_window_rules = None
    if 'customWindowRules' in external:
        rule_definitions = {
            ident: definition for ident, definition in definitions.items()
            if definition.get('sourceKind') == 'window-rule-adapter' and definition.get('profileSupported') is True
        }
        if not rule_definitions:
            raise ManagerError('profile_unsupported_setting', 'The profile contains custom window rules NEXUS cannot safely apply yet.')
        if window_rule_paths is None:
            raise ManagerError('window_rules_paths_missing', 'The custom window rule settings source is unavailable.')
        try:
            desired_window_rules = window_rule_adapter.validate_window_rules(external['customWindowRules'])
            window_rule_adapter.apply_window_rules(
                window_rule_paths, state, desired_window_rules,
                confirm_risk=False, dry_run=True,
            )
        except window_rule_adapter.WindowRuleAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    desired_window_glow = None
    if 'windowGlow' in external:
        glow_definitions = {
            ident: definition for ident, definition in definitions.items()
            if definition.get('sourceKind') == 'window-glow-adapter' and definition.get('profileSupported') is True
        }
        if not glow_definitions or not isinstance(external['windowGlow'], dict):
            raise ManagerError('profile_unsupported_setting', 'The profile contains window glow settings NEXUS cannot safely apply.')
        if window_glow_paths is None:
            raise ManagerError('window_glow_paths_missing', 'The window glow settings source is unavailable.')
        desired_window_glow = external['windowGlow']
        try:
            window_glow_adapter.apply_window_glow(
                window_glow_paths, state, desired_window_glow,
                confirm_risk=False, dry_run=True,
            )
        except window_glow_adapter.WindowGlowAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    desired_motion_profile = None
    if 'motionProfile' in external:
        motion_definitions = {
            ident: definition for ident, definition in definitions.items()
            if definition.get('sourceKind') == 'motion-profile-adapter' and definition.get('profileSupported') is True
        }
        if not motion_definitions:
            raise ManagerError('profile_unsupported_setting', 'The profile contains a motion profile NEXUS cannot safely apply.')
        if motion_paths is None:
            raise ManagerError('motion_paths_missing', 'The motion profile settings source is unavailable.')
        try:
            desired_motion_profile = motion_adapter.validate_motion_profile(external['motionProfile'])
            motion_adapter.apply_motion_profile(
                motion_paths, state, desired_motion_profile,
                confirm_risk=False, dry_run=True,
            )
        except motion_adapter.MotionProfileAdapterError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    desired_hyprland_options = None
    if 'hyprlandOptions' in external:
        option_definitions = {
            ident for ident, definition in definitions.items()
            if definition.get('sourceKind') == 'hyprland-options-adapter'
            and definition.get('profileSupported') is True
            and definition.get('resetSupported') is True
        }
        desired_hyprland_options = external['hyprlandOptions']
        if not isinstance(desired_hyprland_options, dict) or not desired_hyprland_options or not set(desired_hyprland_options).issubset(option_definitions):
            raise ManagerError('profile_unsupported_setting', 'The profile contains Hyprland window settings NEXUS cannot safely apply.')
        if hyprland_options_paths is None:
            raise ManagerError('hyprland_options_paths_missing', 'The Hyprland window settings source is unavailable.')
        try:
            hyprland_options_adapter.validate_apply(hyprland_options_paths, desired_hyprland_options)
        except hyprland_options_adapter.HyprlandOptionsError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    desired_god_menu_values = None
    if 'godMenuValues' in external:
        raw_god = external['godMenuValues']
        if not isinstance(raw_god, dict):
            raise ManagerError('profile_invalid', 'The profile contains invalid adapter settings.')
        if adapter_context is not None and raw_god:
            desired_god_menu_values = raw_god
    result=_apply_action(
        config_path,state,config,raw,st,'profile-load',changed,dry_run,
        cursor_paths,desired_cursor,search_paths,window_rule_paths,
        desired_window_rules,confirm_risk,window_glow_paths,desired_window_glow,
        motion_paths,desired_motion_profile,hyprland_options_paths,
        desired_hyprland_options,risky_config_change,adapter_context,desired_god_menu_values,
    )
    result['profileName']=profile.get('name',path.stem)
    return result


def _preflight_config_transaction(config_path: Path, state: Path, transaction_id: str):
    if not isinstance(transaction_id, str) or not re.fullmatch(r'\d{8}T\d{6}-[a-f0-9]{8}', transaction_id):
        raise ManagerError('undo_snapshot_invalid','The saved recovery copy identifier is invalid.')
    rows=reconcile_pending(config_path,state,read_undo_index(state))
    row=next((item for item in rows if item.get('id') == transaction_id),None)
    if row is None or row.get('status')!='complete' or row.get('undone'):
        raise ManagerError('undo_snapshot_invalid','The saved recovery copy for this change is unavailable.')
    if sha256_file(config_path)!=row.get('afterSha256'):
        raise ManagerError('undo_conflict','The settings file changed after this NEXUS action, so undo was stopped to protect newer edits.')
    snapshot=undo_dir(state)/row['id']/'config.json'
    if not snapshot.is_file() or sha256_file(snapshot)!=row.get('beforeSha256'):
        raise ManagerError('undo_snapshot_invalid','The saved recovery copy for the last change is invalid.')
    return row, rows, snapshot


def _preflight_cursor_transaction(paths: cursor_adapter.CursorPaths, state: Path, transaction_id: str) -> dict:
    if not isinstance(transaction_id, str) or not re.fullmatch(r'[a-f0-9]{32}', transaction_id):
        raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery identifier is invalid.')
    folder = state / 'cursor-undo' / transaction_id
    undo_root = folder.parent
    for directory in (undo_root, folder):
        try:
            directory_info = directory.lstat()
        except OSError as exc:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery directory is unavailable.') from exc
        if not stat.S_ISDIR(directory_info.st_mode) or stat.S_IMODE(directory_info.st_mode) & 0o077:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery directory is not private.')
    transaction_path = folder / 'transaction.json'
    try:
        transaction_info = transaction_path.lstat()
        if not stat.S_ISREG(transaction_info.st_mode) or stat.S_IMODE(transaction_info.st_mode) & 0o077:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information is not a private regular file.')
        transaction = json.loads(transaction_path.read_text(encoding='utf-8'))
    except ManagerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information is unavailable.') from exc
    if transaction.get('schema') != 'nexus-cursor-undo-v1' or transaction.get('undone'):
        raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information is invalid.')
    targets = {str(path) for _, path, _ in cursor_adapter._target_specs(paths)}
    files = transaction.get('files')
    if not isinstance(files, list) or not files or any(not isinstance(item, dict) for item in files):
        raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information is incomplete.')
    recorded_targets = [item.get('path') for item in files]
    is_mirror_reconciliation = transaction.get('action') == 'mirror-reconciliation'
    if is_mirror_reconciliation:
        gtk_targets = {str(paths.gtk3), str(paths.gtk4)}
        valid_target_set = set(recorded_targets).issubset(gtk_targets)
        valid_record_count = 1 <= len(files) <= len(gtk_targets)
        if transaction.get('source') != 'environment.d+Hyprland':
            raise ManagerError('cursor_undo_invalid', 'The saved cursor reconciliation source is invalid.')
    else:
        valid_target_set = set(recorded_targets) == targets
        valid_record_count = len(files) == len(targets)
    if len(set(recorded_targets)) != len(recorded_targets) or not valid_target_set or not valid_record_count:
        raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information contains an unexpected target.')
    for index, item in enumerate(files):
        if item.get('path') not in targets:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information contains an unexpected target.')
        if item.get('snapshot') != f'{index}.before':
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery snapshot path is invalid.')
        snapshot_path = folder / f'{index}.before'
        try:
            snapshot_info = snapshot_path.lstat()
        except OSError as exc:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery snapshot is unavailable.') from exc
        if not stat.S_ISREG(snapshot_info.st_mode) or stat.S_IMODE(snapshot_info.st_mode) & 0o077:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery snapshot is not a private regular file.')
        try:
            current, _, _ = cursor_adapter._read_regular(Path(item['path']))
            current = current.encode('utf-8')
            before = snapshot_path.read_bytes()
        except (OSError, KeyError) as exc:
            raise ManagerError('cursor_undo_invalid', 'The saved cursor recovery information is unavailable.') from exc
        if sha256_bytes(current) != item.get('afterSha256') or sha256_bytes(before) != item.get('beforeSha256'):
            raise ManagerError('undo_conflict', 'Cursor settings changed after this NEXUS action, so undo was stopped.')
    return transaction


def undo_last(config_path: Path,state: Path,dry_run: bool,
              cursor_paths: cursor_adapter.CursorPaths | None = None,
              window_rule_paths: window_rule_adapter.WindowRulePaths | None = None,
              confirm_risk: bool = False,
              window_glow_paths: window_glow_adapter.WindowGlowPaths | None = None,
              motion_paths: motion_adapter.MotionProfilePaths | None = None,
              hyprland_options_paths: hyprland_options_adapter.HyprlandOptionsPaths | None = None,
              adapter_context: adapter_registry.AdapterContext | None = None) -> dict:
    actions=read_action_index(state)
    candidates=[row for row in actions if row.get('status')=='complete' and not row.get('undone')]
    if candidates:
        row=candidates[-1]
        config_id=row.get('configUndoId')
        cursor_id=row.get('cursorTransactionId')
        window_rules_id=row.get('windowRulesTransactionId')
        window_glow_id=row.get('windowGlowTransactionId')
        motion_profile_id=row.get('motionProfileTransactionId')
        hyprland_options_id=row.get('hyprlandOptionsTransactionId')
        adapter_txns=row.get('adapterTransactions') or []
        if row.get('requiresConfirmation') is True and not dry_run and not confirm_risk:
            raise ManagerError('risk_confirmation_required', 'Undoing this advanced settings change requires confirmation.')
        if window_rules_id:
            if window_rule_paths is None:
                raise ManagerError('window_rules_paths_missing','The custom window rule settings source is unavailable.')
            try:
                window_rule_adapter.undo_window_rules(
                    window_rule_paths,state,window_rules_id,confirm_risk=False,dry_run=True,
                )
            except window_rule_adapter.WindowRuleAdapterError as exc:
                raise ManagerError(exc.code,str(exc)) from exc
            if not dry_run and not confirm_risk:
                raise ManagerError('risk_confirmation_required','Undo reloads Hyprland window rules and requires confirmation.')
        if window_glow_id:
            if window_glow_paths is None:
                raise ManagerError('window_glow_paths_missing', 'The window glow settings source is unavailable.')
            try:
                window_glow_adapter.undo_window_glow(
                    window_glow_paths, state, window_glow_id,
                    confirm_risk=False, dry_run=True,
                )
            except window_glow_adapter.WindowGlowAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
            if not dry_run and not confirm_risk:
                raise ManagerError('risk_confirmation_required', 'Undo reloads Hyprland window glow settings and requires confirmation.')
        if motion_profile_id:
            if motion_paths is None:
                raise ManagerError('motion_paths_missing', 'The motion profile settings source is unavailable.')
            try:
                motion_adapter.undo_motion_profile(
                    motion_paths, state, motion_profile_id,
                    confirm_risk=False, dry_run=True,
                )
            except motion_adapter.MotionProfileAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
            if not dry_run and not confirm_risk:
                raise ManagerError('risk_confirmation_required', 'Undo reloads Hyprland motion settings and requires confirmation.')
        if hyprland_options_id:
            if hyprland_options_paths is None:
                raise ManagerError('hyprland_options_paths_missing', 'The Hyprland window settings source is unavailable.')
            try:
                hyprland_options_adapter.undo_options(
                    hyprland_options_paths, state, hyprland_options_id, dry_run=True,
                )
            except hyprland_options_adapter.HyprlandOptionsError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
        if adapter_txns:
            preflight_ctx = adapter_context or build_adapter_context(config_path, state)
            _preflight_adapter_transactions(preflight_ctx, adapter_txns)
        if dry_run: return {'status':'dry_run','action':row.get('action'),'runtimeVerified':False}
        config_data=None
        if config_id:
            config_row, config_rows, snapshot = _preflight_config_transaction(config_path,state,config_id)
            current_raw=config_path.read_bytes()
            config_data=(config_row,config_rows,snapshot,current_raw)
        cursor_before_undo = None
        if cursor_id:
            if cursor_paths is None:
                raise ManagerError('cursor_paths_missing','The cursor settings sources are unavailable.')
            _preflight_cursor_transaction(cursor_paths,state,cursor_id)
            try:
                cursor_before_undo = cursor_adapter.read_cursor_state(cursor_paths)
            except cursor_adapter.CursorAdapterError as exc:
                raise ManagerError('cursor_state_conflict',str(exc)) from exc
        window_rules_before_undo = None
        if window_rules_id:
            try:
                window_rules_before_undo = window_rule_adapter.read_window_rules(window_rule_paths)
            except window_rule_adapter.WindowRuleAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
        window_glow_before_undo = None
        if window_glow_id:
            try:
                window_glow_before_undo = window_glow_adapter.read_window_glow_state(window_glow_paths)
            except window_glow_adapter.WindowGlowAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
        motion_profile_before_undo = None
        if motion_profile_id:
            try:
                motion_profile_before_undo = motion_adapter.read_motion_profile(motion_paths)
            except motion_adapter.MotionProfileAdapterError as exc:
                raise ManagerError(exc.code, str(exc)) from exc
        if config_data:
            config_row,config_rows,snapshot,_=config_data
            temp=prepare_restore_temp(config_path,snapshot)
            os.replace(temp,config_path)
            fd=os.open(config_path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try: os.fsync(fd)
            finally: os.close(fd)
        if cursor_id:
            try:
                cursor_adapter.undo_cursor_state(cursor_paths,state,cursor_id)
            except cursor_adapter.CursorAdapterError as exc:
                if config_data:
                    _,_,_,previous_raw=config_data
                    try:
                        current_stat=config_path.stat()
                        temp=prepare_config_temp(config_path,previous_raw,current_stat)
                        os.replace(temp,config_path)
                        parent_fd=os.open(config_path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                        try: os.fsync(parent_fd)
                        finally: os.close(parent_fd)
                    except Exception as rollback_exc:
                        raise ManagerError('undo_rollback_failed','Cursor undo failed and the configuration could not be restored; manual recovery is required.') from rollback_exc
                raise ManagerError('cursor_undo_failed',str(exc)) from exc
        if window_rules_id:
            try:
                window_rule_adapter.undo_window_rules(
                    window_rule_paths,state,window_rules_id,confirm_risk=True,
                )
            except window_rule_adapter.WindowRuleAdapterError as exc:
                rollback_errors=[]
                if cursor_id and cursor_before_undo is not None:
                    try:
                        cursor_rollback = cursor_adapter.apply_cursor_state(
                            cursor_paths,state,cursor_before_undo['theme'],cursor_before_undo['size'],
                        )
                        retry_cursor_id = cursor_rollback.get('transactionId')
                        if not retry_cursor_id:
                            raise cursor_adapter.CursorAdapterError('Cursor undo recovery did not create a retry transaction.')
                        row['cursorTransactionId'] = retry_cursor_id
                        atomic_private_json(action_index_path(state),{'schema':'nexus-actions-v1','actions':actions[-20:]})
                    except Exception:
                        rollback_errors.append('cursor')
                if config_data:
                    try:
                        _,_,_,previous_raw=config_data
                        current_stat=config_path.stat()
                        temp=prepare_config_temp(config_path,previous_raw,current_stat)
                        os.replace(temp,config_path)
                        parent_fd=os.open(config_path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                        try: os.fsync(parent_fd)
                        finally: os.close(parent_fd)
                    except Exception:
                        rollback_errors.append('config')
                detail=str(exc)
                if rollback_errors:
                    detail='Window rule undo failed and rollback of another setting was incomplete; manual recovery is required.'
                    raise ManagerError('undo_rollback_failed',detail) from exc
                raise ManagerError(exc.code,detail) from exc
        if window_glow_id:
            try:
                window_glow_adapter.undo_window_glow(
                    window_glow_paths, state, window_glow_id, confirm_risk=True,
                )
            except window_glow_adapter.WindowGlowAdapterError as exc:
                rollback_errors = []
                if window_rules_id and window_rules_before_undo is not None:
                    try:
                        retry_rules = window_rule_adapter.apply_window_rules(
                            window_rule_paths, state, window_rules_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_rules.get('transactionId')
                        if not replacement_id:
                            raise window_rule_adapter.WindowRuleAdapterError('Window rule recovery did not create a retry transaction.')
                        row['windowRulesTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('window-rules')
                if cursor_id and cursor_before_undo is not None:
                    try:
                        retry_cursor = cursor_adapter.apply_cursor_state(
                            cursor_paths, state, cursor_before_undo['theme'], cursor_before_undo['size'],
                        )
                        replacement_id = retry_cursor.get('transactionId')
                        if not replacement_id:
                            raise cursor_adapter.CursorAdapterError('Cursor recovery did not create a retry transaction.')
                        row['cursorTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('cursor')
                if config_data:
                    try:
                        _, _, _, previous_raw = config_data
                        current_stat = config_path.stat()
                        temp = prepare_config_temp(config_path, previous_raw, current_stat)
                        os.replace(temp, config_path)
                        parent_fd = os.open(config_path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                        try:
                            os.fsync(parent_fd)
                        finally:
                            os.close(parent_fd)
                    except Exception:
                        rollback_errors.append('config')
                if rollback_errors:
                    atomic_private_json(action_index_path(state), {'schema': 'nexus-actions-v1', 'actions': actions[-20:]})
                    raise ManagerError('undo_rollback_failed', 'Window glow undo failed and rollback of another setting was incomplete; manual recovery is required.') from exc
                atomic_private_json(action_index_path(state), {'schema': 'nexus-actions-v1', 'actions': actions[-20:]})
                raise ManagerError(exc.code, str(exc)) from exc
        if motion_profile_id:
            try:
                motion_adapter.undo_motion_profile(
                    motion_paths, state, motion_profile_id, confirm_risk=True,
                )
            except motion_adapter.MotionProfileAdapterError as exc:
                rollback_errors = []
                if window_glow_id:
                    try:
                        retry_glow = window_glow_adapter.apply_window_glow(
                            window_glow_paths, state, window_glow_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_glow.get('transactionId')
                        if not replacement_id:
                            raise window_glow_adapter.WindowGlowAdapterError('Window glow recovery did not create a retry transaction.')
                        row['windowGlowTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('window-glow')
                if window_rules_id and window_rules_before_undo is not None:
                    try:
                        retry_rules = window_rule_adapter.apply_window_rules(
                            window_rule_paths, state, window_rules_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_rules.get('transactionId')
                        if not replacement_id:
                            raise window_rule_adapter.WindowRuleAdapterError('Window rule recovery did not create a retry transaction.')
                        row['windowRulesTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('window-rules')
                if cursor_id and cursor_before_undo is not None:
                    try:
                        retry_cursor = cursor_adapter.apply_cursor_state(
                            cursor_paths, state, cursor_before_undo['theme'], cursor_before_undo['size'],
                        )
                        replacement_id = retry_cursor.get('transactionId')
                        if not replacement_id:
                            raise cursor_adapter.CursorAdapterError('Cursor recovery did not create a retry transaction.')
                        row['cursorTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('cursor')
                if config_data:
                    try:
                        _, _, _, previous_raw = config_data
                        current_stat = config_path.stat()
                        temp = prepare_config_temp(config_path, previous_raw, current_stat)
                        os.replace(temp, config_path)
                        parent_fd = os.open(config_path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                        try:
                            os.fsync(parent_fd)
                        finally:
                            os.close(parent_fd)
                    except Exception:
                        rollback_errors.append('config')
                atomic_private_json(action_index_path(state), {'schema': 'nexus-actions-v1', 'actions': actions[-20:]})
                detail = str(exc)
                if rollback_errors:
                    detail = 'Motion profile undo failed and rollback of another setting was incomplete; manual recovery is required.'
                    raise ManagerError('undo_rollback_failed', detail) from exc
                raise ManagerError(exc.code, detail) from exc
        if hyprland_options_id:
            try:
                hyprland_options_adapter.undo_options(
                    hyprland_options_paths, state, hyprland_options_id,
                )
            except hyprland_options_adapter.HyprlandOptionsError as exc:
                rollback_errors = []
                if motion_profile_id and isinstance(motion_profile_before_undo, str):
                    try:
                        retry_motion = motion_adapter.apply_motion_profile(
                            motion_paths, state, motion_profile_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_motion.get('transactionId')
                        if not replacement_id:
                            raise motion_adapter.MotionProfileAdapterError('Motion profile recovery did not create a retry transaction.')
                        row['motionProfileTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('motion-profile')
                if window_glow_id and isinstance(window_glow_before_undo, dict):
                    try:
                        retry_glow = window_glow_adapter.apply_window_glow(
                            window_glow_paths, state, window_glow_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_glow.get('transactionId')
                        if not replacement_id:
                            raise window_glow_adapter.WindowGlowAdapterError('Window glow recovery did not create a retry transaction.')
                        row['windowGlowTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('window-glow')
                if window_rules_id and isinstance(window_rules_before_undo, list):
                    try:
                        retry_rules = window_rule_adapter.apply_window_rules(
                            window_rule_paths, state, window_rules_before_undo, confirm_risk=True,
                        )
                        replacement_id = retry_rules.get('transactionId')
                        if not replacement_id:
                            raise window_rule_adapter.WindowRuleAdapterError('Window rule recovery did not create a retry transaction.')
                        row['windowRulesTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('window-rules')
                if cursor_id and isinstance(cursor_before_undo, dict):
                    try:
                        retry_cursor = cursor_adapter.apply_cursor_state(
                            cursor_paths, state, cursor_before_undo['theme'], cursor_before_undo['size'],
                        )
                        replacement_id = retry_cursor.get('transactionId')
                        if not replacement_id:
                            raise cursor_adapter.CursorAdapterError('Cursor recovery did not create a retry transaction.')
                        row['cursorTransactionId'] = replacement_id
                    except Exception:
                        rollback_errors.append('cursor')
                if config_data:
                    try:
                        _, _, _, previous_raw = config_data
                        current_stat = config_path.stat()
                        temp = prepare_config_temp(config_path, previous_raw, current_stat)
                        os.replace(temp, config_path)
                        parent_fd = os.open(config_path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                        try:
                            os.fsync(parent_fd)
                        finally:
                            os.close(parent_fd)
                    except Exception:
                        rollback_errors.append('config')
                atomic_private_json(action_index_path(state), {'schema': 'nexus-actions-v1', 'actions': actions[-20:]})
                if rollback_errors:
                    raise ManagerError('undo_rollback_failed', 'Hyprland option undo failed and rollback of another setting was incomplete; manual recovery is required.') from exc
                raise ManagerError(exc.code, str(exc)) from exc
        adapter_undo_runtime_verified = False
        if adapter_txns:
            ctx = adapter_context or build_adapter_context(config_path, state)
            try:
                undo_results = rollback_adapter_transactions(ctx, adapter_txns)
            except ManagerError as exc:
                if config_data:
                    try:
                        _, _, _, previous_raw = config_data
                        current_stat = config_path.stat()
                        temp = prepare_config_temp(config_path, previous_raw, current_stat)
                        os.replace(temp, config_path)
                        parent_fd = os.open(config_path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                        try:
                            os.fsync(parent_fd)
                        finally:
                            os.close(parent_fd)
                    except Exception:
                        raise ManagerError('undo_rollback_failed', 'Adapter undo failed and configuration rollback could not be completed; manual recovery is required.') from exc
                raise
            adapter_undo_runtime_verified = bool(undo_results) and all(bool(r.get('runtimeVerified')) for r in undo_results)
        if config_data:
            _mark_config_transaction_undone(state,config_row,config_rows)
        row['undone']=True
        row['undoneAt']=dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_private_json(action_index_path(state),{'schema':'nexus-actions-v1','actions':actions[-20:]})
        runtime_status = (
            'hyprland-options-live-values-verified; other-adapter-visual-effects-unverified'
            if hyprland_options_id else
            'hyprland-live-option-verified'
            if adapter_undo_runtime_verified else
            'hyprland-reload-and-config-error-check-passed; visual-effect-unverified'
            if window_rules_id or window_glow_id or motion_profile_id else 'pending-existing-application-reload'
        )
        only_verified = (
            bool(hyprland_options_id and not (config_id or cursor_id or window_rules_id or window_glow_id or motion_profile_id or adapter_txns))
            or bool(adapter_undo_runtime_verified and not (config_id or cursor_id or window_rules_id or window_glow_id or motion_profile_id or hyprland_options_id))
        )
        return {'status':'undo_written_to_config','action':row.get('action'),'runtimeVerified':only_verified,'runtimeStatus':runtime_status}

    legacy_rows=reconcile_pending(config_path,state,read_undo_index(state))
    legacy=[row for row in legacy_rows if row.get('status')=='complete' and not row.get('undone')]
    if not legacy: raise ManagerError('undo_empty','There is no NEXUS change available to undo.')
    row=legacy[-1]
    if dry_run: return {'status':'dry_run','action':row.get('action'),'runtimeVerified':False}
    _restore_config_transaction(config_path,state,row['id'])
    return {'status':'undo_written_to_config','action':row.get('action'),'runtimeVerified':False,'runtimeStatus':'pending-existing-application-reload'}


_GOD_MENU_ADAPTER_IDS: tuple[str, ...] = (
    'desktop-appearance-adapter',
    'app-customization-adapter',
    'hyprland-godmode-adapter',
)


def god_menu_adapter_for_setting(setting_id: str) -> str | None:
    if setting_id in desktop_appearance_adapter.SETTING_SPECS:
        return 'desktop-appearance-adapter'
    if setting_id in app_customization_adapter.ALL_SETTING_IDS:
        return 'app-customization-adapter'
    if setting_id in hyprland_godmode_adapter.ALL_SETTING_IDS:
        return 'hyprland-godmode-adapter'
    return None


def _live_desktop_entry_dirs(data_home: Path) -> tuple[Path, ...]:
    return (
        data_home / 'applications',
        data_home / 'flatpak/exports/share/applications',
        Path('/var/lib/flatpak/exports/share/applications'),
        Path('/usr/local/share/applications'),
        Path('/usr/share/applications'),
    )


def _is_live_config_home(cfg_home: Path) -> bool:
    try:
        return cfg_home.resolve() == (Path.home() / '.config').resolve()
    except OSError:
        return False


def build_adapter_context(
    config_path: Path | None = None,
    state_root: Path | None = None,
    *,
    allow_live_hyprctl: bool | None = None,
) -> adapter_registry.AdapterContext:
    cfg = Path(config_path) if config_path is not None else DEFAULT_CONFIG
    st = Path(state_root) if state_root is not None else DEFAULT_STATE
    cfg_home = CONFIG_HOME
    if cfg != DEFAULT_CONFIG and cfg.parent.name == 'illogical-impulse':
        cfg_home = cfg.parent.parent
    st_home = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    if st != DEFAULT_STATE and st.name == 'nexus' and st.parent.name == 'aegis':
        st_home = st.parent.parent
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    quickshell_root = cfg_home / 'quickshell/ii'
    is_live_desktop = _is_live_config_home(cfg_home)
    effective_live = is_live_desktop if allow_live_hyprctl is None else bool(allow_live_hyprctl)
    desktop_dirs = (
        _live_desktop_entry_dirs(data_home)
        if is_live_desktop
        else (data_home / 'applications',)
    )
    return adapter_registry.AdapterContext.from_defaults(
        enable_live_hyprctl=effective_live,
        config_path=cfg,
        config_qml_path=quickshell_root / 'modules/common/Config.qml',
        state_root=st,
        config_home=cfg_home,
        data_home=data_home,
        quickshell_root=quickshell_root,
        hypr_custom_dir=cfg_home / 'hypr/custom',
        hypr_main_dir=cfg_home / 'hypr/hyprland',
        gtk3_ini=cfg_home / 'gtk-3.0/settings.ini',
        gtk4_ini=cfg_home / 'gtk-4.0/settings.ini',
        kdeglobals=cfg_home / 'kdeglobals',
        desktop_entry_dirs=desktop_dirs,
    )


def read_god_menu_values(context: adapter_registry.AdapterContext) -> dict[str, object]:
    values: dict[str, object] = {}
    reg = adapter_registry.create_default_registry()
    for aid in _GOD_MENU_ADAPTER_IDS:
        adp = reg.get(aid)
        if adp is None:
            continue
        try:
            state_res = adp.read_state(context)
            vals = state_res.get('values') if isinstance(state_res, dict) else None
            if isinstance(vals, dict):
                values.update(vals)
        except Exception:
            continue
    return values


def apply_god_menu_values(
    context: adapter_registry.AdapterContext,
    desired: dict[str, object],
) -> list[dict]:
    reg = adapter_registry.create_default_registry()
    txns: list[dict] = []
    try:
        for sid, val in sorted(desired.items()):
            aid = god_menu_adapter_for_setting(sid)
            if not aid:
                raise ManagerError('setting_unsupported', f'Unsupported setting: {sid}')
            adp = reg.get(aid)
            if adp is None:
                raise ManagerError('adapter_not_registered', f'Adapter not registered: {aid}')
            res = adp.apply_change({'id': sid}, val, context, dry_run=False)
            txn_id = res.get('transactionId') if isinstance(res, dict) else None
            if txn_id:
                txns.append({'adapterId': aid, 'settingId': sid, 'transactionId': txn_id})
    except adapter_registry.AdapterRegistryError as exc:
        if txns:
            try:
                rollback_adapter_transactions(context, txns)
            except Exception:
                pass
        raise ManagerError(exc.code, str(exc)) from exc
    except Exception:
        if txns:
            try:
                rollback_adapter_transactions(context, txns)
            except Exception:
                pass
        raise
    return txns


_ADAPTER_TXN_FOLDERS: dict[str, str] = {
    'desktop-appearance-adapter': 'desktop-appearance-transactions',
    'app-customization-adapter': 'app-customization-transactions',
    'hyprland-godmode-adapter': 'hyprland-godmode-transactions',
}


def _preflight_adapter_transactions(
    context: adapter_registry.AdapterContext,
    txns: list[dict],
) -> None:
    """Read-only verification of all God Menu adapter transactions (including chained edits) before undo."""
    reg = adapter_registry.create_default_registry()
    # Track simulated file state when walking transactions in reverse undo order.
    # Value is None when file is expected absent, or sha256 hex string when expected present.
    simulated_state: dict[str, str | None] = {}

    def _current_file_state(path: Path) -> str | None:
        key = str(path)
        if key in simulated_state:
            return simulated_state[key]
        if path.is_file() and not path.is_symlink():
            return sha256_bytes(path.read_bytes())
        return None

    for entry in reversed(txns):
        aid = str(entry.get('adapterId') or '')
        tid = str(entry.get('transactionId') or '')
        if reg.get(aid) is None or not re.fullmatch(r'[0-9a-f]{32}', tid):
            raise ManagerError('undo_snapshot_invalid', f'Invalid rollback adapter or transaction for {aid}.')
        folder_name = _ADAPTER_TXN_FOLDERS.get(aid)
        if not folder_name:
            continue
        txn_dir = context.state_root / folder_name / tid
        meta_path = txn_dir / 'meta.json'
        if not meta_path.is_file():
            raise ManagerError('undo_snapshot_invalid', f'The saved snapshot for {aid} is missing.')
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManagerError('undo_snapshot_invalid', f'The saved snapshot metadata for {aid} is unreadable.') from exc
        if meta.get('undone'):
            raise ManagerError('undo_already_done', 'This change was already undone.')

        if aid == 'hyprland-godmode-adapter':
            files_meta = meta.get('files')
            if isinstance(files_meta, list) and files_meta:
                for fmeta in files_meta:
                    target = Path(fmeta.get('path') or '')
                    expected_after = fmeta.get('afterSha256') if fmeta.get('existsAfter', True) else None
                    if _current_file_state(target) != expected_after:
                        raise ManagerError('undo_conflict', f'{target.name} changed externally after NEXUS updated it.')
                    if fmeta.get('existed'):
                        snap = txn_dir / str(fmeta.get('snapshot') or '')
                        if not snap.is_file() or sha256_bytes(snap.read_bytes()) != fmeta.get('beforeSha256'):
                            raise ManagerError('undo_snapshot_invalid', 'Hyprland backup failed checksum verification.')
                        simulated_state[str(target)] = fmeta.get('beforeSha256')
                    else:
                        simulated_state[str(target)] = None
            else:
                target = Path(meta.get('targetPath') or '')
                if _current_file_state(target) != meta.get('afterSha256'):
                    raise ManagerError('undo_conflict', f'{target.name} changed externally after NEXUS updated it.')
                if meta.get('existed') and meta.get('snapshot'):
                    snap = txn_dir / str(meta['snapshot'])
                    if not snap.is_file() or sha256_bytes(snap.read_bytes()) != meta.get('beforeSha256'):
                        raise ManagerError('undo_snapshot_invalid', 'Hyprland backup failed checksum verification.')
                    simulated_state[str(target)] = meta.get('beforeSha256')
                else:
                    simulated_state[str(target)] = None
        elif aid == 'desktop-appearance-adapter':
            for fmeta in meta.get('files') or []:
                target = Path(fmeta.get('path') or '')
                snap = txn_dir / str(fmeta.get('snapshot') or '')
                if not snap.is_file() or sha256_bytes(snap.read_bytes()) != fmeta.get('beforeSha256'):
                    raise ManagerError('undo_snapshot_invalid', 'A desktop appearance backup file failed checksum verification.')
                if _current_file_state(target) != fmeta.get('afterSha256'):
                    raise ManagerError('undo_conflict', f'{target.name} changed externally after NEXUS updated it.')
                simulated_state[str(target)] = fmeta.get('beforeSha256')
        elif aid == 'app-customization-adapter':
            for fmeta in meta.get('files') or []:
                target = Path(fmeta.get('path') or '')
                expected_after = fmeta.get('afterSha256') if fmeta.get('existsAfter') else None
                if _current_file_state(target) != expected_after:
                    raise ManagerError('undo_conflict', f'{target.name} changed externally after NEXUS updated it.')
                if fmeta.get('existed'):
                    snap = txn_dir / str(fmeta.get('snapshot') or '')
                    if not snap.is_file() or sha256_bytes(snap.read_bytes()) != fmeta.get('beforeSha256'):
                        raise ManagerError('undo_snapshot_invalid', f'Backup checksum mismatch for {target.name}.')
                    simulated_state[str(target)] = fmeta.get('beforeSha256')
                else:
                    simulated_state[str(target)] = None


def _ensure_god_menu_baseline_entry(
    state: Path,
    context: adapter_registry.AdapterContext,
    setting_id: str,
) -> None:
    """If an existing initial-state.json predates God Menu, capture the pre-mutation starting value first."""
    target = baseline_path(state)
    if not target.is_file():
        return
    try:
        existing = baseline_data(state)
    except ManagerError:
        return
    external = existing.setdefault('externalValues', {})
    saved_god = external.get('godMenuValues')
    if isinstance(saved_god, dict) and setting_id in saved_god:
        return
    aid = god_menu_adapter_for_setting(setting_id)
    if not aid:
        return
    reg = adapter_registry.create_default_registry()
    adp = reg.get(aid)
    if adp is None:
        return
    try:
        res = adp.read_state(context, {'id': setting_id})
        if not isinstance(res, dict) or 'value' not in res:
            return
        val = res['value']
        # Skip unset empty string for desktop-appearance settings where empty is invalid on write
        if aid == 'desktop-appearance-adapter' and val == '':
            return
    except Exception:
        return
    if not isinstance(saved_god, dict):
        saved_god = {}
        external['godMenuValues'] = saved_god
    saved_god[setting_id] = val
    try:
        atomic_private_json(target, existing)
    except Exception:
        pass


def rollback_adapter_transactions(
    context: adapter_registry.AdapterContext,
    txns: list[dict],
) -> list[dict]:
    reg = adapter_registry.create_default_registry()
    results: list[dict] = []
    for entry in reversed(txns):
        aid = str(entry.get('adapterId') or '')
        tid = str(entry.get('transactionId') or '')
        adp = reg.get(aid)
        if adp is None or not tid:
            raise ManagerError('undo_snapshot_invalid', f'Missing rollback adapter or transaction for {aid}.')
        try:
            res = adp.rollback_change(tid, context, confirm_risk=True)
            results.append(res if isinstance(res, dict) else {'status': 'undo_written_to_config'})
        except adapter_registry.AdapterRegistryError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
    return results


def setting_values_command(
    config_path: Path | None = None,
    state_root: Path | None = None,
    *,
    allow_live_hyprctl: bool | None = None,
) -> dict:
    ctx = build_adapter_context(config_path, state_root, allow_live_hyprctl=allow_live_hyprctl)
    vals = read_god_menu_values(ctx)
    try:
        h_opts = hyprland_options_adapter.read_options(ctx.effective_hyprland_options_paths())
        vals.update(h_opts)
    except Exception:
        pass
    return {'status': 'ok', 'values': vals, 'count': len(vals), 'runtimeVerified': False}


def set_universal_setting(
    setting_id: str,
    desired_value: object,
    config_path: Path,
    state: Path,
    definitions: dict[str, dict],
    *,
    confirm_risk: bool = False,
    dry_run: bool = False,
    adapter_context: adapter_registry.AdapterContext | None = None,
) -> dict:
    ctx = adapter_context or build_adapter_context(config_path, state)
    # 1. Existing hyprland-options-adapter (gaps_in, gaps_out, rounding)
    if setting_id in hyprland_options_adapter.OPTION_SPECS:
        return set_hyprland_options(
            state, definitions, {setting_id: desired_value}, dry_run, ctx.effective_hyprland_options_paths()
        )
    # 2. Universal God Menu adapters (desktop-appearance, app-customization, hyprland-godmode)
    aid = god_menu_adapter_for_setting(setting_id)
    if aid is not None:
        reg = adapter_registry.create_default_registry()
        adp = reg.get(aid)
        if adp is None:
            raise ManagerError('adapter_not_registered', f'Adapter unavailable: {aid}')
        if not dry_run:
            _ensure_god_menu_baseline_entry(state, ctx, setting_id)
        try:
            res = adp.apply_change({'id': setting_id}, desired_value, ctx, confirm_risk=confirm_risk, dry_run=dry_run)
        except adapter_registry.AdapterRegistryError as exc:
            raise ManagerError(exc.code, str(exc)) from exc
        if not dry_run and res.get('transactionId'):
            txn_entry = {'adapterId': aid, 'settingId': setting_id, 'transactionId': res['transactionId']}
            try:
                record_action(state, f'setting-set:{setting_id}', adapter_transactions=[txn_entry])
            except Exception as exc:
                try:
                    adp.rollback_change(res['transactionId'], ctx, confirm_risk=True)
                except Exception:
                    pass
                raise ManagerError('action_record_failed', 'The change was rolled back because the undo record could not be saved.') from exc
        return res
    # 3. Direct config-json setting
    defn = definitions.get(setting_id)
    if defn is not None and defn.get('sourceKind') == 'config-json' and isinstance(defn.get('path'), str):
        config, raw, st = read_config(config_path)
        path = defn['path']
        current = get_path(config, path)
        if not same_json_type(desired_value, current):
            raise ManagerError('value_invalid', f'Value type mismatch for {setting_id}.')
        if current == desired_value:
            return {'status': 'no_changes', 'settingId': setting_id, 'value': desired_value, 'runtimeVerified': False}
        if defn.get('risk') == 'confirmation-required' and not dry_run and not confirm_risk:
            raise ManagerError('risk_confirmation_required', f'Changing {setting_id} requires confirmation.')
        set_path(config, path, desired_value)
        return _apply_action(config_path, state, config, raw, st, f'setting-set:{setting_id}', [setting_id], dry_run, requires_confirmation=(defn.get('risk') == 'confirmation-required'))
    raise ManagerError('setting_unsupported', f'Setting {setting_id} does not have a verified apply adapter.')


def apps_catalog_command(
    config_path: Path | None = None,
    state_root: Path | None = None,
) -> dict:
    ctx = build_adapter_context(config_path, state_root)
    app_paths = ctx.effective_app_customization_paths()
    da_paths = ctx.effective_desktop_appearance_paths()
    apps = app_customization_adapter.list_installed_apps(app_paths, ctx.state_root)
    icon_themes = desktop_appearance_adapter.scan_icon_themes(da_paths.icon_search_paths)
    bar_icons: list[str] = []
    assets_icons_dir = (ctx.config_home / 'quickshell/ii/assets/icons')
    if assets_icons_dir.is_dir():
        stems = sorted(
            (p.stem[:-9] if p.stem.endswith('-symbolic') else p.stem)
            for p in assets_icons_dir.glob('*.svg')
            if p.is_file()
        )
        bar_icons = ['distro', *sorted(set(stems), key=str.casefold)]
    return {
        'status': 'ok',
        'apps': apps,
        'appCount': len(apps),
        'iconThemes': icon_themes,
        'barIcons': bar_icons,
        'runtimeVerified': False,
    }


def set_app_icon_command(
    app_id: str,
    icon_name_or_path: str,
    config_path: Path,
    state: Path,
    *,
    dry_run: bool = False,
    adapter_context: adapter_registry.AdapterContext | None = None,
) -> dict:
    ctx = adapter_context or build_adapter_context(config_path, state)
    paths = ctx.effective_app_customization_paths()
    if not dry_run:
        _ensure_god_menu_baseline_entry(state, ctx, 'apps.icons.overrides')
    try:
        res = app_customization_adapter.set_app_icon(paths, state, app_id, icon_name_or_path, dry_run=dry_run)
    except app_customization_adapter.AppCustomizationError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    if not dry_run and res.get('transactionId'):
        txn_entry = {'adapterId': 'app-customization-adapter', 'settingId': 'apps.icons.overrides', 'transactionId': res['transactionId']}
        try:
            record_action(state, f'app-icon-set:{app_id}', adapter_transactions=[txn_entry])
        except Exception as exc:
            try:
                app_customization_adapter.undo_transaction(paths, state, res['transactionId'])
            except Exception:
                pass
            raise ManagerError('action_record_failed', 'The app icon change was rolled back because the undo record could not be saved.') from exc
    res['appId'] = app_id
    return res


def reset_app_icon_command(
    app_id: str,
    config_path: Path,
    state: Path,
    *,
    dry_run: bool = False,
    adapter_context: adapter_registry.AdapterContext | None = None,
) -> dict:
    ctx = adapter_context or build_adapter_context(config_path, state)
    paths = ctx.effective_app_customization_paths()
    if not dry_run:
        _ensure_god_menu_baseline_entry(state, ctx, 'apps.icons.overrides')
    try:
        res = app_customization_adapter.reset_app_icon(paths, state, app_id, dry_run=dry_run)
    except app_customization_adapter.AppCustomizationError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    if not dry_run and res.get('transactionId'):
        txn_entry = {'adapterId': 'app-customization-adapter', 'settingId': 'apps.icons.overrides', 'transactionId': res['transactionId']}
        try:
            record_action(state, f'app-icon-reset:{app_id}', adapter_transactions=[txn_entry])
        except Exception as exc:
            try:
                app_customization_adapter.undo_transaction(paths, state, res['transactionId'])
            except Exception:
                pass
            raise ManagerError('action_record_failed', 'The app icon reset was rolled back because the undo record could not be saved.') from exc
    return res


def set_app_visibility_command(
    app_id: str,
    hidden: bool,
    config_path: Path,
    state: Path,
    *,
    dry_run: bool = False,
    adapter_context: adapter_registry.AdapterContext | None = None,
) -> dict:
    ctx = adapter_context or build_adapter_context(config_path, state)
    paths = ctx.effective_app_customization_paths()
    if not dry_run:
        _ensure_god_menu_baseline_entry(state, ctx, 'apps.visibility.hiddenApps')
    try:
        res = app_customization_adapter.set_app_hidden(paths, state, app_id, hidden, dry_run=dry_run)
    except app_customization_adapter.AppCustomizationError as exc:
        raise ManagerError(exc.code, str(exc)) from exc
    if not dry_run and res.get('transactionId'):
        txn_entry = {'adapterId': 'app-customization-adapter', 'settingId': 'apps.visibility.hiddenApps', 'transactionId': res['transactionId']}
        try:
            record_action(state, f"app-visibility-{'hide' if hidden else 'show'}:{app_id}", adapter_transactions=[txn_entry])
        except Exception as exc:
            try:
                app_customization_adapter.undo_transaction(paths, state, res['transactionId'])
            except Exception:
                pass
            raise ManagerError('action_record_failed', 'The app visibility change was rolled back because the undo record could not be saved.') from exc
    return res


def build_discovery_context(
    config_path: Path | None = None,
    registry_path: Path | None = None,
    state_root: Path | None = None,
    *,
    allow_live_hyprctl: bool | None = None,
) -> discovery_layer.DiscoveryContext:
    cfg = Path(config_path) if config_path is not None else DEFAULT_CONFIG
    reg = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY
    st = Path(state_root) if state_root is not None else DEFAULT_STATE
    cfg_home = CONFIG_HOME
    if cfg != DEFAULT_CONFIG and cfg.parent.name == 'illogical-impulse':
        cfg_home = cfg.parent.parent
    st_home = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    if st != DEFAULT_STATE and st.name == 'nexus' and st.parent.name == 'aegis':
        st_home = st.parent.parent
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    quickshell_root = cfg_home / 'quickshell/ii'
    is_live_desktop = _is_live_config_home(cfg_home)
    effective_live = is_live_desktop if allow_live_hyprctl is None else bool(allow_live_hyprctl)
    desktop_dirs = (
        _live_desktop_entry_dirs(data_home)
        if is_live_desktop
        else (data_home / 'applications',)
    )
    extra_paths: dict[str, object] = {'desktop_entry_dirs': desktop_dirs}
    if not is_live_desktop:
        extra_paths['cursor_search_paths'] = (data_home / 'icons',)
        extra_paths['icon_search_paths'] = (data_home / 'icons',)
    return discovery_layer.DiscoveryContext.from_defaults(
        allow_live_hyprctl=effective_live,
        catalog_path=reg,
        config_json_path=cfg,
        config_home=cfg_home,
        state_home=st_home,
        data_home=data_home,
        quickshell_root=quickshell_root,
        hypr_config_root=cfg_home / 'hypr',
        **extra_paths,
    )


def discover_command(
    config_path: Path | None = None,
    registry_path: Path | None = None,
    state_root: Path | None = None,
) -> dict:
    ctx = build_discovery_context(config_path, registry_path, state_root)
    res = discovery_layer.discover_inventory(ctx)
    payload = res.to_dict()
    candidates = payload.get('candidates', [])
    verified = payload.get('verifiedCandidates', [])
    unverified = payload.get('unverifiedCandidates', [])
    source_counts = payload.get('diagnostics', {}).get('sourceCounts', {})
    return {
        'status': 'ok',
        **payload,
        'settings': candidates,
        'sources': source_counts,
        'summary': {
            'totalCandidates': len(candidates),
            'verifiedCount': len(verified),
            'unverifiedCount': len(unverified),
            'sourceCounts': source_counts,
        },
        'runtimeVerified': False,
    }


_DEFAULT_CATEGORY_COMPONENTS: dict[str, str] = {
    'quick': 'modules/settings/QuickConfig.qml',
    'general': 'modules/settings/GeneralConfig.qml',
    'bar': 'modules/settings/BarConfig.qml',
    'background': 'modules/settings/BackgroundConfig.qml',
    'interface': 'modules/settings/InterfaceConfig.qml',
    'input': 'modules/settings/CursorConfig.qml',
    'services': 'modules/settings/ServicesConfig.qml',
    'appearance': 'modules/settings/AppearanceConfig.qml',
    'windows': 'modules/settings/WindowsConfig.qml',
    'effects': 'modules/settings/EffectsConfig.qml',
    'motion': 'modules/settings/MotionConfig.qml',
    'audio': 'modules/settings/AudioConfig.qml',
    'gaming': 'modules/settings/GamingConfig.qml',
}


def _is_non_ui_schema_component(comp: Any) -> bool:
    if not isinstance(comp, str):
        return False
    s = comp.strip()
    return s == 'modules/common/Config.qml' or s.startswith('modules/common/')


def _build_category_component_map(definitions: dict[str, dict] | None = None) -> dict[str, str]:
    comp_map = dict(_DEFAULT_CATEGORY_COMPONENTS)
    if definitions:
        for defn in definitions.values():
            if not isinstance(defn, dict):
                continue
            raw_cat = defn.get('category')
            raw_comp = defn.get('component')
            if isinstance(raw_cat, str) and raw_cat.strip() and isinstance(raw_comp, str) and raw_comp.strip():
                comp_str = raw_comp.strip()
                if not _is_non_ui_schema_component(comp_str):
                    cid = category_engine._canonicalize_domain_token(raw_cat)
                    if cid:
                        comp_map[cid] = comp_str
    return comp_map


def _enrich_category_tree_components(tree: dict, definitions: dict[str, dict] | None = None) -> dict[str, str]:
    comp_map = _build_category_component_map(definitions)
    for cat in tree.get('categories', []):
        if not isinstance(cat, dict):
            continue
        cid = str(cat.get('id') or '').strip().lower()
        if not cat.get('component'):
            cat['component'] = comp_map.get(cid, 'modules/settings/DynamicCategoryConfig.qml')
    return comp_map


def _enrich_candidates_metadata(
    rows: list[dict],
    tree: dict,
    definitions: dict[str, dict] | None = None,
    comp_map: dict[str, str] | None = None,
) -> None:
    if comp_map is None:
        comp_map = _build_category_component_map(definitions)
    assignments = tree.get('assignments') if isinstance(tree.get('assignments'), dict) else {}
    cat_title_map: dict[str, str] = {}
    cat_comp_map: dict[str, str] = {}
    for cat in tree.get('categories', []):
        if isinstance(cat, dict) and cat.get('id'):
            cat_id_lower = str(cat['id']).strip().lower()
            cat_title_map[cat_id_lower] = str(cat.get('title') or cat['id'])
            raw_cat_comp = cat.get('component')
            if isinstance(raw_cat_comp, str) and raw_cat_comp.strip() and not _is_non_ui_schema_component(raw_cat_comp):
                cat_comp_map[cat_id_lower] = raw_cat_comp.strip()
            else:
                cat_comp_map[cat_id_lower] = comp_map.get(cat_id_lower, 'modules/settings/DynamicCategoryConfig.qml')

    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get('id') or '')
        assign = assignments.get(sid) if isinstance(assignments, dict) else None
        defn = (definitions.get(sid) if definitions else None) or {}
        sem = row.get('semantics') if isinstance(row.get('semantics'), dict) else {}

        if isinstance(assign, dict) and assign.get('categoryId'):
            cid = str(assign['categoryId'])
            sub_id = str(assign.get('subcategoryId') or '') or None
        else:
            resolved_cid, _, _, _, is_fb = category_engine._resolve_domain_and_reason(row)
            if not is_fb and resolved_cid:
                cid = resolved_cid
            elif isinstance(defn.get('category'), str) and defn['category'].strip():
                cid = category_engine._canonicalize_domain_token(defn['category']) or None
            else:
                cid = None
            sub_id = None

        cid_lower = cid.lower() if isinstance(cid, str) and cid else ''
        cat_title = (
            cat_title_map.get(cid_lower)
            or (str(defn['category']).strip() if isinstance(defn.get('category'), str) and defn['category'].strip() else None)
            or (category_engine._humanize_slug(cid) if cid else None)
        )
        defn_comp = (
            str(defn['component']).strip()
            if isinstance(defn.get('component'), str) and defn['component'].strip() and not _is_non_ui_schema_component(defn['component'])
            else None
        )
        sem_comp_hint = (
            str(sem['componentHint']).strip()
            if isinstance(sem.get('componentHint'), str) and sem['componentHint'].strip() and not _is_non_ui_schema_component(sem['componentHint'])
            else None
        )
        comp = (
            cat_comp_map.get(cid_lower)
            or comp_map.get(cid_lower)
            or defn_comp
            or sem_comp_hint
            or ('modules/settings/DynamicCategoryConfig.qml' if cid_lower else None)
        )

        row['categoryId'] = cid
        row['subcategoryId'] = sub_id
        row['category'] = cat_title
        row['component'] = comp


def category_tree_command(
    config_path: Path | None = None,
    registry_path: Path | None = None,
    state_root: Path | None = None,
) -> dict:
    ctx = build_discovery_context(config_path, registry_path, state_root)
    disc_res = discovery_layer.discover_inventory(ctx)
    tree = category_engine.update_tree(disc_res)
    definitions: dict[str, dict] = {}
    reg = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY
    if reg.is_file():
        try:
            _, definitions = load_registry(reg)
        except Exception:
            definitions = {}
    _enrich_category_tree_components(tree, definitions)
    return {
        **tree,
        'status': 'ok',
    }


def catalog_state_command(
    catalog: dict,
    definitions: dict[str, dict],
    config_path: Path | None = None,
    registry_path: Path | None = None,
    state_root: Path | None = None,
) -> dict:
    ctx = build_discovery_context(config_path, registry_path, state_root)
    disc_res = discovery_layer.discover_inventory(ctx)
    disc_dict = disc_res.to_dict()
    candidates = disc_dict.get('candidates', [])
    verified_candidates = disc_dict.get('verifiedCandidates', [])
    unverified_candidates = disc_dict.get('unverifiedCandidates', [])
    tree = category_engine.update_tree(disc_res)
    comp_map = _enrich_category_tree_components(tree, definitions)
    _enrich_candidates_metadata(candidates, tree, definitions, comp_map)
    _enrich_candidates_metadata(verified_candidates, tree, definitions, comp_map)
    _enrich_candidates_metadata(unverified_candidates, tree, definitions, comp_map)
    raw_def_count = catalog.get('definitionCount')
    count_mismatch = (raw_def_count != len(definitions))
    st_root = Path(state_root) if state_root is not None else DEFAULT_STATE
    has_baseline = baseline_path(st_root).is_file()
    adapter_ctx = ctx.to_adapter_context()
    ext_values = read_god_menu_values(adapter_ctx)
    try:
        ext_values.update(hyprland_options_adapter.read_options(adapter_ctx.effective_hyprland_options_paths()))
    except Exception:
        pass
    initial_ext_values: dict[str, object] = {}
    if has_baseline:
        try:
            bdata = baseline_data(st_root)
            bext = bdata.get('externalValues') if isinstance(bdata, dict) else {}
            if isinstance(bext, dict):
                if isinstance(bext.get('godMenuValues'), dict):
                    initial_ext_values.update(bext['godMenuValues'])
                if isinstance(bext.get('hyprlandOptions'), dict):
                    initial_ext_values.update(bext['hyprlandOptions'])
        except Exception:
            pass
    return {
        **tree,
        'status': 'ok',
        'catalogSchema': catalog.get('schema'),
        'catalogDefinitionCount': len(definitions),
        'declaredDefinitionCount': raw_def_count,
        'catalogCountMismatch': count_mismatch,
        'baselineInitialized': has_baseline,
        'externalSettingValues': ext_values,
        'initialExternalSettingValues': initial_ext_values,
        'definitions': candidates,
        'candidates': candidates,
        'settings': candidates,
        'verifiedCandidates': verified_candidates,
        'unverifiedCandidates': unverified_candidates,
        'enrichment': disc_dict.get('enrichment', {}),
        'discoveryDiagnostics': disc_dict.get('diagnostics', {}),
        'categoryTree': tree,
        'tree': tree,
        'runtimeVerified': False,
    }


def resolve_category_setting_ids(
    category_target: str,
    definitions: dict[str, dict],
    *,
    explicit_setting_ids: list[str] | None = None,
    config_path: Path | None = None,
    registry_path: Path | None = None,
    state_root: Path | None = None,
) -> list[str]:
    if explicit_setting_ids:
        resolved: list[str] = []
        for raw_item in explicit_setting_ids:
            for item in str(raw_item).split(','):
                s = item.strip()
                if s and s not in resolved:
                    resolved.append(s)
        return resolved

    target = str(category_target or '').strip()
    if not target:
        return []
    target_cf = target.casefold()
    target_canon = category_engine._canonicalize_domain_token(target)

    # 1. Match catalog definitions by explicit category field (exact or case-insensitive or canonical)
    legacy_ids = [
        ident for ident, d in definitions.items()
        if str(d.get('category') or '').strip() == target
        or str(d.get('category') or '').strip().casefold() == target_cf
        or (target_canon and category_engine._canonicalize_domain_token(str(d.get('category') or '')) == target_canon)
    ]

    # 2. Match dynamic CategoryEngine tree (category id, title, or subcategory id)
    dynamic_ids: list[str] = []
    try:
        ctx = build_discovery_context(config_path, registry_path, state_root)
        disc_res = discovery_layer.discover_inventory(ctx)
        tree = category_engine.update_tree(disc_res)
        for cat in tree.get('categories', []):
            cid = str(cat.get('id') or '')
            ctitle = str(cat.get('title') or '')
            if (
                cid == target
                or cid.casefold() == target_cf
                or ctitle.casefold() == target_cf
                or (target_canon and cid == target_canon)
            ):
                for sid in cat.get('settingIds', []):
                    if sid not in dynamic_ids:
                        dynamic_ids.append(sid)
            for sub in cat.get('subcategories', []):
                sub_id = str(sub.get('id') or '')
                sub_title = str(sub.get('title') or '')
                if sub_id == target or sub_id.casefold() == target_cf or sub_title.casefold() == target_cf:
                    for sid in sub.get('settingIds', []):
                        if sid not in dynamic_ids:
                            dynamic_ids.append(sid)
    except Exception:
        pass

    combined: list[str] = []
    for sid in dynamic_ids + legacy_ids:
        if sid not in combined:
            combined.append(sid)
    return combined


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(add_help=True)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--state-root',type=Path,default=DEFAULT_STATE)
    parser.add_argument('--registry',type=Path,default=DEFAULT_REGISTRY)
    parser.add_argument('--dry-run',action='store_true')
    subs=parser.add_subparsers(dest='command',required=True)
    subs.add_parser('initialize')
    p=subs.add_parser('discover'); p.add_argument('--json',action='store_true')
    p=subs.add_parser('category-tree'); p.add_argument('--json',action='store_true')
    p=subs.add_parser('catalog-state'); p.add_argument('--json',action='store_true')
    subs.add_parser('cursor-status')
    p=subs.add_parser('cursor-reconcile'); p.add_argument('--source',choices=('environment.d+hyprland',),required=True); p.add_argument('--confirm-risk',action='store_true')
    subs.add_parser('window-rules-status')
    subs.add_parser('window-glow-status')
    subs.add_parser('motion-profile-status')
    subs.add_parser('hyprland-options-status')
    subs.add_parser('backup-list')
    p=subs.add_parser('backup-verify'); p.add_argument('backup_id')
    p=subs.add_parser('backup-restore'); p.add_argument('backup_id'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('hyprland-options-set'); p.add_argument('values_json')
    p=subs.add_parser('cursor-set'); p.add_argument('theme'); p.add_argument('size',type=int)
    p=subs.add_parser('setting-values'); p.add_argument('--json',action='store_true')
    p=subs.add_parser('setting-set'); p.add_argument('id'); p.add_argument('value_json'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('apps-catalog'); p.add_argument('--json',action='store_true')
    p=subs.add_parser('app-icon-set'); p.add_argument('app_id'); p.add_argument('icon')
    p=subs.add_parser('app-icon-reset'); p.add_argument('app_id')
    p=subs.add_parser('app-visibility-set'); p.add_argument('app_id'); p.add_argument('mode',choices=('hide','show'))
    subs.add_parser('profile-list')
    p=subs.add_parser('profile-save'); p.add_argument('name')
    p=subs.add_parser('profile-load'); p.add_argument('name'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('profile-copy'); p.add_argument('source'); p.add_argument('target',nargs='?')
    p=subs.add_parser('profile-delete'); p.add_argument('name')
    p=subs.add_parser('reset'); p.add_argument('id'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('reset-category'); p.add_argument('category'); p.add_argument('--setting-ids',nargs='*'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('reset-all'); p.add_argument('--confirm-risk',action='store_true')
    p=subs.add_parser('undo'); p.add_argument('--confirm-risk',action='store_true')
    return parser


def main() -> None:
    args=build_parser().parse_args()
    try:
        catalog,definitions=load_registry(args.registry)
        cli_adapter_ctx=build_adapter_context(args.config,args.state_root)
        if args.command=='initialize':
            result=create_baseline(args.config,args.state_root,definitions,cursor_paths=DEFAULT_CURSOR_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        elif args.command=='discover':
            result=discover_command(args.config,args.registry,args.state_root)
        elif args.command=='category-tree':
            result=category_tree_command(args.config,args.registry,args.state_root)
        elif args.command=='catalog-state':
            result=catalog_state_command(catalog,definitions,args.config,args.registry,args.state_root)
        elif args.command=='setting-values':
            result=setting_values_command(args.config,args.state_root)
        elif args.command=='setting-set':
            try:
                parsed_val=json.loads(args.value_json)
            except json.JSONDecodeError as exc:
                raise ManagerError('values_invalid','The requested setting value is not valid JSON.') from exc
            result=set_universal_setting(args.id,parsed_val,args.config,args.state_root,definitions,confirm_risk=args.confirm_risk,dry_run=args.dry_run,adapter_context=cli_adapter_ctx)
        elif args.command=='apps-catalog':
            result=apps_catalog_command(args.config,args.state_root)
        elif args.command=='app-icon-set':
            result=set_app_icon_command(args.app_id,args.icon,args.config,args.state_root,dry_run=args.dry_run,adapter_context=cli_adapter_ctx)
        elif args.command=='app-icon-reset':
            result=reset_app_icon_command(args.app_id,args.config,args.state_root,dry_run=args.dry_run,adapter_context=cli_adapter_ctx)
        elif args.command=='app-visibility-set':
            result=set_app_visibility_command(args.app_id,args.mode=='hide',args.config,args.state_root,dry_run=args.dry_run,adapter_context=cli_adapter_ctx)
        elif args.command=='cursor-status':
            result=cursor_status(DEFAULT_CURSOR_PATHS,DEFAULT_CURSOR_SEARCH_PATHS)
        elif args.command=='cursor-reconcile':
            result=reconcile_cursor_setting(args.state_root,DEFAULT_CURSOR_PATHS,args.source,args.confirm_risk,args.dry_run,DEFAULT_CURSOR_SEARCH_PATHS)
        elif args.command=='window-rules-status':
            result=window_rule_status(DEFAULT_WINDOW_RULE_PATHS)
        elif args.command=='window-glow-status':
            result=window_glow_status(DEFAULT_WINDOW_GLOW_PATHS)
        elif args.command=='motion-profile-status':
            result=motion_profile_status(DEFAULT_MOTION_PROFILE_PATHS)
        elif args.command=='hyprland-options-status':
            result=hyprland_options_status(DEFAULT_HYPRLAND_OPTIONS_PATHS)
        elif args.command=='backup-list':
            result=backup_list(DEFAULT_BACKUP_RECOVERY_PATHS)
        elif args.command=='backup-verify':
            result=backup_verify(args.backup_id,DEFAULT_BACKUP_RECOVERY_PATHS)
        elif args.command=='backup-restore':
            result=backup_restore(args.backup_id,args.confirm_risk,args.dry_run,DEFAULT_BACKUP_RECOVERY_PATHS)
        elif args.command=='hyprland-options-set':
            try:
                values=json.loads(args.values_json)
            except json.JSONDecodeError as exc:
                raise ManagerError('values_invalid','The requested Hyprland values could not be read.') from exc
            result=set_hyprland_options(args.state_root,definitions,values,args.dry_run,DEFAULT_HYPRLAND_OPTIONS_PATHS)
        elif args.command=='cursor-set':
            result=set_cursor_setting(args.state_root,DEFAULT_CURSOR_PATHS,args.theme,args.size,args.dry_run,DEFAULT_CURSOR_SEARCH_PATHS)
        elif args.command=='profile-list':
            result=list_profiles(args.state_root,definitions)
        elif args.command=='profile-save':
            result=save_profile(args.name,args.config,args.state_root,definitions,cursor_paths=DEFAULT_CURSOR_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,lowercase_slug=True,adapter_context=cli_adapter_ctx)
        elif args.command=='profile-copy':
            result=copy_profile(args.source,args.target,args.state_root,lowercase_slug=True)
        elif args.command=='profile-delete':
            result=delete_profile(args.name,args.state_root)
        elif args.command=='profile-load':
            result=load_profile(args.name,args.config,args.state_root,definitions,args.dry_run,cursor_paths=DEFAULT_CURSOR_PATHS,search_paths=DEFAULT_CURSOR_SEARCH_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,confirm_risk=args.confirm_risk,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        elif args.command=='reset':
            result=reset_values(args.config,args.state_root,definitions,[args.id],args.dry_run,'reset-one',cursor_paths=DEFAULT_CURSOR_PATHS,search_paths=DEFAULT_CURSOR_SEARCH_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,confirm_risk=args.confirm_risk,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        elif args.command=='reset-category':
            ids=resolve_category_setting_ids(
                args.category,
                definitions,
                explicit_setting_ids=args.setting_ids,
                config_path=args.config,
                registry_path=args.registry,
                state_root=args.state_root,
            )
            result=reset_values(args.config,args.state_root,definitions,ids,args.dry_run,'reset-category',cursor_paths=DEFAULT_CURSOR_PATHS,search_paths=DEFAULT_CURSOR_SEARCH_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,confirm_risk=args.confirm_risk,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        elif args.command=='reset-all':
            all_ids=list(definitions) + list(read_god_menu_values(cli_adapter_ctx).keys())
            result=reset_values(args.config,args.state_root,definitions,all_ids,args.dry_run,'reset-all',cursor_paths=DEFAULT_CURSOR_PATHS,search_paths=DEFAULT_CURSOR_SEARCH_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,confirm_risk=args.confirm_risk,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        elif args.command=='undo':
            result=undo_last(args.config,args.state_root,args.dry_run,cursor_paths=DEFAULT_CURSOR_PATHS,window_rule_paths=DEFAULT_WINDOW_RULE_PATHS,confirm_risk=args.confirm_risk,window_glow_paths=DEFAULT_WINDOW_GLOW_PATHS,motion_paths=DEFAULT_MOTION_PROFILE_PATHS,hyprland_options_paths=DEFAULT_HYPRLAND_OPTIONS_PATHS,adapter_context=cli_adapter_ctx)
        else:
            raise ManagerError('unknown_command','The NEXUS action is not supported.')
        result['catalogDefinitionCount']=len(definitions)
        emit(result)
    except ManagerError as exc:
        emit({'status':'error','code':exc.code,'message':str(exc),'runtimeVerified':False},1)
    except backup_recovery.BackupRecoveryError as exc:
        emit({'status':'error','code':exc.code,'message':str(exc),'runtimeVerified':False},1)
    except (OSError, ValueError, TypeError, KeyError):
        emit({'status':'error','code':'operation_failed','message':'The NEXUS action failed safely; the configuration was not reported as applied.','runtimeVerified':False},1)

if __name__=='__main__': main()
