import os
import time

import pytest
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError

import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp
from anonymizer.controller.project import ProjectController
from anonymizer.utils.storage import count_studies_series_images
from tests.controller.dicom_test_files import (
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
    cr1_filename,
    cr1_StudyInstanceUID,
    ct_small_filename,
    ct_small_SeriesInstanceUID,
    ct_small_StudyInstanceUID,
    mr_brain_StudyInstanceUID,
    mr_small_bigendian_filename,
    mr_small_filename,
    mr_small_implicit_filename,
    mr_small_SeriesInstanceUID,
    mr_small_StudyInstanceUID,
    patient1_id,
    patient1_name,
    patient2_id,
    patient2_name,
    patient3_id,
    patient3_name,
    patient4_id,
    patient4_name,
)

# DICOM NODES involved in tests:
from tests.controller.dicom_test_nodes import LocalStorageSCP, OrthancSCP, PACSSimulatorSCP
from tests.controller.helpers import (
    export_patients_from_local_storage_to_test_pacs,
    pacs_storage_dir,
    send_file_to_scp,
    send_files_to_scp,
    verify_files_sent_to_pacs_simulator,
)


def test_send_invalid_filepath_to_test_pacs(temp_dir: str, controller: ProjectController):
    try:
        controller.send(["does_not_exist.dcm"], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, FileNotFoundError)


def test_send_connection_error(temp_dir: str, controller: ProjectController):
    # Stop PACS Simulator SCP then try to send a file:
    pacs_simulator_scp.stop()
    try:
        controller.send([cr1_filename], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, ConnectionError)


def test_send_no_file_meta_dcm(temp_dir: str, controller: ProjectController):
    filepath = str(get_testdata_file("no_meta.dcm"))
    assert filepath
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, InvalidDicomError)


def test_send_SOP_class_not_supported(temp_dir: str, controller: ProjectController):
    filepath = str(get_testdata_file("rtplan.dcm"))
    assert filepath
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, ValueError)  # No presentation context for RT Plan Storage


def test_send_missing_SOPInstanceUID_AttributeError(temp_dir: str, controller: ProjectController):
    ds = get_testdata_file(cr1_filename, read=True)
    assert isinstance(ds, Dataset)
    # Remove SOPInstanceUID from dataset:
    del ds.SOPInstanceUID
    # Save dataset to new file in temp_dir:
    filepath = os.path.join(temp_dir, "missing_SOPInstanceUID.dcm")
    ds.save_as(filepath)
    try:
        controller.send([filepath], PACSSimulatorSCP.aet)
    except Exception as e:
        assert isinstance(e, AttributeError)  # Required element missing: SOPInstanceUID


# TODO: tests for DICOMRuntimeError (range of invalid responses from pacs) & RuntimeError (send_cstore called without association)


def test_send_1_CR_file_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(cr1_filename, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_CT_file_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_MR_file_explicit__VR_little_endian_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(mr_small_filename, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_1_MR_file_implicit_VR_little_endian_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(mr_small_implicit_filename, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


# Explicit VR Big Endian Transfer Syntax is supported but uncommon and to be retired:
def test_send_1_MR_file_explicit_VR_big_endian_to_test_pacs(temp_dir: str, controller: ProjectController):
    ds = get_testdata_file(mr_small_bigendian_filename, read=True)
    assert isinstance(ds, Dataset)
    dcm_file_path = str(get_testdata_file(mr_small_bigendian_filename))
    assert dcm_file_path
    assert controller.send(
        [dcm_file_path],
        PACSSimulatorSCP.aet,
        controller.get_radiology_storage_contexts_BIGENDIAN(),
    )
    verify_files_sent_to_pacs_simulator([ds], temp_dir, controller)


def test_send_CT_MR_files_find_all_studies_on_test_pacs(temp_dir: str, controller: ProjectController):
    ds1: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    ds2: Dataset = send_file_to_scp(mr_small_filename, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2], temp_dir, controller)


def test_send_3_CR_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_send_4_CT_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_send_11_MR_files_to_test_pacs(temp_dir: str, controller: ProjectController):
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)


def test_export_patient_CR_study_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send 1 Study with 1 CR files to local storage:
    send_files_to_scp([cr1_filename], LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    anon_pt_id = controller.model.site_id + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)


def test_export_patient_CT_study_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send 1 Study with 4 CT files to local storage:
    send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    anon_pt_id = controller.model.site_id + "-000001"
    assert len(dirlist) == 1
    assert dirlist[0] == anon_pt_id
    # Export this patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)


def test_export_1_patient_2_studies_CR_CT_to_test_pacs(temp_dir: str, controller: ProjectController):
    # SAME Patient: (Doe^Archibald)
    # Send CR & CT studies to local storage:
    # Send 1 Study with 3 CR files to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    assert cr_phi_dsets[0].PatientName == "Doe^Archibald"
    # Send 1 Study with 4 CT files to local storage:
    ct_phi_dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, LocalStorageSCP, controller)
    time.sleep(0.5)
    assert ct_phi_dsets[0].PatientName == "Doe^Archibald"
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    anon_pt_id = controller.model.site_id + "-000001"
    assert len(dirlist) == 1
    assert anon_pt_id in dirlist
    # Check 2 studies and 7 files in patient directory on local storage:
    assert count_studies_series_images(os.path.join(controller.model.images_dir(), anon_pt_id)) == (2, 4, 7)
    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([anon_pt_id], controller)
    time.sleep(0.5)
    # Check 7 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 7


def test_export_2_patients_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send Patient 1: 1 CR study to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    for ds in cr_phi_dsets:
        assert ds.PatientName == patient1_name
        assert ds.PatientID == patient1_id
        assert ds.StudyInstanceUID == cr1_StudyInstanceUID

    # Send Patient 2: 1 Study with 11 MR files to local storage:
    mr_phi_dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, LocalStorageSCP, controller)
    for ds in mr_phi_dsets:
        assert ds.PatientName == patient2_name
        assert ds.PatientID == patient2_id
        assert ds.StudyInstanceUID == mr_brain_StudyInstanceUID

    time.sleep(1)

    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 2

    patient1_anon_pt_id = controller.model.site_id + "-000001"
    patient2_anon_pt_id = controller.model.site_id + "-000002"

    assert patient1_anon_pt_id in dirlist
    assert patient2_anon_pt_id in dirlist

    # Check 1 study, 3 series and 3 images in ct patient directory on local storage:
    assert count_studies_series_images(os.path.join(controller.model.images_dir(), patient1_anon_pt_id)) == (1, 3, 3)
    # Check 1 study, 3 series and 11 images in mr patient directory on local storage:
    assert count_studies_series_images(os.path.join(controller.model.images_dir(), patient2_anon_pt_id)) == (1, 3, 11)

    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs([patient1_anon_pt_id, patient2_anon_pt_id], controller)
    # Check 14 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 14


def test_export_4_patients_to_test_pacs(temp_dir: str, controller: ProjectController):
    # Send Patient 1:
    # - 1 CR study to local storage:
    cr_phi_dsets: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, LocalStorageSCP, controller)
    for ds in cr_phi_dsets:
        assert ds.PatientName == patient1_name
        assert ds.PatientID == patient1_id
        assert ds.StudyInstanceUID == cr1_StudyInstanceUID

    # Send Patient 2:
    # - 1 Study with 11 MR files to local storage:
    mr_phi_dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, LocalStorageSCP, controller)
    for ds in mr_phi_dsets:
        assert ds.PatientName == patient2_name
        assert ds.PatientID == patient2_id
        assert ds.StudyInstanceUID == mr_brain_StudyInstanceUID

    # Send Patient 3:
    # - 1 Study with 1 compressed CT file to local storage:
    ctsmall_ds: Dataset = send_file_to_scp(ct_small_filename, LocalStorageSCP, controller)
    assert ctsmall_ds.PatientName == patient3_name
    assert ctsmall_ds.PatientID == patient3_id
    assert ctsmall_ds.StudyInstanceUID == ct_small_StudyInstanceUID
    assert ctsmall_ds.SeriesInstanceUID == ct_small_SeriesInstanceUID

    # Send Patient 4:
    # - 1 Study with 1 compressed MR file to local storage:
    mrsmall_ds: Dataset = send_file_to_scp(mr_small_filename, LocalStorageSCP, controller)
    assert mrsmall_ds.PatientName == patient4_name
    assert mrsmall_ds.PatientID == patient4_id
    assert mrsmall_ds.StudyInstanceUID == mr_small_StudyInstanceUID
    assert mrsmall_ds.SeriesInstanceUID == mr_small_SeriesInstanceUID

    time.sleep(1)

    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 4

    patient1_anon_pt_id = controller.model.site_id + "-000001"
    patient2_anon_pt_id = controller.model.site_id + "-000002"
    patient3_anon_pt_id = controller.model.site_id + "-000003"
    patient4_anon_pt_id = controller.model.site_id + "-000004"

    assert patient1_anon_pt_id in dirlist
    assert patient2_anon_pt_id in dirlist
    assert patient3_anon_pt_id in dirlist
    assert patient4_anon_pt_id in dirlist

    # Check 1 study, 3 series and 3 images in patient 1 directory on local storage:
    assert count_studies_series_images(os.path.join(store_dir, patient1_anon_pt_id)) == (1, 3, 3)
    # Check 1 study, 3 series and 11 images in patient 2 directory on local storage:
    assert count_studies_series_images(os.path.join(store_dir, patient2_anon_pt_id)) == (1, 3, 11)
    # Check 1 study, 1 series and 1 image in patient 3 directory on local storage:
    assert count_studies_series_images(os.path.join(store_dir, patient3_anon_pt_id)) == (1, 1, 1)
    # Check 1 study, 1 series and 1 image in patient 4 directory on local storage:
    assert count_studies_series_images(os.path.join(store_dir, patient4_anon_pt_id)) == (1, 1, 1)

    # Export these patient from local storage to test PACS:
    assert export_patients_from_local_storage_to_test_pacs(
        [patient1_anon_pt_id, patient2_anon_pt_id, patient3_anon_pt_id, patient4_anon_pt_id], controller
    )
    # Check 16 files in test pacs directory:
    assert len(os.listdir(pacs_storage_dir(temp_dir))) == 16


# TODO: test export: active storage directory not set, invalid patient directory, valid dir but not files, connection error, invalid response from PACS
# TODO: test retry mechanism for failed export


def test_find_study_uid_hierarchy(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    ds2: Dataset = send_file_to_scp(mr_small_filename, PACSSimulatorSCP, controller)
    ds3: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, PACSSimulatorSCP, controller)
    dsets = [ds1, ds2] + ds3
    ds_series_uids = set([dset.SeriesInstanceUID for dset in dsets])
    ds_instance_uids = [dset.SOPInstanceUID for dset in dsets]
    assert len(ds_series_uids) == 5
    assert len(ds_instance_uids) == 13

    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    error_msg, study1_uid_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds1.StudyInstanceUID, ds1.PatientID
    )

    assert error_msg is None
    assert len(study1_uid_hierarchy.series) == 1
    assert study1_uid_hierarchy.get_number_of_instances() == 1

    error_msg, study3_uid_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds3[0].StudyInstanceUID, ds3[0].PatientID
    )

    assert error_msg is None
    for ds in ds3:
        assert ds.SeriesInstanceUID in study3_uid_hierarchy.series
    assert study3_uid_hierarchy.get_number_of_instances() == 11


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_send_3_studies_to_orthanc_find_with_acc_no_list(temp_dir: str, controller: ProjectController):
    dset1: list[Dataset] = send_files_to_scp(
        MR_STUDY_3_SERIES_11_IMAGES,
        OrthancSCP,
        controller,
    )
    dset2: list[Dataset] = send_files_to_scp(
        CT_STUDY_1_SERIES_4_IMAGES,
        OrthancSCP,
        controller,
    )
    dset3: list[Dataset] = send_files_to_scp(
        CR_STUDY_3_SERIES_3_IMAGES,
        OrthancSCP,
        controller,
    )

    acc1 = dset1[0].AccessionNumber
    acc2 = dset2[0].AccessionNumber
    acc3 = dset3[0].AccessionNumber

    results = controller.find_studies_via_acc_nos(
        scp_name=OrthancSCP.aet,
        acc_no_list=[acc1, acc2, acc3],
        ux_Q=None,
        verify_attributes=False,
    )

    assert results
    assert len(results) == 3
    assert list(set([r.AccessionNumber for r in results])) == list(set([acc1, acc2, acc3]))

    for ds in [dset1[0], dset2[0], dset3[0]]:
        results: list[Dataset] | None = controller.find_studies(
            scp_name=OrthancSCP.aet,
            name="",
            id="",
            acc_no=ds.AccessionNumber,
            study_date="",
            modality=ds.Modality,
            ux_Q=None,
            verify_attributes=False,
        )

        assert results
        assert len(results) == 1
        assert results[0].AccessionNumber == ds.AccessionNumber
        assert results[0].ModalitiesInStudy == ds.Modality
        assert results[0].StudyInstanceUID == ds.StudyInstanceUID
