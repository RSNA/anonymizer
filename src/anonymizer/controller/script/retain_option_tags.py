"""PS3.15 Table E.1-1 retain-option attribute sets for script compile.

Loads the committed E.1-1 extract and merges product device-identity extras
(Manufacturer / model / software) that recent DICOM editions dropped from
Table E.1-1 but that this product still treats as Retain Device Identity.

Public API
----------
RetainFamily
    Catalog family key: device, institution, patient_characteristics,
    full_dates, modified_dates.

RetainTagEntry
    One E.1-1 (or product-extra) attribute: tag, name, basic action, option action.

load_e1_1_retain_catalog() -> dict[str, tuple[RetainTagEntry, ...]]
    All catalog families from the committed JSON.

device_identity_tags() -> tuple[str, ...]
    Tags overlayed to @keep when Retain Device Identity is selected.

institution_identity_tags() -> tuple[str, ...]
    Tags overlayed to @keep when Retain Institution Identity is selected.

patient_characteristics_tags() -> tuple[str, ...]
    Tags overlayed to @keep when Retain Patient Characteristics is selected
    (PatientAge may still be skipped by compile).

patient_age_tag() -> str
    PatientAge tag (00101010); compile keeps @round under the characteristics option.

tags_in_script(tags, script_tags) -> tuple[str, ...]
    Preserve order; keep only tags present in script_tags.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RetainFamily = str

_CATALOG_PATH = Path(__file__).with_name("e1_1_retain_tags.json")

# Product still owns these under Retain Device Identity even though current
# PS3.15 Table E.1-1 no longer lists them (they appear in older editions /
# product UI copy as normally removed under Basic).
_PRODUCT_DEVICE_IDENTITY_EXTRAS: tuple[tuple[str, str, str, str], ...] = (
    ("00080070", "Manufacturer", "X/Z", "K"),
    ("00081090", "Manufacturer's Model Name", "X/Z", "K"),
    ("00181020", "Software Versions", "X/Z", "K"),
    ("00181016", "Secondary Capture Device Manufacturer", "X/Z", "K"),
    ("00181018", "Secondary Capture Device Manufacturer's Model Name", "X/Z", "K"),
    ("00181019", "Secondary Capture Device Software Versions", "X/Z", "K"),
)

_PATIENT_AGE_TAG = "00101010"


@dataclass(frozen=True)
class RetainTagEntry:
    """One retain-option attribute from E.1-1 or a product extra."""

    tag: str
    name: str
    basic: str
    option: str
    product_extra: bool = False


@lru_cache(maxsize=1)
def load_e1_1_retain_catalog() -> dict[str, tuple[RetainTagEntry, ...]]:
    """
    Load the committed Table E.1-1 retain-option catalog.

    Returns:
        Family name → immutable entries (device includes product extras).
    """
    raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    families: dict[str, tuple[RetainTagEntry, ...]] = {}
    for family, rows in (raw.get("families") or {}).items():
        entries = [
            RetainTagEntry(
                tag=str(row["tag"]).upper(),
                name=str(row.get("name") or ""),
                basic=str(row.get("basic") or ""),
                option=str(row.get("option") or ""),
            )
            for row in rows
        ]
        families[str(family)] = tuple(entries)

    device = list(families.get("device", ()))
    seen = {e.tag for e in device}
    for tag, name, basic, option in _PRODUCT_DEVICE_IDENTITY_EXTRAS:
        if tag not in seen:
            device.append(
                RetainTagEntry(
                    tag=tag,
                    name=name,
                    basic=basic,
                    option=option,
                    product_extra=True,
                )
            )
            seen.add(tag)
    families["device"] = tuple(device)
    return families


def _tags_for_family(family: RetainFamily) -> tuple[str, ...]:
    return tuple(e.tag for e in load_e1_1_retain_catalog().get(family, ()))


def device_identity_tags() -> tuple[str, ...]:
    """Device-identity tags for compile overlay (E.1-1 + product extras)."""
    return _tags_for_family("device")


def institution_identity_tags() -> tuple[str, ...]:
    """Institution-identity tags for compile overlay."""
    return _tags_for_family("institution")


def patient_characteristics_tags() -> tuple[str, ...]:
    """Patient-characteristics tags for compile overlay."""
    return _tags_for_family("patient_characteristics")


def patient_age_tag() -> str:
    """PatientAge tag kept as @round when characteristics option is on."""
    return _PATIENT_AGE_TAG


def tags_in_script(tags: Sequence[str], script_tags: Iterable[str]) -> tuple[str, ...]:
    """
    Filter tags to those present in a script, preserving order.

    Args:
        tags: Candidate tags.
        script_tags: Tags defined in the script document.

    Returns:
        Ordered subset present in script_tags.
    """
    present = {str(t).upper() for t in script_tags}
    return tuple(str(t).upper() for t in tags if str(t).upper() in present)


def basic_should_strip(entry: RetainTagEntry) -> bool:
    """
    True when Basic Profile should not leave the value as a plain keep.

    Args:
        entry: Catalog entry.

    Returns:
        True for typical X / Z / D family Basic actions (not U-only UID remap).
    """
    basic = entry.basic.upper().replace(" ", "")
    if entry.tag == _PATIENT_AGE_TAG:
        return False
    if not basic:
        return False
    # UID remap under Basic stays @uid in the script, not this strip helper.
    if basic == "U":
        return False
    return any(code in basic for code in ("X", "Z", "D"))
