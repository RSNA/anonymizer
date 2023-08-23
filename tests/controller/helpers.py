import os
from queue import Queue
from pydicom.data import get_testdata_file
from pydicom import Dataset
from controller.dicom_ae import DICOMNode, DICOMRuntimeError
from controller.dicom_echo_scu import echo
from controller.dicom_find_scu import find
from controller.dicom_move_scu import move
from controller.dicom_send_scu import (
    send,
    export_patients,
    ExportRequest,
    ExportResponse,
)
import controller.dicom_storage_scp as storage_scp
import tests.controller.dicom_pacs_simulator_scp as pacs_simulator_scp

# DICOM NODES involved in tests:
from tests.controller.dicom_test_nodes import (
    LocalSCU,
    LocalStorageSCP,
    PACSSimulatorSCP,
)


# TEST HELPER FUNCTIONS
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


def send_files_to_scp(
    pydicom_test_filenames: list[str], to_pacs_simulator: bool
) -> list[Dataset]:
    # Read datasets from test data which comes with pydicom to return to caller
    datasets: list[Dataset] = [
        get_testdata_file(filename, read=True) for filename in pydicom_test_filenames
    ]  # type: ignore
    assert all(isinstance(item, Dataset) for item in datasets)
    assert datasets[0]
    assert datasets[0].PatientID
    paths = [str(get_testdata_file(filename)) for filename in pydicom_test_filenames]
    assert paths
    assert send(
        paths,
        LocalSCU,
        PACSSimulatorSCP if to_pacs_simulator else LocalStorageSCP,
    )
    return datasets


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


def verify_files_sent_to_pacs_simulator(dsets: list[Dataset], tempdir: str):
    # Check naming convention of files on PACS
    dirlist = sorted(os.listdir(pacs_storage_dir(tempdir)))
    assert len(dirlist) == len(dsets)
    assert (
        dirlist[i] == f"{dsets[i].SeriesInstanceUID}.{dsets[i].InstanceNumber}.dcm"
        for i in range(len(dirlist))
    )

    # TODO: read file from pacs directory and check dataset equivalence against the sent dataset
    # TODO: cater for change in SOP class due to compression / transcoding if implemented

    # Check find results (study query model) match sent datasets
    results = find_all_studies_on_pacs_simulator_scp()
    assert results
    assert len(results) == len(dsets)

    # create result dictionary with key StudyInstanceUID
    result_dict = {result.StudyInstanceUID: result for result in results}

    # Check fields of image instance against find results:
    for dset in dsets:
        assert dset.StudyInstanceUID in result_dict
        result = result_dict[dset.StudyInstanceUID]

        assert result.PatientName == dset.PatientName
        assert result.PatientID == dset.PatientID
        assert result.StudyInstanceUID == dset.StudyInstanceUID

        if hasattr(result, "StudyDescription"):
            assert result.StudyDescription == dset.StudyDescription
        assert result.StudyDate == dset.StudyDate
        if hasattr(result, "ModalitiesInStudy"):
            assert dset.Modality in result.ModalitiesInStudy


def export_patients_from_local_storage_to_test_pacs(
    patient_ids: list[str],
) -> bool:
    ux_Q: Queue[ExportResponse] = Queue()
    req: ExportRequest = ExportRequest(LocalSCU, PACSSimulatorSCP, patient_ids, ux_Q)
    export_patients(req)
    export_count = 0
    while not export_count == len(patient_ids):
        try:
            resp: ExportResponse = ux_Q.get(timeout=6)
            assert not resp == ExportResponse.full_export_critical_error()
            assert not resp == ExportResponse.patient_critical_error(resp.patient_id)
            assert resp.errors == 0  # stop on any send error

            if ExportResponse.patient_export_complete(resp):
                export_count += 1

        except Exception as e:  # timeout reading ux_Q
            assert False

    return True
