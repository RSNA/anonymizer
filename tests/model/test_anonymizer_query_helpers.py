"""Unit tests for AnonymizerModel study/series query helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydicom import Dataset
from pydicom.uid import generate_uid

from anonymizer.model.anonymizer import AnonymizerModel
from tests.opened_anonymizer_model import opened_anonymizer_model

_DB = Path(__file__).parent / ".test_db" / "anonymizer_query_helpers.db"


@pytest.fixture
def model():
    _DB.parent.mkdir(parents=True, exist_ok=True)
    if _DB.exists():
        _DB.unlink()
    with opened_anonymizer_model(f"sqlite:///{_DB}") as m:
        yield m


def _ct_ds(*, patient: str = "P1", study: str | None = None, series: str | None = None) -> Dataset:
    ds = Dataset()
    ds.PatientID = patient
    ds.PatientName = "Doe^Jane"
    ds.PatientSex = "F"
    ds.PatientBirthDate = "19900101"
    ds.StudyInstanceUID = study or generate_uid()
    ds.SeriesInstanceUID = series or generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.StudyDescription = "CT Study"
    ds.SeriesDescription = "CT Series"
    ds.AccessionNumber = "A1"
    return ds


def _cr_ds(*, patient: str = "P1", study: str, series: str | None = None) -> Dataset:
    ds = _ct_ds(patient=patient, study=study, series=series)
    ds.Modality = "CR"
    ds.SeriesDescription = "Chest AP"
    return ds


def test_embedded_phi_uid_sets(model: AnonymizerModel) -> None:
    ds = _ct_ds()
    model.capture_phi(source="pytest", ds=ds, date_delta=0)
    phi = model.get_phi_by_phi_patient_id(ds.PatientID)
    assert phi is not None
    study = phi.studies[0]
    series = study.series[0]
    instance = series.instances[0]

    assert model.study_uids_with_embedded_phi() == set()
    assert model.anon_series_uids_with_embedded_phi() == set()

    assert model.set_instance_embedded_phi(instance.anon_sop_instance_uid, ["Name"]) is True
    assert study.study_uid in model.study_uids_with_embedded_phi()
    assert series.anon_series_uid in model.anon_series_uids_with_embedded_phi()


def test_study_all_series_harmonized_and_fingerprint(model: AnonymizerModel) -> None:
    ds = _ct_ds()
    model.capture_phi(source="pytest", ds=ds, date_delta=0)
    phi = model.get_phi_by_phi_patient_id(ds.PatientID)
    assert phi is not None
    study = phi.studies[0]
    series = study.series[0]
    anon_study = study.anon_study_uid

    assert model.study_all_series_harmonized(anon_study) is False
    assert model.find_studies_with_series_fingerprint(("CT Head",)) == []

    assert model.set_series_harmonized_description(series.anon_series_uid, "CT Head") is True
    assert model.study_all_series_harmonized(anon_study) is True
    assert model.find_studies_with_series_fingerprint(("CT Head",)) == [anon_study]


def test_compatible_descriptions_and_2d_helpers(model: AnonymizerModel) -> None:
    study_uid = generate_uid()
    ct = _ct_ds(study=study_uid)
    model.capture_phi(source="pytest", ds=ct, date_delta=0)
    cr = _cr_ds(study=study_uid)
    model.capture_phi(source="pytest", ds=cr, date_delta=0)

    phi = model.get_phi_by_phi_patient_id(ct.PatientID)
    assert phi is not None
    study = phi.studies[0]
    anon_study = study.anon_study_uid
    ct_series = next(s for s in study.series if (s.modality or "").upper() == "CT")
    cr_series = next(s for s in study.series if (s.modality or "").upper() == "CR")

    model.set_series_harmonized_description(ct_series.anon_series_uid, "CT Chest")
    model.set_series_harmonized_description(cr_series.anon_series_uid, "XR Chest AP")

    compat_ct = model.get_compatible_series_harmonized_descriptions(
        anon_study,
        modality="CT",
        exclude_anon_series_uid=ct_series.anon_series_uid,
    )
    assert compat_ct == []  # only one CT series

    # Add another CT series with a description
    ct2 = deepcopy(ct)
    ct2.SeriesInstanceUID = generate_uid()
    ct2.SOPInstanceUID = generate_uid()
    model.capture_phi(source="pytest", ds=ct2, date_delta=0)
    phi = model.get_phi_by_phi_patient_id(ct.PatientID)
    assert phi is not None
    study = phi.studies[0]
    other_ct = next(
        s
        for s in study.series
        if (s.modality or "").upper() == "CT" and s.anon_series_uid != ct_series.anon_series_uid
    )
    model.set_series_harmonized_description(other_ct.anon_series_uid, "CT Abdomen")
    compat = model.get_compatible_series_harmonized_descriptions(
        anon_study,
        modality="CT",
        exclude_anon_series_uid=ct_series.anon_series_uid,
    )
    assert "CT Abdomen" in compat

    assert model.get_2d_series_instance_count(anon_study) >= 1
    assert model.find_studies_with_2d_series_fingerprint(("XR Chest AP",)) == [anon_study]
    assert model.get_compatible_series_harmonized_descriptions(anon_study, modality=None) == []
    assert model.study_all_series_harmonized("missing-uid") is False
