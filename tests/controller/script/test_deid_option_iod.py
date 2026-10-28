"""Opt-in de-id option tests on synthetic SR / US / PDF IODs (marker deid_option_iod)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pydicom import dcmread

from anonymizer.controller.ai.embedded_phi.metadata.extract import apply_text_at_path
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.report.process_report_text import remove_phi
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import BASIC_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes
from tests.controller.dicom.support.test_nodes import LocalSCU
from tests.controller.script.support_iod_fixtures import (
    build_basic_text_sr,
    build_encapsulated_pdf_shell,
    build_secondary_capture_with_descriptions,
    build_ultrasound_shell,
)

pytestmark = pytest.mark.deid_option_iod


def _codes_on(ds) -> set[str]:
    seq = getattr(ds, "DeidentificationMethodCodeSequence", None)
    if not seq:
        return set()
    return {str(item.CodeValue) for item in seq}


@pytest.mark.parametrize(
    "builder",
    [build_ultrasound_shell, build_basic_text_sr, build_encapsulated_pdf_shell],
    ids=["us", "sr", "pdf"],
)
def test_device_identity_keeps_manufacturer_on_iod(
    controller: ProjectController, builder
) -> None:
    """Retain Device Identity keeps Manufacturer on non-CT shells."""
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.DEVICE_IDENTITY}
    )
    ds = builder(patient_id=f"IOD-DEV-{builder.__name__}")
    ds.Manufacturer = "ACME-IOD"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.Manufacturer == "ACME-IOD"


@pytest.mark.parametrize(
    "builder",
    [build_ultrasound_shell, build_basic_text_sr],
    ids=["us", "sr"],
)
def test_institution_and_sex_kept_on_iod(
    controller: ProjectController, builder
) -> None:
    """Institution + Patient Characteristics spot tags on US/SR."""
    controller.apply_confidentiality_options(
        BASIC_OPTIONS
        | {
            DeidMethodCode.INSTITUTION_IDENTITY,
            DeidMethodCode.PATIENT_CHARACTERISTICS,
        }
    )
    ds = builder(patient_id=f"IOD-INST-{builder.__name__}")
    ds.InstitutionName = "IOD Hospital"
    ds.PatientSex = "F"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert ds.InstitutionName == "IOD Hospital"
    assert ds.PatientSex == "F"


def test_clean_descriptors_blanks_descriptions_and_stamps(tmp_path: Path) -> None:
    """
    Controller-level Clean Descriptors: blank PHI in descriptions and stamp 113105.

    Mirrors metadata assessment save (apply_text_at_path + record_deid_method_codes)
    without the Tk dialog.
    """
    full = build_secondary_capture_with_descriptions(
        patient_id="DESC-CLEAN",
        study_description="CT CHEST Jane Doe MRN123",
        series_description="AXIAL Jane",
    )
    study_phi = "Jane Doe"
    assert study_phi in str(full.StudyDescription)
    start = str(full.StudyDescription).index(study_phi)
    cleaned_study = remove_phi(
        str(full.StudyDescription),
        [Entity(label="NAME", start=start, end=start + len(study_phi))],
        synthetic=False,
    )
    apply_text_at_path(full, "StudyDescription", cleaned_study)
    series_text = str(full.SeriesDescription)
    jane = "Jane"
    s0 = series_text.index(jane)
    cleaned_series = remove_phi(
        series_text,
        [Entity(label="NAME", start=s0, end=s0 + len(jane))],
        synthetic=False,
    )
    apply_text_at_path(full, "SeriesDescription", cleaned_series)
    record_deid_method_codes(full, {DeidMethodCode.CLEAN_DESCRIPTORS})

    path = tmp_path / "desc.dcm"
    full.save_as(str(path), enforce_file_format=True)
    on_disk = dcmread(str(path))
    assert "Jane" not in str(on_disk.StudyDescription)
    assert "Jane" not in str(on_disk.SeriesDescription)
    assert str(int(DeidMethodCode.CLEAN_DESCRIPTORS)) in _codes_on(on_disk)


def test_clean_structured_content_on_sr_series(tmp_path: Path) -> None:
    """SR series through report-text batch path stamps Clean Structured Content."""
    from anonymizer.controller.ai import batch_process

    series_dir = tmp_path / "1.2.3.sr.series"
    series_dir.mkdir()
    ds = build_basic_text_sr(
        patient_id="STRUCT-SR",
        finding_text="Patient John Doe seen for follow-up",
    )
    # Stable UIDs for batch layout
    ds.StudyInstanceUID = "1.2.3.study"
    ds.SeriesInstanceUID = "1.2.3.sr.series"
    ds.SOPInstanceUID = "1.2.3.instance"
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    src_path = series_dir / "instance.dcm"
    ds.save_as(str(src_path), enforce_file_format=True)

    from tests.controller.core.test_ai_batch_process import _pending_anon_model

    anon_model = _pending_anon_model()
    anon_model.get_study_phi_header_by_anon_study_uid.return_value = None

    text = "Patient John Doe seen for follow-up"
    with patch.object(
        batch_process,
        "detect_phi",
        return_value=(text, [Entity(label="NAME", start=8, end=16)]),
    ):
        outcome = batch_process._apply_report_text_phi_series(
            series_dir, anon_model=anon_model
        )
    assert outcome.status != "failed", outcome.message

    cleaned_src = dcmread(str(src_path))
    assert str(int(DeidMethodCode.CLEAN_STRUCTURED_CONTENT)) in _codes_on(cleaned_src)
    assert "John Doe" not in cleaned_src.ContentSequence[0].TextValue
