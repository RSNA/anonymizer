"""Unit tests for ProjectionView title formatting."""

from __future__ import annotations

from anonymizer.controller.phi.phi_io import PHI_IndexRecord
from anonymizer.view.series.projection import format_projection_view_title


def _study(
    uid: str,
    description: str = "Chest CT",
    *,
    patient: str = "anon-1",
) -> PHI_IndexRecord:
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
        harmonized_description=description,
        num_series=2,
        num_instances=10,
    )


def test_single_study_title_uses_description_and_anon_patient_id() -> None:
    title = format_projection_view_title(
        [_study("s1", "Chest CT", patient="994250-000005")],
        total_series=3,
        pages=1,
    )
    assert title.startswith("View Chest CT 994250-000005 with 3 Series")
    assert "ANON ID:" not in title


def test_single_study_title_includes_anon_id_when_description_empty() -> None:
    title = format_projection_view_title(
        [_study("s1", "", patient="994250-000006")],
        total_series=1,
        pages=1,
    )
    assert title.startswith("View (no description) 994250-000006 with 1 Series")
    assert "ANON ID:" not in title


def test_multi_study_title_uses_study_count() -> None:
    records = [_study("s1"), _study("s2", "Abdomen", patient="anon-2")]
    title = format_projection_view_title(records, total_series=5, pages=2)
    assert title.startswith("View 2 Studies with 5 Series")
    assert title.endswith("over 2 Pages")
