import os
import time
from anonymizer.controller.project import ProjectController
from anonymizer.utils.storage import (
    JavaAnonymizerExportedStudy,
    read_java_anonymizer_index_xlsx,
)
from pydicom.dataset import Dataset
from anonymizer.model.anonymizer import AnonymizerModel
    
from tests.controller.dicom_test_nodes import LocalStorageSCP
from tests.controller.helpers import send_file_to_scp
from tests.controller.dicom_test_files import (
    ct_small_filename,
    
    hash_ct_small_StudyInstanceUID,
    hash_ct_small_SeriesInstanceUID,
    hash_ct_small_SOPInstanceUID,
    hash_ct_small_FrameOfReferenceUID
)


def test_read_java_anonymizer_index_xlsx(temp_dir: str, controller: ProjectController) -> None:
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)
    assert studies
    assert len(studies) == 112
    assert studies[0].ANON_PatientName == "527408-000001"
    assert studies[0].ANON_PatientID == "527408-000001"
    assert studies[0].PHI_PatientName == "TEST"
    assert studies[0].PHI_PatientID == "999"
    assert studies[69].PHI_PatientName == "Mary Martinez"
    assert studies[69].PHI_PatientID == "574856-000200"


def test_load_java_index_into_new_project(temp_dir: str, controller: ProjectController) -> None:
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)

    controller.anonymizer.model.process_java_phi_studies(studies)
    assert controller.anonymizer.model.get_patient_id_count() == 83
    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id("527408-000001") == "TEST"


def test_load_java_index_into_new_project_and_import_ct_small(temp_dir: str, controller: ProjectController) -> None:
    index_file = "tests/controller/assets/JavaGeneratedIndex.xlsx"
    studies: list[JavaAnonymizerExportedStudy] = read_java_anonymizer_index_xlsx(index_file)

    controller.anonymizer.model.process_java_phi_studies(studies)
    assert controller.anonymizer.model.get_patient_id_count() == 83
    assert controller.anonymizer.model.get_phi_name_by_anon_patient_id("527408-000001") == "TEST"

    uid_mapping_count = controller.anonymizer.model.get_uid_count()

    # After loading java index file import pydicom test file by sending to LocalStorageSCP
    ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    model: AnonymizerModel = controller.anonymizer.model
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == model._site_id + "-000083"
    prefix = f"{model._uid_root}.{model._site_id}"
    assert model.get_anon_uid(ds.StudyInstanceUID) == hash_ct_small_StudyInstanceUID
    assert model.get_anon_uid(ds.SeriesInstanceUID) == hash_ct_small_SeriesInstanceUID
    assert model.get_anon_uid(ds.SOPInstanceUID) == hash_ct_small_SOPInstanceUID
    assert model.get_anon_uid(ds.FrameOfReferenceUID) == hash_ct_small_FrameOfReferenceUID

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
