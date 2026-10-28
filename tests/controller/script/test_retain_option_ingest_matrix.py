"""Retain-option ingest matrix: catalog ∩ script tags kept or stripped at anonymize."""

from __future__ import annotations

from pydicom import dcmread
from pydicom.data import get_testdata_file

import pytest

from anonymizer.controller.project import ProjectController
from anonymizer.controller.script.compile import compile_script, script_operations_by_tag
from anonymizer.controller.script.operands import is_remove_operation
from anonymizer.controller.script.retain_option_tags import patient_age_tag
from anonymizer.model.project import BASIC_OPTIONS, ProjectModel
from anonymizer.utils.dicom import DeidMethodCode
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU
from tests.controller.script.support_retain_matrix import (
    plant_strip_entries,
    strip_entries_for_family,
    tag_present,
    tag_value,
)

_DEFAULT = ProjectModel.default_anonymizer_script_path()
_AGE = patient_age_tag()

_FAMILY_OPTION: dict[str, DeidMethodCode] = {
    "device": DeidMethodCode.DEVICE_IDENTITY,
    "institution": DeidMethodCode.INSTITUTION_IDENTITY,
    "patient_characteristics": DeidMethodCode.PATIENT_CHARACTERISTICS,
}


def _base_ds(*, patient_id: str, sop_suffix: str):
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = patient_id
    ds.StudyDate = "20200115"
    ds.SOPInstanceUID = f"1.2.840.10008.retain.matrix.{sop_suffix}"
    return ds


@pytest.mark.parametrize("family", sorted(_FAMILY_OPTION))
def test_retain_family_keeps_planted_strip_tags(
    controller: ProjectController, family: str
) -> None:
    """
    One anonymize per family: all Basic-strip catalog∩script (non-SQ) tags kept
    when the retain option is on (PatientAge stays band-rounded).
    """
    entries = strip_entries_for_family(family)
    assert entries, f"no strip entries for {family}"
    option = _FAMILY_OPTION[family]
    controller.apply_confidentiality_options(BASIC_OPTIONS | {option})

    ds = _base_ds(patient_id=f"MATRIX-{family}", sop_suffix=family)
    planted = plant_strip_entries(ds, entries)
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    ops = script_operations_by_tag(compile_script(BASIC_OPTIONS | {option}, _DEFAULT))
    for tag, expected in planted.items():
        assert tag_present(ds, tag), f"{family} lost {tag} under {option.name}"
        got = tag_value(ds, tag)
        if tag == _AGE:
            assert str(got) == "045Y", f"PatientAge should round 043Y→045Y, got {got!r}"
            continue
        # @safe / @keep leave the value; empty operand normalized to keep.
        op = ops.get(tag, "@keep")
        assert not is_remove_operation(op), f"{tag} still remove under option: {op}"
        assert str(got) == str(expected), f"{family} {tag}: {got!r} != {expected!r}"


@pytest.mark.parametrize("family", sorted(_FAMILY_OPTION))
def test_basic_strips_planted_family_tags(controller: ProjectController, family: str) -> None:
    """Same planted tags are removed or emptied under Basic alone."""
    entries = strip_entries_for_family(family)
    controller.apply_confidentiality_options(BASIC_OPTIONS)

    ds = _base_ds(patient_id=f"BASIC-{family}", sop_suffix=f"basic-{family}")
    planted = plant_strip_entries(ds, entries)
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    ops = script_operations_by_tag(compile_script(BASIC_OPTIONS, _DEFAULT))
    for tag in planted:
        op = ops.get(tag, "@remove()")
        if is_remove_operation(op):
            assert not tag_present(ds, tag), f"Basic should remove {tag}"
        elif str(op).startswith("@empty"):
            assert tag_present(ds, tag)
            val = tag_value(ds, tag)
            assert val in ("", None) or (isinstance(val, str) and not val.strip())
        elif str(op).startswith("@round"):
            # PatientAge under Basic still rounds rather than remove.
            assert tag_present(ds, tag)
        else:
            # Other strip-class operands (hashdate etc.) — tag may transform.
            assert tag in ops


def test_full_dates_keeps_planted_study_and_series_date(
    controller: ProjectController,
) -> None:
    """Full Dates: StudyDate and SeriesDate retained (not shifted)."""
    controller.apply_confidentiality_options(BASIC_OPTIONS | {DeidMethodCode.FULL_DATES})
    ds = _base_ds(patient_id="FULL-DATES-MATRIX", sop_suffix="fulldates")
    ds.StudyDate = "20200115"
    ds.SeriesDate = "20200116"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.StudyDate == "20200115"
    assert ds.SeriesDate == "20200116"


def test_retain_uids_keeps_study_and_series_uid(controller: ProjectController) -> None:
    """Retain UIDs: Study/Series Instance UIDs unchanged."""
    controller.apply_confidentiality_options(BASIC_OPTIONS | {DeidMethodCode.RETAIN_UIDS})
    ds = _base_ds(patient_id="UID-MATRIX", sop_suffix="uids")
    study = "1.2.840.10008.1.2.3.retain.matrix.study"
    series = "1.2.840.10008.1.2.3.retain.matrix.series"
    ds.StudyInstanceUID = study
    ds.SeriesInstanceUID = series
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.StudyInstanceUID == study
    assert ds.SeriesInstanceUID == series
