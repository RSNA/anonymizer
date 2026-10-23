"""Free-text / alias modality parsing for MCP project create/open only.

Model and controller must not import this module.
"""

import re

from anonymizer.utils.modalities import (
    DEFAULT_PROJECT_MODALITIES,
    Modality,
    get_modality_catalog,
)

# Friendly names → DICOM modality codes (for create/open modalities=).
_MODALITY_ALIASES: dict[str, str] = {
    "ultrasound": "US",
    "sono": "US",
    "sonography": "US",
    "mri": "MR",
    "magneticresonance": "MR",
    "ct": "CT",
    "computedtomography": "CT",
    "computertomography": "CT",
    "xray": "DX",
    "x-ray": "DX",
    "xr": "DX",
    "radiograph": "DX",
    "radiography": "DX",
    "cr": "CR",
    "dx": "DX",
    "mammography": "MG",
    "mammo": "MG",
    "mg": "MG",
    "pet": "PT",
    "positronemissiontomography": "PT",
    "nm": "NM",
    "nuclearmedicine": "NM",
    "sc": "SC",
    "secondarycapture": "SC",
    "sr": "SR",
    "structuredreport": "SR",
}

_DEFAULT_MODALITY_TOKENS = frozenset({"default", "defaults", "default_modalities"})

_DEFAULTS_IN_TEXT_RE = re.compile(
    r"\bdefaults?\b|\bdefault\s+modalit(?:y|ies)\b",
    re.IGNORECASE,
)


def _alias_key(token: str) -> str:
    """Normalize a token for alias lookup."""
    return token.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def resolve_modality_code(token: str) -> str | None:
    """
    Map a code, alias, or modality description to a known DICOM modality code.

    Args:
        token: User-supplied modality token.

    Returns:
        DICOM modality code string, or None if unknown.
    """
    raw = str(token or "").strip()
    if not raw:
        return None
    catalog = get_modality_catalog()
    modality = Modality.from_code(raw)
    if modality is not None and modality in catalog:
        return modality.value
    alias = _MODALITY_ALIASES.get(_alias_key(raw))
    if alias is not None:
        aliased = Modality.from_code(alias)
        if aliased is not None and aliased in catalog:
            return aliased.value
    needle = raw.lower().strip()
    for mod, entry in catalog.items():
        desc = str(entry.description).lower().strip()
        if desc == needle or _alias_key(desc) == _alias_key(raw):
            return mod.value
    return None


def _modality_phrase_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Longest-first patterns: (regex, code) for NL extraction."""
    catalog = get_modality_catalog()
    pairs: list[tuple[str, str]] = []
    for code in catalog:
        pairs.append((code.value, code.value))
    for alias, code in _MODALITY_ALIASES.items():
        if Modality.from_code(code) in catalog:
            pairs.append((alias, code))
    for code, entry in catalog.items():
        desc = str(entry.description).strip()
        if desc:
            pairs.append((desc, code.value))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    patterns: list[tuple[re.Pattern[str], str]] = []
    seen: set[str] = set()
    for phrase, code in pairs:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        escaped = re.escape(phrase).replace(r"\ ", r"[\s\-_/]*")
        patterns.append((re.compile(rf"\b{escaped}\b", re.IGNORECASE), code))
    return patterns


def extract_modality_tokens_from_text(text: str) -> list[str]:
    """
    Extract modality tokens from natural language or abbreviation lists.

    Args:
        text: Free-text modalities phrase.

    Returns:
        Tokens such as defaults or DICOM codes.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    tokens: list[str] = []
    if _DEFAULTS_IN_TEXT_RE.search(raw):
        tokens.append("defaults")
    for pattern, code in _modality_phrase_patterns():
        if pattern.search(raw) and code not in tokens:
            tokens.append(code)
    return tokens


def _coerce_modality_token_list(modalities: list[str] | str | None) -> list[str] | None:
    """Normalize list/str input into raw tokens (may still include defaults)."""
    if modalities is None:
        return None
    if isinstance(modalities, str):
        text = modalities.strip()
        if not text:
            return None
        if (
            _DEFAULTS_IN_TEXT_RE.search(text)
            or re.search(r"\b(?:and|plus|with|also)\b", text, re.IGNORECASE)
            or (" " in text and "," not in text and ";" not in text)
        ):
            extracted = extract_modality_tokens_from_text(text)
            if extracted:
                return extracted
        parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
        return parts or None

    tokens: list[str] = []
    for item in modalities:
        text = str(item or "").strip()
        if not text:
            continue
        if len(modalities) == 1 and (
            _DEFAULTS_IN_TEXT_RE.search(text)
            or re.search(r"\b(?:and|plus|with|also)\b", text, re.IGNORECASE)
        ):
            extracted = extract_modality_tokens_from_text(text)
            if extracted:
                return extracted
        if "," in text or ";" in text:
            tokens.extend(p.strip() for p in text.replace(";", ",").split(",") if p.strip())
        else:
            tokens.append(text)
    return tokens or None


def resolve_project_modalities(
    modalities: list[str] | str | None,
    *,
    default_modalities: list[str] | None = None,
) -> list[str] | None:
    """
    Resolve create/open modalities to DICOM codes.

    Args:
        modalities: Codes, aliases, comma-separated string, or natural language.
        default_modalities: Expansion for the defaults token.

    Returns:
        Resolved DICOM modality code strings, or None if input empty.
    """
    tokens = _coerce_modality_token_list(modalities)
    if not tokens:
        return None

    defaults = (
        list(default_modalities)
        if default_modalities is not None
        else [m.value for m in DEFAULT_PROJECT_MODALITIES]
    )
    catalog = get_modality_catalog()
    resolved: list[str] = []
    unknown: list[str] = []

    def _add(code: str) -> None:
        modality = Modality.from_code(code)
        if modality is None or modality not in catalog:
            unknown.append(code)
            return
        if modality.value not in resolved:
            resolved.append(modality.value)

    for token in tokens:
        if token.strip().lower() in _DEFAULT_MODALITY_TOKENS:
            for code in defaults:
                _add(code)
            continue
        if Modality.from_code(token) in catalog:
            _add(token)
            continue
        code = resolve_modality_code(token)
        if code is None:
            unknown.append(token)
        else:
            _add(code)

    if unknown:
        known = ", ".join(sorted(m.value for m in catalog))
        raise ValueError(
            f"Unknown modality token(s): {', '.join(repr(u) for u in unknown)}. "
            f"Use DICOM codes, names like ultrasound, or 'defaults'. Known codes: {known}"
        )
    if not resolved:
        raise ValueError("modalities resolved to an empty list")
    return resolved
