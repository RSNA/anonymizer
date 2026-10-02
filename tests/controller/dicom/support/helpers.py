import os
from pathlib import Path
from queue import Queue

from pydicom import Dataset
from pydicom.data import get_testdata_file

from anonymizer.controller.project import (
    ExportPatientsRequest,
    ExportPatientsResponse,
    MoveStudiesRequest,
    ProjectController,
    StudyUIDHierarchy,
)
from anonymizer.model.project import DICOMNode

# DICOM NODES involved in tests:
from tests.controller.dicom.support.test_nodes import LocalStorageSCP, PACSSimulatorSCP  # , OrthancSCP

# from anonymizer.model.project import ProjectModel


# TEST HELPER FUNCTION
def pacs_storage_dir(temp_dir: str):
    return Path(temp_dir, PACSSimulatorSCP.aet)


def send_file_to_scp(pydicom_test_filename: str, scp: DICOMNode, controller: ProjectController) -> Dataset:
    # Use test data which comes with pydicom,
    # if not found, get_testdata_file() will try and download it
    ds = get_testdata_file(pydicom_test_filename, read=True)
    assert isinstance(ds, Dataset)
    assert ds
    # assert ds.PatientID
    dcm_file_path = str(get_testdata_file(pydicom_test_filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)
    files_sent = controller.send(
        [dcm_file_path],
        scp.aet,
    )
    assert files_sent == 1
    return ds


def send_files_to_scp(
    pydicom_test_filenames: list[str],
    scp: DICOMNode,
    controller: ProjectController,
) -> list[Dataset]:
    # Read datasets from test data which comes with pydicom to return to caller
    datasets: list[Dataset] = [get_testdata_file(filename, read=True) for filename in pydicom_test_filenames]  # type: ignore
    assert all(isinstance(item, Dataset) for item in datasets)
    assert datasets[0]
    assert datasets[0].PatientID
    paths = [str(get_testdata_file(filename)) for filename in pydicom_test_filenames]
    assert paths
    files_sent = controller.send(
        paths,
        scp.aet,
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


def request_to_move_studies_from_scp_to_local_scp(
    level: str, studies: list[StudyUIDHierarchy], scp: DICOMNode, controller: ProjectController
) -> bool:
    req: MoveStudiesRequest = MoveStudiesRequest(
        scp_name=scp.aet, dest_scp_ae=LocalStorageSCP.aet, level=level, studies=studies
    )
    controller.move_studies_ex(mr=req)
    return True


def verify_files_sent_to_pacs_simulator(dsets: list[Dataset], tempdir: str, controller: ProjectController):
    # Check naming convention of files on PACS
    dirlist = sorted(os.listdir(pacs_storage_dir(tempdir)))
    assert len(dirlist) == len(dsets)
    assert (dirlist[i] == f"{dsets[i].SeriesInstanceUID}.{dsets[i].InstanceNumber}.dcm" for i in range(len(dirlist)))

    # TODO: read file from pacs directory and check dataset equivalence against the sent dataset
    # TODO: cater for change in SOP class due to compression / transcoding if implemented

    # Check find results (study query model) match relevant tallys from response
    results = find_all_studies_on_pacs_simulator_scp(controller)
    assert results

    dset_study_uids = list(set([inst.StudyInstanceUID for inst in dsets if hasattr(inst, "StudyInstanceUID")]))
    assert len(results) == len(dset_study_uids)

    # create result dictionary with key StudyInstanceUID
    result_dict = {result.StudyInstanceUID: result for result in results}

    # Check fields of image instance against find results:
    for dset in dsets:
        assert dset.StudyInstanceUID in result_dict
        result = result_dict[dset.StudyInstanceUID]

        assert result.PatientName == dset.PatientName
        assert result.PatientID == dset.PatientID
        assert result.StudyInstanceUID == dset.StudyInstanceUID

        if hasattr(dset, "StudyDescription"):
            assert result.StudyDescription == dset.StudyDescription
        assert result.StudyDate == dset.StudyDate
        if hasattr(result, "ModalitiesInStudy"):
            assert dset.Modality in result.ModalitiesInStudy


def export_patients_from_local_storage_to_test_pacs(patient_ids: list[str], controller) -> bool:
    ux_Q: Queue[ExportPatientsResponse] = Queue()
    req: ExportPatientsRequest = ExportPatientsRequest(PACSSimulatorSCP.aet, patient_ids, ux_Q)
    controller.export_patients_ex(req)
    export_count = 0
    while export_count != len(patient_ids):
        try:
            resp: ExportPatientsResponse = ux_Q.get(timeout=6)
            assert not resp.error

            if resp.complete:
                export_count += 1

        except Exception:  # timeout reading ux_Q
            return False

    return True


def cxr_paths() -> list[str]:
    """Davidson CXR fixture path(s) under assets/test_dcm_files."""
    from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

    path = (
        CONTROLLER_TEST_DCM_FILES_DIR
        / "davidson_cxr"
        / "davidson_cxr_monochrome1_uncompressed.dcm"
    )
    assert path.is_file(), f"Missing CXR fixture: {path}"
    return [str(path)]


def ct_head_paths() -> list[str]:
    """CT Head With Contrast series DICOM paths under assets/test_dcm_files."""
    from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

    series_dir = CONTROLLER_TEST_DCM_FILES_DIR / "CT_Head_With_Contrast"
    paths = sorted(p for p in series_dir.glob("*.dcm") if p.is_file())
    assert paths, f"Missing CT fixtures in {series_dir}"
    return [str(p) for p in paths]


def send_paths_to_scp(paths: list[str], scp: DICOMNode, controller: ProjectController) -> int:
    """C-STORE or STOW (depending on remote.dicomweb) a list of absolute DICOM paths."""
    from pydicom import dcmread
    from pynetdicom.presentation import build_context

    assert paths
    for path in paths:
        assert os.path.exists(path), path

    node = controller.model.remote_scps.get(scp.aet, scp)
    if getattr(node, "dicomweb", False):
        sent = controller.send(paths, scp.aet)
        assert sent == len(paths)
        return sent

    # DIMSE: negotiate SOPClass+TransferSyntax for each file (covers JPEG 2000 CT fixtures).
    contexts = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        ds = dcmread(path, stop_before_pixels=True)
        sop = str(ds.SOPClassUID)
        ts = str(ds.file_meta.TransferSyntaxUID)
        key = (sop, ts)
        if key not in seen:
            seen.add(key)
            contexts.append(build_context(sop, ts))
            if ts not in controller.model.transfer_syntaxes:
                controller.model.transfer_syntaxes = list(controller.model.transfer_syntaxes) + [ts]
    # Refresh local SCP contexts so C-GET/MOVE can receive compressed instances.
    controller.set_radiology_storage_contexts()

    sent = controller.send(paths, scp.aet, send_contexts=contexts)
    assert sent == len(paths)
    return sent


def ensure_compressed_transfer_syntaxes(controller: ProjectController) -> None:
    """Allow JPEG 2000 (and similar) on the local SCP for Orthanc retrieve tests."""
    extra = [
        "1.2.840.10008.1.2.4.90",  # JPEG 2000 Lossless
        "1.2.840.10008.1.2.4.91",  # JPEG 2000
    ]
    current = list(controller.model.transfer_syntaxes)
    for uid in extra:
        if uid not in current:
            current.append(uid)
    controller.model.transfer_syntaxes = current
    controller.set_radiology_storage_contexts()
