"""Orthanc dicom_integration: QIDO-RS / WADO-RS / STOW-RS with managed Orthanc."""

from __future__ import annotations

import os

import pytest
from pydicom import dcmread

from anonymizer.controller.dicom.hierarchies import StudyUIDHierarchy
from anonymizer.controller.dicom.requests import MoveStudiesRequest
from anonymizer.controller.project import ProjectController
from anonymizer.utils.storage import count_studies_series_images
from tests.controller.dicom.support.helpers import (
    ct_head_paths,
    cxr_paths,
    ensure_compressed_transfer_syntaxes,
    send_paths_to_scp,
)
from tests.controller.dicom.support.orthanc import enable_orthanc_dicomweb_remote, wipe_orthanc
from tests.controller.dicom.support.orthanc_bundle import ManagedOrthanc
from tests.controller.dicom.support.test_nodes import LocalStorageSCP, OrthancSCP


def _study_meta(path: str) -> tuple[str, str]:
    ds = dcmread(path, stop_before_pixels=True)
    return str(ds.StudyInstanceUID), str(ds.PatientID)


@pytest.mark.dicom_integration
def test_dicomweb_send_find_import_cxr_ct(
    temp_dir: str,
    controller: ProjectController,
    managed_orthanc: ManagedOrthanc,
) -> None:
    wipe_orthanc(managed_orthanc)
    enable_orthanc_dicomweb_remote(controller, managed_orthanc)
    ensure_compressed_transfer_syntaxes(controller)

    cxr = cxr_paths()
    ct = ct_head_paths()
    # STOW via StoreMixin when remote.dicomweb is set
    send_paths_to_scp(cxr + ct, OrthancSCP, controller)

    cxr_uid, cxr_ptid = _study_meta(cxr[0])
    ct_uid, ct_ptid = _study_meta(ct[0])

    cr_results = controller.find_studies(OrthancSCP.aet, "", "", "", "", "CR", ux_Q=None, verify_attributes=True)
    assert cr_results
    assert cxr_uid in {getattr(r, "StudyInstanceUID", None) for r in cr_results}

    ct_results = controller.find_studies(OrthancSCP.aet, "", "", "", "", "CT", ux_Q=None, verify_attributes=True)
    assert ct_results
    assert ct_uid in {getattr(r, "StudyInstanceUID", None) for r in ct_results}

    studies: list[StudyUIDHierarchy] = []
    for study_uid, ptid in ((cxr_uid, cxr_ptid), (ct_uid, ct_ptid)):
        err, study = controller.get_study_uid_hierarchy(OrthancSCP.aet, study_uid, ptid, True)
        assert err is None, err
        assert study.series
        studies.append(study)

    req = MoveStudiesRequest(
        scp_name=OrthancSCP.aet,
        dest_scp_ae=LocalStorageSCP.aet,
        level="STUDY",
        studies=studies,
    )
    controller.manage_move(req)
    assert controller._last_retrieve_modality == "WADO"
    for study in studies:
        assert controller.get_number_of_pending_instances(study) == 0

    store_dir = controller.model.images_dir()
    dirlist = [d for d in os.listdir(store_dir) if os.path.isdir(os.path.join(store_dir, d))]
    assert len(dirlist) >= 1
    total_images = 0
    for patient_dir in dirlist:
        _, _, n_img = count_studies_series_images(os.path.join(store_dir, patient_dir))
        total_images += n_img
    assert total_images >= 1 + len(ct)
