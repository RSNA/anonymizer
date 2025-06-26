# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import time
from pathlib import Path

from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from pynetdicom.presentation import build_context

from anonymizer.controller.create_projections import PROJECTION_FILENAME, create_projection_from_series
from anonymizer.controller.project import ProjectController
from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.dicom_test_files import (
    COMPRESSED_TEST_FILES,
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
    cr1_filename,
    ct_small_filename,
    mr_small_filename,
)
from tests.controller.dicom_test_nodes import TEST_SITEID, TEST_UIDROOT, LocalStorageSCP
from tests.controller.helpers import send_file_to_scp, send_files_to_scp


def test_send_cr1(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(cr1_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 1


def test_send_ct_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 1


def test_send_mr_small(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description is None  # No StudyDescription in MR Small
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 1


def test_send_ct_small_AND_mr_small(temp_dir: str, controller):
    # Send CT SMALL:
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription") if hasattr(ds, "StudyDescription") else None
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 1

    # Send MR SMALL:
    ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 2
    assert TEST_SITEID + "-000002" in dirlist

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".5"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".6"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".7"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description is None  # No StudyDescription in MR Small
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 1


def test_send_ct_Archibald_Doe_PHI_stored(temp_dir: str, controller):
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert series.instances
    assert len(series.instances) == 4


def test_send_ct_Archibald_Doe_Projection_create_cached(temp_dir: str, controller):
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    series_path = store_dir / dirlist[0] / (prefix + ".1") / (prefix + ".2")
    projection = create_projection_from_series(series_path)

    # Check Projection created
    assert projection.patient_id == model.get_anon_patient_id(ds.PatientID)
    assert projection.series_description == ds.SeriesDescription
    assert projection.study_uid == prefix + ".1"
    assert projection.series_uid == prefix + ".2"
    assert projection.proj_images
    assert len(projection.proj_images) == 3

    # Check Projection cached
    projection_file_path = series_path / PROJECTION_FILENAME
    cached = projection_file_path.exists() and projection_file_path.is_file()
    assert cached


def test_send_cr_and_ct_Archibald_Doe(temp_dir: str, controller):
    # Send CR_STUDY_3_SERIES_3_IMAGES:
    dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    assert len(phi.studies[0].series) == 3
    study = phi.studies[0]
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    for series in study.series:
        assert series.series_uid in [ds.get("SeriesInstanceUID") for ds in dsets]
        assert series.description in [ds.get("SeriesDescription") for ds in dsets]
        assert series.modality in [ds.get("Modality") for ds in dsets]
        assert len(series.instances) == 1

    # Send CT_STUDY_1_SERIES_4_IMAGES:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"  # Same Patient

    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    ds = dsets[0]
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".8"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".9"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".10"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 2
    study = phi.studies[1]
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(study.study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    assert study.series
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 4


def test_send_ct_small_then_delete_study(temp_dir: str, controller):
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == prefix + ".4"

    # Verify PHI / Study / Series stored correctly in AnonymizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    assert phi.patient_name == ds.PatientName
    assert phi.dob == ds.get("PatientBirthDate")
    assert phi.sex == ds.get("PatientSex")
    assert phi.ethnic_group == ds.get("EthnicGroup")
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert len(phi.studies[0].series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    assert study.series
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    totals = model.get_totals()
    assert totals == (1, 1, 1, 1)

    # DELETE STUDY:
    assert controller.delete_study(anon_ptid, model.get_anon_uid(ds.StudyInstanceUID))
    # Patient without any studies should have directory removed from storage directory:
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 0

    # Patient without any studies should be removed from AnonymizerModel:
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid is None

    # Check AmoynizerModel patients, studies, series, instances counts are 0:
    totals = model.get_totals()
    assert totals == (0, 0, 0, 0)


def test_send_cr_and_ct_Archibald_Doe_then_delete_studies(temp_dir: str, controller):
    # Send CR_STUDY_3_SERIES_3_IMAGES:
    dsets1: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    study1_uid = dsets1[0].StudyInstanceUID

    # Send CT_STUDY_1_SERIES_4_IMAGES:
    dsets2: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(1)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"  # Same Patient
    study2_uid = dsets2[0].StudyInstanceUID

    phi_ptid = dsets1[0].PatientID

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(phi_ptid)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == phi_ptid
    assert phi.studies
    assert len(phi.studies) == 2

    totals = model.get_totals()
    assert totals == (1, 2, 4, 7)

    # DELETE STUDIES:
    # Delete Study 1:
    assert controller.delete_study(anon_ptid, model.get_anon_uid(study1_uid))
    # Patient with only Study 2 should still have directory in storage directory:
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    # Patient with only Study 2 should still be in AnonymizerModel:
    anon_ptid = model.get_anon_patient_id(phi_ptid)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == phi_ptid
    assert phi.studies
    assert len(phi.studies) == 1

    totals = model.get_totals()
    assert totals == (1, 1, 1, 4)

    # Delete Study 2:
    assert controller.delete_study(anon_ptid, model.get_anon_uid(study2_uid))
    # Patient without any studies should have directory removed from storage directory:
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 0
    # Patient without any studies should be removed from AnonymizerModel:
    anon_ptid = model.get_anon_patient_id(phi_ptid)
    assert anon_ptid is None

    totals = model.get_totals()
    assert totals == (0, 0, 0, 0)


def test_send_ct_Archibald_Doe_mr_Peter_Doe_then_delete_studies(temp_dir: str, controller):
    # Patient 1: Archibald Doe
    # Send CT_STUDY_1_SERIES_4_IMAGES:
    dsets1: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    time.sleep(0.25)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"  #  Patient 1
    study1_uid = dsets1[0].StudyInstanceUID

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    phi_ptid_1 = dsets1[0].PatientID
    anon_ptid_1 = model.get_anon_patient_id(phi_ptid_1)
    assert anon_ptid_1
    phi_1 = model.get_phi_by_anon_patient_id(anon_ptid_1)
    assert phi_1
    assert phi_1.patient_id == phi_ptid_1
    assert phi_1.studies
    assert len(phi_1.studies) == 1

    totals = model.get_totals()
    assert totals == (1, 1, 1, 4)

    # Patient 2: Peter Doe
    # Send MR_STUDY_3_SERIES_11_IMAGES:
    dsets2: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    dirlist = sorted([d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))])
    assert len(dirlist) == 2
    assert dirlist[1] == TEST_SITEID + "-000002"  #  Patient 2
    study2_uid = dsets2[0].StudyInstanceUID

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    phi_ptid_2 = dsets2[0].PatientID
    assert phi_ptid_2 != phi_ptid_1
    anon_ptid_2 = model.get_anon_patient_id(phi_ptid_2)
    assert anon_ptid_2
    assert anon_ptid_2 != anon_ptid_1
    phi_2 = model.get_phi_by_anon_patient_id(anon_ptid_2)
    assert phi_2
    assert phi_2.patient_id == phi_ptid_2
    assert phi_2.studies
    assert len(phi_2.studies) == 1
    assert study2_uid != study1_uid

    totals = model.get_totals()
    assert totals == (2, 2, 4, 15)

    # DELETE PATIENT 1 / STUDY 1:
    anon_study1_uid = model.get_anon_uid(study1_uid)
    assert anon_study1_uid
    assert controller.delete_study(anon_ptid_1, anon_study1_uid)

    # Patient 2 directory should remain in storage directory
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000002"  #  Patient 2

    # Patient with only Study 2 should still be in AnonymizerModel:
    anon_ptid_1 = model.get_anon_patient_id(phi_ptid_1)
    assert not anon_ptid_1
    assert model.get_patient_id_count() == 2  # includes default for blank ptid
    anon_ptid_2 = model.get_anon_patient_id(phi_ptid_2)
    assert anon_ptid_2
    phi_2 = model.get_phi_by_anon_patient_id(anon_ptid_2)
    assert phi_2
    assert phi_2.patient_id == phi_ptid_2
    assert phi_2.studies
    assert len(phi_2.studies) == 1

    totals = model.get_totals()
    assert totals == (1, 1, 3, 11)

    # DELETE PATIENT 2 / STUDY 2:
    anon_study2_uid = model.get_anon_uid(study2_uid)
    assert anon_study2_uid
    assert controller.delete_study(anon_ptid_2, anon_study2_uid)

    # No patient sub-dirs should remain in storage directory
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 0

    anon_ptid_2 = model.get_anon_patient_id(phi_ptid_2)
    assert anon_ptid_2 is None
    assert model.get_patient_id_count() == 1
    assert model.get_phi_index() is None
    assert model.get_totals() == (0, 0, 0, 0)


# Test sending compressed syntaxes to local storage SCP:
# TODO: loop through COMPRESSED_TEST_FILES in single test?


# Transfer Syntax: "1.2.840.10008.1.2.4.50",  # JPEG Baseline ISO_10918_1
# SOPClass: 1.2.840.10008.5.1.4.1.1.7 # Secondary Capture
# No PatientID & PatientName, StudyDate
def test_send_JPEG_Baseline(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Baseline"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_BASELINE_TS = "1.2.840.10008.1.2.4.50"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_BASELINE_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    # Try and send this Secondary Capture to LocalStorageSCP, default config of does not include SC
    # This should fail to establish an association due to no matching presentation contexts:
    try:
        files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet)
    except Exception as e:
        assert "No presentation context" in str(e)

    # By default, LocalStorageSCP is configured to only accept uncompressed syntaxes

    # Add Secondary Capture to ProjectModel storage classes:
    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    # Add JPEG Baseline to ProjectModel transfer syntaxes:
    controller.model.add_transfer_syntax(JPEG_BASELINE_TS)
    # Restart LocalStorageSCP to apply new config:
    controller.update_model()

    # Try again to send test file, even though LocalStorageSCP is setup with required context, send_context must be specified:
    try:
        files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet)
    except Exception as e:
        assert "No presentation context" in str(e)

    # Create Presentation Context for sending as per the file format, since no transcoding is implemented:
    # If this is not specified (as above in last send) the ProjectController AE will use the SCP contexts in requested_contexts property
    # which includes the default syntaxes and the negotiation will settle on first common syntax which wil be Explicit VR Little Endian
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_BASELINE_TS)

    # Try again to send test file to LocalStorageSCP, this should now succeed
    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    # This test file has no patient ID so it will file in default anonymized patient directory site_id + "000000"
    assert dirlist[0] == controller.anonymizer.model.default_anon_pt_id
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_BASELINE_TS
    assert ds.PatientID == controller.anonymizer.model.default_anon_pt_id
    assert ds.PatientName == controller.anonymizer.model.default_anon_pt_id
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.51" JPEG Extended
def test_send_JPEG_Extended(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Extended"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_EXTENDED_TS = "1.2.840.10008.1.2.4.51"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)

    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_EXTENDED_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_EXTENDED_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_EXTENDED_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(1)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_EXTENDED_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.70" Nonhierarchical, First-Order Prediction (Processes 14 [Selection Value 1])
def test_send_JPEG_Lossless_P14_FOP(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG_Lossless_P14_FOP"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_LOSSLESS_P14_TS = "1.2.840.10008.1.2.4.70"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LOSSLESS_P14_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_LOSSLESS_P14_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LOSSLESS_P14_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LOSSLESS_P14_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.80" JPEG-LS Lossless
def test_send_JPEG_LS_Lossless(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG-LS_Lossless"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    JPEG_LS_LOSSLESS_TS = "1.2.840.10008.1.2.4.80"
    # Ensure test file is present from assets/test_files:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSLESS_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_transfer_syntax(JPEG_LS_LOSSLESS_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LS_LOSSLESS_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSLESS_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-LS Lossy
# This Storage class not provided in pydicom data, so use test file from assets
def test_send_JPEG_LS_Lossy(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG-LS_Lossy"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_LS_LOSSY_TS = "1.2.840.10008.1.2.4.81"

    if "test_dcm_files" in filename:
        # Get file from test assets:
        dcm_file_path = Path("tests/controller/assets/", filename)
        ds = dcmread(dcm_file_path)
    else:
        # Get test file from pydicom data:
        ds = get_testdata_file(filename, read=True)
        dcm_file_path = str(get_testdata_file(filename))

    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSY_TS

    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_LS_LOSSY_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_LS_LOSSY_TS)

    files_sent = controller.send([str(dcm_file_path)], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_LS_LOSSY_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-2000 Lossless
def test_send_JPEG_2000_Lossless(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG2000_Lossless"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    JPEG_2000_LOSSLESS_TS = "1.2.840.10008.1.2.4.90"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_LOSSLESS_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_transfer_syntax(JPEG_2000_LOSSLESS_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_2000_LOSSLESS_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_LOSSLESS_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD


# "1.2.840.10008.1.2.4.81" JPEG-2000
def test_send_JPEG_2000(temp_dir: str, controller: ProjectController):
    filename = COMPRESSED_TEST_FILES["JPEG2000"]
    assert filename
    SC_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.7"
    JPEG_2000_TS = "1.2.840.10008.1.2.4.91"
    # Ensure test file is present from pydicom data:
    ds = get_testdata_file(filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_TS

    dcm_file_path = str(get_testdata_file(filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    controller.model.add_storage_class(SC_SOP_CLASS_UID)
    controller.model.add_transfer_syntax(JPEG_2000_TS)
    controller.update_model()
    send_context = build_context(SC_SOP_CLASS_UID, JPEG_2000_TS)

    files_sent = controller.send([dcm_file_path], LocalStorageSCP.aet, [send_context])

    assert files_sent == 1

    time.sleep(0.5)

    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == TEST_SITEID + "-000001"
    prefix = f"{TEST_UIDROOT}.{TEST_SITEID}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == prefix + ".1"
    assert model.get_anon_uid(ds.SeriesInstanceUID) == prefix + ".2"
    assert model.get_anon_uid(ds.SOPInstanceUID) == prefix + ".3"

    # Verify PHI / Study / Series stored correctly in AnonmyizerModel
    anon_ptid = model.get_anon_patient_id(ds.PatientID)
    assert anon_ptid
    phi = model.get_phi_by_anon_patient_id(anon_ptid)
    assert phi
    assert phi.patient_id == ds.PatientID
    if phi.patient_name is not None:
        assert phi.patient_name == ds.PatientName
    assert phi.studies
    assert len(phi.studies) == 1
    study = phi.studies[0]
    assert study
    assert len(study.series) == 1
    assert study.study_uid == ds.StudyInstanceUID
    assert study.study_date == ds.get("StudyDate")
    date_delta, _ = controller.anonymizer._hash_date(phi.studies[0].study_date, phi.patient_id)
    assert study.anon_date_delta == date_delta
    assert study.description == ds.get("StudyDescription")
    assert study.accession_number == ds.get("AccessionNumber")
    assert study.target_instance_count == 0  # Set by controller move operation
    series = study.series[0]
    assert series.series_uid == ds.get("SeriesInstanceUID")
    assert series.description == ds.get("SeriesDescription")
    assert series.modality == ds.get("Modality")
    assert len(series.instances) == 1

    # Read the anonymize file and check the SOPClassUID and TransferSyntaxUID:
    anon_file_path = os.path.join(store_dir, dirlist[0], prefix + ".1", prefix + ".2", prefix + ".3.dcm")
    assert os.path.exists(anon_file_path)
    ds = dcmread(anon_file_path)
    assert ds
    assert ds.SOPClassUID == SC_SOP_CLASS_UID
    assert ds.file_meta.TransferSyntaxUID == JPEG_2000_TS
    assert ds.PatientID == TEST_SITEID + "-000001"
    assert ds.PatientName == TEST_SITEID + "-000001"
    assert ds.file_meta.ImplementationVersionName == controller.model.IMPLEMENTATION_VERSION_NAME
    assert ds.file_meta.ImplementationClassUID == controller.model.IMPLEMENTATION_CLASS_UID
    assert ds.DeidentificationMethod == controller.anonymizer.DEIDENTIFICATION_METHOD
