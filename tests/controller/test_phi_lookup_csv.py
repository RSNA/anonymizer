"""Tests for series-grain Patient Lookup CSV rows."""

from __future__ import annotations

from anonymizer.controller.phi_io import PHI_IndexRecord, PHI_SeriesIndexRecord


def _study_with_series() -> PHI_IndexRecord:
    return PHI_IndexRecord(
        anon_patient_id="SITE-000001",
        anon_patient_name="SITE-000001",
        phi_patient_name="Doe^Jane",
        phi_patient_id="P1",
        date_offset=3,
        phi_study_date="20200101",
        anon_accession="A1",
        phi_accession="ACC1",
        anon_study_uid="anon-study-1",
        phi_study_uid="phi-study-1",
        num_series=2,
        num_instances=15,
        harmonize=False,
        face_blurred="",
        pixel_phi_removed=False,
        pixel_phi="",
        series=[
            PHI_SeriesIndexRecord(
                anon_series_uid="ser-1",
                modality="CT",
                description="SCOUT",
                harmonized_description="",
                instance_count=2,
                face_blur_algorithm="",
                pixel_phi_removed=False,
                pixel_phi="",
            ),
            PHI_SeriesIndexRecord(
                anon_series_uid="ser-2",
                modality="CT",
                description="Ax",
                harmonized_description="CT Chest Ax PortVen",
                instance_count=13,
                face_blur_algorithm="gaussian",
                pixel_phi_removed=True,
                pixel_phi="Name",
            ),
        ],
    )


def test_iter_lookup_csv_rows_one_per_series() -> None:
    study = _study_with_series()
    rows = list(study.iter_lookup_csv_rows())
    assert len(rows) == 2
    assert len(rows[0]) == len(PHI_IndexRecord.LOOKUP_CSV_FIELD_TITLES)
    assert len(rows[1]) == len(PHI_IndexRecord.LOOKUP_CSV_FIELD_TITLES)

    titles = PHI_IndexRecord.LOOKUP_CSV_FIELD_TITLES
    by_name_0 = dict(zip(titles, rows[0], strict=True))
    by_name_1 = dict(zip(titles, rows[1], strict=True))

    assert by_name_0["ANON-StudyUID"] == by_name_1["ANON-StudyUID"] == "anon-study-1"
    assert by_name_0["PHI-PatientName"] == "Doe^Jane"
    assert by_name_0["Series"] == 2
    assert by_name_0["StudyInstances"] == 15
    assert "StudyHarmonized" not in by_name_0
    assert "HarmonizedDescription" not in by_name_0

    assert by_name_0["ANON-SeriesUID"] == "ser-1"
    assert by_name_0["SeriesDescription"] == "SCOUT"
    assert by_name_0["SeriesHarmonized"] == "No"
    assert by_name_0["Instances"] == 2

    assert by_name_1["ANON-SeriesUID"] == "ser-2"
    assert by_name_1["SeriesHarmonized"] == "Yes"
    assert by_name_1["Instances"] == 13
    assert by_name_1["FaceBlurred"] == "Gaussian"
    assert by_name_1["PixelPHIRemoved"] == "Yes"
    assert by_name_1["PixelPHI"] == "Name"


def test_iter_lookup_csv_rows_empty_series_emits_study_row() -> None:
    study = PHI_IndexRecord(
        anon_patient_id="SITE-000002",
        anon_patient_name="SITE-000002",
        phi_patient_name="",
        phi_patient_id="P2",
        date_offset=0,
        phi_study_date="20210101",
        anon_accession="A2",
        phi_accession="",
        anon_study_uid="anon-study-2",
        phi_study_uid="phi-study-2",
        num_series=0,
        num_instances=0,
        series=[],
    )
    rows = list(study.iter_lookup_csv_rows())
    assert len(rows) == 1
    by_name = dict(zip(PHI_IndexRecord.LOOKUP_CSV_FIELD_TITLES, rows[0], strict=True))
    assert by_name["ANON-StudyUID"] == "anon-study-2"
    assert by_name["ANON-SeriesUID"] == ""
    assert by_name["SeriesHarmonized"] == "No"
    assert by_name["PixelPHIRemoved"] == "No"


def test_lookup_csv_row_count() -> None:
    with_series = _study_with_series()
    empty = PHI_IndexRecord(
        anon_patient_id="x",
        anon_patient_name="x",
        phi_patient_name="",
        phi_patient_id="y",
        date_offset=0,
        phi_study_date="",
        anon_accession="",
        phi_accession="",
        anon_study_uid="s",
        phi_study_uid="p",
        series=[],
    )
    assert PHI_IndexRecord.lookup_csv_row_count([with_series, empty]) == 3


def test_lookup_csv_entity_counts() -> None:
    study_a = _study_with_series()
    study_b = PHI_IndexRecord(
        anon_patient_id="SITE-000001",
        anon_patient_name="SITE-000001",
        phi_patient_name="Doe^Jane",
        phi_patient_id="P1",
        date_offset=0,
        phi_study_date="20200202",
        anon_accession="A2",
        phi_accession="ACC2",
        anon_study_uid="anon-study-2",
        phi_study_uid="phi-study-2",
        num_series=0,
        num_instances=0,
        series=[],
    )
    study_c = PHI_IndexRecord(
        anon_patient_id="SITE-000002",
        anon_patient_name="SITE-000002",
        phi_patient_name="Roe^John",
        phi_patient_id="P2",
        date_offset=1,
        phi_study_date="20200303",
        anon_accession="A3",
        phi_accession="ACC3",
        anon_study_uid="anon-study-3",
        phi_study_uid="phi-study-3",
        num_series=1,
        num_instances=2,
        series=[
            PHI_SeriesIndexRecord(
                anon_series_uid="ser-3",
                modality="MR",
                description="Ax",
                harmonized_description="",
                instance_count=2,
                face_blur_algorithm="",
                pixel_phi_removed=False,
                pixel_phi="",
            ),
        ],
    )
    # 2 patients (SITE-000001 twice + SITE-000002), 3 studies, 2+0+1 = 3 series
    assert PHI_IndexRecord.lookup_csv_entity_counts([study_a, study_b, study_c]) == (2, 3, 3)
