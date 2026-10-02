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


def test_lookup_dateoffset_shifts_study_date(lookup_controller) -> None:
    """TCIA: @lookup(this,dateoffset) must apply the table offset, not hash."""
    from datetime import datetime, timedelta

    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "12345"
    ds.StudyDate = "20200101"
    if hasattr(ds, "AcquisitionDateTime"):
        ds.AcquisitionDateTime = "20200101123000.000000"

    error = lookup_controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is None

    expected = (datetime(2020, 1, 1) + timedelta(days=127)).strftime("%Y%m%d")
    assert ds.StudyDate == expected
    assert ds.LongitudinalTemporalInformationModified == "MODIFIED"
    if hasattr(ds, "AcquisitionDateTime"):
        assert str(ds.AcquisitionDateTime).startswith(expected)
    # Lookup offset alone must not invent REGISTRATION (basedate / @rebasedate only).
    assert not hasattr(ds, "LongitudinalTemporalEventType")
    codes = {str(item.CodeValue) for item in ds.DeidentificationMethodCodeSequence}
    assert "113107" in codes


def test_lookup_dateoffset_preserves_study_interval(lookup_controller) -> None:
    from datetime import datetime

    early = dcmread(get_testdata_file(ct_small_filename))
    early.PatientID = "12345"
    early.StudyDate = "20200101"
    early.StudyInstanceUID = "1.2.840.10008.lookup.interval.1"
    early.SeriesInstanceUID = "1.2.840.10008.lookup.interval.1.1"
    early.SOPInstanceUID = "1.2.840.10008.lookup.interval.1.1.1"

    late = dcmread(get_testdata_file(ct_small_filename))
    late.PatientID = "12345"
    late.StudyDate = "20200131"
    late.StudyInstanceUID = "1.2.840.10008.lookup.interval.2"
    late.SeriesInstanceUID = "1.2.840.10008.lookup.interval.2.1"
    late.SOPInstanceUID = "1.2.840.10008.lookup.interval.2.1.1"

    assert lookup_controller.anonymizer.anonymize(LocalSCU, early) is None
    assert lookup_controller.anonymizer.anonymize(LocalSCU, late) is None
    assert (
        datetime.strptime(str(late.StudyDate), "%Y%m%d")
        - datetime.strptime(str(early.StudyDate), "%Y%m%d")
    ).days == 30


def test_lookup_dateoffset_is_per_patient(controller, tmp_path: Path) -> None:
    from datetime import datetime, timedelta

    props = tmp_path / "multi.properties"
    _write_properties(
        props,
        [
            "ptid/PT-A=527408-000001",
            "ptid/PT-B=527408-000002",
            "dateoffset/PT-A=10",
            "dateoffset/PT-B=100",
        ],
    )
    commit_ctp_lookup(controller, preview_ctp_lookup(props))

    a = dcmread(get_testdata_file(ct_small_filename))
    a.PatientID = "PT-A"
    a.StudyDate = "20200101"
    a.StudyInstanceUID = "1.2.840.10008.lookup.pta.1"
    a.SeriesInstanceUID = "1.2.840.10008.lookup.pta.1.1"
    a.SOPInstanceUID = "1.2.840.10008.lookup.pta.1.1.1"

    b = dcmread(get_testdata_file(ct_small_filename))
    b.PatientID = "PT-B"
    b.StudyDate = "20200101"
    b.StudyInstanceUID = "1.2.840.10008.lookup.ptb.1"
    b.SeriesInstanceUID = "1.2.840.10008.lookup.ptb.1.1"
    b.SOPInstanceUID = "1.2.840.10008.lookup.ptb.1.1.1"

    assert controller.anonymizer.anonymize(LocalSCU, a) is None
    assert controller.anonymizer.anonymize(LocalSCU, b) is None
    assert a.StudyDate == (datetime(2020, 1, 1) + timedelta(days=10)).strftime("%Y%m%d")
    assert b.StudyDate == (datetime(2020, 1, 1) + timedelta(days=100)).strftime("%Y%m%d")
    assert a.StudyDate != b.StudyDate


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


def test_existing_phi_bypasses_lookup_requirement(controller, tmp_path: Path) -> None:
    """Patients already imported keep working without a lookup-table row."""
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "PREEXISTING"
    ds.StudyDate = "20200101"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7.8.9.10"

    error = controller.anonymizer.anonymize(LocalSCU, ds)
    assert error is None
    anon_ptid = ds.PatientID

    props = tmp_path / "other_patients.properties"
    _write_properties(
        props,
        [
            "ptid/OTHER=527408-000099",
            "dateoffset/OTHER=10",
        ],
    )
    commit_ctp_lookup(controller, preview_ctp_lookup(props))
    assert controller.anonymizer.model._lookup_required is True
    assert controller.anonymizer.model.get_lookup_patient("PREEXISTING") is None

    # New SOP for the same PHI PatientID must succeed without a lookup row.
    again = dcmread(get_testdata_file(ct_small_filename))
    again.PatientID = "PREEXISTING"
    again.StudyDate = "20200101"
    again.StudyInstanceUID = "1.2.840.10008.1.2.3.4.5.6.7.8"
    again.SeriesInstanceUID = "1.2.840.10008.1.2.3.4.5.6.7.9"
    again.SOPInstanceUID = "1.2.840.10008.1.2.3.4.5.6.7.10"
    error2 = controller.anonymizer.anonymize(LocalSCU, again)
    assert error2 is None
    assert again.PatientID == anon_ptid

    # A brand-new PatientID still quarantines when missing from the table.
    stranger = dcmread(get_testdata_file(ct_small_filename))
    stranger.PatientID = "BRANDNEW"
    stranger.StudyDate = "20200101"
    stranger.StudyInstanceUID = "1.2.840.10008.9.9.9.1"
    stranger.SeriesInstanceUID = "1.2.840.10008.9.9.9.2"
    stranger.SOPInstanceUID = "1.2.840.10008.9.9.9.3"
    error3 = controller.anonymizer.anonymize(LocalSCU, stranger)
    assert error3 is not None
    quarantine_dir = controller.model.private_dir() / controller.model.QUARANTINE_DIR
    lookup_miss = quarantine_dir / QuarantineDirectories.LOOKUP_MISS.value
    assert lookup_miss.is_dir()
    assert any(lookup_miss.iterdir())
