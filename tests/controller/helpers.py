import os
from pydicom.data import get_testdata_file
from pydicom import Dataset
from controller.dicom_ae import DICOMNode, DICOMRuntimeError
from controller.dicom_echo_scu import echo
from controller.dicom_find_scu import find
from controller.dicom_move_scu import move
from controller.dicom_send_scu import send, ExportRequest, ExportResponse
from controller.dicom_ae import get_network_timeout
import controller.dicom_storage_scp as storage_scp
import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp

from tests.controller.dicom_test_nodes import (
    LocalSCU,
    LocalStorageSCP,
    PACSSimulatorSCP,
)


# HELPER FUNCTIONS
def local_storage_dir(temp_dir: str):
    return os.path.join(temp_dir, LocalStorageSCP.aet)


def pacs_storage_dir(temp_dir: str):
    return os.path.join(temp_dir, PACSSimulatorSCP.aet)


def start_local_storage_scp(temp_dir: str):
    try:
        storage_scp.start(
            LocalStorageSCP,
            local_storage_dir(temp_dir),
        )
        return True
    except DICOMRuntimeError as e:
        return False


def stop_local_storage_scp():
    storage_scp.stop(True)
    assert not storage_scp.server_running()


def echo_local_storage_scp():
    assert echo(LocalSCU, LocalStorageSCP)


def start_pacs_simulator_scp(
    temp_dir: str, known_nodes: list[DICOMNode] = [LocalStorageSCP]
):
    assert pacs_simulator_scp.start(
        PACSSimulatorSCP,
        pacs_storage_dir(temp_dir),
        known_nodes,  # one move destination
    )
    assert pacs_simulator_scp.server_running()


def stop_pacs_simulator_scp():
    pacs_simulator_scp.stop(True)
    assert not pacs_simulator_scp.server_running()


def echo_pacs_simulator_scp():
    assert echo(LocalSCU, PACSSimulatorSCP)


def send_file_to_scp(pydicom_test_filename: str, to_pacs_simulator: bool) -> Dataset:
    # Use test data which comes with pydicom,
    # if not found, get_testdata_file() will try and download it
    ds = get_testdata_file(pydicom_test_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    dcm_file_path = str(get_testdata_file(pydicom_test_filename))
    assert dcm_file_path
    assert send(
        [dcm_file_path],
        LocalSCU,
        PACSSimulatorSCP if to_pacs_simulator else LocalStorageSCP,
    )
    return ds


# def send_to_scp(
#     patient_id: str,
#     files: list[str],
#     ux_Q: queue.Queue[SendResponse],
#     to_pacs_simulator: bool,
# ):
#     if to_pacs_simulator:
#         ip = TEST_PACS_IP
#         port = TEST_PACS_PORT
#         aet = TEST_PACS_AET
#     else:
#         ip = TEST_LOCAL_SCP_IP
#         port = TEST_LOCAL_SCP_PORT
#         aet = TEST_LOCAL_SCP_AET

#     req: SendRequest = SendRequest(
#         scp_ip=ip,
#         scp_port=port,
#         scp_ae=aet,
#         scu_ip=TEST_SCU_IP,
#         scu_ae=TEST_SCU_AET,
#         patient_id=patient_id,
#         dicom_file_paths=files,
#         ux_Q=ux_Q,
#     )
#     send(req)


def find_all_studies_on_pacs_simulator_scp():
    results = find(
        LocalSCU,
        PACSSimulatorSCP,
        "",
        "",
        "",
        "",
        "",
    )
    return results


def move_study_from_pacs_simulator_scp_to_local_scp(study_uid: str):
    return move(
        LocalSCU,
        PACSSimulatorSCP,
        LocalStorageSCP.aet,
        study_uid,
    )
