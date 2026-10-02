"""Non-GPU harmonize pipeline: real description mappings + similar-study peers."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.harmonize.pipeline import (
    auto_apply_best_study_descriptions,
    find_similar_series_uids,
    find_similar_study_uids,
)
from anonymizer.model.anonymizer import AnonymizerModel
from tests.opened_anonymizer_model import opened_anonymizer_model

TEST_DB_DIR = Path(__file__).parent / ".test_db"
TEST_DB_FILE = TEST_DB_DIR / "harmonize_mapping_pipeline.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"


@pytest.fixture
def anon_model():
    if TEST_DB_FILE.exists():
        TEST_DB_FILE.unlink()
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
    with opened_anonymizer_model(TEST_DB_URL) as model:
        yield model


def _write_minimal_dcm(path: Path, *, study_description: str = "OLD") -> None:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "CR"
    ds.StudyDescription = study_description
    ds.SeriesDescription = "Chest AP"
    ds.Rows = 2
    ds.Columns = 2
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(2 * 2 * 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True, little_endian=True, implicit_vr=False)


def _capture_study(model: AnonymizerModel, *, study_uid: str, series_uid: str, sop: str, desc: str) -> str:
    """Capture PHI and return the anonymized study UID."""
    ds = Dataset()
    ds.PatientID = "P-MAP-1"
    ds.PatientName = "Map^Test"
    ds.PatientSex = "M"
    ds.PatientBirthDate = "19800101"
    ds.StudyInstanceUID = study_uid
    ds.AccessionNumber = "ACC-MAP"
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop
    ds.Modality = "CR"
    ds.StudyDescription = desc
    ds.SeriesDescription = "Chest AP"
    ds.StudyDate = "20230101"
    model.capture_phi(source="pytest", ds=ds, date_offset_from_hash=0)
    for phi in model.load_phi_with_studies_series_no_instances():
        for study in phi.studies or []:
            if getattr(study, "study_uid", None) == study_uid:
                return study.anon_study_uid
    raise AssertionError(f"anon study uid not found for {study_uid}")


def test_auto_apply_prefers_stored_study_mapping(anon_model: AnonymizerModel, tmp_path: Path) -> None:
    study_uid = "1.2.3.study.map.1"
    anon_study_uid = _capture_study(
        anon_model,
        study_uid=study_uid,
        series_uid="1.2.3.series.map.1",
        sop="1.2.3.sop.map.1",
        desc="Chest XR Original",
    )
    assert anon_model.upsert_description_mapping(
        kind="study",
        original="Chest XR Original",
        harmonized="XR Chest AP",
        modality="XR",
        loinc="36572-6",
    )
    patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
    assert patient_id
    study_root = tmp_path / "images" / patient_id / anon_study_uid
    _write_minimal_dcm(study_root / "series-a" / "1.dcm", study_description="Chest XR Original")

    results = auto_apply_best_study_descriptions(
        images_dir=tmp_path / "images",
        anon_model=anon_model,
        anon_study_uids=(anon_study_uid,),
        prefer_description_mappings=True,
    )
    hit = anon_model.lookup_description_mapping(
        kind="study",
        original="Chest XR Original",
        modality="XR",
    )
    assert hit is not None
    assert hit.harmonized_description == "XR Chest AP"
    assert hit.loinc == "36572-6"
    assert isinstance(results, list)
    assert results, "expected mapping prefer-path to apply"
    assert anon_model.get_study_harmonized_description(anon_study_uid) == "XR Chest AP"


def test_apply_study_offer_records_loinc_rank_origin(
    anon_model: AnonymizerModel, tmp_path: Path
) -> None:
    """LOINC auto-apply stores Origin=LOINC rank for non-blank study originals."""
    from anonymizer.controller.ai.harmonize.loinc_study import LoincStudyMatch, StudyDescriptionOffer
    from anonymizer.controller.ai.harmonize.mapping_origin import DESCRIPTION_MAPPING_ORIGIN_LOINC_RANK
    from anonymizer.controller.ai.harmonize.pipeline import apply_study_description_offer

    anon_study_uid = _capture_study(
        anon_model,
        study_uid="1.2.3.study.offer.1",
        series_uid="1.2.3.series.offer.1",
        sop="1.2.3.sop.offer.1",
        desc="TC ANGIOTOMO CEREBRAL",
    )
    patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
    assert patient_id
    study_root = tmp_path / "images" / patient_id / anon_study_uid
    _write_minimal_dcm(study_root / "series-a" / "1.dcm", study_description="TC ANGIOTOMO CEREBRAL")

    offer = StudyDescriptionOffer(
        anon_study_uid=anon_study_uid,
        fingerprint=(),
        matches=(
            LoincStudyMatch(
                loinc_number="24725-4",
                long_common_name="CT Brain WO and W contrast IV",
                score=0.9,
            ),
        ),
        peer_study_uids=(),
        ambiguous=False,
    )
    updated = apply_study_description_offer(
        images_dir=tmp_path / "images",
        anon_model=anon_model,
        offer=offer,
        description="CT Brain WO and W contrast IV",
        apply_to_peers=False,
        loinc_number="24725-4",
    )
    assert updated == [anon_study_uid]
    rows = anon_model.list_description_mappings(kind="study")
    assert len(rows) == 1
    assert rows[0].origin == DESCRIPTION_MAPPING_ORIGIN_LOINC_RANK
    assert rows[0].original_display == "TC ANGIOTOMO CEREBRAL"
    assert rows[0].harmonized_description == "CT Brain WO and W contrast IV"
    assert rows[0].loinc == "24725-4"


def test_find_similar_study_uids_from_candidates(anon_model: AnonymizerModel) -> None:
    _capture_study(
        anon_model,
        study_uid="1.2.3.study.a",
        series_uid="1.2.3.series.a",
        sop="1.2.3.sop.a",
        desc="XR Chest AP",
    )
    _capture_study(
        anon_model,
        study_uid="1.2.3.study.b",
        series_uid="1.2.3.series.b",
        sop="1.2.3.sop.b",
        desc="XR Chest AP",
    )
    peers = find_similar_study_uids(
        anon_model,
        "1.2.3.study.a",
        candidates=[
            ("1.2.3.study.a", "XR Chest AP", "XR "),
            ("1.2.3.study.b", "XR Chest AP", "XR "),
            ("1.2.3.study.c", "XR Chest PA", "XR "),
        ],
    )
    assert peers == ["1.2.3.study.b"]


def test_find_similar_series_uids_cohort() -> None:
    peers = find_similar_series_uids(
        [
            ("s1", "CR", "Chest AP"),
            ("s2", "DX", "Chest AP"),
            ("s3", "CR", "Chest PA"),
            ("s4", "US", "Chest AP"),
        ],
        seed_uid="s1",
        seed_modality="CR",
        seed_description="Chest AP",
    )
    assert peers == ["s2"]
