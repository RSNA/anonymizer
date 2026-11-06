"""Clean Descriptors batch helper (Embedded PHI Metadata path)."""

import logging
from pathlib import Path
from unittest.mock import patch

from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.scrub import (
    scrub_dataset_descriptors,
    scrub_file_descriptors,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    apply_project_uids_to_sr,
    build_basic_text_sr,
)
from anonymizer.utils.dicom import DeidMethodCode


def test_scrub_dataset_descriptors_blanks_phi_and_stamps_clean_descriptors() -> None:
    ds = Dataset()
    ds.StudyDescription = "Follow-up John Smith CT"
    ds.SeriesDescription = "AX T1"
    ds.Modality = "CT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        if "John Smith" not in text:
            return []
        idx = text.index("John Smith")
        return [Entity(label="FIRST_NAME", start=idx, end=idx + 10)]

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("John" in r and "Smith" in r for r in removed) or "John Smith" in removed
    assert "John Smith" not in str(ds.StudyDescription)
    codes = {
        int(getattr(item, "CodeValue", 0) or 0)
        for item in ds.get("DeidentificationMethodCodeSequence", [])
    }
    assert DeidMethodCode.CLEAN_DESCRIPTORS in codes


def test_scrub_dataset_descriptors_noop_when_no_phi() -> None:
    ds = Dataset()
    ds.StudyDescription = "ROUTINE CHEST"
    ds.Modality = "CT"

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is False
    assert removed == []
    assert "DeidentificationMethodCodeSequence" not in ds


def test_scrub_blanks_compact_date_ner_missed() -> None:
    """Detect merges pattern DATE; one remove blanks YYYYMMDD OpenMed skipped."""
    ds = Dataset()
    ds.SeriesDescription = "PET-CT SERIES 20101203"
    ds.Modality = "PT"

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert "20101203" in removed
    assert "20101203" not in str(ds.SeriesDescription)
    assert "PET-CT SERIES" in str(ds.SeriesDescription)
    codes = {
        int(getattr(item, "CodeValue", 0) or 0)
        for item in ds.get("DeidentificationMethodCodeSequence", [])
    }
    assert DeidMethodCode.CLEAN_DESCRIPTORS in codes


def test_scrub_skips_safe_device_serial() -> None:
    """@safe() Device Serial is not NER'd or blanked even if model would hit."""
    ds = Dataset()
    ds.DeviceSerialNumber = "G4EGU8PGUYWPI"
    ds.StudyDescription = "Follow-up John Smith CT"
    ds.Modality = "MR"

    seen: list[str] = []

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        seen.append(text)
        out: list[Entity] = []
        for needle, label in (("John Smith", "FIRST_NAME"), ("G4EGU8PGUYWPI", "ID")):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label=label, start=i, end=i + len(needle)))
        return out

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(
            ds,
            replace_mode="blank",
            script_operations={"00181000": "@safe()", "00081030": "@keep"},
        )

    assert changed is True
    assert seen, "OpenMed should run on non-@safe Content"
    assert all("G4EGU8PGUYWPI" not in blob for blob in seen)
    assert "John Smith" in removed or any("John" in r for r in removed)
    assert "John Smith" not in str(ds.StudyDescription)
    assert str(ds.DeviceSerialNumber) == "G4EGU8PGUYWPI"
    assert "G4EGU8PGUYWPI" not in removed


def test_scrub_preserves_anonymized_patient_id_and_name() -> None:
    """Clean Descriptors must not blank Patient ID / Patient Name set at ingest."""
    ds = Dataset()
    ds.PatientID = "990001-000001"
    ds.PatientName = "990001-000001"
    ds.StudyDescription = "Follow-up John Smith CT"
    ds.Modality = "CT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        for needle, label in (("990001-000001", "ID"), ("John Smith", "FIRST_NAME")):
            if needle in text:
                i = text.index(needle)
                out.append(Entity(label=label, start=i, end=i + len(needle)))
        return out

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert str(ds.PatientID) == "990001-000001"
    assert str(ds.PatientName) == "990001-000001"
    assert "990001-000001" not in removed
    assert changed is True
    assert "John Smith" not in str(ds.StudyDescription)


def test_scrub_blanks_date_like_series_number_keeps_frame_duration() -> None:
    """YYYYMMDD Series Number is DATE-filled; Actual Frame Duration 360000 is kept."""
    ds = Dataset()
    ds.SeriesNumber = "20101203"
    ds.ActualFrameDuration = "360000"
    ds.Modality = "PT"

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        return_value=[],
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert "20101203" in removed
    assert "20101203" not in str(ds.SeriesNumber)
    assert str(ds.ActualFrameDuration) == "360000"
    assert changed is True


def test_scrub_writes_cleaned_text_to_every_tag_with_same_content() -> None:
    """ID tagged once for shared Content must blank every tag that holds it."""
    shared = "Ordered for 8371727310 by DH"
    ds = Dataset()
    ds.RequestedProcedureDescription = shared
    ds.StudyComments = shared
    ds.Modality = "PT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        needle = "8371727310"
        if needle not in text:
            return []
        i = text.index(needle)
        return [Entity(label="ID", start=i, end=i + len(needle), raw_label="credit_debit_card")]

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("8371727310" in r for r in removed)
    assert "8371727310" not in str(ds.RequestedProcedureDescription)
    assert "8371727310" not in str(ds.StudyComments)


def test_scrub_logs_numbered_clean_descriptors_steps(caplog) -> None:
    """Clean Descriptors 1/7…7/7 logging with tagged + after remove."""
    ds = Dataset()
    ds.ReferringPhysicianName = "LOPEZ^JOANN"
    ds.StudyDescription = "PET for 626-44-1936"
    ds.Modality = "PT"

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        out: list[Entity] = []
        if "LOPEZ" in text:
            i = text.index("LOPEZ")
            out.append(Entity(label="LAST_NAME", start=i, end=i + 5))
        if "JOANN" in text:
            i = text.index("JOANN")
            out.append(Entity(label="FIRST_NAME", start=i, end=i + 5))
        if "626441936" in text:
            i = text.index("626441936")
            out.append(Entity(label="ID", start=i, end=i + 9))
        return out

    with (
        patch(
            "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
            side_effect=_fake_detect,
        ),
        caplog.at_level(logging.INFO),
    ):
        changed, removed = scrub_dataset_descriptors(ds, replace_mode="blank")

    assert changed is True
    assert any("LOPEZ" in r for r in removed) and any("JOANN" in r for r in removed)
    # PN caret blanked away (not left as lone ^).
    assert "^" not in str(ds.ReferringPhysicianName)
    blob = "\n".join(r.message for r in caplog.records)
    assert "Clean Descriptors step 1/7" in blob
    assert "Clean Descriptors step 2/7" in blob
    assert "Clean Descriptors step 3/7" in blob
    assert "Clean Descriptors step 4/7" in blob
    assert "Clean Descriptors step 5/7" in blob
    assert "Clean Descriptors step 6/7" in blob
    assert "Clean Descriptors step 7/7" in blob
    assert "<LAST_NAME>LOPEZ</LAST_NAME>" in blob
    assert "after remove" in blob
    assert "report: remove start" not in blob
    assert "ner: replace result" not in blob


def test_apply_project_uids_to_sr_uses_allocate_uid() -> None:
    source = Dataset()
    source.PatientID = "990001-000001"
    source.StudyInstanceUID = "1.2.3.study"
    sr = build_basic_text_sr(source, ["line one"])
    before_series = str(sr.SeriesInstanceUID)
    before_sop = str(sr.SOPInstanceUID)

    allocated: dict[str, str] = {}

    def allocate(key: str) -> str:
        uid = f"1.2.826.0.1.3680043.10.474.2.990001.2.{abs(hash(key)) % 10**18}"
        allocated[key] = uid
        return uid

    apply_project_uids_to_sr(sr, allocate_uid=allocate, source_key="src-sop-1")
    assert str(sr.SeriesInstanceUID) != before_series
    assert str(sr.SOPInstanceUID) != before_sop
    assert str(sr.file_meta.MediaStorageSOPInstanceUID) == str(sr.SOPInstanceUID)
    assert any(k.startswith("ai-report-series:") for k in allocated)
    assert any(k.startswith("ai-report-sop:") for k in allocated)


def _write_instance(path: Path, *, modality: str, description: str, sop_class: str) -> None:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = sop_class
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = modality
    ds.StudyDescription = description
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True)


def _axilla_ner(text: str, *, locale: str = "en_US") -> list[Entity]:
    del locale
    if "AXILLA" not in text:
        return []
    start = text.index("AXILLA")
    return [Entity(label="LOCATION", start=start, end=start + len("AXILLA"))]


def test_batch_report_metadata_keeps_study_whitelist_term(tmp_path: Path) -> None:
    """AI batch Clean Descriptors on a one-file report keeps the parent study term."""
    project = tmp_path / "project"
    (project / "whitelists").mkdir(parents=True)
    (project / "whitelists" / "us.txt").write_text("AXILLA\n", encoding="utf-8")
    study = tmp_path / "study"
    report = study / "sr" / "report.dcm"
    _write_instance(
        report,
        modality="SR",
        description="Clinic AXILLA",
        sop_class="1.2.840.10008.5.1.4.1.1.88.11",
    )
    _write_instance(
        study / "us" / "image.dcm",
        modality="US",
        description="Breast",
        sop_class="1.2.840.10008.5.1.4.1.1.6.1",
    )
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_axilla_ner,
    ):
        changed, removed = scrub_file_descriptors(report, project_dir=project)
    assert changed is False
    assert removed == []
    assert dcmread(report).StudyDescription == "Clinic AXILLA"


def test_batch_imaging_metadata_uses_own_modality_whitelist(tmp_path: Path) -> None:
    """AI batch Clean Descriptors on an imaging file does not take a sibling list."""
    project = tmp_path / "project"
    (project / "whitelists").mkdir(parents=True)
    (project / "whitelists" / "us.txt").write_text("AXILLA\n", encoding="utf-8")
    (project / "whitelists" / "ct.txt").write_text("AXIAL\n", encoding="utf-8")
    study = tmp_path / "study"
    ct = study / "ct" / "image.dcm"
    _write_instance(
        ct,
        modality="CT",
        description="Clinic AXILLA",
        sop_class="1.2.840.10008.5.1.4.1.1.2",
    )
    _write_instance(
        study / "us" / "image.dcm",
        modality="US",
        description="Breast",
        sop_class="1.2.840.10008.5.1.4.1.1.6.1",
    )
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_axilla_ner,
    ):
        changed, removed = scrub_file_descriptors(ct, project_dir=project)
    assert changed is True
    assert "AXILLA" in removed
    assert "AXILLA" not in str(dcmread(ct).StudyDescription)
