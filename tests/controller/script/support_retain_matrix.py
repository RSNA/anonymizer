"""Helpers for retain-option ingest matrix tests (catalog ∩ script)."""

from __future__ import annotations

from pydicom.dataset import Dataset
from pydicom.datadict import dictionary_VR
from pydicom.tag import Tag

from anonymizer.controller.script.document import load_script_rules
from anonymizer.controller.script.retain_option_tags import (
    RetainTagEntry,
    basic_should_strip,
    load_e1_1_retain_catalog,
    patient_age_tag,
    tags_in_script,
)
from anonymizer.model.project import ProjectModel


def script_tag_set() -> set[str]:
    """Uppercase tags defined in the packaged default anonymizer script."""
    path = ProjectModel.default_anonymizer_script_path()
    return {r.tag.upper() for r in load_script_rules(path).rules}


def strip_entries_for_family(family: str) -> list[RetainTagEntry]:
    """
    Catalog entries for family that are in the script and Basic should strip.

    Skips sequence VRs (SQ): planting empty sequences is not required for the
    matrix; overlays still cover them at compile time.
    """
    catalog = load_e1_1_retain_catalog().get(family, ())
    present = script_tag_set()
    in_script = set(tags_in_script([e.tag for e in catalog], present))
    out: list[RetainTagEntry] = []
    for entry in catalog:
        if entry.tag not in in_script or not basic_should_strip(entry):
            continue
        try:
            vr = dictionary_VR(Tag(int(entry.tag, 16)))
        except Exception:
            continue
        if str(vr).upper() == "SQ":
            continue
        out.append(entry)
    return out


def plant_value_for_vr(vr: str, *, tag: str) -> object:
    """
    Minimal plant value accepted by pydicom for vr.

    Args:
        vr: DICOM VR.
        tag: Eight-hex tag (for stable UID suffixes).

    Returns:
        A value suitable for Dataset.add_new.
    """
    vr_u = str(vr or "LO").upper()
    if vr_u == "DA":
        return "20200115"
    if vr_u == "TM":
        return "120000.000"
    if vr_u == "DT":
        return "20200115120000"
    if vr_u == "UI":
        return f"1.2.840.10008.matrix.{tag.lower()}"
    if vr_u == "PN":
        return "PLANTED^VALUE"
    if vr_u == "CS":
        return "PLANTED"
    if vr_u in {"IS", "SL", "SS", "US", "UL"}:
        return "42" if vr_u == "IS" else 42
    if vr_u in {"DS", "FL", "FD"}:
        return "1.5"
    if tag == patient_age_tag():
        return "043Y"
    return f"P{tag[-4:]}"


def plant_strip_entries(ds: Dataset, entries: list[RetainTagEntry]) -> dict[str, object]:
    """
    Plant values for strip entries on ds.

    Args:
        ds: Dataset to mutate.
        entries: Catalog entries to plant.

    Returns:
        tag → planted value for assertions.
    """
    planted: dict[str, object] = {}
    for entry in entries:
        tag_int = int(entry.tag, 16)
        vr = str(dictionary_VR(Tag(tag_int))).upper()
        value = plant_value_for_vr(vr, tag=entry.tag)
        if entry.tag == patient_age_tag():
            value = "043Y"
        ds.add_new(tag_int, vr, value)
        planted[entry.tag] = value
    return planted


def tag_present(ds: Dataset, tag: str) -> bool:
    """True when tag exists on ds."""
    return Tag(int(tag, 16)) in ds


def tag_value(ds: Dataset, tag: str) -> object | None:
    """Raw element value or None when absent."""
    t = Tag(int(tag, 16))
    if t not in ds:
        return None
    return ds[t].value
