"""Tests for Export DICOM-SEG conversion switch."""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.annotations import add_user_label, save_annotate_session, stamp_brush
from anonymizer.controller.annotations.store import load_annotate_session
from anonymizer.controller.project import ExportPatientsRequest, ProjectController


def test_export_patients_request_default_dicom_seg_off() -> None:
    req = ExportPatientsRequest(dest_name="EXPORT", patient_ids=["p1"], ux_Q=Queue())
    assert req.export_dicom_seg is False


def test_export_patients_request_accepts_dicom_seg_flag() -> None:
    req = ExportPatientsRequest(
        dest_name="EXPORT",
        patient_ids=["p1"],
        ux_Q=Queue(),
        export_dicom_seg=True,
    )
    assert req.export_dicom_seg is True


def _write_annotation_volume(cache_dir: Path, shape_zyx: tuple[int, int, int] = (4, 16, 16)) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image
    import json

    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(img)) + "\n", encoding="utf-8"
    )


def test_prepare_patient_dicom_segs_writes_file(tmp_path: Path) -> None:
    patient = tmp_path / "PAT1"
    series = patient / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    (series / "slice.dcm").write_bytes(b"not-a-real-dicom")
    cache = resolve_series_cache_dir(series)
    _write_annotation_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "lesion")
    stamp_brush(session.labels, slice_index=1, cy=8, cx=8, radius=3, value=entry.label_id)
    save_annotate_session(session)

    stub = type("Stub", (), {"ROI_SEG_FILENAME": ProjectController.ROI_SEG_FILENAME})()
    ProjectController._prepare_patient_dicom_segs(stub, patient)

    seg_path = series / ProjectController.ROI_SEG_FILENAME
    assert seg_path.is_file()
    from pydicom import dcmread

    ds = dcmread(str(seg_path), force=True)
    assert str(ds.SOPClassUID) == "1.2.840.10008.5.1.4.1.1.66.4"


def test_export_patient_skips_seg_when_flag_off(tmp_path: Path) -> None:
    patient = tmp_path / "PAT1"
    series = patient / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    # Minimal fake dcm so walk finds something; export will fail on read — we only assert prepare not called.
    (series / "1.2.3.dcm").write_bytes(b"x")

    controller = MagicMock()
    controller.model = MagicMock()
    controller.model.images_dir.return_value = tmp_path
    controller.model.export_to_AWS = True
    controller._abort_export = False
    controller._export_file_time_slice_interval = 0
    controller._aws_user_directory = "user"
    controller.AWS_get_instances.return_value = []
    controller.AWS_authenticate.return_value = MagicMock()
    controller._prepare_patient_dicom_segs = MagicMock()

    ux_Q: Queue = Queue()
    # AWS path will try upload — mock upload_file via authenticate return
    s3 = controller.AWS_authenticate.return_value
    s3.upload_file = MagicMock()

    ProjectController._export_patient(controller, "AWS", "PAT1", ux_Q, export_dicom_seg=False)
    controller._prepare_patient_dicom_segs.assert_not_called()


def test_export_patient_calls_prepare_when_flag_on(tmp_path: Path) -> None:
    patient = tmp_path / "PAT1"
    series = patient / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    (series / "1.2.3.dcm").write_bytes(b"x")

    controller = MagicMock()
    controller.model = MagicMock()
    controller.model.images_dir.return_value = tmp_path
    controller.model.export_to_AWS = True
    controller.model.aws_cognito.s3_prefix = "private"
    controller.model.aws_cognito.s3_bucket = "bucket"
    controller.model.project_name = "proj"
    controller._abort_export = False
    controller._export_file_time_slice_interval = 0
    controller._aws_user_directory = "user"
    controller.AWS_get_instances.return_value = []
    s3 = MagicMock()
    controller.AWS_authenticate.return_value = s3
    controller._prepare_patient_dicom_segs = MagicMock()

    ux_Q: Queue = Queue()
    ProjectController._export_patient(controller, "AWS", "PAT1", ux_Q, export_dicom_seg=True)
    controller._prepare_patient_dicom_segs.assert_called_once()
    called_dir = controller._prepare_patient_dicom_segs.call_args[0][0]
    assert Path(called_dir) == patient
