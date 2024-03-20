import os
from pathlib import Path
from queue import Queue
from pydicom.data import get_testdata_file
from pydicom import Dataset
from controller.project import (
    ProjectController,
    ExportStudyRequest,
    ExportStudyResponse,
    MoveStudiesRequest,
)
from model.project import DICOMNode, DICOMRuntimeError
from controller.dicom_C_codes import C_SUCCESS, C_PENDING_A, C_PENDING_B

# from controller.dicom_send_scu import (
#     export_patients,
#     ExportRequest,
#     ExportResponse,
# )

# DICOM NODES involved in tests:
from tests.controller.dicom_test_nodes import (
    LocalStorageSCP,
    PACSSimulatorSCP,
)


# TEST HELPER FUNCTIONS
def local_storage_dir(temp_dir: str):
    return Path(temp_dir, LocalStorageSCP.aet)


def pacs_storage_dir(temp_dir: str):
    return Path(temp_dir, PACSSimulatorSCP.aet)


def send_file_to_scp(
    pydicom_test_filename: str, to_pacs_simulator: bool, controller: ProjectController
) -> Dataset:
    # Use test data which comes with pydicom,
    # if not found, get_testdata_file() will try and download it
    ds = get_testdata_file(pydicom_test_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    assert ds.PatientID
    dcm_file_path = str(get_testdata_file(pydicom_test_filename))
    assert dcm_file_path
    files_sent = controller.send(
        [dcm_file_path],
        PACSSimulatorSCP.aet if to_pacs_simulator else LocalStorageSCP.aet,
    )
    assert files_sent == 1
    return ds


def send_files_to_scp(
    pydicom_test_filenames: list[str],
    to_pacs_simulator: bool,
    controller: ProjectController,
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
    files_sent = controller.send(
        paths,
        PACSSimulatorSCP.aet if to_pacs_simulator else LocalStorageSCP.aet,
    )
    assert files_sent == len(datasets)
    return datasets


def find_all_studies_on_pacs_simulator_scp(controller: ProjectController):
    results = controller.find_studies(
        PACSSimulatorSCP.aet,
        "",
        "",
        "",
        "",
        "",
        None,
        False,
    )
    return results


def move_studies_from_pacs_simulator_scp_to_local_scp(
    study_ids: list[str], controller: ProjectController
) -> bool:
    ux_Q: Queue[Dataset] = Queue()
    req: MoveStudiesRequest = MoveStudiesRequest(
        PACSSimulatorSCP.aet, LocalStorageSCP.aet, study_ids, ux_Q
    )
    controller.move_studies(req)
    move_count = 0
    while move_count < len(study_ids):
        try:
            resp: Dataset = ux_Q.get(timeout=6)
            assert resp.Status in [C_SUCCESS, C_PENDING_A, C_PENDING_B]
            assert resp.NumberOfCompletedSuboperations != 0
            assert resp.NumberOfFailedSuboperations == 0
            assert resp.NumberOfWarningSuboperations == 0
            if resp.Status == C_SUCCESS:
                move_count += 1

        except Exception as e:  # timeout reading ux_Q
            assert False

    return True


def verify_files_sent_to_pacs_simulator(
    dsets: list[Dataset], tempdir: str, controller: ProjectController
):
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
    results = find_all_studies_on_pacs_simulator_scp(controller)
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
    patient_ids: list[str], controller
) -> bool:
    ux_Q: Queue[ExportStudyResponse] = Queue()
    req: ExportStudyRequest = ExportStudyRequest(
        PACSSimulatorSCP.aet, patient_ids, ux_Q
    )
    controller.export_patients(req)
    export_count = 0
    while not export_count == len(patient_ids):
        try:
            resp: ExportStudyResponse = ux_Q.get(timeout=6)
            assert not resp.error

            if resp.complete:
                export_count += 1

        except Exception as e:  # timeout reading ux_Q
            assert False

    return True
