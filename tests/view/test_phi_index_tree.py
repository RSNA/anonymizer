"""Unit tests for nested PHI Index tree helpers."""

from __future__ import annotations

from pathlib import Path

from anonymizer.controller.phi_io import PHI_IndexRecord, PHI_SeriesIndexRecord
from anonymizer.view.project.dataset import (
    parse_series_tree_iid,
    parse_study_tree_iid,
    resolve_selected_study_records,
    series_path_for_record,
    series_tree_iid,
    study_tree_iid,
)


def _study(uid: str, *, patient: str = "anon-1", description: str = "") -> PHI_IndexRecord:
    return PHI_IndexRecord(
        anon_patient_id=patient,
        anon_patient_name=patient,
        phi_patient_name="Doe^Jane",
        phi_patient_id="P1",
        date_offset=0,
        phi_study_date="20200101",
        anon_accession="A1",
        phi_accession="ACC1",
        anon_study_uid=uid,
        phi_study_uid=f"phi-{uid}",
        study_description=description,
        num_series=1,
        num_instances=10,
    )


def _series(uid: str, modality: str = "CT") -> PHI_SeriesIndexRecord:
    return PHI_SeriesIndexRecord(
        anon_series_uid=uid,
        modality=modality,
        description="Ax",
        harmonized_description="",
        instance_count=5,
        face_blur_algorithm="",
        pixel_phi_removed=False,
        pixel_phi="",
    )


def test_study_and_series_tree_iid_roundtrip() -> None:
    assert study_tree_iid("1.2.3") == "study:1.2.3"
    assert parse_study_tree_iid("study:1.2.3") == "1.2.3"
    assert parse_study_tree_iid("series:1.2.3") is None
    assert series_tree_iid("9.9") == "series:9.9"
    assert parse_series_tree_iid("series:9.9") == "9.9"
    assert parse_series_tree_iid("study:9.9") is None


def test_resolve_selected_study_records_dedupes_mixed_selection() -> None:
    study_a = _study("study-a")
    study_b = _study("study-b", patient="anon-2")
    studies_by_uid = {"study-a": study_a, "study-b": study_b}
    series_parent = {"ser-a1": "study-a", "ser-a2": "study-a", "ser-b1": "study-b"}

    selected = [
        study_tree_iid("study-a"),
        series_tree_iid("ser-a1"),
        series_tree_iid("ser-a2"),
        series_tree_iid("ser-b1"),
    ]
    resolved = resolve_selected_study_records(selected, studies_by_uid, series_parent)
    assert [r.anon_study_uid for r in resolved] == ["study-a", "study-b"]


def test_series_path_for_record() -> None:
    study = _study("stu")
    series = _series("ser")
    path = series_path_for_record(Path("/images"), study, series)
    assert path == Path("/images/anon-1/stu/ser")


def test_tree_label_is_description_only() -> None:
    study = _study("stu", description="Chest CT")
    assert study.tree_label() == "Chest CT"
    assert _study("stu2", description="").tree_label() == "(no description)"
    series = _series("ser")
    assert series.tree_label() == "Ax"
    series.harmonized_description = "CT Chest Ax"
    assert series.tree_label() == "CT Chest Ax"


def test_series_tree_values_align_with_study_display_columns() -> None:
    study = _study("stu")
    study.face_blurred = "Gaussian"
    study.pixel_phi_removed = True
    study.series = [_series("ser-ct", "CT"), _series("ser-mr", "MR"), _series("ser-ct2", "CT")]
    series = study.series[1]
    series.harmonized_description = "MR Brain"
    series.face_blur_algorithm = "gaussian"
    series.pixel_phi_removed = True
    series.pixel_phi = "DOE, MRN"

    study_vals = study.tree_values()
    series_vals = study.series_tree_values(series)
    fields = PHI_IndexRecord.get_tree_display_fields()
    assert len(study_vals) == len(series_vals) == len(fields)
    assert "anon_study_uid" not in fields
    assert PHI_IndexRecord.get_tree_display_titles()[fields.index("modality")] == "Modality"

    study_by_name = dict(zip(fields, study_vals, strict=True))
    assert study_by_name["modality"] == "CT, MR"
    assert study_by_name["phi_patient_id"] == "P1"
    assert study_by_name["num_instances"] == 10
    assert study_by_name["harmonize"] == "No"
    assert study_by_name["face_blurred"] == "Yes"
    assert study_by_name["pixel_phi_removed"] == "Yes"

    series_by_name = dict(zip(fields, series_vals, strict=True))
    assert series_by_name["modality"] == "MR"
    assert series_by_name["num_instances"] == 5
    assert series_by_name["harmonize"] == "Yes"
    assert series_by_name["face_blurred"] == "Gaussian"
    assert series_by_name["pixel_phi_removed"] == "DOE, MRN"
    assert series_by_name["phi_patient_id"] == ""
    assert series_by_name["anon_patient_id"] == ""