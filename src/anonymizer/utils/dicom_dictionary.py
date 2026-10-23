"""DICOM Part 6 public dictionary lookups.

Public API
----------
TagDictionaryMeta
    Part 6 dictionary fields for one public tag (from pydicom).

DictHit
    One dictionary search hit.

normalize_tag_hex(tag: str) -> str | None
    Return 8-hex uppercase tag, or None if not a valid DICOM tag string.

tag_dictionary_meta(tag: str) -> TagDictionaryMeta | None
    Look up Part 6 Name/VR/VM/retired/keyword for tag.

format_tag_description_line(meta: TagDictionaryMeta, *, retired_label: str='Retired') -> str
    One-line blurb: Part 6 Name, with retired suffix when applicable.

dicom_standard_version() -> str
    DICOM Standard dated issue used for pydicom's public dictionary.

dicom_applicable_standard_text() -> str
    Display string for UI: major.minor family + pydicom dated issue.

tag_dictionary_vr(tag: str) -> str | None
    Return the DICOM dictionary VR for tag (8-hex).

format_dicom_tag(tag: str) -> str
    Format an 8-hex tag as DICOM GGGG,EEEE.

display_tag_vr(tag: str) -> str
    VR string for UI columns (first token of multi-VR entries).

search_dicom_dictionary(query: str, *, limit: int=50, exclude_tags: set[str] | None=None) -> list[DictHit]
    Substring search over pydicom keyword dict (capped).
"""
import re
from dataclasses import dataclass

try:
    from pydicom._version import __dicom_version__
except Exception:
    __dicom_version__ = None  # type: ignore[assignment,misc]
from pydicom.datadict import DicomDictionary, keyword_dict

_TAG_HEX_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


@dataclass(frozen=True)
class TagDictionaryMeta:
    """Part 6 dictionary fields for one public tag (from pydicom)."""

    tag: str
    description: str
    vr: str
    vm: str
    retired: bool
    keyword: str


@dataclass(frozen=True)
class DictHit:
    """One dictionary search hit."""

    tag: str
    keyword: str
    vr: str
    description: str = ""


def normalize_tag_hex(tag: str) -> str | None:
    """
    Return 8-hex uppercase tag, or None if not a valid DICOM tag string.

    Args:
        tag: Candidate tag text (may include commas or spaces).

    Returns:
        Normalized 8-hex tag, or None.
    """
    text = str(tag or "").strip().upper().replace(",", "").replace(" ", "")
    if len(text) != 8 or any(c not in "0123456789ABCDEF" for c in text):
        return None
    return text


def tag_dictionary_meta(tag: str) -> TagDictionaryMeta | None:
    """
    Look up Part 6 Name/VR/VM/retired/keyword for tag.

    Args:
        tag: Eight-hex DICOM tag (commas/spaces allowed).

    Returns:
        Meta row, or None if unknown.
    """
    hex_tag = normalize_tag_hex(tag)
    if hex_tag is None:
        return None
    entry = DicomDictionary.get(int(hex_tag, 16))
    if entry is None or len(entry) < 5:
        return None
    vr = str(entry[0] or "")
    if " " in vr:
        vr = vr.split()[0]
    retired_raw = str(entry[3] or "").strip().lower()
    retired = retired_raw in {"retired", "y", "yes", "true", "1"}
    return TagDictionaryMeta(
        tag=hex_tag,
        description=str(entry[2] or "").strip(),
        vr=vr.upper(),
        vm=str(entry[1] or "").strip(),
        retired=retired,
        keyword=str(entry[4] or "").strip(),
    )


def format_tag_description_line(meta: TagDictionaryMeta, *, retired_label: str = "Retired") -> str:
    """
    One-line blurb: Part 6 Name, with retired suffix when applicable.

    Args:
        meta: Dictionary meta for the tag.
        retired_label: Label appended when the attribute is retired.

    Returns:
        Display line (no VR/VM).
    """
    name = (meta.description or "").strip()
    if meta.retired:
        label = str(retired_label or "Retired").strip() or "Retired"
        return f"{name} · {label}" if name else label
    return name


def dicom_standard_version() -> str:
    """
    DICOM Standard dated issue used for pydicom's public dictionary.

    Returns:
        Edition string (e.g. 2024c), or empty when unavailable.
    """
    return str(__dicom_version__ or "").strip()


def dicom_applicable_standard_text() -> str:
    """
    Display string for UI: major.minor family + pydicom dated issue.

    Returns:
        e.g. DICOM 3.0 (2024c), or empty when edition unknown.
    """
    edition = dicom_standard_version()
    if not edition:
        return ""
    return f"DICOM 3.0 ({edition})"


def tag_dictionary_vr(tag: str) -> str | None:
    """
    Return the DICOM dictionary VR for tag (8-hex).

    Args:
        tag: Eight-hex DICOM tag.

    Returns:
        VR string, or None if unknown.
    """
    meta = tag_dictionary_meta(tag)
    return meta.vr if meta is not None and meta.vr else None


def format_dicom_tag(tag: str) -> str:
    """
    Format an 8-hex tag as DICOM GGGG,EEEE.

    Args:
        tag: Eight-hex tag or other text.

    Returns:
        GGGG,EEEE when valid; otherwise stripped input.
    """
    hex_tag = normalize_tag_hex(tag)
    if hex_tag is not None:
        return f"{hex_tag[:4]},{hex_tag[4:]}"
    return str(tag or "").strip()


def display_tag_vr(tag: str) -> str:
    """
    VR string for UI columns (first token of multi-VR entries).

    Args:
        tag: Eight-hex DICOM tag.

    Returns:
        VR or empty string.
    """
    return tag_dictionary_vr(tag) or ""


def search_dicom_dictionary(
    query: str,
    *,
    limit: int = 50,
    exclude_tags: set[str] | None = None,
) -> list[DictHit]:
    """
    Substring search over pydicom keyword dict (capped).

    Empty query lists the first limit tags (after exclusions) for browse UIs.
    Non-empty queries shorter than 2 characters return no hits.

    Args:
        query: Keyword or tag substring.
        limit: Maximum hits.
        exclude_tags: Tags to skip (uppercase 8-hex).

    Returns:
        Matching dictionary hits.
    """
    needle = str(query or "").strip().lower()
    if needle and len(needle) < 2:
        return []
    limit = max(1, int(limit))
    excluded = {t.upper() for t in (exclude_tags or set())}
    hits: list[DictHit] = []
    items = sorted(keyword_dict.items(), key=lambda kv: str(kv[0]).lower())
    for keyword, tag_int in items:
        name = str(keyword or "").strip()
        if not name:
            continue
        tag = f"{int(tag_int):08X}"
        if tag in excluded:
            continue
        if needle and needle not in name.lower() and needle not in tag.lower():
            continue
        entry = DicomDictionary.get(tag_int)
        vr = ""
        description = ""
        if entry is not None and len(entry) >= 1:
            vr = str(entry[0] or "")
            if " " in vr:
                vr = vr.split()[0]
        if entry is not None and len(entry) >= 3:
            description = str(entry[2] or "").strip()
        hits.append(DictHit(tag=tag, keyword=name, vr=vr, description=description))
        if len(hits) >= limit:
            break
    return hits


