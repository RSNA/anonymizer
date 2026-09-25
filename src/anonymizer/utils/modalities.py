
from __future__ import annotations

import re

from anonymizer.utils.translate import _

# List of supported Modalities
# Modality Code => Description, Set of Related SOP Storage Class UIDs

# see: https://dicom.nema.org/medical/dicom/current/output/chtml/part16/sect_CID_29.html


# Description dynamically updated due to language dependency
def get_modalities() -> dict[str, tuple[str, list[str]]]:

    return {
        "CR": (_("Computed Radiography"), ["1.2.840.10008.5.1.4.1.1.1"]),
        "DX": (
            _("Digital X-Ray"),
            ["1.2.840.10008.5.1.4.1.1.1.1", "1.2.840.10008.5.1.4.1.1.1.1.1"],
        ),
        "IO": (
            _("Intra-oral Radiography"),
            ["1.2.840.10008.5.1.4.1.1.1.3", "1.2.840.10008.5.1.4.1.1.1.3.1"],
        ),
        "MG": (
            _("Mammography"),
            [
                "1.2.840.10008.5.1.4.1.1.1.2",
                "1.2.840.10008.5.1.4.1.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.13.1.3",
                "1.2.840.10008.5.1.4.1.1.13.1.4",
                "1.2.840.10008.5.1.4.1.1.13.1.5",
            ],
        ),
        "CT": (
            _("Computer Tomography"),
            [
                "1.2.840.10008.5.1.4.1.1.2",
                "1.2.840.10008.5.1.4.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.2.2",
            ],
        ),
        "MR": (
            _("Magnetic Resonance"),
            ["1.2.840.10008.5.1.4.1.1.4", "1.2.840.10008.5.1.4.1.1.4.1"],
        ),
        "US": (
            _("Ultrasound"),
            ["1.2.840.10008.5.1.4.1.1.6.1", "1.2.840.10008.5.1.4.1.1.6.2", "1.2.840.10008.5.1.4.1.1.3.1"],
        ),
        "PT": (
            _("Positron Emission Tomography"),
            [
                "1.2.840.10008.5.1.4.1.1.128",
                "1.2.840.10008.5.1.4.1.1.128.1",
                "1.2.840.10008.5.1.4.1.1.130",
            ],
        ),
        "NM": (_("Nuclear Medicine"), ["1.2.840.10008.5.1.4.1.1.20"]),
        "SC": (_("Secondary Capture"), ["1.2.840.10008.5.1.4.1.1.7"]),
        "SR": (
            _("Structured Report"),
            [
                "1.2.840.10008.5.1.4.1.1.88.11",
                "1.2.840.10008.5.1.4.1.1.88.22",
                "1.2.840.10008.5.1.4.1.1.88.33",
                "1.2.840.10008.5.1.4.1.1.88.34",
                "1.2.840.10008.5.1.4.1.1.88.35",
            ],
        ),
        "PR": (
            _("Presentation State"),
            [
                "1.2.840.10008.5.1.4.1.1.11.1",
                "1.2.840.10008.5.1.4.1.1.11.2",
                "1.2.840.10008.5.1.4.1.1.11.3",
                "1.2.840.10008.5.1.4.1.1.11.4",
                "1.2.840.10008.5.1.4.1.1.11.5",
                "1.2.840.10008.5.1.4.1.1.11.6",
                "1.2.840.10008.5.1.4.1.1.11.7",
                "1.2.840.10008.5.1.4.1.1.11.8",
                "1.2.840.10008.5.1.4.1.1.11.9",
                "1.2.840.10008.5.1.4.1.1.11.10",
                "1.2.840.10008.5.1.4.1.1.11.11",
            ],
        ),
        "PDF": (_("Encapsulated PDF"), ["1.2.840.10008.5.1.4.1.1.104.1"]),
        "OT": (_("Other"), []),
        "DOC": (_("Document"), []),
    }

    #     "GM", _("General Microscopy"),
    #     "PX", _("Panoramic X-Ray"),
    #     "RT",
    #     "ECG",
    #     "VL",
    #     "MPR":  _("Multi-planar Reconstruction"),
    #     "CDA": _("Clinical Document Architecture")
    #     "STL",
    #     "OBJ",
    #     "MTL",
    #     "CAD",
    #     "3D",
    #     "XA": _("X-Ray Angiography")
    #     "XRF",
    #     "SEG",
    #     "REG",
    #     "KO", _("Key Object Selection")


def normalize_modality(value: object | None) -> str:
    """Return uppercase modality code; map MRI → MR."""
    text = str(value or "").strip().upper()
    if text == "MRI":
        return "MR"
    return text


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
    return token.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def resolve_modality_code(token: str) -> str | None:
    """Map a code, alias, or modality description to a known DICOM modality code."""
    raw = str(token or "").strip()
    if not raw:
        return None
    catalog = get_modalities()
    code = normalize_modality(raw)
    if code in catalog:
        return code
    alias = _MODALITY_ALIASES.get(_alias_key(raw))
    if alias and alias in catalog:
        return alias
    needle = raw.lower().strip()
    for mod, (description, _uids) in catalog.items():
        desc = str(description).lower().strip()
        if desc == needle or _alias_key(desc) == _alias_key(raw):
            return mod
    return None


def _modality_phrase_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Longest-first patterns: (regex, token) for NL extraction → resolve_modality_code."""
    catalog = get_modalities()
    pairs: list[tuple[str, str]] = []
    for code in catalog:
        pairs.append((code, code))
    for alias, code in _MODALITY_ALIASES.items():
        if code in catalog:
            pairs.append((alias, code))
    for code, (description, _uids) in catalog.items():
        desc = str(description).strip()
        if desc:
            pairs.append((desc, code))
    # Prefer longer phrases (Magnetic Resonance before MR).
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
    """Extract modality tokens from natural language or abbreviation lists.

    Examples:
      \"defaults and ultrasound\" → [\"defaults\", \"US\"]
      \"CT, MR, US\" → [\"CT\", \"MR\", \"US\"]
      \"only mammography\" → [\"MG\"]
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
    """Normalize list/str input into raw tokens (may still include ``defaults``)."""
    if modalities is None:
        return None
    if isinstance(modalities, str):
        text = modalities.strip()
        if not text:
            return None
        # Natural-language phrase or mixed list → scan for known terms.
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
    """Resolve create/open ``modalities`` to DICOM codes.

    Accepts a list of codes/aliases, a comma-separated string, or natural language
    (e.g. ``\"defaults and ultrasound\"``). ``None`` / empty → ``None`` (caller keeps
    existing settings). Token ``defaults`` expands to ProjectModel defaults.
    """
    tokens = _coerce_modality_token_list(modalities)
    if not tokens:
        return None

    from anonymizer.model.project import ProjectModel

    defaults = list(default_modalities) if default_modalities is not None else list(
        ProjectModel.default_modalities()
    )
    catalog = get_modalities()
    resolved: list[str] = []
    unknown: list[str] = []

    def _add(code: str) -> None:
        if code not in catalog:
            unknown.append(code)
            return
        if code not in resolved:
            resolved.append(code)

    for token in tokens:
        if token.strip().lower() in _DEFAULT_MODALITY_TOKENS:
            for code in defaults:
                _add(normalize_modality(code))
            continue
        # Already a resolved code from NL extraction
        if token in catalog:
            _add(token)
            continue
        code = resolve_modality_code(token)
        if code is None:
            unknown.append(token)
        else:
            _add(code)

    if unknown:
        known = ", ".join(sorted(catalog.keys()))
        raise ValueError(
            f"Unknown modality token(s): {', '.join(repr(u) for u in unknown)}. "
            f"Use DICOM codes, names like ultrasound, or 'defaults'. Known codes: {known}"
        )
    if not resolved:
        raise ValueError("modalities resolved to an empty list")
    return resolved


def is_ct_modality(value: object | None) -> bool:
    return normalize_modality(value) == "CT"


def is_mr_modality(value: object | None) -> bool:
    return normalize_modality(value) == "MR"


def is_tseg_modality(value: object | None) -> bool:
    """CT or MR — TotalSegmentator Harmonize / Face Blur path only."""
    return normalize_modality(value) in {"CT", "MR"}


def series_is_tseg_eligible(modality: object | None) -> bool:
    """ORM / study-complete helper: CT or MR series participate in TSEG Harmonize."""
    return is_tseg_modality(modality)


# Planar (non-3D) Harmonize: metadata Playbook only — never TotalSegmentator.
_PLANAR_HARMONIZE_MODALITIES = frozenset({"CR", "DX", "US", "MG"})


def is_planar_harmonize_modality(value: object | None) -> bool:
    """CR/DX (XR), US, or MG — metadata Harmonize path (isolated from TSEG)."""
    return normalize_modality(value) in _PLANAR_HARMONIZE_MODALITIES


def series_is_planar_harmonize_eligible(modality: object | None) -> bool:
    """ORM helper: planar series participate in metadata Harmonize / planar LOINC."""
    return is_planar_harmonize_modality(modality)


def is_harmonize_modality(value: object | None) -> bool:
    """Any series Harmonize can run: CT/MR (TSEG) or CR/DX/US/MG (planar)."""
    return is_tseg_modality(value) or is_planar_harmonize_modality(value)


def series_is_harmonize_eligible(modality: object | None) -> bool:
    """ORM helper: series participates in some Harmonize path."""
    return is_harmonize_modality(modality)


def planar_harmonize_cohort(value: object | None) -> str | None:
    """Return XR / US / MG cohort code, or None if not a planar Harmonize modality."""
    code = normalize_modality(value)
    if code in {"CR", "DX"}:
        return "XR"
    if code == "US":
        return "US"
    if code == "MG":
        return "MG"
    return None
