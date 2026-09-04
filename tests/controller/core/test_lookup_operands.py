"""Tests for @lookup operands and Lookup_Miss quarantine."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller.anonymizer import QuarantineDirectories
from anonymizer.controller.process_ctp_lookup import commit_ctp_lookup, preview_ctp_lookup
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU


def _write_properties(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def lookup_controller(controller, tmp_path):
    props = tmp_path / "trial.properties"
    _write_properties(
        props,
        [
            "ptid/12345=527408-000042",
            "dateoffset/12345=127",
        ],
    )
    preview = preview_ctp_lookup(props)
    commit_ctp_lookup(controller, preview)
    return controller


def test_lookup_hit_anonymizes_patient_id(lookup_controller) -> None:
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "12345"
    ds.StudyDate = "20200101"

    error = lookup_controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is None
    assert ds.PatientID == "527408-000042"
    assert ds.PatientName == "527408-000042"


def test_lookup_miss_quarantines(lookup_controller) -> None:
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "UNKNOWN"
    ds.StudyDate = "20200101"

    error = lookup_controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is not None

    quarantine_dir = lookup_controller.model.private_dir() / lookup_controller.model.QUARANTINE_DIR
    lookup_miss = quarantine_dir / QuarantineDirectories.LOOKUP_MISS.value
    assert lookup_miss.is_dir()
    assert any(lookup_miss.iterdir())
