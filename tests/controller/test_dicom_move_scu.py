# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import time

import pytest
from pydicom.dataset import Dataset

# from anonymizer.controller.dicom_C_codes import (
#     C_FAILURE,
#     C_MOVE_UNKNOWN_AE,
#     C_PENDING_A,
#     C_SUCCESS,
# )
from anonymizer.controller.project import (
    InstanceUIDHierarchy,
    ProjectController,
    SeriesUIDHierarchy,
    StudyUIDHierarchy,
)
from anonymizer.utils.storage import count_studies_series_images
from tests.controller.dicom_test_files import (
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
    cr1_filename,
    # cr1_StudyInstanceUID,
    ct_small_filename,
    ct_small_SeriesInstanceUID,
    ct_small_SOPInstanceUID,
    ct_small_StudyInstanceUID,
    mr_brain_StudyInstanceUID,
    # mr_brain_SeriesInstanceUID,
    # mr_small_bigendian_filename,
    # # mr_small_filename,
    # mr_small_implicit_filename,
    # mr_small_SeriesInstanceUID,
    # mr_small_StudyInstanceUID,
    patient1_id,
    # patient1_name,
    patient2_id,
    # patient2_name,
    patient3_id,
    #     patient3_name,
    #     patient4_id,
    #     patient4_name,
)
from tests.controller.dicom_test_nodes import (
    LocalStorageSCP,
    OrthancSCP,
    PACSSimulatorSCP,
)
from tests.controller.helpers import (
    pacs_storage_dir,
    request_to_move_studies_from_scp_to_local_scp,
    send_file_to_scp,
    send_files_to_scp,
    verify_files_sent_to_pacs_simulator,
)


def test_move_at_study_level_1_CT_file_from_pacs_with_file_to_unknown_AET(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1
    assert study_uid_hierarchy.get_number_of_instances() == 1
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert error_msg
    assert "MOVE DESTINATION UNKNOWN" in error_msg.upper()


def test_move_at_series_level_1_CT_file_from_pacs_with_file_to_unknown_AET(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1
    assert study_uid_hierarchy.get_number_of_instances() == 1
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert error_msg
    assert "MOVE DESTINATION UNKNOWN" in error_msg.upper()


def test_move_at_instance_level_1_CT_file_from_pacs_with_file_to_unknown_AET(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    assert ds
    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, True
    )
    time.sleep(0.5)
    assert error_msg is None
    assert study_uid_hierarchy.get_number_of_instances() == 1
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1
    assert len(series.instances) == 1
    assert series.instances[ct_small_SOPInstanceUID]
    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert error_msg
    assert "MOVE DESTINATION UNKNOWN" in error_msg.upper()


def test_move_at_study_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={})
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", number=1)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Instances" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server


def test_move_at_series_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", number=1)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Instances" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server


def test_move_at_instance_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", ptid="99", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert error_msg
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", number=1)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_instance_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy
    )
    assert error_msg
    assert "No Instances" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server


def test_move_at_study_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert ct_small_study_hierarchy.get_number_of_instances() == 1
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1

    error_msg = controller._move_study_at_study_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert ct_small_study_hierarchy.completed_sub_ops == 1
    assert ct_small_study_hierarchy.failed_sub_ops == 0
    assert ct_small_study_hierarchy.warning_sub_ops == 0
    assert ct_small_study_hierarchy.remaining_sub_ops == 0

    time.sleep(0.5)

    assert controller.get_number_of_pending_instances(ct_small_study_hierarchy) == 0
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"


def test_move_at_series_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT small study file to PACS:
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert ct_small_study_hierarchy.get_number_of_instances() == 1
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1

    error_msg = controller._move_study_at_series_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert controller.get_number_of_pending_instances(ct_small_study_hierarchy) == 0
    assert series.completed_sub_ops == 1
    assert series.failed_sub_ops == 0
    assert series.warning_sub_ops == 0
    assert series.remaining_sub_ops == 0

    time.sleep(1)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"


def test_move_at_instance_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT small study file to PACS:
    ds: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id, True
    )
    assert error_msg is None
    assert ct_small_study_hierarchy.get_number_of_instances() == 1
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instance_count == 1
    assert series.instances[ct_small_SOPInstanceUID]

    error_msg = controller._move_study_at_instance_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert controller.get_number_of_pending_instances(ct_small_study_hierarchy) == 0
    assert series.completed_sub_ops == 1
    assert series.failed_sub_ops == 0
    assert series.warning_sub_ops == 0
    assert series.remaining_sub_ops == 0


def test_move_at_study_level_CT_1_Series_4_Images_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT study file to PACS:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid, patient1_id)
    assert error_msg is None
    assert ct_study_hierarchy.get_number_of_instances() == 4
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert series.instance_count == 4

    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert ct_study_hierarchy.completed_sub_ops == 4
    assert ct_study_hierarchy.failed_sub_ops == 0

    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    time.sleep(0.5)

    total_studies = 0
    total_series = 0
    total_files = 0
    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4


def test_move_at_series_level_CT_1_Series_4_Images_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT study file to PACS:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid, patient1_id)
    assert error_msg is None
    assert ct_study_hierarchy.get_number_of_instances() == 4
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert series.instance_count == 4

    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert series.completed_sub_ops == 4
    assert series.failed_sub_ops == 0

    time.sleep(1)  # wait for file system to update

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_files = count_studies_series_images(os.path.join(store_dir, dirlist[0]))
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4

    # Do the MOVE AGAIN to verify move of instances is done (because of Series level) and files are not duplicated:
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)

    assert error_msg
    assert "All Instances already imported" in error_msg

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_images = count_studies_series_images(
        os.path.join(controller.model.images_dir(), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4


def test_move_at_instance_level_CT_1_Series_4_Images_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT study file to PACS:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, study_uid, patient1_id, True
    )
    assert error_msg is None
    assert ct_study_hierarchy.get_number_of_instances() == 4
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert series.instance_count == 4
    assert len(series.instances) == 4
    assert controller.get_number_of_pending_instances(ct_study_hierarchy) == 4

    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert series.completed_sub_ops == 4
    assert series.failed_sub_ops == 0

    time.sleep(1)  # wait for file system to update

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_files = count_studies_series_images(
        os.path.join(controller.model.images_dir(), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4

    # Do the MOVE AGAIN to verify move of instances is NOT done and files are not duplicated:
    # Update hierarchy to set Imported state:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, study_uid, patient1_id, True
    )
    assert error_msg is None
    assert ct_study_hierarchy.get_number_of_instances() == 4
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert series.instance_count == 4
    assert len(series.instances) == 4
    assert controller.get_number_of_pending_instances(ct_study_hierarchy) == 0

    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)

    assert error_msg is None
    assert series.completed_sub_ops == 0
    assert series.failed_sub_ops == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    store_dir = controller.model.images_dir()

    total_studies, total_series, total_images = count_studies_series_images(os.path.join(store_dir, dirlist[0]))
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4


def test_move_at_study_level_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, PACSSimulatorSCP, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds1.StudyInstanceUID, patient1_id
    )
    assert error_msg is None
    assert study1_hierarchy.get_number_of_instances() == 1

    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds2.StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    assert study2_hierarchy.get_number_of_instances() == 1

    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID, patient2_id
    )
    assert error_msg is None
    assert study3_hierarchy.get_number_of_instances() == 11

    # MOVE Study 1 at STUDY LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "STUDY",
        [study1_hierarchy],
        PACSSimulatorSCP,
        controller,
    )

    # Montior study1_hierarchy for completion within 5 seconds:
    timeout = 5
    while timeout > 0:
        if controller.get_number_of_pending_instances(study1_hierarchy) == 0:
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    # Check Study 1 Move:
    assert study1_hierarchy.completed_sub_ops == 1
    assert study1_hierarchy.failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study1_hierarchy) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    store_dir = controller.model.images_dir()
    total_studies, total_series, total_files = count_studies_series_images(os.path.join(store_dir, dirlist[0]))
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 1

    # MOVE Study 2,3 at STUDY LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "STUDY",
        [study2_hierarchy, study3_hierarchy],
        PACSSimulatorSCP,
        controller,
    )

    # Montior study2_hierarchy & study3_hierarchy:
    timeout = controller.model.network_timeouts.network
    while timeout > 0:
        if (
            controller.get_number_of_pending_instances(study2_hierarchy) == 0
            and controller.get_number_of_pending_instances(study3_hierarchy) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    time.sleep(1)

    assert timeout > 0

    assert study2_hierarchy.completed_sub_ops == 1
    assert study2_hierarchy.failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study2_hierarchy) == 0

    assert study3_hierarchy.completed_sub_ops == 11
    assert study3_hierarchy.failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study3_hierarchy) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images
    assert total_studies == 3
    total_series = 3
    assert total_files == 13


def test_move_at_series_level_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, PACSSimulatorSCP, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds1.StudyInstanceUID, patient1_id
    )
    assert error_msg is None
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds2.StudyInstanceUID, patient3_id
    )
    assert error_msg is None
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID, patient2_id
    )
    assert error_msg is None

    # Get Series uids:
    study1_series1_uid = ds1.SeriesInstanceUID
    study2_series1_uid = ds2.SeriesInstanceUID
    study3_series1_uid = dsets[0].SeriesInstanceUID

    # MOVE Study 1,2,3 at SERIES LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "SERIES",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        PACSSimulatorSCP,
        controller,
    )

    # Montior move of 3 studies / 13 images for completion within controller NetworkTimeout (set in conftest.py):
    # this timeout may occur in debug mode on slow systems
    timeout = controller.model.network_timeouts.network - 1
    while timeout > 0:
        if (
            controller.get_number_of_pending_instances(study1_hierarchy) == 0
            and controller.get_number_of_pending_instances(study2_hierarchy) == 0
            and controller.get_number_of_pending_instances(study3_hierarchy) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    time.sleep(1)

    assert study1_hierarchy.series[study1_series1_uid].completed_sub_ops == 1
    assert study1_hierarchy.series[study1_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study1_hierarchy) == 0

    assert study2_hierarchy.series[study2_series1_uid].completed_sub_ops == 1
    assert study2_hierarchy.series[study2_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study2_hierarchy) == 0

    assert study3_hierarchy.series[study3_series1_uid].completed_sub_ops == 1
    assert study3_hierarchy.series[study3_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study3_hierarchy) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    total_series = 3
    assert total_files == 13


def test_move_at_instance_level_of_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, PACSSimulatorSCP, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, PACSSimulatorSCP, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds1.StudyInstanceUID, patient1_id, True
    )
    assert error_msg is None
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ds2.StudyInstanceUID, patient3_id, True
    )
    assert error_msg is None
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID, patient2_id, True
    )
    assert error_msg is None

    # Get Series uids:
    study1_series1_uid = ds1.SeriesInstanceUID
    study2_series1_uid = ds2.SeriesInstanceUID
    study3_series1_uid = dsets[0].SeriesInstanceUID

    # MOVE Study 1 at INSTANCE LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "IMAGE",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        PACSSimulatorSCP,
        controller,
    )

    # Montior move of 3 studies / 13 images for completion within controller NetworkTimeout:
    # this timeout may occur in debug mode on slow systems
    timeout = controller.model.network_timeouts.network - 1
    while timeout > 0:
        if (
            controller.get_number_of_pending_instances(study1_hierarchy) == 0
            and controller.get_number_of_pending_instances(study2_hierarchy) == 0
            and controller.get_number_of_pending_instances(study3_hierarchy) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    time.sleep(1)

    assert study1_hierarchy.series[study1_series1_uid].completed_sub_ops == 1
    assert study1_hierarchy.series[study1_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study1_hierarchy) == 0

    assert study2_hierarchy.series[study2_series1_uid].completed_sub_ops == 1
    assert study2_hierarchy.series[study2_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study2_hierarchy) == 0

    assert study3_hierarchy.series[study3_series1_uid].completed_sub_ops == 1
    assert study3_hierarchy.series[study3_series1_uid].failed_sub_ops == 0
    assert controller.get_number_of_pending_instances(study3_hierarchy) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    total_series = 3
    assert total_files == 13


def test_move_at_series_level_via_accession_number_list_from_pacs_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    pass


# ORTHANC PACS TESTS:
# TODO: setup Orthanc PACS for testing in all Github action enviromnents
# include orthanc binaries in repository


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_move_at_study_level_1_CT_file_from_orthanc_to_local_storage(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(ct_small_filename, OrthancSCP, controller)
    assert ds
    # Get study_uid_hierarchy for CT small study:
    error_msg, study = controller.get_study_uid_hierarchy(OrthancSCP.aet, ct_small_StudyInstanceUID, patient3_id, True)

    assert error_msg is None
    assert study.get_number_of_instances() == 1
    assert study.uid == ct_small_StudyInstanceUID
    assert len(study.series) == 1
    series = study.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.uid == ct_small_SeriesInstanceUID
    assert series.number == 1
    assert series.instance_count == 1

    # logging.getLogger("pynetdicom").setLevel("DEBUG")

    # Move study at STUDY LEVEL from Orthanc to Local Storage:
    error_msg = controller._move_study_at_study_level(OrthancSCP.aet, LocalStorageSCP.aet, study)

    assert error_msg is None
    assert study.completed_sub_ops == 1
    assert study.failed_sub_ops == 0
    assert study.warning_sub_ops == 0
    assert study.remaining_sub_ops == 0
    assert controller.get_number_of_pending_instances(study) == 0

    time.sleep(1)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"
    assert count_studies_series_images(os.path.join(store_dir, dirlist[0])) == (1, 1, 1)


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_move_at_study_level_with_network_timeout_then_series_level_MR_Study_from_orthanc_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, OrthancSCP, controller)

    # Get study_uid_hierarchy for MR study:
    error_msg, study = controller.get_study_uid_hierarchy(OrthancSCP.aet, mr_brain_StudyInstanceUID, patient2_id, True)

    assert error_msg is None
    assert study.uid == mr_brain_StudyInstanceUID
    assert len(study.series) == 3
    assert study.get_number_of_instances() == 11

    # logging.getLogger("pynetdicom").setLevel("DEBUG")

    # Set Network Timeout to 0.1 second to ensure move timeout occurs:
    controller.model.network_timeouts.network = 0.1

    # Move study at STUDY LEVEL from Orthanc to Local Storage: (orthanc must be configured in async mode for this to work)
    error_msg = controller._move_study_at_study_level(OrthancSCP.aet, LocalStorageSCP.aet, study)

    assert error_msg
    assert "Import Timeout" in error_msg

    controller.model.network_timeouts.network = 15

    error_msg = controller._move_study_at_series_level(OrthancSCP.aet, LocalStorageSCP.aet, study)

    assert len(study.series) == 3
    assert sum(series.instance_count for series in study.series.values()) == 11
    assert controller.get_number_of_pending_instances(study) == 0

    time.sleep(1)
    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"
    assert count_studies_series_images(os.path.join(store_dir, dirlist[0])) == (
        1,
        3,
        11,
    )


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_move_at_instance_level_3_studies_2_patients_from_orthanc_to_local_storage(controller: ProjectController):
    # Send 3 studies to ORTHANC PACS:
    ds1: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, OrthancSCP, controller)  # Doe^Archibald
    ds2: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, OrthancSCP, controller)  # Doe^Archibald
    ds3: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, OrthancSCP, controller)  # Doe^Peter

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds1[0].StudyInstanceUID, patient1_id, True
    )
    assert error_msg is None
    assert study1_hierarchy.get_number_of_instances() == 3
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds2[0].StudyInstanceUID, patient1_id, True
    )
    assert error_msg is None
    assert study2_hierarchy.get_number_of_instances() == 4
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds3[0].StudyInstanceUID, patient2_id, True
    )
    assert error_msg is None
    assert study3_hierarchy.get_number_of_instances() == 11

    # MOVE Study 1,2,3 at INSTANCE LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "IMAGE",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        OrthancSCP,
        controller,
    )

    # Montior move of 3 studies / 13 images for completion within controller NetworkTimeout:
    # this timeout may occur in debug mode on slow systems
    timeout = controller.model.network_timeouts.network
    while timeout > 0:
        if (
            controller.get_number_of_pending_instances(study1_hierarchy) == 0
            and controller.get_number_of_pending_instances(study2_hierarchy) == 0
            and controller.get_number_of_pending_instances(study3_hierarchy) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    assert controller.get_number_of_pending_instances(study1_hierarchy) == 0
    assert controller.get_number_of_pending_instances(study2_hierarchy) == 0
    assert controller.get_number_of_pending_instances(study3_hierarchy) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 2

    total_studies = 0
    total_series = 0
    total_files = 0

    store_dir = controller.model.images_dir()

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    assert total_series == 7
    assert total_files == 18


@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_move_at_study_level_3_studies_with_network_timeout_then_series_level_from_orthance_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send 3 studies to ORTHANC PACS:
    ds1: list[Dataset] = send_files_to_scp(CR_STUDY_3_SERIES_3_IMAGES, OrthancSCP, controller)  # Doe^Archibald
    ds2: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, OrthancSCP, controller)  # Doe^Archibald
    ds3: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, OrthancSCP, controller)  # Doe^Peter

    store_dir = controller.model.images_dir()
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds1[0].StudyInstanceUID, patient1_id, True
    )
    assert error_msg is None
    assert study1_hierarchy.get_number_of_instances() == 3

    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds2[0].StudyInstanceUID, patient1_id, True
    )
    assert error_msg is None
    assert study2_hierarchy.get_number_of_instances() == 4

    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(
        OrthancSCP.aet, ds3[0].StudyInstanceUID, patient2_id, True
    )
    assert error_msg is None
    assert study3_hierarchy.get_number_of_instances() == 11

    # Set Network Timeout to 1 second to ensure move timeout occurs:
    controller.model.network_timeouts.network = 1

    # MOVE Study 1,2,3 at STUDY LEVEL:
    assert request_to_move_studies_from_scp_to_local_scp(
        "STUDY",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        OrthancSCP,
        controller,
    )

    time.sleep(1)

    while controller.bulk_move_active():
        time.sleep(1)

    # assert study1_hierarchy.last_error_msg

    controller.model.network_timeouts.network = 10

    assert request_to_move_studies_from_scp_to_local_scp(
        "SERIES",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        OrthancSCP,
        controller,
    )

    time.sleep(1)

    while controller.bulk_move_active():
        time.sleep(2)

    s1_pending = controller.get_number_of_pending_instances(study1_hierarchy)
    assert s1_pending == 0
    s2_pending = controller.get_number_of_pending_instances(study2_hierarchy)
    assert s2_pending == 0
    s3_pending = controller.get_number_of_pending_instances(study3_hierarchy)
    assert s3_pending == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 2

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(store_dir, dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    assert total_series == 7
    assert total_files == 18
