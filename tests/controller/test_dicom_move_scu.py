# UNIT TESTS for controller/dicom_storage_scp.py
# use pytest from terminal to show full logging output: pytest --log-cli-level=DEBUG
import os
import logging
import time
from queue import Queue
from pydicom.dataset import Dataset
from utils.storage import count_studies_series_images

from controller.project import ProjectController, StudyUIDHierarchy, SeriesUIDHierarchy, InstanceUIDHierarchy
from tests.controller.dicom_test_nodes import LocalStorageSCP, PACSSimulatorSCP
from tests.controller.helpers import (
    send_file_to_scp,
    send_files_to_scp,
    request_to_move_studies_from_pacs_simulator_scp_to_local_scp,
    pacs_storage_dir,
    local_storage_dir,
    verify_files_sent_to_pacs_simulator,
)
from controller.dicom_C_codes import (
    C_FAILURE,
    C_MOVE_UNKNOWN_AE,
    C_SUCCESS,
    C_PENDING_A,
)
from tests.controller.dicom_test_files import (
    cr1_filename,
    cr1_StudyInstanceUID,
    cr1_SeriesInstanceUID,
    cr1_SOPInstanceUID,
    ct_small_filename,
    ct_small_StudyInstanceUID,
    ct_small_SeriesInstanceUID,
    ct_small_SOPInstanceUID,
    mr_small_filename,
    mr_small_implicit_filename,
    mr_small_bigendian_filename,
    CR_STUDY_3_SERIES_3_IMAGES,
    CT_STUDY_1_SERIES_4_IMAGES,
    MR_STUDY_3_SERIES_11_IMAGES,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def test_move_at_study_level_1_CT_file_from_pacs_with_file_to_unknown_AET(temp_dir: str, controller: ProjectController):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)

    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ct_small_StudyInstanceUID)
    assert error_msg == None
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert "destination unknown" in error_msg


def test_move_at_series_level_1_CT_file_from_pacs_with_file_to_unknown_AET(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ct_small_StudyInstanceUID)
    assert error_msg == None
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert "destination unknown" in error_msg


def test_move_at_instance_level_1_CT_file_from_pacs_with_file_to_unknown_AET(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    error_msg, study_uid_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ct_small_StudyInstanceUID)
    assert error_msg == None
    assert len(study_uid_hierarchy.series) == 1
    series = study_uid_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]
    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, "UNKNOWNAE", study_uid_hierarchy)
    assert "destination unknown" in error_msg


def test_move_at_study_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={})
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", imported=False)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "Import Timeout" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server
    assert bogus_instance.imported == False


def test_move_at_series_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", imported=False)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "Import Timeout" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server
    assert bogus_instance.imported == False


def test_move_at_instance_level_1_file_from_empty_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 0
    # Request move of bogus study with no series:
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Series" in error_msg

    # Request move of bogus study with one series but no instances:
    bogus_series = SeriesUIDHierarchy(uid="1.2.3.4.5.6.1", modality="CT", description="Bogus Series", instances={})
    bogus_study_hierarchy = StudyUIDHierarchy(uid="1.2.3.4.5.6", series={bogus_series.uid: bogus_series})
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy)
    assert "No Instances" in error_msg

    # Request move of bogus study uid with one series and one instance:
    bogus_instance = InstanceUIDHierarchy(uid="1.2.3.4.5.6.2", imported=False)
    bogus_series.instances = {bogus_instance.uid: bogus_instance}
    error_msg = controller._move_study_at_instance_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, bogus_study_hierarchy
    )
    assert "Import Timeout" in error_msg
    assert bogus_series.completed_sub_ops == 0  # instance was not on server
    assert bogus_instance.imported == False


def test_move_at_study_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID
    )
    assert error_msg == None
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]

    error_msg = controller._move_study_at_study_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert ct_small_study_hierarchy.completed_sub_ops == 1
    assert ct_small_study_hierarchy.failed_sub_ops == 0
    assert ct_small_study_hierarchy.warning_sub_ops == 0
    assert ct_small_study_hierarchy.remaining_sub_ops == 0
    assert len(series.get_pending_instances()) == 0
    instance = series.instances[ct_small_SOPInstanceUID]
    assert instance.imported == True

    time.sleep(1)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"


def test_move_at_series_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT small study file to PACS:
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID
    )
    assert error_msg == None
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]

    error_msg = controller._move_study_at_series_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert len(series.get_pending_instances()) == 0
    assert series.completed_sub_ops == 1
    assert series.failed_sub_ops == 0
    assert series.warning_sub_ops == 0
    assert series.remaining_sub_ops == 0
    instance = series.instances[ct_small_SOPInstanceUID]
    assert instance.imported == True

    time.sleep(1)
    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    assert dirlist[0] == controller.model.site_id + "-000001"


def test_move_at_instance_level_1_CT_file_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT small study file to PACS:
    ds: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dirlist = os.listdir(pacs_storage_dir(temp_dir))
    assert len(dirlist) == 1
    assert dirlist[0] == ds.SeriesInstanceUID + ".1.dcm"

    # Get study_uid_hierarchy for CT small study:
    error_msg, ct_small_study_hierarchy = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID
    )
    assert error_msg == None
    assert len(ct_small_study_hierarchy.series) == 1
    series = ct_small_study_hierarchy.series[ct_small_SeriesInstanceUID]
    assert series
    assert series.instances[ct_small_SOPInstanceUID]

    error_msg = controller._move_study_at_instance_level(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_small_study_hierarchy
    )
    assert error_msg is None
    assert len(series.get_pending_instances()) == 0
    assert series.completed_sub_ops == 1
    assert series.failed_sub_ops == 0
    assert series.warning_sub_ops == 0
    assert series.remaining_sub_ops == 0
    instance = series.instances[ct_small_SOPInstanceUID]
    assert instance.imported == True


def test_move_at_study_level_CT_1_Series_4_Images_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT study file to PACS:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid)
    assert error_msg == None
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert len(series.instances) == 4

    error_msg = controller._move_study_at_study_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert ct_study_hierarchy.completed_sub_ops == 4
    assert ct_study_hierarchy.failed_sub_ops == 0

    store_dir = local_storage_dir(temp_dir)
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    time.sleep(0.5)
    total_studies = 0
    total_series = 0
    total_files = 0
    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(local_storage_dir(temp_dir), dirlist[i]))
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
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    store_dir = local_storage_dir(temp_dir)
    total_studies = 0
    total_series = 0
    total_files = 0

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid)
    assert error_msg == None
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert len(series.instances) == 4

    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert series.completed_sub_ops == 4
    assert series.failed_sub_ops == 0

    time.sleep(1)  # wait for file system to update

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_files = count_studies_series_images(
        os.path.join(local_storage_dir(temp_dir), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4

    # Do the MOVE AGAIN to verify move of instances is done (because of Series level) and files are not duplicated:
    error_msg = controller._move_study_at_series_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)

    assert error_msg is None
    assert series.completed_sub_ops == 4
    assert series.failed_sub_ops == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_images = count_studies_series_images(
        os.path.join(local_storage_dir(temp_dir), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4


def test_move_at_instance_level_CT_1_Series_4_Images_from_pacs_with_file_to_local_storage(
    temp_dir: str, controller: ProjectController
):
    # Send CT study file to PACS:
    dsets: list[Dataset] = send_files_to_scp(CT_STUDY_1_SERIES_4_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator(dsets, temp_dir, controller)

    store_dir = local_storage_dir(temp_dir)
    total_studies = 0
    total_series = 0
    total_files = 0

    study_uid = dsets[0].StudyInstanceUID
    series_uid = dsets[0].SeriesInstanceUID

    # Get study_uid_hierarchy for CT study:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid)
    assert error_msg == None
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert len(series.instances) == 4
    assert len(ct_study_hierarchy.get_pending_instances()) == 4

    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)
    assert error_msg is None
    assert series.completed_sub_ops == 4
    assert series.failed_sub_ops == 0

    time.sleep(1)  # wait for file system to update

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_files = count_studies_series_images(
        os.path.join(local_storage_dir(temp_dir), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4

    # Do the MOVE AGAIN to verify move of instances is NOT done and files are not duplicated:
    # Update hierarchy to set Imported state:
    error_msg, ct_study_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, study_uid)
    assert error_msg == None
    assert len(ct_study_hierarchy.series) == 1
    series = ct_study_hierarchy.series[series_uid]
    assert series
    assert len(series.instances) == 4
    assert len(ct_study_hierarchy.get_pending_instances()) == 0

    error_msg = controller._move_study_at_instance_level(PACSSimulatorSCP.aet, LocalStorageSCP.aet, ct_study_hierarchy)

    assert error_msg is None
    assert series.completed_sub_ops == 0
    assert series.failed_sub_ops == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1

    total_studies, total_series, total_images = count_studies_series_images(
        os.path.join(local_storage_dir(temp_dir), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 4


def test_move_at_study_level_of_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, True, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = local_storage_dir(temp_dir)
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds1.StudyInstanceUID)
    assert error_msg == None
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds2.StudyInstanceUID)
    assert error_msg == None
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID)
    assert error_msg == None

    # MOVE Study 1 at STUDY LEVEL:
    assert request_to_move_studies_from_pacs_simulator_scp_to_local_scp(
        "STUDY",
        [study1_hierarchy],
        controller,
    )

    # Montior study1_hierarchy for completion within 5 seconds:
    timeout = 5
    while timeout > 0:
        if len(study1_hierarchy.get_pending_instances()) == 0:
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    # Check Study 1 Move:
    assert study1_hierarchy.completed_sub_ops == 1
    assert study1_hierarchy.failed_sub_ops == 0
    assert len(study1_hierarchy.get_pending_instances()) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 1
    total_studies, total_series, total_files = count_studies_series_images(
        os.path.join(local_storage_dir(temp_dir), dirlist[0])
    )
    assert total_studies == 1
    assert total_series == 1
    assert total_files == 1

    assert request_to_move_studies_from_pacs_simulator_scp_to_local_scp(
        "STUDY",
        [study2_hierarchy, study3_hierarchy],
        controller,
    )

    # Montior study2_hierarchy & study3_hierarchy:
    timeout = controller.model.network_timeouts.network - 1
    while timeout > 0:
        if len(study2_hierarchy.get_pending_instances()) == 0 and len(study3_hierarchy.get_pending_instances()) == 0:
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    assert study2_hierarchy.completed_sub_ops == 1
    assert study2_hierarchy.failed_sub_ops == 0
    assert len(study2_hierarchy.get_pending_instances()) == 0

    assert study3_hierarchy.completed_sub_ops == 11
    assert study3_hierarchy.failed_sub_ops == 0
    assert len(study3_hierarchy.get_pending_instances()) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(local_storage_dir(temp_dir), dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images
    assert total_studies == 3
    total_series = 3
    assert total_files == 13


def test_move_at_series_level_of_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, True, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = local_storage_dir(temp_dir)
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds1.StudyInstanceUID)
    assert error_msg == None
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds2.StudyInstanceUID)
    assert error_msg == None
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID)
    assert error_msg == None

    # Get Series uids:
    study1_series1_uid = ds1.SeriesInstanceUID
    study2_series1_uid = ds2.SeriesInstanceUID
    study3_series1_uid = dsets[0].SeriesInstanceUID

    # MOVE Study 1 at SERIES LEVEL:
    assert request_to_move_studies_from_pacs_simulator_scp_to_local_scp(
        "SERIES",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        controller,
    )

    # Montior move of 3 studies / 13 images for completion within controller NetworkTimeout:
    # this timeout may occur in debug mode on slow systems
    timeout = controller.model.network_timeouts.network - 1
    while timeout > 0:
        if (
            len(study1_hierarchy.get_pending_instances()) == 0
            and len(study2_hierarchy.get_pending_instances()) == 0
            and len(study3_hierarchy.get_pending_instances()) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    assert study1_hierarchy.series[study1_series1_uid].completed_sub_ops == 1
    assert study1_hierarchy.series[study1_series1_uid].failed_sub_ops == 0
    assert len(study1_hierarchy.get_pending_instances()) == 0

    assert study2_hierarchy.series[study2_series1_uid].completed_sub_ops == 1
    assert study2_hierarchy.series[study2_series1_uid].failed_sub_ops == 0
    assert len(study2_hierarchy.get_pending_instances()) == 0

    assert study3_hierarchy.series[study3_series1_uid].completed_sub_ops == 1
    assert study3_hierarchy.series[study3_series1_uid].failed_sub_ops == 0
    assert len(study3_hierarchy.get_pending_instances()) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(local_storage_dir(temp_dir), dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    total_series = 3
    assert total_files == 13


def test_move_at_instance_level_of_3_studies_from_pacs_to_local_storage(temp_dir: str, controller: ProjectController):
    # Send 3 studies to TEST PACS
    ds1: Dataset = send_file_to_scp(cr1_filename, True, controller)
    ds2: Dataset = send_file_to_scp(ct_small_filename, True, controller)
    dsets: list[Dataset] = send_files_to_scp(MR_STUDY_3_SERIES_11_IMAGES, True, controller)
    verify_files_sent_to_pacs_simulator([ds1, ds2] + dsets, temp_dir, controller)

    store_dir = local_storage_dir(temp_dir)
    total_studies = 0
    total_series = 0
    total_files = 0

    # Get StudyUIDHierachies:
    error_msg, study1_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds1.StudyInstanceUID)
    assert error_msg == None
    error_msg, study2_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, ds2.StudyInstanceUID)
    assert error_msg == None
    error_msg, study3_hierarchy = controller.get_study_uid_hierarchy(PACSSimulatorSCP.aet, dsets[0].StudyInstanceUID)
    assert error_msg == None

    # Get Series uids:
    study1_series1_uid = ds1.SeriesInstanceUID
    study2_series1_uid = ds2.SeriesInstanceUID
    study3_series1_uid = dsets[0].SeriesInstanceUID

    # MOVE Study 1 at INSTANCE LEVEL:
    assert request_to_move_studies_from_pacs_simulator_scp_to_local_scp(
        "IMAGE",
        [study1_hierarchy, study2_hierarchy, study3_hierarchy],
        controller,
    )

    # Montior move of 3 studies / 13 images for completion within controller NetworkTimeout:
    # this timeout may occur in debug mode on slow systems
    timeout = controller.model.network_timeouts.network - 1
    while timeout > 0:
        if (
            len(study1_hierarchy.get_pending_instances()) == 0
            and len(study2_hierarchy.get_pending_instances()) == 0
            and len(study3_hierarchy.get_pending_instances()) == 0
        ):
            break
        time.sleep(1)
        timeout -= 1

    assert timeout > 0

    assert study1_hierarchy.series[study1_series1_uid].completed_sub_ops == 1
    assert study1_hierarchy.series[study1_series1_uid].failed_sub_ops == 0
    assert len(study1_hierarchy.get_pending_instances()) == 0

    assert study2_hierarchy.series[study2_series1_uid].completed_sub_ops == 1
    assert study2_hierarchy.series[study2_series1_uid].failed_sub_ops == 0
    assert len(study2_hierarchy.get_pending_instances()) == 0

    assert study3_hierarchy.series[study3_series1_uid].completed_sub_ops == 1
    assert study3_hierarchy.series[study3_series1_uid].failed_sub_ops == 0
    assert len(study3_hierarchy.get_pending_instances()) == 0

    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) == 3

    total_studies = 0
    total_series = 0
    total_files = 0

    for i in range(len(dirlist)):
        studies, series, images = count_studies_series_images(os.path.join(local_storage_dir(temp_dir), dirlist[i]))
        total_studies += studies
        total_series += series
        total_files += images

    assert total_studies == 3
    total_series = 3
    assert total_files == 13
