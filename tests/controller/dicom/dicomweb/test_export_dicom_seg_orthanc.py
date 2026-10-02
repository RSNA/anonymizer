"""Orthanc dicom_integration: export patient with DICOM-SEG (TS seg masks) via STOW-RS."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from queue import Queue

import numpy as np
import pytest
import requests
import SimpleITK as sitk
from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.uid import SegmentationStorage

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image
from anonymizer.controller.project import ExportPatientsResponse, ProjectController
from tests.controller.dicom.support.orthanc import enable_orthanc_dicomweb_remote, wipe_orthanc
from tests.controller.dicom.support.orthanc_bundle import (
    HTTP_PORT,
    ORTHANC_PASSWORD,
    ORTHANC_USER,
    ManagedOrthanc,
)
from tests.controller.dicom.support.test_nodes import OrthancSCP


def _write_volume_and_brain_mask(cache_dir: Path, shape_zyx: tuple[int, int, int]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    vol = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(vol)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(img)) + "\n", encoding="utf-8"
    )
    seg_dir = cache_dir / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((z, y, x), dtype=np.uint8)
    mask[0, y // 4 : y // 2, x // 4 : x // 2] = 1
    mask_img = sitk.GetImageFromArray(mask)
    mask_img.CopyInformation(img)
    sitk.WriteImage(mask_img, str(seg_dir / "brain.nii.gz"), True)


@pytest.mark.dicom_integration
def test_export_patient_dicom_seg_to_orthanc(
    controller: ProjectController,
    managed_orthanc: ManagedOrthanc,
) -> None:
    """TS ``seg/`` masks alone produce DICOM-SEG; Orthanc STOW stores CT + SEG."""
    wipe_orthanc(managed_orthanc)
    enable_orthanc_dicomweb_remote(controller, managed_orthanc)
    controller.model.export_to_AWS = False
    controller._export_file_time_slice_interval = 0
    controller._abort_export = False

    src = get_testdata_file("CT_small.dcm")
    assert src
    ds = dcmread(src)
    patient_id = str(ds.PatientID)
    study_uid = str(ds.StudyInstanceUID)
    series_uid = str(ds.SeriesInstanceUID)
    rows, cols = int(ds.Rows), int(ds.Columns)

    series_dir = Path(controller.model.images_dir()) / patient_id / study_uid / series_uid
    series_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, series_dir / f"{ds.SOPInstanceUID}.dcm")

    cache = resolve_series_cache_dir(series_dir)
    _write_volume_and_brain_mask(cache, (1, rows, cols))
    assert not (cache / "annotations").exists()

    ux_Q: Queue = Queue()
    ProjectController._export_patient(
        controller,
        OrthancSCP.aet,
        patient_id,
        ux_Q,
        export_dicom_seg=True,
    )

    responses: list[ExportPatientsResponse] = []
    while not ux_Q.empty():
        responses.append(ux_Q.get_nowait())
    assert responses, "export produced no UX responses"
    final = responses[-1]
    assert final.complete
    assert final.error is None, final.error
    assert final.files_sent >= 2, f"expected CT+SEG, got files_sent={final.files_sent}"

    seg_local = series_dir / ProjectController.ROI_SEG_FILENAME
    assert seg_local.is_file()
    seg_ds = dcmread(str(seg_local), force=True)
    assert str(seg_ds.SOPClassUID) == str(SegmentationStorage)
    assert str(seg_ds.Modality) == "SEG"
    seg_sop = str(seg_ds.SOPInstanceUID)

    auth = (ORTHANC_USER, ORTHANC_PASSWORD)
    base = f"http://127.0.0.1:{HTTP_PORT}"
    instances = requests.get(f"{base}/instances", auth=auth, timeout=10)
    assert instances.status_code == 200
    found_seg = False
    for iid in instances.json():
        tags = requests.get(f"{base}/instances/{iid}/simplified-tags", auth=auth, timeout=10)
        assert tags.status_code == 200
        payload = tags.json()
        if payload.get("SOPInstanceUID") == seg_sop or payload.get("Modality") == "SEG":
            assert payload.get("Modality") == "SEG"
            found_seg = True
            break
    assert found_seg, "DICOM-SEG was not stored on Orthanc"
