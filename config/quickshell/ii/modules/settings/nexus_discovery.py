"""Layer 2 Central Multi-Source Discovery & Verification Gate for NEXUS."""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field, replace
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tomllib
from typing import Any, Callable, Iterable, Sequence

from nexus_adapter_registry import (
    BUILTIN_ADAPTER_IDS,
    AdapterContext,
    AdapterRegistry,
    CapabilityProbeResult,
    create_default_registry,
    map_quickshell_namespace,
    parse_hl_config_blocks,
)
import nexus_desktop_appearance_adapter as desktop_appearance_adapter
import nexus_hyprland_options_adapter as hyprland_options_adapter


_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))

ALL_SOURCES: frozenset[str] = frozenset(
    {
        "catalog",
        "quickshell",
        "hyprland",
        "aegis_pulsar",
        "adapters",
        "theme_locale",
        "apps",
        "dynamic_features",
    }
)

_AUTHORITY_RANK: dict[str, int] = {
    "adapters": 0,
    "catalog": 1,
    "dynamic_features": 2,
    "quickshell": 3,
    "hyprland": 4,
    "aegis_pulsar": 5,
    "theme_locale": 6,
    "apps": 7,
}

_HUMAN_PRIORITY: dict[str, int] = {
    "catalog": 0,
    "adapters": 1,
    "dynamic_features": 2,
    "quickshell": 3,
    "hyprland": 4,
    "aegis_pulsar": 5,
    "theme_locale": 6,
    "apps": 7,
}

_SOURCE_KIND_TO_ADAPTER: dict[str, str] = {
    "config-json": "config-json",
    "cursor-adapter": "cursor-adapter",
    "window-rule-adapter": "window-rule-adapter",
    "window-glow-adapter": "window-glow-adapter",
    "motion-profile-adapter": "motion-profile-adapter",
    "hyprland-options-adapter": "hyprland-options-adapter",
    "desktop-appearance-adapter": "desktop-appearance-adapter",
    "app-customization-adapter": "app-customization-adapter",
    "hyprland-godmode-adapter": "hyprland-godmode-adapter",
    "script-backed": "script-backed",
}

_HYPRLAND_OPTION_MAP: dict[str, str] = {
    spec["option"]: sid for sid, spec in hyprland_options_adapter.OPTION_SPECS.items()
}


@dataclass(frozen=True)
class DiscoveryContext:
    """Explicit path, registry, and runner injection context for Layer 2 discovery."""

    catalog_path: Path
    config_json_path: Path
    quickshell_root: Path
    hypr_config_root: Path
    config_home: Path
    state_home: Path
    data_home: Path
    adapter_registry: AdapterRegistry | None = None
    feature_manifest_dirs: tuple[Path, ...] = ()
    cursor_search_paths: tuple[Path, ...] = ()
    icon_search_paths: tuple[Path, ...] = ()
    translations_dirs: tuple[Path, ...] = ()
    desktop_entry_dirs: tuple[Path, ...] = ()
    allow_live_hyprctl: bool = False
    hyprctl: str = "hyprctl"
    hyprctl_runner: Callable[[list[str]], Any] | None = None
    enabled_sources: frozenset[str] = ALL_SOURCES
    extra_candidates: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_defaults(
        cls,
        *,
        allow_live_hyprctl: bool = True,
        adapter_registry: AdapterRegistry | None = None,
        **overrides: Any,
    ) -> "DiscoveryContext":
        config_home = Path(overrides.pop("config_home", _CONFIG_HOME))
        state_home = Path(overrides.pop("state_home", _STATE_HOME))
        data_home = Path(overrides.pop("data_home", _DATA_HOME))
        quickshell_root = Path(
            overrides.pop("quickshell_root", config_home / "quickshell/ii")
        )
        base = cls(
            catalog_path=Path(__file__).with_name("nexus-settings.json"),
            config_json_path=config_home / "illogical-impulse/config.json",
            quickshell_root=quickshell_root,
            hypr_config_root=config_home / "hypr",
            config_home=config_home,
            state_home=state_home,
            data_home=data_home,
            adapter_registry=adapter_registry,
            feature_manifest_dirs=(
                quickshell_root / "modules/settings/features.d",
            ),
            cursor_search_paths=(
                data_home / "icons",
                Path.home() / ".icons",
                Path("/usr/share/icons"),
                Path("/usr/share/pixmaps"),
            ),
            icon_search_paths=(
                data_home / "icons",
                Path.home() / ".icons",
                Path("/usr/share/icons"),
            ),
            translations_dirs=(quickshell_root / "translations",),
            desktop_entry_dirs=(
                data_home / "applications",
                data_home / "flatpak/exports/share/applications",
                Path("/var/lib/flatpak/exports/share/applications"),
                Path("/usr/local/share/applications"),
                Path("/usr/share/applications"),
            ),
            allow_live_hyprctl=allow_live_hyprctl,
        )
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields}
        return replace(base, **filtered)

    @classmethod
    def isolated(cls, root: Path, **overrides: Any) -> "DiscoveryContext":
        """Create a hermetically isolated context rooted under `root` with allow_live_hyprctl=False."""
        root_path = Path(root)
        config_home = Path(overrides.pop("config_home", root_path / ".config"))
        state_home = Path(overrides.pop("state_home", root_path / ".local/state"))
        data_home = Path(overrides.pop("data_home", root_path / ".local/share"))
        quickshell_root = Path(
            overrides.pop("quickshell_root", config_home / "quickshell/ii")
        )
        hypr_config_root = Path(
            overrides.pop("hypr_config_root", config_home / "hypr")
        )
        base = cls(
            catalog_path=root_path / "nexus-settings.json",
            config_json_path=config_home / "illogical-impulse/config.json",
            quickshell_root=quickshell_root,
            hypr_config_root=hypr_config_root,
            config_home=config_home,
            state_home=state_home,
            data_home=data_home,
            adapter_registry=overrides.pop("adapter_registry", None),
            feature_manifest_dirs=(
                quickshell_root / "modules/settings/features.d",
            ),
            cursor_search_paths=(data_home / "icons",),
            icon_search_paths=(data_home / "icons",),
            translations_dirs=(quickshell_root / "translations",),
            desktop_entry_dirs=(data_home / "applications",),
            allow_live_hyprctl=False,
        )
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in overrides.items() if k in valid_fields}
        return replace(base, **filtered)

    def to_adapter_context(self) -> AdapterContext:
        return AdapterContext.isolated(
            self.config_home.parent,
            config_path=self.config_json_path,
            config_qml_path=self.quickshell_root / "modules/common/Config.qml",
            state_root=self.state_home / "aegis/nexus",
            config_home=self.config_home,
            data_home=self.data_home,
            cursor_search_paths=self.cursor_search_paths,
            hypr_custom_dir=self.hypr_config_root / "custom",
            hypr_main_dir=self.hypr_config_root / "hyprland",
            game_mode_helper=self.quickshell_root / "scripts/game-mode/pulsar_game_mode.py",
            game_mode_detector=self.quickshell_root / "scripts/game-mode/pulsar_game_detector.py",
            game_mode_state_file=self.state_home / "quickshell/user/game-mode.json",
            matugen_config=self.config_home / "matugen/config.toml",
            matugen_colors=self.state_home / "quickshell/user/generated/colors.json",
            gtk3_ini=self.config_home / "gtk-3.0/settings.ini",
            gtk4_ini=self.config_home / "gtk-4.0/settings.ini",
            kdeglobals=self.config_home / "kdeglobals",
            kde_material_you_conf=self.config_home / "kde-material-you-colors/config.conf",
            translations_dirs=self.translations_dirs,
            desktop_entry_dirs=self.desktop_entry_dirs,
            hyprctl=self.hyprctl,
            enable_live_hyprctl=self.allow_live_hyprctl,
            hyprctl_runner=self.hyprctl_runner,
            allow_script_execution=False,
        )


@dataclass
class DiscoveredCandidate:
    """Normalized candidate setting across all 8 sources."""

    id: str
    title: str
    description: str
    valueType: str
    source: str
    sourceKind: str
    adapter: str | None
    path: str | None
    controlType: str
    risk: str
    sensitive: bool
    applyMethod: str
    profileSupported: bool
    resetSupported: bool
    keywords: list[str] = field(default_factory=list)
    choices: list[Any] | None = None
    limits: dict[str, Any] | None = None
    discoveredFrom: list[str] = field(default_factory=list)
    semantics: dict[str, Any] = field(
        default_factory=lambda: {
            "domainHints": [],
            "featureGroup": "",
            "componentHint": None,
            "targetApp": None,
            "tags": [],
        }
    )
    verification: dict[str, Any] = field(
        default_factory=lambda: {
            "readable": False,
            "applicable": False,
            "verified": False,
            "verifiedRead": False,
            "verifiedApply": False,
            "manageable": False,
            "runtimeVerified": False,
            "reason": "unverified",
            "verificationReason": "unverified",
        }
    )
    canonicalKey: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "valueType": self.valueType,
            "source": self.source,
            "sourceKind": self.sourceKind,
            "adapter": self.adapter,
            "path": self.path,
            "controlType": self.controlType,
            "risk": self.risk,
            "sensitive": self.sensitive,
            "applyMethod": self.applyMethod,
            "profileSupported": self.profileSupported,
            "resetSupported": self.resetSupported,
            "keywords": list(self.keywords),
            "choices": list(self.choices) if self.choices is not None else None,
            "limits": dict(self.limits) if self.limits is not None else None,
            "discoveredFrom": list(self.discoveredFrom),
            "semantics": {
                "domainHints": list(self.semantics.get("domainHints", [])),
                "featureGroup": self.semantics.get("featureGroup", ""),
                "componentHint": self.semantics.get("componentHint"),
                "targetApp": self.semantics.get("targetApp"),
                "tags": list(self.semantics.get("tags", [])),
            },
            "verification": dict(self.verification),
        }


@dataclass
class DiscoveryResult:
    """Complete Layer 2 discovery output for Layer 3 (Category Engine) and Layer 4 (Catalog)."""

    schema: str
    inventoryHash: str
    stateSnapshotHash: str
    generatedAt: str
    candidates: list[DiscoveredCandidate]
    verifiedCandidates: list[DiscoveredCandidate]
    unverifiedCandidates: list[DiscoveredCandidate]
    enrichment: dict[str, Any]
    delta: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "inventoryHash": self.inventoryHash,
            "stateSnapshotHash": self.stateSnapshotHash,
            "generatedAt": self.generatedAt,
            "candidates": [c.to_dict() for c in self.candidates],
            "verifiedCandidates": [c.to_dict() for c in self.verifiedCandidates],
            "unverifiedCandidates": [c.to_dict() for c in self.unverifiedCandidates],
            "enrichment": dict(self.enrichment),
            "delta": dict(self.delta),
            "diagnostics": dict(self.diagnostics),
        }


# ---------------------------------------------------------------------------
# Pure-Python Safety & Parsing Helpers
# ---------------------------------------------------------------------------

def _is_regular_file(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


def _read_regular_text(path: Path) -> str | None:
    if not _is_regular_file(path):
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _human_title(identifier: str) -> str:
    leaf = identifier.split(".")[-1]
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    spaced = spaced.replace("_", " ").replace("-", " ").strip()
    if not spaced:
        return identifier
    return spaced[0].upper() + spaced[1:].lower()


def _sanitize_setting_title(title: Any, setting_id: str) -> str:
    """Clean truncated QML/catalog titles (e.g. dangling '(', '[', ':') while preserving valid titles."""
    if not isinstance(title, str):
        return _human_title(setting_id)
    cleaned = re.sub(r"\s+", " ", title).strip()
    for open_ch, close_ch in (("(", ")"), ("[", "]"), ("{", "}")):
        while cleaned.count(open_ch) > cleaned.count(close_ch):
            idx = cleaned.rfind(open_ch)
            if idx < 0:
                break
            cleaned = cleaned[:idx].rstrip()
    cleaned = re.sub(r"[\s:+\-]+$", "", cleaned).strip()
    if not cleaned:
        return _human_title(setting_id)
    return cleaned


def _sanitize_setting_description(description: Any, raw_title: Any, clean_title: str) -> str:
    text = str(description or "").strip()
    if not text:
        return ""
    if isinstance(raw_title, str):
        raw_norm = raw_title.strip()
        if raw_norm and raw_norm != clean_title and text.startswith(raw_norm):
            text = clean_title + text[len(raw_norm):]
    return text


def _split_camel_tokens(text: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [tok.lower() for tok in re.split(r"[^A-Za-z0-9]+", spaced) if tok]


def _flatten_json(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    leaves: dict[str, Any] = {}
    for key, val in obj.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict) and val:
            leaves.update(_flatten_json(val, dotted))
        else:
            leaves[dotted] = val
    return leaves


def _infer_value_type(value: Any) -> str:
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


def _infer_control_type(value_type: str, *, choices: Sequence[Any] | None = None, path: str = "", value: Any = None) -> str:
    if value_type == "boolean":
        return "ConfigSwitch"
    if value_type == "integer":
        return "ConfigSpinBox"
    if value_type == "number":
        lower = path.lower()
        if any(k in lower for k in ("opacity", "transparency", "scale", "factor", "harmony", "boost", "zoom")) or (
            isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0
        ):
            return "ConfigSlider"
        return "ConfigSpinBox"
    if value_type == "string":
        if choices:
            return "ConfigSelectionArray"
        return "MaterialTextArea"
    if value_type == "array":
        if isinstance(value, list) and any(isinstance(x, dict) for x in value):
            return "custom-editor"
        return "list-editor"
    if value_type == "object":
        return "custom-editor"
    return "readonly-info"


def _extract_comment_hints(comment: str) -> tuple[list[str] | None, str | None]:
    """Extract inline enum choices and unit hints from a Config.qml trailing comment."""
    if not comment:
        return None, None
    clean = comment.strip().lstrip("/").strip()
    unit: str | None = None
    if re.search(r"\bmilliseconds\b", clean, re.IGNORECASE):
        unit = "milliseconds"
    elif re.search(r"\bminutes\b", clean, re.IGNORECASE):
        unit = "minutes"
    elif "%" in clean:
        unit = "percent"

    # Pattern 1: `0: No | 1: Yes | 2: Local`
    if "|" in clean and re.search(r"\b\d+\s*:", clean):
        opts = [part.strip() for part in clean.split("|") if part.strip()]
        if len(opts) >= 2:
            return opts, unit

    # Pattern 2: quoted strings like `"auto", "scheme-content"` or `Options: "cookie", "digital"`
    quoted = re.findall(r'"([^"]+)"', clean)
    if len(quoted) >= 2 and not any(w in clean.lower() for w in ("format:", "example", "like ", "when ")):
        return quoted, unit

    # Pattern 3: `Allowed: a, b, c` or `Options: a, b, c` or `search, functions, or none`
    m = re.match(r"^(?:Allowed|Options)\s*:\s*(.+)$", clean, re.IGNORECASE)
    if m:
        raw_list = m.group(1)
        items = [
            re.sub(r"^or\s+", "", part.strip().strip('"').strip("'"))
            for part in raw_list.split(",")
        ]
        items = [x for x in items if x and " " not in x]
        if len(items) >= 2:
            return items, unit

    m_or = re.fullmatch(r"([A-Za-z0-9_-]+(?:\s*,\s*[A-Za-z0-9_-]+)+)\s*,?\s*or\s+([A-Za-z0-9_-]+)", clean)
    if m_or:
        head = [x.strip() for x in m_or.group(1).split(",") if x.strip()]
        head.append(m_or.group(2).strip())
        if len(head) >= 2:
            return head, unit

    return None, unit


def parse_config_qml(qml_text: str) -> dict[str, dict[str, Any]]:
    """Pure-Python string-aware parser for `JsonAdapter { ... }` in `Config.qml`."""
    adapter_match = re.search(r"\bJsonAdapter\s*\{", qml_text)
    if not adapter_match:
        return {}

    pos = adapter_match.end()
    n = len(qml_text)
    stack: list[str] = []
    # Track brace scopes that belong to JsonObject properties vs root JsonAdapter
    brace_stack: list[str | None] = ["__ROOT__"]
    results: dict[str, dict[str, Any]] = {}

    def skip_ws_and_comments(idx: int) -> int:
        while idx < n:
            ch = qml_text[idx]
            if ch in " \t\r\n":
                idx += 1
            elif qml_text.startswith("//", idx):
                nl = qml_text.find("\n", idx)
                idx = n if nl == -1 else nl + 1
            elif qml_text.startswith("/*", idx):
                end = qml_text.find("*/", idx + 2)
                idx = n if end == -1 else end + 2
            else:
                break
        return idx

    def read_rhs_and_comment(start_idx: int) -> tuple[str, str, int]:
        """Read RHS expression (single-line or balanced []/{}) plus trailing `//` comment."""
        i = start_idx
        while i < n and qml_text[i] in " \t":
            i += 1
        buf: list[str] = []
        bracket_depth = 0
        brace_depth = 0
        paren_depth = 0
        quote: str | None = None
        inline_comment = ""

        while i < n:
            ch = qml_text[i]
            if quote is not None:
                buf.append(ch)
                if ch == "\\" and i + 1 < n:
                    buf.append(qml_text[i + 1])
                    i += 2
                    continue
                if ch == quote:
                    quote = None
                i += 1
                continue

            if ch in ('"', "'", "`"):
                quote = ch
                buf.append(ch)
                i += 1
                continue

            if qml_text.startswith("//", i):
                nl = qml_text.find("\n", i)
                end_line = n if nl == -1 else nl
                comment_txt = qml_text[i + 2 : end_line].strip()
                if bracket_depth == 0 and brace_depth == 0 and paren_depth == 0:
                    inline_comment = comment_txt
                    i = end_line
                    break
                # Inside multi-line literal: skip comment without breaking
                i = end_line
                continue

            if ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth = max(0, bracket_depth - 1)
            elif ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth = max(0, brace_depth - 1)
            elif ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth = max(0, paren_depth - 1)
            elif ch == "\n" and bracket_depth == 0 and brace_depth == 0 and paren_depth == 0:
                break

            buf.append(ch)
            i += 1

        return "".join(buf).strip(), inline_comment, i

    def parse_literal(rhs: str, qml_type: str) -> tuple[Any, str]:
        if not rhs:
            return None, "empty"
        if rhs.startswith("`") and rhs.endswith("`") and len(rhs) >= 2:
            return rhs[1:-1], "backtick-string"
        # Attempt clean JSON parse (stripping trailing commas)
        cleaned = re.sub(r",\s*([\]\}])", r"\1", rhs)
        try:
            return json.loads(cleaned), "literal"
        except json.JSONDecodeError:
            return rhs, "runtime-expression"

    qml_to_valtype = {
        "bool": "boolean",
        "int": "integer",
        "real": "number",
        "string": "string",
        "list<string>": "array",
        "list<var>": "array",
    }

    while pos < n and brace_stack:
        pos = skip_ws_and_comments(pos)
        if pos >= n:
            break
        ch = qml_text[pos]
        if ch == "}":
            popped = brace_stack.pop()
            if popped and popped != "__ROOT__":
                stack.pop()
            pos += 1
            continue
        if ch in ('"', "'", "`"):
            quote = ch
            pos += 1
            while pos < n:
                if qml_text[pos] == "\\" and pos + 1 < n:
                    pos += 2
                    continue
                if qml_text[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue

        # Check for `property JsonObject <name>: JsonObject {`
        obj_match = re.match(
            r"property\s+JsonObject\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*JsonObject\s*\{",
            qml_text[pos:],
        )
        if obj_match:
            obj_name = obj_match.group(1)
            stack.append(obj_name)
            brace_stack.append(obj_name)
            pos += obj_match.end()
            continue

        # Check for `property <type> <name>: <rhs>`
        prop_match = re.match(
            r"property\s+(bool|int|real|string|list<string>|list<var>)\s+([A-Za-z_][A-Za-z0-9_]*)\s*:",
            qml_text[pos:],
        )
        if prop_match:
            qml_type = prop_match.group(1)
            prop_name = prop_match.group(2)
            pos += prop_match.end()
            rhs, comment, pos = read_rhs_and_comment(pos)
            default_val, default_source = parse_literal(rhs, qml_type)
            choices, unit = _extract_comment_hints(comment)
            dotted = ".".join([*stack, prop_name])
            results[dotted] = {
                "path": dotted,
                "qmlType": qml_type,
                "valueType": qml_to_valtype.get(qml_type, "unknown"),
                "defaultValue": default_val,
                "defaultSource": default_source,
                "comment": comment,
                "choices": choices,
                "unit": unit,
            }
            continue

        pos += 1

    return results


# ---------------------------------------------------------------------------
# Source 1: nexus-settings.json Catalog
# ---------------------------------------------------------------------------

def discover_source_1_catalog(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    text = _read_regular_text(context.catalog_path)
    if text is None:
        if diagnostics is not None:
            diagnostics.setdefault("warnings", []).append(
                f"catalog missing or unreadable: {context.catalog_path}"
            )
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        if diagnostics is not None:
            diagnostics.setdefault("errors", []).append(
                {"source": "catalog", "error": f"invalid JSON: {exc}"}
            )
        return []

    definitions = payload.get("definitions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list):
        return []

    candidates: list[DiscoveredCandidate] = []
    for row in definitions:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        sid = row["id"]
        source_kind = str(row.get("sourceKind") or "config-json")
        adapter_id = row.get("adapter") or _SOURCE_KIND_TO_ADAPTER.get(source_kind)
        vtype = str(row.get("valueType") or "unknown")
        raw_title = row.get("title")
        title = _sanitize_setting_title(raw_title, sid)
        description = _sanitize_setting_description(row.get("description"), raw_title, title)
        control_type = row.get("controlType")
        if not isinstance(control_type, str) or not control_type.strip():
            if source_kind == "script-backed":
                control_type = "readonly-info"
            elif source_kind == "hyprland-options-adapter":
                control_type = "ConfigSpinBox"
            elif source_kind in ("window-rule-adapter", "window-glow-adapter"):
                control_type = "custom-editor"
            elif source_kind == "motion-profile-adapter":
                control_type = "combo"
            else:
                control_type = _infer_control_type(vtype, path=str(row.get("path") or sid))

        path = row.get("path")
        if path is None and source_kind == "hyprland-options-adapter":
            spec = hyprland_options_adapter.OPTION_SPECS.get(sid)
            if spec:
                path = spec["option"]

        row_sem = row.get("semantics") if isinstance(row.get("semantics"), dict) else {}
        cat_hint = str(row.get("category") or "").strip().lower()
        if cat_hint in ("", "legacystatichint"):
            cat_hint = ""
        raw_row_hints = [str(x).strip().lower() for x in row_sem.get("domainHints", []) if isinstance(x, str) and str(x).strip()]
        id_prefix = sid.split(".")[0].strip().lower()
        domain_hints = [p for p in ([cat_hint] + raw_row_hints) if p and p != "legacystatichint"]
        if not domain_hints and id_prefix and id_prefix != "legacystatichint":
            domain_hints = [id_prefix]
        domain_hints = list(dict.fromkeys(domain_hints))
        component_hint = row.get("component") if "component" in row else row_sem.get("componentHint")
        feature_group = str(row_sem.get("featureGroup") or (".".join(sid.split(".")[:2]) if "." in sid else sid))
        target_app = row_sem.get("targetApp")
        tags = ["catalog"]
        for t in row_sem.get("tags", []):
            if isinstance(t, str) and t.strip() and t.strip() not in tags:
                tags.append(t.strip())
        if row.get("status") and str(row["status"]) not in tags:
            tags.append(str(row["status"]))

        candidates.append(
            DiscoveredCandidate(
                id=sid,
                title=title,
                description=description,
                valueType=vtype,
                source=str(row.get("source") or ""),
                sourceKind=source_kind,
                adapter=adapter_id,
                path=path,
                controlType=control_type,
                risk=str(row.get("risk") or "low"),
                sensitive=bool(row.get("sensitive", False)),
                applyMethod=str(row.get("applyMethod") or ""),
                profileSupported=bool(row.get("profileSupported", False)),
                resetSupported=bool(row.get("resetSupported", False)),
                keywords=[str(k).lower() for k in row.get("keywords", []) if isinstance(k, str)],
                choices=list(row["choices"]) if isinstance(row.get("choices"), list) else None,
                limits=dict(row["limits"]) if isinstance(row.get("limits"), dict) else None,
                discoveredFrom=["catalog"],
                semantics={
                    "domainHints": domain_hints,
                    "featureGroup": feature_group,
                    "componentHint": component_hint,
                    "targetApp": target_app,
                    "tags": tags,
                },
                metadata={"catalogStatus": row.get("status")},
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Source 2: Quickshell Config.qml + config.json + QML Binding Scan
# ---------------------------------------------------------------------------

def _scan_qml_bindings(quickshell_root: Path) -> dict[str, dict[str, Any]]:
    """Scan QML files under `quickshell_root` for `Config.options.<path>` references."""
    refs: dict[str, dict[str, Any]] = {}
    if not quickshell_root.is_dir():
        return refs

    settings_dir = quickshell_root / "modules/settings"
    services_dir = quickshell_root / "services"

    qml_files = sorted(quickshell_root.rglob("*.qml"))
    for qml_file in qml_files:
        text = _read_regular_text(qml_file)
        if text is None or "Config.options" not in text:
            continue
        rel = str(qml_file.relative_to(quickshell_root))
        is_settings = settings_dir in qml_file.parents and qml_file.name != "DynamicCategoryConfig.qml"
        is_service = services_dir in qml_file.parents

        for match in re.finditer(r"Config\.options\??\.([A-Za-z_][A-Za-z0-9_.]*)", text):
            raw_path = match.group(1).rstrip(".")
            entry = refs.setdefault(
                raw_path,
                {
                    "settingsComponents": [],
                    "serviceComponents": [],
                    "otherComponents": [],
                    "tags": set(),
                },
            )
            if is_settings and rel not in entry["settingsComponents"]:
                entry["settingsComponents"].append(rel)
            elif is_service and rel not in entry["serviceComponents"]:
                entry["serviceComponents"].append(rel)
            elif rel not in entry["otherComponents"]:
                entry["otherComponents"].append(rel)

        # Detect notable side-effect couplings cleanly
        if qml_file.name == "GeneralConfig.qml" and "hyprlock.conf" in text and "Config.options.time.format" in text:
            refs.setdefault("time.format", {"settingsComponents": [], "serviceComponents": [], "otherComponents": [], "tags": set()})["tags"].add("side-effect:hyprlock-conf")
        if qml_file.name == "QuickConfig.qml" and "wallpaperSwitchScriptPath" in text:
            refs.setdefault("appearance.palette.type", {"settingsComponents": [], "serviceComponents": [], "otherComponents": [], "tags": set()})["tags"].add("side-effect:switchwall")
        if qml_file.name == "PulsarAudioVisualizer.qml":
            refs.setdefault("appearance.pulsarAudioVisualizer.enabled", {"settingsComponents": [], "serviceComponents": [], "otherComponents": [], "tags": set()})["tags"].add("side-effect:resets-visualizer-subprops")

    return refs


def _infer_sensitive_and_risk(path: str) -> tuple[bool, str]:
    lower = path.lower()
    if (
        lower.endswith("path")
        or lower.endswith("url")
        or "systemprompt" in lower
        or "useragent" in lower
        or lower == "crosshair.code"
        or "worksafety.triggercondition" in lower
        or "extramodels" in lower
    ):
        return True, "confirmation-required"
    if lower.startswith(("hacks.", "conflictkiller.", "gamemode.")):
        return False, "confirmation-required"
    return False, "low"


def discover_source_2_quickshell(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    qml_path = context.quickshell_root / "modules/common/Config.qml"
    qml_text = _read_regular_text(qml_path)
    qml_props = parse_config_qml(qml_text) if qml_text is not None else {}

    json_text = _read_regular_text(context.config_json_path)
    json_leaves: dict[str, Any] = {}
    if json_text is not None:
        try:
            loaded = json.loads(json_text)
            if isinstance(loaded, dict):
                json_leaves = _flatten_json(loaded)
        except json.JSONDecodeError as exc:
            if diagnostics is not None:
                diagnostics.setdefault("errors", []).append(
                    {"source": "quickshell", "error": f"config.json invalid JSON: {exc}"}
                )

    qml_bindings = _scan_qml_bindings(context.quickshell_root)
    all_keys = sorted(set(qml_props) | set(json_leaves))
    candidates: list[DiscoveredCandidate] = []

    for dotted in all_keys:
        qml_meta = qml_props.get(dotted, {})
        has_json_val = dotted in json_leaves
        json_val = json_leaves.get(dotted)

        if qml_meta:
            vtype = qml_meta["valueType"]
        else:
            vtype = _infer_value_type(json_val)

        choices = qml_meta.get("choices")
        control_type = _infer_control_type(
            vtype, choices=choices, path=dotted, value=json_val
        )
        sensitive, risk = _infer_sensitive_and_risk(dotted)
        complex_list = isinstance(json_val, list) and any(
            isinstance(x, dict) for x in json_val
        )
        if not complex_list and qml_meta.get("qmlType") == "list<var>":
            dv = qml_meta.get("defaultValue")
            if isinstance(dv, list) and any(isinstance(x, dict) for x in dv):
                complex_list = True

        binding = qml_bindings.get(dotted, {})
        settings_comps = binding.get("settingsComponents", [])
        service_comps = binding.get("serviceComponents", [])
        other_comps = binding.get("otherComponents", [])
        component_hint = (
            settings_comps[0]
            if settings_comps
            else service_comps[0]
            if service_comps
            else other_comps[0]
            if other_comps
            else "modules/common/Config.qml"
        )

        parts = dotted.split(".")
        domain, feature_group = map_quickshell_namespace(dotted)
        domain_hints = [domain]

        tags: set[str] = {"config-json"}
        if settings_comps:
            tags.add("has-static-ui")
        if qml_meta:
            tags.add("config-qml")
        if qml_meta.get("unit"):
            tags.add(f"unit:{qml_meta['unit']}")
        if complex_list:
            tags.add("complex-object-list")
        if not has_json_val:
            tags.add("missing-in-config-json")
        tags.update(binding.get("tags", set()))

        keywords = sorted(
            {
                tok
                for part in parts
                for tok in _split_camel_tokens(part)
            }
            | {"quickshell", "config"}
        )

        candidates.append(
            DiscoveredCandidate(
                id=dotted,
                title=_human_title(dotted),
                description=f"Quickshell Config.qml / config.json option '{dotted}'.",
                valueType=vtype,
                source="illogical-impulse/config.json",
                sourceKind="config-json",
                adapter="config-json",
                path=dotted,
                controlType=control_type,
                risk=risk,
                sensitive=sensitive,
                applyMethod="Quickshell watches the config file; runtime effect is not independently verified",
                profileSupported=not sensitive and not complex_list,
                resetSupported=not complex_list,
                keywords=keywords,
                choices=list(choices) if choices else None,
                limits=None,
                discoveredFrom=["quickshell"],
                semantics={
                    "domainHints": list(dict.fromkeys(domain_hints)),
                    "featureGroup": feature_group,
                    "componentHint": component_hint,
                    "targetApp": "quickshell",
                    "tags": sorted(tags),
                },
                metadata={
                    "qmlType": qml_meta.get("qmlType"),
                    "presentInConfigJson": has_json_val,
                    "presentInConfigQml": bool(qml_meta),
                    "complexList": complex_list,
                },
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Source 3: Hyprland Lua Configs & Optional/Injected hyprctl descriptions
# ---------------------------------------------------------------------------

def _run_hyprctl_command(context: DiscoveryContext, args: list[str]) -> tuple[int, str, str] | None:
    if not context.allow_live_hyprctl and context.hyprctl_runner is None:
        return None
    cmd = [context.hyprctl, *args]
    if context.hyprctl_runner is not None:
        res = context.hyprctl_runner(cmd)
        if isinstance(res, subprocess.CompletedProcess):
            return res.returncode, res.stdout, res.stderr
        if isinstance(res, tuple) and len(res) == 3:
            return int(res[0]), str(res[1]), str(res[2])
        raise TypeError("hyprctl_runner must return CompletedProcess or (rc, stdout, stderr)")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired):
        return (1, "", "hyprctl unavailable")


def _map_hyprland_section(section: str) -> tuple[str, str]:
    sec = str(section or "").strip().lower()
    if sec in ("general", "decoration", "dwindle", "master", "group", "misc"):
        return "windows", f"windows.hyprland-{sec}"
    if sec == "animations":
        return "motion", "motion.hyprland-animations"
    if sec in ("input", "gestures", "cursor", "binds"):
        return "input", f"input.hyprland-{sec}"
    if sec:
        return sec, f"hyprland.{sec}"
    return "windows", "windows.hyprland"


def discover_source_3_hyprland(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    by_id: dict[str, DiscoveredCandidate] = {}
    main_dir = context.hypr_config_root / "hyprland"

    # 3a. Static Lua files
    lua_files = [
        main_dir / "general.lua",
        main_dir / "colors.lua",
        main_dir / "shellOverrides/main.lua",
    ]
    for lua_path in lua_files:
        text = _read_regular_text(lua_path)
        if text is None:
            continue
        for dotted, value, vtype in parse_hl_config_blocks(text):
            setting_id = f"hyprland.{dotted}"
            colon_path = dotted.replace(".", ":", 1)
            is_managed = setting_id in hyprland_options_adapter.OPTION_SPECS
            section = dotted.split(".")[0]
            hl_domain, hl_feature_group = _map_hyprland_section(section)
            limits = (
                hyprland_options_adapter.option_metadata().get(setting_id)
                if is_managed
                else None
            )
            by_id[setting_id] = DiscoveredCandidate(
                id=setting_id,
                title=_human_title(setting_id),
                description=f"Hyprland option '{colon_path}' parsed from {lua_path.name}.",
                valueType=vtype,
                source=str(lua_path),
                sourceKind=(
                    "hyprland-options-adapter"
                    if is_managed
                    else "hyprland-lua-readonly"
                ),
                adapter="hyprland-options-adapter" if is_managed else None,
                path=colon_path,
                controlType="ConfigSpinBox" if is_managed else "readonly-info",
                risk="reversible" if is_managed else "review-required",
                sensitive=False,
                applyMethod=(
                    "Live Hyprland eval with atomic Lua persistence and live readback verification."
                    if is_managed
                    else "Read-only Lua option without a verified transactional adapter."
                ),
                profileSupported=is_managed,
                resetSupported=is_managed,
                keywords=sorted(set(dotted.split(".") + ["hyprland", "lua"])),
                choices=None,
                limits=limits,
                discoveredFrom=["hyprland"],
                semantics={
                    "domainHints": [hl_domain],
                    "featureGroup": hl_feature_group,
                    "componentHint": None,
                    "targetApp": None,
                    "tags": ["hyprland", "lua"] + (["adapter-managed"] if is_managed else ["readonly"]),
                },
                metadata={"luaReadable": True, "currentValue": value},
            )

    # 3b. Optional / injected `hyprctl descriptions`
    desc_out = _run_hyprctl_command(context, ["descriptions"])
    if desc_out is not None and desc_out[0] == 0:
        try:
            items = json.loads(desc_out[1])
        except json.JSONDecodeError as exc:
            items = None
            if diagnostics is not None:
                diagnostics.setdefault("errors", []).append(
                    {"source": "hyprland", "error": f"invalid hyprctl descriptions JSON: {exc}"}
                )
        if isinstance(items, list):
            for entry in items:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    continue
                opt_name = entry["name"]
                norm = opt_name.replace(":", ".")
                setting_id = _HYPRLAND_OPTION_MAP.get(opt_name, f"hyprland.{norm}")
                is_managed = setting_id in hyprland_options_adapter.OPTION_SPECS
                section = norm.split(".")[0]
                hl_domain, hl_feature_group = _map_hyprland_section(section)
                default_val = entry.get("default")
                vtype = _infer_value_type(default_val)
                limits: dict[str, Any] | None = None
                if is_managed:
                    limits = hyprland_options_adapter.option_metadata().get(setting_id)
                elif entry.get("min") is not None or entry.get("max") is not None:
                    limits = {}
                    if entry.get("min") is not None:
                        limits["minimum"] = entry["min"]
                    if entry.get("max") is not None:
                        limits["maximum"] = entry["max"]

                if setting_id in by_id:
                    existing = by_id[setting_id]
                    if entry.get("description"):
                        existing.description = str(entry["description"])
                    if limits and not existing.limits:
                        existing.limits = limits
                    existing.metadata["hyprctlDescription"] = True
                    existing.metadata["hyprctlCurrent"] = entry.get("current")
                    continue

                by_id[setting_id] = DiscoveredCandidate(
                    id=setting_id,
                    title=_human_title(setting_id),
                    description=str(entry.get("description") or f"Hyprland option {opt_name}."),
                    valueType=vtype,
                    source="hyprctl descriptions",
                    sourceKind=(
                        "hyprland-options-adapter"
                        if is_managed
                        else "hyprland-option-readonly"
                    ),
                    adapter="hyprland-options-adapter" if is_managed else None,
                    path=opt_name,
                    controlType="ConfigSpinBox" if is_managed else "readonly-info",
                    risk="reversible" if is_managed else "review-required",
                    sensitive=False,
                    applyMethod=(
                        "Live Hyprland eval with atomic Lua persistence."
                        if is_managed
                        else "Read-only Hyprland option without a verified transactional adapter."
                    ),
                    profileSupported=is_managed,
                    resetSupported=is_managed,
                    keywords=sorted(set(norm.split(".") + ["hyprland", "hyprctl"])),
                    choices=None,
                    limits=limits,
                    discoveredFrom=["hyprland"],
                    semantics={
                        "domainHints": [hl_domain],
                        "featureGroup": hl_feature_group,
                        "componentHint": None,
                        "targetApp": None,
                        "tags": ["hyprland", "hyprctl"] + (["adapter-managed"] if is_managed else ["readonly"]),
                    },
                    metadata={
                        "hyprctlDescription": True,
                        "hyprctlCurrent": entry.get("current"),
                    },
                )

    return [by_id[k] for k in sorted(by_id)]


# ---------------------------------------------------------------------------
# Source 4: Aegis / Pulsar Helper Scripts (Zero Mutating Execution)
# ---------------------------------------------------------------------------

def discover_source_4_aegis_pulsar(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    custom_dir = context.hypr_config_root / "custom"
    candidates: list[DiscoveredCandidate] = []

    script_specs = (
        (
            "integration.acrylic-blur",
            "Acrylic blur",
            custom_dir / "aegis-glassctl.py",
            custom_dir / "general.lua",
            "aegis-glassctl.py writes custom/general.lua non-atomically without a shared lock against aegis-window-effects.py and aegis-motion-profile.py, and executes hyprctl reload.",
            ["effects", "windows"],
            "window-blur-effects",
            None,
        ),
        (
            "integration.window-effects",
            "Window opacity and depth",
            custom_dir / "aegis-window-effects.py",
            custom_dir / "general.lua",
            "aegis-window-effects.py writes custom/general.lua non-atomically without a shared lock against aegis-glassctl.py and would overwrite live wobble settings.",
            ["effects", "windows"],
            "window-blur-effects",
            None,
        ),
        (
            "integration.opacity-rules",
            "Opaque window exceptions",
            custom_dir / "aegis-opacity-rules.py",
            custom_dir / "rules.lua",
            "aegis-opacity-rules.py shares custom/rules.lua with aegis-pip-floatctl.py and aegis-custom-opacity.py without a shared lock.",
            ["windows", "apps"],
            "per-app-window-rules",
            "per-window",
        ),
        (
            "integration.picture-in-picture",
            "Picture in picture",
            custom_dir / "aegis-pip-floatctl.py",
            custom_dir / "rules.lua",
            "aegis-pip-floatctl.py shares custom/rules.lua with aegis-opacity-rules.py and aegis-custom-opacity.py without a shared lock.",
            ["windows", "apps"],
            "per-app-window-rules",
            "zen",
        ),
        (
            "integration.game-mode",
            "Pulsar Game Mode",
            context.quickshell_root / "scripts/game-mode/pulsar_game_mode.py",
            context.quickshell_root / "services/PulsarGameMode.qml",
            "pulsar_game_mode.py only supports enter/restore without a status subcommand and mutates live Hyprland options competing with hyprland-options-adapter.",
            ["gaming", "performance"],
            "game-mode",
            "steam",
        ),
    )

    for sid, title, helper_path, target_path, blocker, domains, fgroup, target_app in script_specs:
        helper_ok = _is_regular_file(helper_path)
        target_ok = _is_regular_file(target_path)
        if not helper_ok and not target_ok:
            continue
        candidates.append(
            DiscoveredCandidate(
                id=sid,
                title=title,
                description=blocker,
                valueType="unknown",
                source=str(helper_path),
                sourceKind="script-backed",
                adapter="script-backed",
                path=None,
                controlType="readonly-info",
                risk="review-required",
                sensitive=False,
                applyMethod=blocker,
                profileSupported=False,
                resetSupported=False,
                keywords=sorted(set(sid.replace(".", "-").split("-") + ["aegis", "pulsar", "review"])),
                choices=None,
                limits=None,
                discoveredFrom=["aegis_pulsar"],
                semantics={
                    "domainHints": domains,
                    "featureGroup": fgroup,
                    "componentHint": "modules/settings/AdvancedConfig.qml",
                    "targetApp": target_app,
                    "tags": ["script-backed", "adapter-review-required"],
                },
            )
        )

    # Adapted helpers (if files exist on disk, emit with their verified adapter)
    adapted_specs = (
        (
            "integration.custom-window-rules",
            "Custom window rules",
            custom_dir / "aegis-custom-opacity.py",
            "window-rule-adapter",
            "windowRules.customOpacity",
            "array",
            ["windows", "apps", "window-rules"],
            "per-app-window-rules",
            "per-window",
        ),
        (
            "integration.window-glow",
            "Window glow",
            custom_dir / "aegis-glowctl.py",
            "window-glow-adapter",
            "windowGlow.settings",
            "object",
            ["windows", "effects", "glow"],
            "window-glow",
            None,
        ),
        (
            "integration.motion-profile",
            "Motion profile",
            custom_dir / "aegis-motion-profile.py",
            "motion-profile-adapter",
            "motionProfile",
            "string",
            ["motion", "animations"],
            "motion-animations",
            None,
        ),
    )
    for sid, title, helper_path, adapter_id, path, vtype, domains, fgroup, target_app in adapted_specs:
        if not _is_regular_file(helper_path):
            continue
        candidates.append(
            DiscoveredCandidate(
                id=sid,
                title=title,
                description=f"Adapted Aegis helper {helper_path.name}.",
                valueType=vtype,
                source=str(helper_path),
                sourceKind=adapter_id,
                adapter=adapter_id,
                path=path,
                controlType="combo" if vtype == "string" else "custom-editor",
                risk="confirmation-required",
                sensitive=(sid == "integration.custom-window-rules"),
                applyMethod=f"Managed via {adapter_id}.",
                profileSupported=True,
                resetSupported=True,
                keywords=sorted(set(sid.replace(".", "-").split("-") + ["aegis"])),
                choices=["off", "light", "full"] if sid == "integration.motion-profile" else None,
                limits=None,
                discoveredFrom=["aegis_pulsar"],
                semantics={
                    "domainHints": domains,
                    "featureGroup": fgroup,
                    "componentHint": "modules/settings/AdvancedConfig.qml",
                    "targetApp": target_app,
                    "tags": ["aegis", "adapter-backed"],
                },
            )
        )
    return candidates


# ---------------------------------------------------------------------------
# Source 5: Registered Adapters in AdapterRegistry
# ---------------------------------------------------------------------------

def _candidate_from_dict(
    raw: dict[str, Any], *, discovered_from: str
) -> DiscoveredCandidate:
    sid = str(raw["id"])
    sem = raw.get("semantics") if isinstance(raw.get("semantics"), dict) else {}
    return DiscoveredCandidate(
        id=sid,
        title=str(raw.get("title") or _human_title(sid)),
        description=str(raw.get("description") or ""),
        valueType=str(raw.get("valueType") or "unknown"),
        source=str(raw.get("source") or ""),
        sourceKind=str(raw.get("sourceKind") or raw.get("adapter") or "unknown"),
        adapter=raw.get("adapter"),
        path=raw.get("path"),
        controlType=str(raw.get("controlType") or "readonly-info"),
        risk=str(raw.get("risk") or "low"),
        sensitive=bool(raw.get("sensitive", False)),
        applyMethod=str(raw.get("applyMethod") or ""),
        profileSupported=bool(raw.get("profileSupported", False)),
        resetSupported=bool(raw.get("resetSupported", False)),
        keywords=[str(k).lower() for k in raw.get("keywords", []) if isinstance(k, str)],
        choices=list(raw["choices"]) if isinstance(raw.get("choices"), list) else None,
        limits=dict(raw["limits"]) if isinstance(raw.get("limits"), dict) else None,
        discoveredFrom=[discovered_from],
        semantics={
            "domainHints": [str(x) for x in sem.get("domainHints", [])],
            "featureGroup": str(sem.get("featureGroup") or ""),
            "componentHint": sem.get("componentHint"),
            "targetApp": sem.get("targetApp"),
            "tags": [str(x) for x in sem.get("tags", [])],
        },
        canonicalKey=raw.get("canonicalKey"),
    )


def discover_source_5_adapters(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    registry = context.adapter_registry or create_default_registry()
    adapter_ctx = context.to_adapter_context()
    raw_items, adapter_diags = registry.discover_all(adapter_ctx)
    if diagnostics is not None and adapter_diags:
        diagnostics.setdefault("errors", []).extend(adapter_diags)
    candidates: list[DiscoveredCandidate] = []
    for raw in raw_items:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        origin = "dynamic_features" if raw.get("adapter") not in BUILTIN_ADAPTER_IDS else "adapters"
        candidates.append(_candidate_from_dict(raw, discovered_from=origin))
    return candidates


# ---------------------------------------------------------------------------
# Source 6: System Theme, Appearance & Locale Sources
# ---------------------------------------------------------------------------

def _discover_cursor_and_icon_themes(
    cursor_search_paths: Sequence[Path], icon_search_paths: Sequence[Path]
) -> tuple[list[str], list[str]]:
    cursor_themes: set[str] = set()
    icon_themes: set[str] = set()
    theme_name_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

    for base in cursor_search_paths:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        try:
            children = sorted(base_path.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not theme_name_re.fullmatch(child.name):
                continue
            meta = child / "index.theme"
            cursors_dir = child / "cursors"
            txt = _read_regular_text(meta)
            if txt is None or not cursors_dir.is_dir():
                continue
            if (
                re.search(r"^\[Icon Theme\]\s*$", txt, re.MULTILINE)
                and re.search(r"^Name\s*=\s*.+$", txt, re.MULTILINE)
            ):
                try:
                    if any(item.is_file() for item in cursors_dir.iterdir()):
                        cursor_themes.add(child.name)
                except OSError:
                    continue

    for base in icon_search_paths:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        try:
            children = sorted(base_path.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name in ("default", "hicolor", "locolor"):
                continue
            txt = _read_regular_text(child / "index.theme")
            if txt is None:
                continue
            if desktop_appearance_adapter._is_cursor_only_icon_theme(child):
                continue
            if (
                re.search(r"^\[Icon Theme\]\s*$", txt, re.MULTILINE)
                and re.search(r"^Name\s*=\s*.+$", txt, re.MULTILINE)
            ):
                icon_themes.add(child.name)

    return sorted(cursor_themes, key=str.casefold), sorted(icon_themes, key=str.casefold)


def _parse_ini_safe(path: Path) -> configparser.ConfigParser | None:
    text = _read_regular_text(path)
    if text is None:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    return parser


def discover_source_6_theme_locale(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> tuple[list[DiscoveredCandidate], dict[str, Any]]:
    cursor_themes, icon_themes = _discover_cursor_and_icon_themes(
        context.cursor_search_paths, context.icon_search_paths
    )
    locales_set: set[str] = set()
    for tdir in context.translations_dirs:
        tpath = Path(tdir)
        if not tpath.is_dir():
            continue
        for child in sorted(tpath.glob("*.json")):
            if _is_regular_file(child):
                locales_set.add(child.stem)
    locales = sorted(locales_set)

    matugen_templates: list[str] = []
    candidates: list[DiscoveredCandidate] = []

    # Matugen config.toml
    matugen_path = context.config_home / "matugen/config.toml"
    matugen_txt = _read_regular_text(matugen_path)
    if matugen_txt is not None:
        try:
            mdata = tomllib.loads(matugen_txt)
            templates = mdata.get("templates")
            if isinstance(templates, dict):
                matugen_templates = sorted(templates.keys())
                candidates.append(
                    DiscoveredCandidate(
                        id="theme.matugen.templates",
                        title="Matugen color templates",
                        description="Material You color generation targets configured in matugen/config.toml.",
                        valueType="array",
                        source=str(matugen_path),
                        sourceKind="system-theme-readonly",
                        adapter="system-theme-readonly",
                        path="templates",
                        controlType="readonly-info",
                        risk="review-required",
                        sensitive=False,
                        applyMethod="Generated by Matugen / switchwall.sh.",
                        profileSupported=False,
                        resetSupported=False,
                        keywords=["matugen", "material", "colors", "templates"],
                        choices=matugen_templates,
                        discoveredFrom=["theme_locale"],
                        semantics={
                            "domainHints": ["appearance", "colors", "theming"],
                            "featureGroup": "material-theming",
                            "componentHint": None,
                            "targetApp": None,
                            "tags": ["matugen", "generated_by_matugen"],
                        },
                    )
                )
        except tomllib.TOMLDecodeError as exc:
            if diagnostics is not None:
                diagnostics.setdefault("warnings", []).append(
                    f"matugen config.toml parse error: {exc}"
                )

    # Cursor mirror sources (90-cursor.conf + GTK3/4 cursor keys) -> merge into cursor.theme / cursor.size!
    env_cursor_path = context.config_home / "environment.d/90-cursor.conf"
    env_txt = _read_regular_text(env_cursor_path)
    if env_txt is not None:
        if re.search(r"^\s*XCURSOR_THEME\s*=", env_txt, re.MULTILINE):
            candidates.append(
                DiscoveredCandidate(
                    id="cursor.theme",
                    title="Cursor theme",
                    description="XCURSOR_THEME from environment.d/90-cursor.conf.",
                    valueType="string",
                    source=str(env_cursor_path),
                    sourceKind="cursor-adapter",
                    adapter="cursor-adapter",
                    path="cursor.theme",
                    controlType="combo",
                    risk="reversible",
                    sensitive=False,
                    applyMethod="Synchronized via cursor-adapter.",
                    profileSupported=True,
                    resetSupported=True,
                    keywords=["cursor", "xcursor", "theme"],
                    choices=cursor_themes or None,
                    discoveredFrom=["theme_locale"],
                    semantics={
                        "domainHints": ["input", "pointer", "appearance"],
                        "featureGroup": "cursor-appearance",
                        "componentHint": "modules/settings/CursorConfig.qml",
                        "targetApp": None,
                        "tags": ["environment.d", "mirror-synced"],
                    },
                    canonicalKey="cursor:theme",
                )
            )
        if re.search(r"^\s*XCURSOR_SIZE\s*=", env_txt, re.MULTILINE):
            candidates.append(
                DiscoveredCandidate(
                    id="cursor.size",
                    title="Cursor size",
                    description="XCURSOR_SIZE from environment.d/90-cursor.conf.",
                    valueType="integer",
                    source=str(env_cursor_path),
                    sourceKind="cursor-adapter",
                    adapter="cursor-adapter",
                    path="cursor.size",
                    controlType="number",
                    risk="reversible",
                    sensitive=False,
                    applyMethod="Synchronized via cursor-adapter.",
                    profileSupported=True,
                    resetSupported=True,
                    keywords=["cursor", "xcursor", "size"],
                    discoveredFrom=["theme_locale"],
                    semantics={
                        "domainHints": ["input", "pointer", "appearance"],
                        "featureGroup": "cursor-appearance",
                        "componentHint": "modules/settings/CursorConfig.qml",
                        "targetApp": None,
                        "tags": ["environment.d", "mirror-synced"],
                    },
                    canonicalKey="cursor:size",
                )
            )

    # GTK 3 & GTK 4 settings.ini
    gtk_specs = (
        ("gtk3", context.config_home / "gtk-3.0/settings.ini"),
        ("gtk4", context.config_home / "gtk-4.0/settings.ini"),
    )
    gtk_non_cursor_keys = {
        "gtk-theme-name": ("theme.gtk3.themeName", "GTK theme", "string"),
        "gtk-icon-theme-name": ("theme.gtk3.iconThemeName", "GTK icon theme", "string"),
        "gtk-font-name": ("theme.gtk3.fontName", "GTK font", "string"),
        "gtk-application-prefer-dark-theme": (
            "theme.gtk3.preferDarkTheme",
            "GTK prefer dark theme",
            "boolean",
        ),
    }
    for gtk_label, gtk_path in gtk_specs:
        parser = _parse_ini_safe(gtk_path)
        if parser is None or not parser.has_section("Settings"):
            continue
        if parser.has_option("Settings", "gtk-cursor-theme-name"):
            candidates.append(
                DiscoveredCandidate(
                    id="cursor.theme",
                    title="Cursor theme",
                    description=f"GTK cursor theme mirror in {gtk_path.name}.",
                    valueType="string",
                    source=str(gtk_path),
                    sourceKind="cursor-adapter",
                    adapter="cursor-adapter",
                    path="cursor.theme",
                    controlType="combo",
                    risk="reversible",
                    sensitive=False,
                    applyMethod="Synchronized via cursor-adapter.",
                    profileSupported=True,
                    resetSupported=True,
                    keywords=["cursor", gtk_label, "gtk"],
                    choices=cursor_themes or None,
                    discoveredFrom=["theme_locale"],
                    semantics={
                        "domainHints": ["input", "pointer", "appearance"],
                        "featureGroup": "cursor-appearance",
                        "componentHint": "modules/settings/CursorConfig.qml",
                        "targetApp": None,
                        "tags": [gtk_label, "mirror-synced"],
                    },
                    canonicalKey="cursor:theme",
                )
            )
        if parser.has_option("Settings", "gtk-cursor-theme-size"):
            candidates.append(
                DiscoveredCandidate(
                    id="cursor.size",
                    title="Cursor size",
                    description=f"GTK cursor size mirror in {gtk_path.name}.",
                    valueType="integer",
                    source=str(gtk_path),
                    sourceKind="cursor-adapter",
                    adapter="cursor-adapter",
                    path="cursor.size",
                    controlType="number",
                    risk="reversible",
                    sensitive=False,
                    applyMethod="Synchronized via cursor-adapter.",
                    profileSupported=True,
                    resetSupported=True,
                    keywords=["cursor", gtk_label, "gtk"],
                    discoveredFrom=["theme_locale"],
                    semantics={
                        "domainHints": ["input", "pointer", "appearance"],
                        "featureGroup": "cursor-appearance",
                        "componentHint": "modules/settings/CursorConfig.qml",
                        "targetApp": None,
                        "tags": [gtk_label, "mirror-synced"],
                    },
                    canonicalKey="cursor:size",
                )
            )
        if gtk_label == "gtk3":
            for ini_key, (sid, title, vtype) in gtk_non_cursor_keys.items():
                if parser.has_option("Settings", ini_key):
                    choices = icon_themes if ini_key == "gtk-icon-theme-name" and icon_themes else None
                    candidates.append(
                        DiscoveredCandidate(
                            id=sid,
                            title=title,
                            description=f"GTK3 setting '{ini_key}' from settings.ini (read-only).",
                            valueType=vtype,
                            source=str(gtk_path),
                            sourceKind="system-theme-readonly",
                            adapter="system-theme-readonly",
                            path=f"Settings.{ini_key}",
                            controlType="readonly-info",
                            risk="review-required",
                            sensitive=False,
                            applyMethod="Externally managed by GTK / theme scripts.",
                            profileSupported=False,
                            resetSupported=False,
                            keywords=["gtk", "gtk3", "theme", "appearance"],
                            choices=choices,
                            discoveredFrom=["theme_locale"],
                            semantics={
                                "domainHints": ["appearance", "desktop-toolkit"],
                                "featureGroup": "toolkit-theme",
                                "componentHint": None,
                                "targetApp": "gtk",
                                "tags": ["gtk3", "gtk4", "readonly"],
                            },
                        )
                    )

    # KDE globals
    kde_path = context.config_home / "kdeglobals"
    kde_ini = _parse_ini_safe(kde_path)
    if kde_ini is not None:
        kde_entries = (
            ("General", "ColorScheme", "theme.kde.colorScheme", "KDE color scheme", "string", None),
            ("Icons", "Theme", "theme.kde.iconTheme", "KDE icon theme", "string", icon_themes or None),
            ("KDE", "widgetStyle", "theme.kde.widgetStyle", "KDE widget style", "string", None),
        )
        for section, key, sid, title, vtype, choices in kde_entries:
            if kde_ini.has_option(section, key):
                candidates.append(
                    DiscoveredCandidate(
                        id=sid,
                        title=title,
                        description=f"KDE global setting [{section}] {key} (read-only).",
                        valueType=vtype,
                        source=str(kde_path),
                        sourceKind="system-theme-readonly",
                        adapter="system-theme-readonly",
                        path=f"{section}.{key}",
                        controlType="readonly-info",
                        risk="review-required",
                        sensitive=False,
                        applyMethod="Externally managed by KDE / Matugen.",
                        profileSupported=False,
                        resetSupported=False,
                        keywords=["kde", "qt", "theme", "appearance"],
                        choices=choices,
                        discoveredFrom=["theme_locale"],
                        semantics={
                            "domainHints": ["appearance", "desktop-toolkit"],
                            "featureGroup": "toolkit-theme",
                            "componentHint": None,
                            "targetApp": "kde",
                            "tags": ["kdeglobals", "readonly"],
                        },
                    )
                )

    # kde-material-you-colors/config.conf
    kmy_path = context.config_home / "kde-material-you-colors/config.conf"
    kmy_ini = _parse_ini_safe(kmy_path)
    if kmy_ini is not None and kmy_ini.has_section("CUSTOM"):
        kmy_entries = (
            ("scheme_variant", "theme.kde.materialYou.schemeVariant", "KDE Material You scheme variant", "integer"),
            ("chroma_multiplier", "theme.kde.materialYou.chromaMultiplier", "KDE Material You chroma multiplier", "number"),
            ("tone_multiplier", "theme.kde.materialYou.toneMultiplier", "KDE Material You tone multiplier", "number"),
        )
        for key, sid, title, vtype in kmy_entries:
            if kmy_ini.has_option("CUSTOM", key):
                candidates.append(
                    DiscoveredCandidate(
                        id=sid,
                        title=title,
                        description=f"KDE Material You setting '{key}' (read-only).",
                        valueType=vtype,
                        source=str(kmy_path),
                        sourceKind="system-theme-readonly",
                        adapter="system-theme-readonly",
                        path=f"CUSTOM.{key}",
                        controlType="readonly-info",
                        risk="review-required",
                        sensitive=False,
                        applyMethod="Controlled by switchwall.sh / kde-material-you-colors.",
                        profileSupported=False,
                        resetSupported=False,
                        keywords=["kde", "material", "you", "colors"],
                        discoveredFrom=["theme_locale"],
                        semantics={
                            "domainHints": ["appearance", "colors", "theming"],
                            "featureGroup": "material-theming",
                            "componentHint": None,
                            "targetApp": "kde",
                            "tags": ["matugen", "kde-material-you-colors", "qt"],
                        },
                    )
                )

    bar_icons_set: set[str] = set()
    assets_icons_dir = context.quickshell_root / "assets/icons"
    if assets_icons_dir.is_dir():
        try:
            for svg in sorted(assets_icons_dir.glob("*.svg")):
                if _is_regular_file(svg):
                    stem = svg.stem
                    if stem.endswith("-symbolic"):
                        stem = stem[:-9]
                    if stem:
                        bar_icons_set.add(stem)
        except OSError:
            pass
    bar_icons = ["distro", *sorted(bar_icons_set, key=str.casefold)] if bar_icons_set else []

    enrichment = {
        "cursorThemes": cursor_themes,
        "iconThemes": icon_themes,
        "locales": locales,
        "matugenTemplates": matugen_templates,
        "barIcons": bar_icons,
    }
    return candidates, enrichment


# ---------------------------------------------------------------------------
# Source 7: Application Discovery Mechanisms
# ---------------------------------------------------------------------------

def _parse_desktop_entry(path: Path) -> dict[str, Any] | None:
    text = _read_regular_text(path)
    if text is None:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error:
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    sec = parser["Desktop Entry"]
    if sec.get("Hidden", "").lower() == "true":
        return None
    name = sec.get("Name", "").strip()
    if not name:
        return None
    cats_raw = sec.get("Categories", "")
    cats = [c.strip() for c in cats_raw.split(";") if c.strip()]
    wm_class = sec.get("StartupWMClass", "").strip() or None
    exec_cmd = sec.get("Exec", "").strip()
    is_game = "Game" in cats or "steam://rungameid/" in exec_cmd
    return {
        "id": path.stem,
        "name": name,
        "categories": cats,
        "icon": sec.get("Icon", "").strip() or None,
        "wmClass": wm_class,
        "noDisplay": sec.get("NoDisplay", "").lower() == "true",
        "isGame": is_game,
        "desktopPath": str(path),
    }


def discover_source_7_apps(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> tuple[list[DiscoveredCandidate], dict[str, Any]]:
    apps_by_id: dict[str, dict[str, Any]] = {}
    app_categories: set[str] = set()

    for base in context.desktop_entry_dirs:
        base_path = Path(base)
        if not base_path.is_dir():
            continue
        for desktop_file in sorted(base_path.glob("*.desktop")):
            parsed = _parse_desktop_entry(desktop_file)
            if parsed is None:
                continue
            app_id = parsed["id"]
            if app_id not in apps_by_id:
                apps_by_id[app_id] = parsed
            app_categories.update(parsed["categories"])

    installed_apps = [apps_by_id[k] for k in sorted(apps_by_id)]
    game_rules: dict[str, Any] = {}
    detector_path = context.quickshell_root / "scripts/game-mode/pulsar_game_detector.py"
    detector_txt = _read_regular_text(detector_path)
    if detector_txt is not None:
        m = re.search(r"NON_GAME_STEAM_APP_IDS\s*=\s*frozenset\(\{([^}]*)\}\)", detector_txt)
        excluded = re.findall(r'"(\d+)"', m.group(1)) if m else []
        game_rules = {
            "detectorPresent": True,
            "excludedSteamAppIds": sorted(excluded),
        }

    # Note: Do NOT emit fake settings per .desktop file; emit app-targeting metadata / enrichments only.
    enrichment = {
        "installedApps": installed_apps,
        "appCategories": sorted(app_categories),
        "gameDetectionRules": game_rules,
    }
    return [], enrichment


# ---------------------------------------------------------------------------
# Source 8: Dynamic / Newly Added Features & Manifests
# ---------------------------------------------------------------------------

def discover_source_8_dynamic(
    context: DiscoveryContext, diagnostics: dict[str, Any] | None = None
) -> list[DiscoveredCandidate]:
    candidates: list[DiscoveredCandidate] = []

    # 8a. Non-builtin registered adapters
    if context.adapter_registry is not None:
        adapter_ctx = context.to_adapter_context()
        for adapter in context.adapter_registry.all_adapters():
            aid = adapter.descriptor.adapter_id
            if aid in BUILTIN_ADAPTER_IDS:
                continue
            try:
                items = adapter.discover_settings(adapter_ctx)
                for raw in items:
                    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                        raw.setdefault("adapter", aid)
                        raw.setdefault("sourceKind", adapter.descriptor.source_kind)
                        candidates.append(_candidate_from_dict(raw, discovered_from="dynamic_features"))
            except Exception as exc:
                if diagnostics is not None:
                    diagnostics.setdefault("errors", []).append(
                        {"source": "dynamic_features", "adapterId": aid, "error": str(exc)}
                    )

    # 8b. Drop-in feature manifests (`nexus-feature-manifest-v1`)
    for mdir in context.feature_manifest_dirs:
        dir_path = Path(mdir)
        if not dir_path.is_dir():
            continue
        for mf_path in sorted(dir_path.glob("*.json")):
            text = _read_regular_text(mf_path)
            if text is None:
                continue
            try:
                manifest = json.loads(text)
            except json.JSONDecodeError as exc:
                if diagnostics is not None:
                    diagnostics.setdefault("errors", []).append(
                        {"source": "dynamic_features", "file": str(mf_path), "error": f"invalid manifest JSON: {exc}"}
                    )
                continue
            manifest_rows: list[Any] | None = None
            if isinstance(manifest, dict):
                if manifest.get("schema") == "nexus-feature-manifest-v1" and isinstance(manifest.get("settings"), list):
                    manifest_rows = manifest["settings"]
                elif "schema" not in manifest and isinstance(manifest.get("definitions"), list):
                    manifest_rows = manifest["definitions"]
                elif "schema" not in manifest and isinstance(manifest.get("settings"), list):
                    manifest_rows = manifest["settings"]
            if manifest_rows is None:
                if diagnostics is not None:
                    diagnostics.setdefault("warnings", []).append(
                        f"ignored invalid feature manifest schema: {mf_path}"
                    )
                continue

            feature_id = str(manifest.get("featureId") or mf_path.stem)
            default_adapter = manifest.get("adapterId")
            for row in manifest_rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row.get("title"):
                    if diagnostics is not None:
                        diagnostics.setdefault("warnings", []).append(
                            f"malformed setting entry in {mf_path}"
                        )
                    continue
                enriched_row = dict(row)
                enriched_row.setdefault("adapter", default_adapter)
                enriched_row.setdefault("sourceKind", default_adapter or "dynamic-manifest")
                enriched_row.setdefault("source", str(mf_path))
                sem = dict(enriched_row.get("semantics") or {})
                sem.setdefault("featureGroup", feature_id)
                tags = list(sem.get("tags") or [])
                if "dynamic-feature" not in tags:
                    tags.append("dynamic-feature")
                sem["tags"] = tags
                enriched_row["semantics"] = sem
                candidates.append(_candidate_from_dict(enriched_row, discovered_from="dynamic_features"))

    # 8c. Explicit extra_candidates in context
    for raw in context.extra_candidates:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            candidates.append(_candidate_from_dict(raw, discovered_from="dynamic_features"))

    return candidates


# ---------------------------------------------------------------------------
# Deduplication & Merging Across Sources
# ---------------------------------------------------------------------------

def canonical_equivalence_key(candidate: DiscoveredCandidate) -> str:
    if candidate.canonicalKey:
        return candidate.canonicalKey
    if candidate.id in ("cursor.theme", "cursor.size"):
        return f"cursor:{candidate.id.split('.')[1]}"
    if candidate.sourceKind == "config-json" and candidate.path:
        return f"config-json:{candidate.path}"
    if candidate.id.startswith("hyprland.") or candidate.sourceKind in (
        "hyprland-options-adapter",
        "hyprland-lua-readonly",
        "hyprland-option-readonly",
    ):
        norm = candidate.id.removeprefix("hyprland.").replace(":", ".")
        return f"hypr-option:{norm}"
    return f"id:{candidate.id}"


def _best_source_rank(candidate: DiscoveredCandidate, table: dict[str, int]) -> int:
    if not candidate.discoveredFrom:
        return 99
    return min(table.get(src, 99) for src in candidate.discoveredFrom)


def merge_and_deduplicate(
    raw_candidates: Sequence[DiscoveredCandidate],
) -> tuple[list[DiscoveredCandidate], list[dict[str, Any]]]:
    groups: dict[str, list[DiscoveredCandidate]] = {}
    for cand in raw_candidates:
        key = canonical_equivalence_key(cand)
        groups.setdefault(key, []).append(cand)

    merged_list: list[DiscoveredCandidate] = []
    merge_log: list[dict[str, Any]] = []

    for key in sorted(groups):
        group = groups[key]
        by_tech = sorted(
            group,
            key=lambda c: (
                _best_source_rank(c, _AUTHORITY_RANK),
                c.id,
                c.sourceKind,
                c.source,
            ),
        )
        by_human = sorted(
            group,
            key=lambda c: (
                _best_source_rank(c, _HUMAN_PRIORITY),
                c.id,
                c.sourceKind,
                c.source,
            ),
        )
        primary_tech = by_tech[0]
        primary_human = by_human[0]

        chosen_id = next(
            (c.id for c in by_human if "catalog" in c.discoveredFrom),
            primary_tech.id,
        )
        raw_chosen_title = next((c.title for c in by_human if c.title and c.title.strip()), primary_tech.title)
        title = _sanitize_setting_title(raw_chosen_title, chosen_id)
        description = _sanitize_setting_description(
            next(
                (c.description for c in by_human if c.description and c.description.strip()),
                primary_tech.description,
            ),
            raw_chosen_title,
            title,
        )
        apply_method = next(
            (c.applyMethod for c in by_human if c.applyMethod and c.applyMethod.strip()),
            primary_tech.applyMethod,
        )

        discovered_from = sorted(
            {src for c in group for src in c.discoveredFrom}
        )
        keywords = sorted(
            {kw.lower() for c in group for kw in c.keywords if kw}
        )
        catalog_item = next((c for c in group if "catalog" in c.discoveredFrom), None)
        domain_hints: list[str] = []
        if catalog_item and catalog_item.semantics.get("domainHints"):
            for d in catalog_item.semantics.get("domainHints", []):
                if d and d not in domain_hints:
                    domain_hints.append(d)
        elif "adapters" in primary_tech.discoveredFrom and primary_tech.semantics.get("domainHints"):
            for d in primary_tech.semantics.get("domainHints", []):
                if d and d not in domain_hints:
                    domain_hints.append(d)
        else:
            for c in by_human:
                for d in c.semantics.get("domainHints", []):
                    if d and d not in domain_hints:
                        domain_hints.append(d)
        tags = sorted(
            {t for c in group for t in c.semantics.get("tags", []) if t}
        )

        feature_group = (
            catalog_item.semantics.get("featureGroup")
            if catalog_item and catalog_item.semantics.get("featureGroup")
            else next(
                (
                    c.semantics.get("featureGroup")
                    for c in by_tech
                    if c.semantics.get("featureGroup")
                ),
                "",
            )
        )
        component_hint = next(
            (
                c.semantics.get("componentHint")
                for c in by_human
                if c.semantics.get("componentHint")
            ),
            None,
        )
        target_app = next(
            (
                c.semantics.get("targetApp")
                for c in by_tech
                if c.semantics.get("targetApp")
            ),
            None,
        )

        # Merge choices deterministically while preserving meaningful adapter/enum order
        choices: list[Any] | None = None
        for c in by_tech:
            if c.choices:
                choices = list(c.choices)
                break
        if choices is None:
            for c in by_human:
                if c.choices:
                    choices = list(c.choices)
                    break

        limits = next((dict(c.limits) for c in by_tech if c.limits), None)

        merged_metadata: dict[str, Any] = {}
        for c in reversed(by_tech):
            merged_metadata.update(c.metadata)

        # Preserve curated catalog risk/sensitive when tech source only guessed defaults
        risk = catalog_item.risk if catalog_item else primary_tech.risk
        sensitive = (
            any(c.sensitive for c in group)
        )
        profile_supported = (
            primary_tech.profileSupported
            if "adapters" in discovered_from
            else (catalog_item.profileSupported if catalog_item else primary_tech.profileSupported)
        )
        reset_supported = (
            primary_tech.resetSupported
            if "adapters" in discovered_from
            else (catalog_item.resetSupported if catalog_item else primary_tech.resetSupported)
        )

        merged = DiscoveredCandidate(
            id=chosen_id,
            title=title,
            description=description,
            valueType=(
                primary_tech.valueType
                if primary_tech.valueType != "unknown"
                else primary_human.valueType
            ),
            source=primary_human.source or primary_tech.source,
            sourceKind=primary_tech.sourceKind,
            adapter=primary_tech.adapter,
            path=primary_tech.path if primary_tech.path is not None else primary_human.path,
            controlType=(
                primary_human.controlType
                if catalog_item and primary_human.controlType != "readonly-info"
                else primary_tech.controlType
            ),
            risk=risk,
            sensitive=sensitive,
            applyMethod=apply_method,
            profileSupported=profile_supported,
            resetSupported=reset_supported,
            keywords=keywords,
            choices=choices,
            limits=limits,
            discoveredFrom=discovered_from,
            semantics={
                "domainHints": domain_hints,
                "featureGroup": feature_group,
                "componentHint": component_hint,
                "targetApp": target_app,
                "tags": tags,
            },
            canonicalKey=key,
            metadata=merged_metadata,
        )
        merged_list.append(merged)

        if len(group) > 1:
            merge_log.append(
                {
                    "canonicalKey": key,
                    "resolvedId": chosen_id,
                    "mergedCount": len(group),
                    "sources": discovered_from,
                }
            )

    merged_list.sort(key=lambda c: c.id)
    return merged_list, merge_log


# ---------------------------------------------------------------------------
# Enrichment Application (Sources 6 & 7 -> Candidates)
# ---------------------------------------------------------------------------

def _apply_enrichment(
    candidates: Sequence[DiscoveredCandidate], enrichment: dict[str, Any]
) -> None:
    cursor_themes = enrichment.get("cursorThemes") or []
    icon_themes = enrichment.get("iconThemes") or []
    locales = enrichment.get("locales") or []
    bar_icons = enrichment.get("barIcons") or []
    installed_apps = enrichment.get("installedApps") or []
    app_ids = [app["id"] for app in installed_apps if isinstance(app, dict) and app.get("id")]

    for cand in candidates:
        if cand.id == "cursor.theme" and cursor_themes:
            cand.choices = list(cursor_themes)
        elif cand.id == "bar.topLeftIcon" and bar_icons:
            cand.choices = list(bar_icons)
        elif cand.id == "language.ui" and locales:
            cand.choices = ["auto", *locales]
        elif cand.id == "calendar.locale" and locales:
            cand.choices = list(locales)
        elif cand.id in ("theme.gtk3.iconThemeName", "theme.kde.iconTheme") and icon_themes:
            cand.choices = list(icon_themes)
        elif cand.id in ("launcher.pinnedApps", "dock.pinnedApps") and app_ids:
            if not cand.choices:
                cand.choices = list(app_ids)
            if "xdg-desktop" not in cand.semantics["tags"]:
                cand.semantics["tags"] = sorted({*cand.semantics["tags"], "xdg-desktop"})
            if not cand.semantics.get("targetApp"):
                cand.semantics["targetApp"] = "desktop-apps"
        elif cand.id.startswith("apps.") and not cand.semantics.get("targetApp"):
            cand.semantics["targetApp"] = "desktop-apps"
        elif cand.id == "gameMode.automatic":
            game_rules = enrichment.get("gameDetectionRules") or {}
            if game_rules.get("detectorPresent"):
                cand.semantics["tags"] = sorted(
                    {*cand.semantics["tags"], "pulsar", "auto-detect", "gamescope"}
                )
            if not cand.semantics.get("targetApp"):
                cand.semantics["targetApp"] = "steam"
        elif cand.id == "integration.opacity-rules":
            cand.semantics["tags"] = sorted(
                {*cand.semantics["tags"], "app-targeting", "rules.lua"}
            )


# ---------------------------------------------------------------------------
# Read / Apply Verification Gate (Fail-Closed)
# ---------------------------------------------------------------------------

def _verification_dict_from_probe(probe: CapabilityProbeResult) -> dict[str, Any]:
    manageable = bool(probe.verified_read and probe.verified_apply)
    payload: dict[str, Any] = {
        "readable": bool(probe.verified_read),
        "applicable": bool(probe.verified_apply),
        "verified": manageable,
        "verifiedRead": bool(probe.verified_read),
        "verifiedApply": bool(probe.verified_apply),
        "manageable": manageable,
        "runtimeVerified": bool(probe.runtime_verified and manageable),
        "reason": probe.reason,
        "verificationReason": probe.reason,
        "verificationDetail": probe.verification_reason,
    }
    if "reconciliationAvailable" in probe.details:
        payload["reconciliationAvailable"] = bool(probe.details["reconciliationAvailable"])
    return payload


def verify_candidates(
    candidates: Sequence[DiscoveredCandidate], context: DiscoveryContext
) -> list[DiscoveredCandidate]:
    """Evaluate every candidate through the real Read/Apply Verification Gate."""
    registry = context.adapter_registry or create_default_registry()
    adapter_ctx = context.to_adapter_context()
    verified_list: list[DiscoveredCandidate] = []

    for cand in candidates:
        # Internal / non-user-facing Config.qml keys (never expose as active settings)
        if cand.id.startswith("hacks.") or cand.id == "background.thumbnailPath":
            cand.verification = {
                "readable": bool(cand.metadata.get("presentInConfigJson", True)),
                "applicable": False,
                "verified": False,
                "verifiedRead": bool(cand.metadata.get("presentInConfigJson", True)),
                "verifiedApply": False,
                "manageable": False,
                "runtimeVerified": False,
                "reason": "internal_non_user_facing",
                "verificationReason": "internal_non_user_facing",
                "verificationDetail": "internal_non_user_facing: Internal runtime state or workaround parameter.",
            }
            verified_list.append(cand)
            continue

        # Arch-only update checker settings when checkupdates is not installed
        if cand.id.startswith("updates.") and shutil.which("checkupdates") is None:
            cand.verification = {
                "readable": bool(cand.metadata.get("presentInConfigJson", True)),
                "applicable": False,
                "verified": False,
                "verifiedRead": bool(cand.metadata.get("presentInConfigJson", True)),
                "verifiedApply": False,
                "manageable": False,
                "runtimeVerified": False,
                "reason": "unsupported_distro_feature",
                "verificationReason": "unsupported_distro_feature",
                "verificationDetail": "unsupported_distro_feature: Updates service requires Arch checkupdates, which is not available on this host.",
            }
            verified_list.append(cand)
            continue

        # Read-only raw Hyprland option without adapter
        if cand.sourceKind in ("hyprland-option-readonly",):
            has_read = bool(cand.metadata.get("hyprctlDescription") or cand.metadata.get("luaReadable"))
            cand.verification = {
                "readable": has_read,
                "applicable": False,
                "verified": False,
                "verifiedRead": has_read,
                "verifiedApply": False,
                "manageable": False,
                "runtimeVerified": False,
                "reason": "no_verified_apply_adapter",
                "verificationReason": "no_verified_apply_adapter",
                "verificationDetail": "no_verified_apply_adapter: read-only Hyprland option",
            }
            verified_list.append(cand)
            continue

        # Complex object-list schema check for config-json
        if cand.sourceKind == "config-json" and cand.metadata.get("complexList"):
            cand.verification = {
                "readable": bool(cand.metadata.get("presentInConfigJson", True)),
                "applicable": False,
                "verified": False,
                "verifiedRead": bool(cand.metadata.get("presentInConfigJson", True)),
                "verifiedApply": False,
                "manageable": False,
                "runtimeVerified": False,
                "reason": "schema_complex_editor_required",
                "verificationReason": "schema_complex_editor_required",
                "verificationDetail": "schema_complex_editor_required: Complex list<var> object list cannot be safely edited via simple controls.",
            }
            verified_list.append(cand)
            continue

        probe = registry.probe_setting(
            {
                "id": cand.id,
                "adapter": cand.adapter,
                "sourceKind": cand.sourceKind,
                "path": cand.path,
                "source": cand.source,
                "risk": cand.risk,
                "sensitive": cand.sensitive,
            },
            adapter_ctx,
        )
        cand.verification = _verification_dict_from_probe(probe)
        verified_list.append(cand)

    return verified_list


# ---------------------------------------------------------------------------
# Deterministic Inventory Hashing & Delta Hints
# ---------------------------------------------------------------------------

def _canonical_candidate_structure(cand: DiscoveredCandidate | dict[str, Any]) -> dict[str, Any]:
    d = cand.to_dict() if isinstance(cand, DiscoveredCandidate) else dict(cand)
    sem = d.get("semantics") or {}
    ver = d.get("verification") or {}
    choices = d.get("choices")
    return {
        "id": d.get("id"),
        "valueType": d.get("valueType"),
        "sourceKind": d.get("sourceKind"),
        "adapter": d.get("adapter"),
        "path": d.get("path"),
        "controlType": d.get("controlType"),
        "risk": d.get("risk"),
        "sensitive": bool(d.get("sensitive", False)),
        "profileSupported": bool(d.get("profileSupported", False)),
        "resetSupported": bool(d.get("resetSupported", False)),
        "choices": sorted(choices, key=lambda x: str(x)) if isinstance(choices, list) else None,
        "limits": d.get("limits"),
        "semantics": {
            "domainHints": sorted(sem.get("domainHints") or []),
            "featureGroup": sem.get("featureGroup") or "",
            "componentHint": sem.get("componentHint"),
            "targetApp": sem.get("targetApp"),
            "tags": sorted(sem.get("tags") or []),
        },
        "verification": {
            "verifiedRead": bool(ver.get("verifiedRead", False)),
            "verifiedApply": bool(ver.get("verifiedApply", False)),
            "manageable": bool(ver.get("manageable", False)),
            "runtimeVerified": bool(ver.get("runtimeVerified", False)),
            "verificationReason": ver.get("verificationReason") or "",
        },
    }


def _candidate_structural_hash(cand: DiscoveredCandidate | dict[str, Any]) -> str:
    payload = json.dumps(
        _canonical_candidate_structure(cand),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_inventory_hash(candidates: Sequence[DiscoveredCandidate | dict[str, Any]]) -> str:
    """Compute a timestamp- and value-invariant SHA-256 fingerprint of structural inventory."""
    ordered = sorted(
        (_canonical_candidate_structure(c) for c in candidates),
        key=lambda row: str(row.get("id") or ""),
    )
    encoded = json.dumps(
        ordered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def compute_delta_hints(
    current: Sequence[DiscoveredCandidate | dict[str, Any]],
    previous: DiscoveryResult | dict[str, Any] | None,
) -> dict[str, Any]:
    """Compute incremental delta hints for Layer 3 background updates."""
    if previous is None:
        return {
            "hasPrevious": False,
            "changed": True,
            "addedIds": [],
            "removedIds": [],
            "modifiedIds": [],
            "unchangedCount": len(current),
            "affectedSources": [],
        }

    prev_candidates = (
        previous.candidates
        if isinstance(previous, DiscoveryResult)
        else previous.get("candidates", [])
    )
    prev_map: dict[str, tuple[str, list[str]]] = {}
    for item in prev_candidates:
        cid = item.id if isinstance(item, DiscoveredCandidate) else str(item.get("id"))
        sources = (
            list(item.discoveredFrom)
            if isinstance(item, DiscoveredCandidate)
            else list(item.get("discoveredFrom", []))
        )
        prev_map[cid] = (_candidate_structural_hash(item), sources)

    curr_map: dict[str, tuple[str, list[str]]] = {}
    for item in current:
        cid = item.id if isinstance(item, DiscoveredCandidate) else str(item.get("id"))
        sources = (
            list(item.discoveredFrom)
            if isinstance(item, DiscoveredCandidate)
            else list(item.get("discoveredFrom", []))
        )
        curr_map[cid] = (_candidate_structural_hash(item), sources)

    added_ids = sorted(set(curr_map) - set(prev_map))
    removed_ids = sorted(set(prev_map) - set(curr_map))
    modified_ids = sorted(
        cid for cid in (set(curr_map) & set(prev_map)) if curr_map[cid][0] != prev_map[cid][0]
    )
    unchanged_count = len((set(curr_map) & set(prev_map))) - len(modified_ids)

    affected_sources: set[str] = set()
    for cid in added_ids + modified_ids:
        affected_sources.update(curr_map[cid][1])
    for cid in removed_ids:
        affected_sources.update(prev_map[cid][1])

    return {
        "hasPrevious": True,
        "changed": bool(added_ids or removed_ids or modified_ids),
        "addedIds": added_ids,
        "removedIds": removed_ids,
        "modifiedIds": modified_ids,
        "unchangedCount": unchanged_count,
        "affectedSources": sorted(affected_sources),
    }


def _compute_state_snapshot_hash(context: DiscoveryContext) -> str:
    h = hashlib.sha256()
    for label, p in (
        ("catalog", context.catalog_path),
        ("config", context.config_json_path),
        ("general_lua", context.hypr_config_root / "hyprland/general.lua"),
        ("custom_general_lua", context.hypr_config_root / "custom/general.lua"),
        ("custom_rules_lua", context.hypr_config_root / "custom/rules.lua"),
        ("custom_execs_lua", context.hypr_config_root / "custom/execs.lua"),
        ("custom_env_lua", context.hypr_config_root / "custom/env.lua"),
        ("custom_keybinds_lua", context.hypr_config_root / "custom/keybinds.lua"),
        ("gtk3_ini", context.config_home / "gtk-3.0/settings.ini"),
        ("gtk4_ini", context.config_home / "gtk-4.0/settings.ini"),
        ("kdeglobals", context.config_home / "kdeglobals"),
        ("mimeapps_list", context.config_home / "mimeapps.list"),
    ):
        h.update(label.encode("utf-8"))
        if _is_regular_file(p):
            try:
                h.update(p.read_bytes())
            except OSError:
                h.update(b"<unreadable>")
        else:
            h.update(b"<missing>")
    return "sha256:" + h.hexdigest()


# ---------------------------------------------------------------------------
# Main Pipeline Entrypoint
# ---------------------------------------------------------------------------

def discover_inventory(
    context: DiscoveryContext | None = None,
    *,
    previous_result: DiscoveryResult | dict[str, Any] | None = None,
) -> DiscoveryResult:
    """Collect, deduplicate, enrich, and verify settings across all 8 sources."""
    ctx = context or DiscoveryContext.from_defaults()
    diagnostics: dict[str, Any] = {
        "sourceCounts": {},
        "mergedDuplicates": 0,
        "mergeLog": [],
        "warnings": [],
        "errors": [],
    }
    raw_candidates: list[DiscoveredCandidate] = []
    enrichment: dict[str, Any] = {
        "cursorThemes": [],
        "iconThemes": [],
        "locales": [],
        "matugenTemplates": [],
        "installedApps": [],
        "appCategories": [],
        "gameDetectionRules": {},
    }

    def _run_source(name: str, fn: Callable[[], list[DiscoveredCandidate]]) -> None:
        if name not in ctx.enabled_sources:
            diagnostics["sourceCounts"][name] = 0
            return
        try:
            items = fn()
            diagnostics["sourceCounts"][name] = len(items)
            raw_candidates.extend(items)
        except Exception as exc:
            diagnostics["sourceCounts"][name] = 0
            diagnostics["errors"].append({"source": name, "error": str(exc)})

    _run_source("catalog", lambda: discover_source_1_catalog(ctx, diagnostics))
    _run_source("quickshell", lambda: discover_source_2_quickshell(ctx, diagnostics))
    _run_source("hyprland", lambda: discover_source_3_hyprland(ctx, diagnostics))
    _run_source("aegis_pulsar", lambda: discover_source_4_aegis_pulsar(ctx, diagnostics))
    _run_source("adapters", lambda: discover_source_5_adapters(ctx, diagnostics))

    if "theme_locale" in ctx.enabled_sources:
        try:
            t_items, t_enrich = discover_source_6_theme_locale(ctx, diagnostics)
            diagnostics["sourceCounts"]["theme_locale"] = len(t_items)
            raw_candidates.extend(t_items)
            enrichment.update(t_enrich)
        except Exception as exc:
            diagnostics["sourceCounts"]["theme_locale"] = 0
            diagnostics["errors"].append({"source": "theme_locale", "error": str(exc)})
    else:
        diagnostics["sourceCounts"]["theme_locale"] = 0

    if "apps" in ctx.enabled_sources:
        try:
            a_items, a_enrich = discover_source_7_apps(ctx, diagnostics)
            diagnostics["sourceCounts"]["apps"] = len(a_items)
            raw_candidates.extend(a_items)
            enrichment.update(a_enrich)
        except Exception as exc:
            diagnostics["sourceCounts"]["apps"] = 0
            diagnostics["errors"].append({"source": "apps", "error": str(exc)})
    else:
        diagnostics["sourceCounts"]["apps"] = 0

    _run_source("dynamic_features", lambda: discover_source_8_dynamic(ctx, diagnostics))

    merged, merge_log = merge_and_deduplicate(raw_candidates)
    diagnostics["mergeLog"] = merge_log
    diagnostics["mergedDuplicates"] = sum(row["mergedCount"] - 1 for row in merge_log)

    _apply_enrichment(merged, enrichment)
    verified_all = verify_candidates(merged, ctx)

    verified_only = [c for c in verified_all if c.verification.get("manageable") is True]
    unverified_only = [c for c in verified_all if c.verification.get("manageable") is not True]

    inventory_hash = compute_inventory_hash(verified_all)
    snapshot_hash = _compute_state_snapshot_hash(ctx)
    delta = compute_delta_hints(verified_all, previous_result)
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return DiscoveryResult(
        schema="nexus-discovery-v1",
        inventoryHash=inventory_hash,
        stateSnapshotHash=snapshot_hash,
        generatedAt=generated_at,
        candidates=verified_all,
        verifiedCandidates=verified_only,
        unverifiedCandidates=unverified_only,
        enrichment=enrichment,
        delta=delta,
        diagnostics=diagnostics,
    )


def discover_settings(
    context: DiscoveryContext | dict[str, Any] | None = None,
    *,
    previous_result: DiscoveryResult | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint accepting DiscoveryContext, dict overrides, or None, returning a JSON-serializable dict."""
    if isinstance(context, DiscoveryContext):
        ctx = context
    elif isinstance(context, dict):
        ctx = DiscoveryContext.from_defaults(**context)
    else:
        ctx = DiscoveryContext.from_defaults()
    return discover_inventory(ctx, previous_result=previous_result).to_dict()

