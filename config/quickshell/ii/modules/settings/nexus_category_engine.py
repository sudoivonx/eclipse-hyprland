"""Layer 3 NEXUS Deterministic Category & Subcategory Engine.

Generates dynamic categories, subcategories, setting assignments, and search
index metadata from verified discovered setting candidates using pure-Python
deterministic rules and semantic metadata (zero external LLM/API dependencies).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "nexus-category-tree-v1"
ENGINE_VERSION = "1.0.0"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

_TURKISH_CHAR_MAP = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "I": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
        "â": "a",
        "Â": "a",
        "î": "i",
        "Î": "i",
        "û": "u",
        "Û": "u",
    }
)

# Canonical domain synonym mapping (all keys are lowercased & Turkish-ASCII folded).
# IMPORTANT: Keep distinct domains (e.g. "audio-effects" vs "window-effects",
# "a_b" vs "a-b", "gaming" vs "bluetooth", "audio" vs "power") strictly separate.
DOMAIN_SYNONYMS: dict[str, str] = {
    # Windows & window management
    "windows": "windows",
    "window": "windows",
    "window-management": "windows",
    "window_management": "windows",
    "windowmanagement": "windows",
    "pencereler": "windows",
    "pencere": "windows",
    "pencere-yonetimi": "windows",
    # Audio & sound
    "audio": "audio",
    "sound": "audio",
    "ses": "audio",
    "ses-ayarlari": "audio",
    # Appearance & theming
    "appearance": "appearance",
    "gorunum": "appearance",
    "tema-ve-gorunum": "appearance",
    # Bar / top panel
    "bar": "bar",
    "top-bar": "bar",
    "topbar": "bar",
    "panel-bar": "bar",
    "ust-cubuk": "bar",
    # Background & wallpaper
    "background": "background",
    "wallpaper": "background",
    "arkaplan": "background",
    "duvar-kagidi": "background",
    # Cursor & pointer
    "cursor": "cursor",
    "imlec": "cursor",
    "fare-imleci": "cursor",
    # Motion & animations
    "motion": "motion",
    "hareket": "motion",
    # Gaming
    "gaming": "gaming",
    "oyun": "gaming",
    # Power & battery
    "power": "power",
    "guc": "power",
    # Bluetooth
    "bluetooth": "bluetooth",
    # Dock
    "dock": "dock",
    # Effects
    "effects": "effects",
    "efektler": "effects",
    # General / misc
    "general": "general",
    "genel": "general",
    # Services
    "services": "services",
    "servisler": "services",
    # Quick settings
    "quick": "quick",
    "hizli": "quick",
}

CANONICAL_DOMAIN_TITLES: dict[str, str] = {
    "appearance": "Appearance",
    "apps": "Applications",
    "audio": "Audio",
    "background": "Background",
    "bar": "Bar",
    "battery": "Battery",
    "bluetooth": "Bluetooth",
    "calendar": "Calendar",
    "clock": "Clock",
    "cooling": "Cooling",
    "cursor": "Cursor",
    "display": "Display",
    "dock": "Dock",
    "effects": "Effects",
    "fallback": "Uncategorized",
    "gaming": "Gaming",
    "general": "General",
    "hyprland": "Hyprland",
    "input": "Input",
    "interface": "Interface",
    "language": "Language & Locale",
    "launcher": "Launcher",
    "lock": "Lock Screen",
    "media": "Media",
    "motion": "Motion & Animations",
    "network": "Network",
    "network-vpn": "Network VPN",
    "notifications": "Notifications",
    "osd": "On-Screen Display",
    "overview": "Overview",
    "performance": "Performance",
    "policies": "Policies",
    "power": "Power",
    "printing": "Printing",
    "privacy": "Privacy",
    "quick": "Quick Settings",
    "resources": "System Resources",
    "screen": "Screen",
    "search": "Search",
    "security": "Security",
    "services": "Services",
    "sidebar": "Sidebar",
    "sounds": "Sounds",
    "system": "System",
    "telemetry": "Telemetry",
    "theme": "Theme",
    "time": "Time & Date",
    "update": "Updates",
    "user": "User",
    "waffles": "Waffles",
    "windows": "Windows",
    "workspaces": "Workspaces",
}

CANONICAL_DOMAIN_ORDER: dict[str, int] = {
    "quick": 10,
    "general": 20,
    "bar": 30,
    "background": 40,
    "appearance": 50,
    "theme": 55,
    "interface": 60,
    "waffles": 65,
    "windows": 70,
    "hyprland": 75,
    "effects": 80,
    "motion": 90,
    "cursor": 100,
    "input": 105,
    "audio": 110,
    "sounds": 112,
    "media": 115,
    "gaming": 120,
    "performance": 125,
    "services": 130,
    "power": 140,
    "battery": 142,
    "cooling": 145,
    "network": 150,
    "network-vpn": 152,
    "bluetooth": 155,
    "dock": 160,
    "launcher": 162,
    "overview": 165,
    "sidebar": 168,
    "notifications": 170,
    "osd": 172,
    "time": 175,
    "clock": 176,
    "calendar": 178,
    "language": 180,
    "search": 185,
    "apps": 190,
    "resources": 195,
    "policies": 200,
    "privacy": 205,
    "security": 210,
    "telemetry": 215,
    "printing": 220,
    "system": 230,
    "fallback": 999,
}

_GENERIC_DOMAINS = frozenset(
    {
        "",
        "unknown",
        "none",
        "null",
        "misc",
        "miscellaneous",
        "mystery",
        "unclassified",
        "uncategorized",
        "raw",
    }
)

_COMPONENT_STEM_TO_DOMAIN: dict[str, str] = {
    "audioconfig": "audio",
    "backgroundconfig": "background",
    "barconfig": "bar",
    "cursorconfig": "cursor",
    "gamingconfig": "gaming",
    "generalconfig": "general",
    "interfaceconfig": "interface",
    "motionconfig": "motion",
    "quickconfig": "quick",
    "servicesconfig": "services",
    "themesconfig": "appearance",
    "windoweffectsconfig": "effects",
    "windowsconfig": "windows",
}


def _ascii_fold(text: str) -> str:
    """Fold Turkish and common accented characters to lowercase ASCII."""
    translated = text.translate(_TURKISH_CHAR_MAP).lower()
    return translated


def _sanitize_slug(raw: str, *, default: str = "general") -> str:
    """Convert an arbitrary string into a valid slug matching ^[a-z0-9][a-z0-9._-]*$."""
    folded = _ascii_fold(raw.strip())
    if not folded:
        return default
    # Replace whitespace and slashes with hyphens, keep '_', '-', '.' distinct
    slug = re.sub(r"[\s/\\:]+", "-", folded)
    slug = re.sub(r"[^a-z0-9._-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.lstrip("._-")
    slug = slug.rstrip("._-")
    if not slug or not slug[0].isalnum():
        slug = f"c-{slug}" if slug else default
    if not _SLUG_RE.fullmatch(slug):
        slug = re.sub(r"[^a-z0-9]", "", slug) or default
    return slug


def _humanize_slug(slug: str) -> str:
    """Turn a slug or identifier into a clean human-readable display title."""
    if not slug:
        return "General"
    if slug in CANONICAL_DOMAIN_TITLES:
        return CANONICAL_DOMAIN_TITLES[slug]
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", slug)
    spaced = spaced.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    if not spaced:
        return "General"
    words = []
    acronyms = {"ui", "vpn", "osd", "eq", "fps", "gpu", "cpu", "ai", "api", "gtk", "kde", "qt", "icc", "url"}
    for w in spaced.split():
        if w.lower() in acronyms:
            words.append(w.upper())
        else:
            words.append(w[0].upper() + w[1:].lower())
    return " ".join(words)


def _canonicalize_domain_token(raw_token: str) -> str:
    """Canonicalize a domain hint while preserving collision resistance for distinct tokens."""
    if not isinstance(raw_token, str):
        return ""
    stripped = raw_token.strip()
    if not stripped:
        return ""
    slug = _sanitize_slug(stripped, default="")
    if not slug:
        return ""
    if slug in DOMAIN_SYNONYMS:
        return DOMAIN_SYNONYMS[slug]
    # Also check hyphen-normalized form ONLY if it matches a known multi-word synonym
    hyphen_norm = slug.replace("_", "-").replace(".", "-")
    if hyphen_norm in DOMAIN_SYNONYMS and "_" not in slug:
        return DOMAIN_SYNONYMS[hyphen_norm]
    return slug


def _extract_candidates_list(inventory: Any) -> list[Any]:
    """Unwrap inventory from DiscoveryResult, dict, or sequence safely."""
    if inventory is None:
        return []
    if hasattr(inventory, "to_dict") and callable(inventory.to_dict):
        inventory = inventory.to_dict()
    if isinstance(inventory, Mapping):
        for key in ("candidates", "verifiedCandidates", "definitions", "settings", "items"):
            val = inventory.get(key)
            if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
                return list(val)
        return []
    if isinstance(inventory, Iterable) and not isinstance(inventory, (str, bytes)):
        return list(inventory)
    return []


def _candidate_to_dict(item: Any) -> dict[str, Any] | None:
    """Convert a candidate object or dict to a normalized dictionary, or None if invalid."""
    if hasattr(item, "to_dict") and callable(item.to_dict):
        try:
            item = item.to_dict()
        except Exception:
            return None
    if not isinstance(item, Mapping):
        return None
    raw_id = item.get("id")
    if not isinstance(raw_id, str) or not raw_id.strip():
        return None
    return dict(item)


def _is_candidate_verified(cand: Mapping[str, Any]) -> bool:
    """Check whether a candidate passes the Read/Apply Verification Gate."""
    ver = cand.get("verification")
    if isinstance(ver, Mapping):
        if "verified" in ver and ver.get("verified") is False:
            return False
        if "manageable" in ver and ver.get("manageable") is False:
            return False
        if "readable" in ver and ver.get("readable") is False:
            return False
        if "applicable" in ver and ver.get("applicable") is False:
            return False
        if (
            ver.get("verified") is True
            or ver.get("manageable") is True
            or (ver.get("readable") is True and ver.get("applicable") is True)
        ):
            return True
        return False

    # Fallback when verification dict is omitted (e.g. raw catalog entry)
    status = str(cand.get("status") or "").strip().lower()
    if status in ("unverified", "adapter-review-required", "review-required", "blocked", "unsupported"):
        return False
    source_kind = str(cand.get("sourceKind") or "").strip().lower()
    if source_kind.endswith("-readonly") or source_kind == "script-backed":
        return False
    apply_method = str(cand.get("applyMethod") or "").strip().lower()
    if apply_method in ("none", "readonly", "read-only"):
        return False
    return True


def _is_expert_only(cand: Mapping[str, Any]) -> bool:
    """Determine if a setting is marked expert-only."""
    if isinstance(cand.get("expertOnly"), bool):
        return cand["expertOnly"]
    sem = cand.get("semantics")
    if isinstance(sem, Mapping) and isinstance(sem.get("expertOnly"), bool):
        return sem["expertOnly"]
    tags = sem.get("tags") if isinstance(sem, Mapping) else None
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        if any(str(t).lower() in ("expert", "expertonly", "expert-only") for t in tags):
            return True
    return False


def _resolve_domain_and_reason(
    cand: Mapping[str, Any],
) -> tuple[str, str | None, str, float, bool]:
    """Determine (category_id, explicit_display_title, rule_reason, confidence, is_fallback).

    Resolution is strictly invariant to keyword ordering and description edits.
    """
    sid = str(cand.get("id") or "").strip()
    sem = cand.get("semantics") if isinstance(cand.get("semantics"), Mapping) else {}
    explicit_display_title: str | None = None
    raw_display = sem.get("categoryDisplayTitle") or cand.get("categoryDisplayTitle")
    if isinstance(raw_display, str) and raw_display.strip():
        explicit_display_title = raw_display.strip()

    # 1. Explicit semantics.domainHints
    raw_hints = sem.get("domainHints")
    valid_hints: list[tuple[str, str]] = []
    if isinstance(raw_hints, Sequence) and not isinstance(raw_hints, (str, bytes)):
        for h in raw_hints:
            if isinstance(h, str) and h.strip():
                canon = _canonicalize_domain_token(h)
                if canon and canon not in _GENERIC_DOMAINS:
                    if not any(c == canon for c, _ in valid_hints):
                        valid_hints.append((canon, h.strip()))

    def _resolve_hint_title(cat_id: str, orig_hint: str) -> str | None:
        if explicit_display_title is not None:
            return explicit_display_title
        if orig_hint != cat_id and not _SLUG_RE.fullmatch(orig_hint):
            return (
                CANONICAL_DOMAIN_TITLES[cat_id]
                if cat_id in CANONICAL_DOMAIN_TITLES
                else _humanize_slug(orig_hint)
            )
        return None

    if len(valid_hints) == 1:
        cat_id, orig_hint = valid_hints[0]
        return (
            cat_id,
            _resolve_hint_title(cat_id, orig_hint),
            f"domainHint:{cat_id}",
            0.95,
            False,
        )

    if len(valid_hints) > 1:
        # Multi-domain ambiguity resolution: respect primary curated domain hints
        # unless the leading hint is merely a generic namespace/wrapper token.
        wrapper_domains = ("integration", "hyprland", "custom", "plugin", "manifest", "quickshell")
        hint_orig_by_canon = {c: orig for c, orig in valid_hints}
        non_wrapper = [c for c, _ in valid_hints if c not in wrapper_domains]
        primary_hint, primary_orig = valid_hints[0]
        if primary_hint not in wrapper_domains:
            return (
                primary_hint,
                _resolve_hint_title(primary_hint, primary_orig),
                f"domainHintPrimary:{primary_hint}",
                0.92,
                False,
            )

        id_parts = [_canonicalize_domain_token(p) for p in sid.split(".") if p]
        for idx, part in enumerate(id_parts):
            if idx == 0 and len(id_parts) > 1 and part in wrapper_domains:
                continue
            for canon in non_wrapper:
                if canon == part:
                    return (
                        canon,
                        _resolve_hint_title(canon, hint_orig_by_canon.get(canon, canon)),
                        f"multiDomainHintMatchedId:{canon}",
                        0.85,
                        False,
                    )
        chosen = non_wrapper[0] if non_wrapper else primary_hint
        return (
            chosen,
            _resolve_hint_title(chosen, hint_orig_by_canon.get(chosen, chosen)),
            f"multiDomainHintPrimary:{chosen}",
            0.82,
            False,
        )

    # 2. Check componentHint (e.g. "modules/settings/AudioConfig.qml" or "AudioConfig")
    comp_hint = sem.get("componentHint") or cand.get("component")
    if isinstance(comp_hint, str) and comp_hint.strip():
        stem = comp_hint.strip().split("/")[-1].removesuffix(".qml").lower()
        if stem in _COMPONENT_STEM_TO_DOMAIN:
            mapped = _COMPONENT_STEM_TO_DOMAIN[stem]
            return (mapped, explicit_display_title, f"componentHint:{mapped}", 0.88, False)
        if stem.endswith("config") and len(stem) > 6:
            prefix = _canonicalize_domain_token(stem[:-6])
            if prefix and prefix not in _GENERIC_DOMAINS and prefix not in ("advanced", "common"):
                return (prefix, explicit_display_title, f"componentStem:{prefix}", 0.85, False)

    # 3. Check explicit category field on candidate (if not generic legacy placeholder)
    cat_field = cand.get("category")
    if isinstance(cat_field, str) and cat_field.strip():
        canon_cat = _canonicalize_domain_token(cat_field)
        if canon_cat and canon_cat not in _GENERIC_DOMAINS and canon_cat != "legacystatichint":
            return (canon_cat, explicit_display_title, f"catalogCategory:{canon_cat}", 0.85, False)

    # 4. Derive from setting ID / path structure
    id_tokens = [p for p in re.split(r"[.:/]+", sid) if p]
    if id_tokens:
        first_raw = id_tokens[0]
        first_canon = _canonicalize_domain_token(first_raw)
        if first_canon == "hyprland" and len(id_tokens) >= 2:
            sec = _canonicalize_domain_token(id_tokens[1])
            if sec in ("general", "decoration", "dwindle", "master"):
                return ("windows", explicit_display_title, f"hyprlandSection:{sec}->windows", 0.85, False)
            if sec in ("animations",):
                return ("motion", explicit_display_title, "hyprlandSection:animations->motion", 0.85, False)
            if sec in ("input", "gestures"):
                return ("input", explicit_display_title, f"hyprlandSection:{sec}->input", 0.85, False)
        if first_canon == "integration" and len(id_tokens) >= 2:
            sub_tok = _canonicalize_domain_token(id_tokens[1])
            if "window" in sub_tok or "opacity" in sub_tok or "pip" in sub_tok:
                return ("windows", explicit_display_title, f"integrationId:{sub_tok}->windows", 0.80, False)
            if "motion" in sub_tok:
                return ("motion", explicit_display_title, f"integrationId:{sub_tok}->motion", 0.80, False)
            if "game" in sub_tok:
                return ("gaming", explicit_display_title, f"integrationId:{sub_tok}->gaming", 0.80, False)

        # Check if the candidate lacks semantic metadata & comes from an unknown/generic prefix
        source_kind = str(cand.get("sourceKind") or "").strip().lower()
        source = str(cand.get("source") or "").strip().lower()
        has_any_semantics = bool(
            valid_hints
            or (isinstance(sem.get("featureGroup"), str) and sem.get("featureGroup").strip())
            or (isinstance(sem.get("componentHint"), str) and sem.get("componentHint").strip())
            or (
                isinstance(sem.get("tags"), Sequence)
                and not isinstance(sem.get("tags"), (str, bytes))
                and len(sem.get("tags")) > 0
            )
        )
        if (
            first_canon in _GENERIC_DOMAINS
            or (not has_any_semantics and (source in ("", "unknown", "none") or source_kind in ("", "unknown", "none")))
        ):
            return (
                "fallback",
                explicit_display_title or "Uncategorized",
                "fallback:missing_domain_and_semantics",
                0.45,
                True,
            )

        if first_canon and first_canon not in _GENERIC_DOMAINS:
            if (
                explicit_display_title is None
                and first_canon not in CANONICAL_DOMAIN_TITLES
                and first_raw != first_canon
                and not _SLUG_RE.fullmatch(first_raw)
            ):
                explicit_display_title = _humanize_slug(first_raw)
            return (
                first_canon,
                explicit_display_title,
                f"idPrefix:{first_canon}",
                0.78,
                False,
            )

    # 5. Ultimate deterministic fallback
    return (
        "fallback",
        explicit_display_title or "Uncategorized",
        "fallback:unresolvable_domain",
        0.40,
        True,
    )


def _resolve_raw_subcategory_group(cand: Mapping[str, Any], category_id: str) -> tuple[str, str]:
    """Determine initial (raw_sub_slug, raw_sub_title) for a candidate inside category_id."""
    sid = str(cand.get("id") or "").strip()
    sem = cand.get("semantics") if isinstance(cand.get("semantics"), Mapping) else {}
    fg = sem.get("featureGroup")
    if isinstance(fg, str) and fg.strip():
        fg_clean = fg.strip()
        # Strip redundant leading "<category_id>." or "<category_id>-" prefix when multi-segment
        parts = [p for p in re.split(r"[./:]+", fg_clean) if p]
        if len(parts) >= 2 and _canonicalize_domain_token(parts[0]) == category_id:
            parts = parts[1:]
        sub_raw = "-".join(parts) if parts else fg_clean
        sub_slug = _sanitize_slug(sub_raw, default="general")
        sub_title = _humanize_slug(sub_raw)
        return sub_slug, sub_title

    # Derive from setting ID segments
    id_parts = [p for p in re.split(r"[.:/]+", sid) if p]
    if len(id_parts) >= 3:
        sub_raw = id_parts[1]
        return _sanitize_slug(sub_raw, default="general"), _humanize_slug(sub_raw)
    return "general", "General"


def _build_subcategories_for_category(
    cat_id: str,
    cat_candidates: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Group a category's settings into subcategories and merge tiny 1-item singleton clusters.

    Returns (subcategories_list, setting_id_to_subcategory_id).
    """
    raw_groups: dict[str, list[str]] = {}
    raw_titles: dict[str, str] = {}

    for cand in sorted(cat_candidates, key=lambda c: str(c["id"])):
        sid = str(cand["id"])
        sub_slug, sub_title = _resolve_raw_subcategory_group(cand, cat_id)
        raw_groups.setdefault(sub_slug, []).append(sid)
        raw_titles.setdefault(sub_slug, sub_title)

    total_settings = len(cat_candidates)

    # Smart grouping rule:
    # When a category has >= 2 total settings and contains 1-item singleton groups alongside
    # other groups, merge the 1-item singletons so no noisy 1-item subcategories remain.
    if total_settings >= 2 and len(raw_groups) >= 2:
        multi_groups = {k: v for k, v in raw_groups.items() if len(v) >= 2}
        singleton_keys = sorted(k for k, v in raw_groups.items() if len(v) == 1)

        if singleton_keys:
            singleton_sids: list[str] = []
            for sk in singleton_keys:
                singleton_sids.extend(raw_groups[sk])
            singleton_sids.sort()

            if len(singleton_sids) >= 2:
                # Merge all singletons into a shared "general" (or "other") subcategory
                target_key = "general" if "general" not in multi_groups else "other"
                merged_list = list(multi_groups.get(target_key, [])) + singleton_sids
                merged_list.sort()
                multi_groups[target_key] = merged_list
                raw_titles.setdefault(
                    target_key,
                    "General" if target_key == "general" else "Other Settings",
                )
                raw_groups = multi_groups
            elif len(singleton_sids) == 1:
                # Exactly 1 singleton alongside >= 1 multi_group: merge into "general" if present,
                # otherwise into the largest/first multi_group so every subcategory has >= 2 items.
                if "general" in multi_groups:
                    target_key = "general"
                else:
                    target_key = sorted(
                        multi_groups.keys(),
                        key=lambda k: (-len(multi_groups[k]), k),
                    )[0]
                merged_list = sorted(multi_groups[target_key] + singleton_sids)
                multi_groups[target_key] = merged_list
                raw_groups = multi_groups

    subcategories: list[dict[str, Any]] = []
    sid_to_subid: dict[str, str] = {}

    ordered_sub_keys = sorted(
        raw_groups.keys(),
        key=lambda k: (0 if k == "general" else 1 if k != "other" else 2, k),
    )

    for idx, sub_slug in enumerate(ordered_sub_keys, start=1):
        sids = sorted(raw_groups[sub_slug])
        full_sub_id = f"{cat_id}.{sub_slug}" if not sub_slug.startswith(f"{cat_id}.") else sub_slug
        if not _SLUG_RE.fullmatch(full_sub_id):
            full_sub_id = _sanitize_slug(full_sub_id, default=f"{cat_id}.general")
        sub_title = raw_titles.get(sub_slug) or _humanize_slug(sub_slug)
        subcategories.append(
            {
                "id": full_sub_id,
                "title": sub_title,
                "order": idx * 10,
                "settingIds": sids,
            }
        )
        for sid in sids:
            sid_to_subid[sid] = full_sub_id

    return subcategories, sid_to_subid


def _canonical_verified_item_for_hash(cand: Mapping[str, Any]) -> dict[str, Any]:
    """Build a canonical structural representation of a verified candidate for inventoryHash.

    Order-invariant and invariant to keyword order or description punctuation edits
    only where appropriate, while changing whenever inventory membership or structure mutates.
    """
    sem = cand.get("semantics") if isinstance(cand.get("semantics"), Mapping) else {}
    raw_hints = sem.get("domainHints")
    hints = (
        [str(x) for x in raw_hints if isinstance(x, str)]
        if isinstance(raw_hints, Sequence) and not isinstance(raw_hints, (str, bytes))
        else []
    )
    raw_kws = cand.get("keywords")
    kws = (
        sorted(str(x).lower() for x in raw_kws if isinstance(x, str))
        if isinstance(raw_kws, Sequence) and not isinstance(raw_kws, (str, bytes))
        else []
    )
    return {
        "id": str(cand.get("id") or ""),
        "valueType": str(cand.get("valueType") or "unknown"),
        "sourceKind": str(cand.get("sourceKind") or ""),
        "adapter": str(cand.get("adapter") or ""),
        "path": str(cand.get("path") or ""),
        "domainHints": hints,
        "featureGroup": str(sem.get("featureGroup") or ""),
        "expertOnly": _is_expert_only(cand),
        "sensitive": bool(cand.get("sensitive", False)),
        "keywords": kws,
    }


def compute_verified_inventory_hash(verified_candidates: Sequence[Mapping[str, Any]]) -> str:
    """Compute a deterministic SHA-256 hex digest of verified candidates."""
    canonical_rows = sorted(
        (_canonical_verified_item_for_hash(c) for c in verified_candidates),
        key=lambda r: r["id"],
    )
    payload = json.dumps(
        canonical_rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _normalize_keywords(cand: Mapping[str, Any], cat_id: str, sub_id: str, title: str) -> list[str]:
    """Collect a deduplicated, sorted list of lowercase search keywords for a setting."""
    kw_set: set[str] = set()
    raw_kws = cand.get("keywords")
    if isinstance(raw_kws, Sequence) and not isinstance(raw_kws, (str, bytes)):
        for k in raw_kws:
            if isinstance(k, str) and k.strip():
                kw_set.add(k.strip().lower())
    sem = cand.get("semantics") if isinstance(cand.get("semantics"), Mapping) else {}
    tags = sem.get("tags")
    if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes)):
        for t in tags:
            if isinstance(t, str) and t.strip():
                kw_set.add(t.strip().lower())
    for tok in re.split(r"[^A-Za-z0-9]+", str(cand.get("id") or "")):
        if tok:
            kw_set.add(tok.lower())
    for tok in re.split(r"[^A-Za-z0-9]+", title):
        if tok:
            kw_set.add(tok.lower())
    kw_set.add(cat_id.lower())
    kw_set.add(sub_id.split(".")[-1].lower())
    return sorted(kw_set)


def update_tree(
    inventory: Any,
    previous_tree: dict[str, Any] | None = None,
    changed_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Generate or incrementally update the Layer 3 CategoryTreeOutput (`nexus-category-tree-v1`).

    Parameters
    ----------
    inventory:
        List of candidate dicts/objects, or a DiscoveryResult/catalog dict wrapping candidates.
    previous_tree:
        Optional prior CategoryTreeOutput dict for incremental updates.
    changed_ids:
        Optional list of changed setting IDs. When `changed_ids == []` and `previous_tree` is a
        valid tree dict, returns a no-op update with `diagnostics["incrementalChanges"] = []`.
    """
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fast-path no-op when changed_ids is explicitly an empty list and previous_tree is valid
    if (
        changed_ids is not None
        and isinstance(changed_ids, Sequence)
        and len(changed_ids) == 0
        and isinstance(previous_tree, Mapping)
        and previous_tree.get("schema") == SCHEMA_VERSION
    ):
        noop_tree = copy.deepcopy(dict(previous_tree))
        noop_diag = dict(noop_tree.get("diagnostics") or {})
        noop_diag["incrementalChanges"] = []
        noop_tree["diagnostics"] = noop_diag
        return noop_tree

    raw_items = _extract_candidates_list(inventory)

    seen_ids: set[str] = set()
    duplicates_prevented = 0
    malformed_skipped = 0

    verified_by_id: dict[str, dict[str, Any]] = {}
    all_domains_seen: set[str] = set()
    active_domains: set[str] = set()

    domain_resolution_cache: dict[str, tuple[str, str | None, str, float, bool]] = {}

    for raw in raw_items:
        cand = _candidate_to_dict(raw)
        if cand is None:
            malformed_skipped += 1
            continue
        sid = cand["id"].strip()
        cand["id"] = sid
        if sid in seen_ids:
            duplicates_prevented += 1
            continue
        seen_ids.add(sid)

        cat_id, disp_title, reason, conf, is_fb = _resolve_domain_and_reason(cand)
        all_domains_seen.add(cat_id)

        if not _is_candidate_verified(cand):
            continue

        active_domains.add(cat_id)
        verified_by_id[sid] = cand
        domain_resolution_cache[sid] = (cat_id, disp_title, reason, conf, is_fb)

    # Also detect categories present in previous_tree that were completely removed
    prev_cat_ids: set[str] = set()
    if isinstance(previous_tree, Mapping) and isinstance(previous_tree.get("categories"), Sequence):
        for pcat in previous_tree.get("categories", []):
            if isinstance(pcat, Mapping) and isinstance(pcat.get("id"), str):
                prev_cat_ids.add(pcat["id"])

    unverified_only_domains = all_domains_seen - active_domains
    removed_prev_domains = prev_cat_ids - active_domains
    empty_pruned = len(unverified_only_domains | removed_prev_domains)

    # Group verified candidates by canonical category_id
    by_category: dict[str, list[dict[str, Any]]] = {}
    category_display_overrides: dict[str, str] = {}
    fallback_assigned = 0

    for sid in sorted(verified_by_id.keys()):
        cand = verified_by_id[sid]
        cat_id, disp_title, _, _, is_fb = domain_resolution_cache[sid]
        if is_fb:
            fallback_assigned += 1
        by_category.setdefault(cat_id, []).append(cand)
        if disp_title and cat_id not in category_display_overrides:
            category_display_overrides[cat_id] = disp_title

    # Determine incrementalChanges diagnostics
    incremental_changes: list[str] = []
    affected_categories: set[str] = set()
    has_valid_previous = (
        isinstance(previous_tree, Mapping)
        and previous_tree.get("schema") == SCHEMA_VERSION
        and isinstance(previous_tree.get("categories"), list)
        and isinstance(previous_tree.get("assignments"), Mapping)
    )

    if has_valid_previous:
        prev_assignments: Mapping[str, Any] = previous_tree["assignments"]  # type: ignore[index]
        if changed_ids is not None:
            for cid in changed_ids:
                if not isinstance(cid, str):
                    continue
                if cid in verified_by_id:
                    incremental_changes.append(cid)
                    affected_categories.add(domain_resolution_cache[cid][0])
                elif cid in prev_assignments:
                    incremental_changes.append(cid)
                    prev_cat = prev_assignments[cid].get("categoryId")
                    if isinstance(prev_cat, str):
                        affected_categories.add(prev_cat)
        else:
            # Diff automatically against previous_tree assignments
            prev_sids = set(prev_assignments.keys())
            curr_sids = set(verified_by_id.keys())
            delta_sids = sorted((curr_sids - prev_sids) | (prev_sids - curr_sids))
            for cid in delta_sids:
                incremental_changes.append(cid)
                if cid in domain_resolution_cache:
                    affected_categories.add(domain_resolution_cache[cid][0])
                elif cid in prev_assignments:
                    prev_cat = prev_assignments[cid].get("categoryId")
                    if isinstance(prev_cat, str):
                        affected_categories.add(prev_cat)

    # Sort categories deterministically
    ordered_cat_ids = sorted(
        by_category.keys(),
        key=lambda cid: (CANONICAL_DOMAIN_ORDER.get(cid, 500), cid),
    )

    prev_cats_by_id: dict[str, dict[str, Any]] = {}
    if has_valid_previous:
        for pcat in previous_tree["categories"]:  # type: ignore[index]
            if isinstance(pcat, Mapping) and isinstance(pcat.get("id"), str):
                prev_cats_by_id[pcat["id"]] = dict(pcat)

    categories_out: list[dict[str, Any]] = []
    assignments_out: dict[str, dict[str, Any]] = {}
    search_index_out: list[dict[str, Any]] = []

    for idx, cat_id in enumerate(ordered_cat_ids, start=1):
        cat_candidates = sorted(by_category[cat_id], key=lambda c: str(c["id"]))
        cat_sids = [str(c["id"]) for c in cat_candidates]

        # If incremental update and this category was completely untouched and has identical members,
        # preserve previous category object (updating order only if needed, or keeping exact subtree)
        can_reuse_prev_cat = (
            has_valid_previous
            and changed_ids is not None
            and cat_id not in affected_categories
            and cat_id in prev_cats_by_id
            and prev_cats_by_id[cat_id].get("settingIds") == cat_sids
        )

        if can_reuse_prev_cat:
            reused_cat = copy.deepcopy(prev_cats_by_id[cat_id])
            categories_out.append(reused_cat)
            sid_to_subid = {
                sid: str(sub["id"])
                for sub in reused_cat.get("subcategories", [])
                if isinstance(sub, Mapping)
                for sid in sub.get("settingIds", [])
            }
        else:
            subcategories, sid_to_subid = _build_subcategories_for_category(cat_id, cat_candidates)
            cat_title = category_display_overrides.get(cat_id) or _humanize_slug(cat_id)
            all_expert = all(_is_expert_only(c) for c in cat_candidates)
            cat_order = CANONICAL_DOMAIN_ORDER.get(cat_id, 500 + idx * 10)
            cat_summary = (
                f"{len(cat_sids)} verified setting{'s' if len(cat_sids) != 1 else ''} "
                f"across {len(subcategories)} subcategor{'ies' if len(subcategories) != 1 else 'y'}."
            )
            categories_out.append(
                {
                    "id": cat_id,
                    "title": cat_title,
                    "summary": cat_summary,
                    "expertOnly": bool(all_expert),
                    "order": cat_order,
                    "settingIds": cat_sids,
                    "subcategories": subcategories,
                    "settingCount": len(cat_sids),
                }
            )

        for cand in cat_candidates:
            sid = str(cand["id"])
            _, _, reason, conf, _ = domain_resolution_cache[sid]
            sub_id = sid_to_subid.get(sid, f"{cat_id}.general")
            assignments_out[sid] = {
                "categoryId": cat_id,
                "subcategoryId": sub_id,
                "ruleReason": reason,
                "confidence": round(float(conf), 4),
            }

            raw_title = cand.get("title")
            title = (
                raw_title.strip()
                if isinstance(raw_title, str) and raw_title.strip()
                else _humanize_slug(sid.split(".")[-1])
            )
            raw_desc = cand.get("description")
            description = (
                raw_desc.strip()
                if isinstance(raw_desc, str) and raw_desc.strip()
                else f"Setting {sid}"
            )
            keywords = _normalize_keywords(cand, cat_id, sub_id, title)

            search_index_out.append(
                {
                    "kind": "setting",
                    "id": sid,
                    "title": title,
                    "description": description,
                    "categoryId": cat_id,
                    "subcategoryId": sub_id,
                    "keywords": keywords,
                    "manageable": True,
                }
            )

    search_index_out.sort(key=lambda item: str(item["id"]))
    inv_hash = compute_verified_inventory_hash(list(verified_by_id.values()))

    return {
        "schema": SCHEMA_VERSION,
        "engineVersion": ENGINE_VERSION,
        "inventoryHash": inv_hash,
        "generatedAt": now_iso,
        "categories": categories_out,
        "assignments": dict(sorted(assignments_out.items())),
        "searchIndex": search_index_out,
        "diagnostics": {
            "emptyPruned": empty_pruned,
            "duplicatesPrevented": duplicates_prevented,
            "fallbackAssigned": fallback_assigned,
            "malformedSkipped": malformed_skipped,
            "incrementalChanges": incremental_changes,
        },
    }


def build_category_tree(
    inventory: Any,
    *,
    previous_tree: dict[str, Any] | None = None,
    changed_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Alias for `update_tree`."""
    return update_tree(inventory, previous_tree=previous_tree, changed_ids=changed_ids)


def generate_category_tree(
    inventory: Any,
    *,
    previous_tree: dict[str, Any] | None = None,
    changed_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Alias for `update_tree`."""
    return update_tree(inventory, previous_tree=previous_tree, changed_ids=changed_ids)


@dataclass
class CategoryEngine:
    """Stateful/helper wrapper around the deterministic Layer 3 Category Engine."""

    current_tree: dict[str, Any] | None = field(default=None)

    def build(self, inventory: Any) -> dict[str, Any]:
        self.current_tree = update_tree(inventory)
        return self.current_tree

    def update(
        self,
        inventory: Any,
        *,
        previous_tree: dict[str, Any] | None = None,
        changed_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        base = previous_tree if previous_tree is not None else self.current_tree
        self.current_tree = update_tree(inventory, previous_tree=base, changed_ids=changed_ids)
        return self.current_tree
