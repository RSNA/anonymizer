"""Tests for Export DICOM-SEG conversion switch."""

from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import numpy as np
import SimpleITK as sitk
from pydicom import dcmread
from pydicom.uid import SegmentationStorage

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image
from anonymizer.controller.annotations import (
    add_user_label,
    build_dicom_seg_export_session,
    count_exportable_segment_labels,
    count_patient_exportable_segment_labels,
    save_annotate_session,
    stamp_brush,
)
from anonymizer.controller.annotations.store import load_annotate_session
from anonymizer.controller.project import ExportPatientsRequest, ProjectController
from anonymizer.view.project.export import _count_patient_images_excluding_seg


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


def _write_annotation_volume(cache_dir: Path, shape_zyx: tuple[int, int, int] = (4, 16, 16)) -> sitk.Image:
    cache_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(cache_dir / "volume.nii.gz"), True)
    (cache_dir / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(img)) + "\n", encoding="utf-8"
    )
    return img


def _write_ts_binary_mask(
    cache_dir: Path,
    stem: str,
    shape_zyx: tuple[int, int, int] = (4, 16, 16),
    *,
    y0: int = 4,
    y1: int = 12,
    x0: int = 4,
    x1: int = 12,
) -> None:
    seg_dir = cache_dir / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    z, y, x = shape_zyx
    arr = np.zeros((z, y, x), dtype=np.uint8)
    arr[min(1, z - 1), y0:y1, x0:x1] = 1
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing((1.0, 1.0, 1.0))
    img.SetOrigin((0.0, 0.0, 0.0))
    sitk.WriteImage(img, str(seg_dir / f"{stem}.nii.gz"), True)


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
    ds = dcmread(str(seg_path), force=True)
    assert str(ds.SOPClassUID) == "1.2.840.10008.5.1.4.1.1.66.4"


def test_prepare_patient_dicom_segs_from_ts_masks_only(tmp_path: Path) -> None:
    """Brain/TS ``seg/`` masks alone (no annotations/) must produce DICOM-SEG."""
    patient = tmp_path / "PAT1"
    series = patient / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    (series / "slice.dcm").write_bytes(b"not-a-real-dicom")
    cache = resolve_series_cache_dir(series)
    _write_annotation_volume(cache)
    _write_ts_binary_mask(cache, "brain", y0=2, y1=8, x0=2, x1=8)
    _write_ts_binary_mask(cache, "frontal_lobe", y0=8, y1=14, x0=8, x1=14)
    # Face blur mask must not be required / must be skipped.
    _write_ts_binary_mask(cache, "face", y0=0, y1=4, x0=0, x1=4)

    assert not (cache / "annotations").exists()
    export_session = build_dicom_seg_export_session(cache)
    assert export_session is not None
    names = {entry.name for entry in export_session.label_map.values()}
    assert "brain" in names
    assert "frontal_lobe" in names
    assert "face" not in names

    stub = type("Stub", (), {"ROI_SEG_FILENAME": ProjectController.ROI_SEG_FILENAME})()
    ProjectController._prepare_patient_dicom_segs(stub, patient)

    seg_path = series / ProjectController.ROI_SEG_FILENAME
    assert seg_path.is_file()
    ds = dcmread(str(seg_path), force=True)
    assert str(ds.SOPClassUID) == str(SegmentationStorage)
    assert str(ds.Modality) == "SEG"
    assert str(ds.ContentLabel) == "ANATOMY_SEG"
    segment_labels = {str(item.SegmentLabel) for item in ds.SegmentSequence}
    assert "brain" in segment_labels
    assert "frontal_lobe" in segment_labels
    assert "face" not in segment_labels
    assert all(str(item.SegmentAlgorithmType) == "AUTOMATIC" for item in ds.SegmentSequence)


def test_dicom_seg_iod_compliance_referenced_series_and_dimensions(tmp_path: Path) -> None:
    """SEG export includes ImageType, ReferencedSeriesSequence, and dimension indexes."""
    import shutil

    from anonymizer.controller.ai.tseg.dicom_geometry import (
        build_sitk_volume_from_series_frames,
        stackable_dicom_paths,
    )
    from anonymizer.controller.ai.tseg.seg_retention import MASK_GEOMETRY_FILENAME, mask_geometry_from_image
    from anonymizer.controller.annotations import export_dicom_seg
    from anonymizer.controller.series_io import load_series_frames
    from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

    fixture = CONTROLLER_TEST_DCM_FILES_DIR / "CT_Head_With_Contrast"
    if not fixture.is_dir():
        pytest.skip("CT_Head_With_Contrast fixture missing")

    source_paths = stackable_dicom_paths(fixture)
    assert len(source_paths) >= 3
    n_slices = 5 if len(source_paths) >= 5 else len(source_paths)

    series_dir = tmp_path / "PAT" / "STUDY" / "SERIES"
    series_dir.mkdir(parents=True)
    for path in source_paths[:n_slices]:
        shutil.copy(path, series_dir / path.name)

    loaded = load_series_frames(series_dir)
    volume = build_sitk_volume_from_series_frames(loaded.metadata, loaded.frames, loaded.slice_paths)
    z = int(volume.GetSize()[2])
    rows = int(volume.GetSize()[1])
    cols = int(volume.GetSize()[0])
    assert z == n_slices

    cache = resolve_series_cache_dir(series_dir)
    cache.mkdir(parents=True)
    sitk.WriteImage(volume, str(cache / "volume.nii.gz"), True)
    (cache / MASK_GEOMETRY_FILENAME).write_text(
        json.dumps(mask_geometry_from_image(volume)) + "\n", encoding="utf-8"
    )
    mask = np.zeros((z, rows, cols), dtype=np.uint8)
    mid = z // 2
    mask[mid, rows // 4 : rows // 2, cols // 4 : cols // 2] = 1
    mask_img = sitk.GetImageFromArray(mask)
    mask_img.CopyInformation(volume)
    (cache / "seg").mkdir(parents=True)
    sitk.WriteImage(mask_img, str(cache / "seg" / "brain.nii.gz"), True)

    dest = series_dir / ProjectController.ROI_SEG_FILENAME
    export_dicom_seg(cache, dest, series_dir=series_dir)
    ds = dcmread(str(dest), force=True)

    assert str(ds.SOPClassUID) == str(SegmentationStorage)
    assert list(ds.ImageType)[:2] == ["DERIVED", "PRIMARY"]
    assert str(ds.SegmentationType) == "BINARY"
    assert not hasattr(ds, "MaximumFractionalValue")

    assert hasattr(ds, "ReferencedSeriesSequence")
    assert len(ds.ReferencedSeriesSequence) == 1
    ref_series = ds.ReferencedSeriesSequence[0]
    first_src = dcmread(str(source_paths[0]), stop_before_pixels=True, force=True)
    assert str(ref_series.SeriesInstanceUID) == str(first_src.SeriesInstanceUID)
    assert len(ref_series.ReferencedInstanceSequence) == n_slices

    assert hasattr(ds, "DimensionOrganizationSequence")
    assert len(ds.DimensionOrganizationSequence) == 1
    assert hasattr(ds, "DimensionIndexSequence")
    assert len(ds.DimensionIndexSequence) == 2
    assert ds.DimensionIndexSequence[0].DimensionIndexPointer == (0x0062, 0x000B)
    assert ds.DimensionIndexSequence[1].DimensionIndexPointer == (0x0020, 0x0032)

    assert int(ds.NumberOfFrames) == 1  # only mid-slice has voxels
    fg = ds.PerFrameFunctionalGroupsSequence[0]
    assert hasattr(fg, "FrameContentSequence")
    assert list(fg.FrameContentSequence[0].DimensionIndexValues) == [1, mid + 1]
    assert int(fg.SegmentIdentificationSequence[0].ReferencedSegmentNumber) == 1
    assert hasattr(fg, "PlanePositionSequence")
    assert hasattr(fg, "DerivationImageSequence")
    src = fg.DerivationImageSequence[0].SourceImageSequence[0]
    mid_src = dcmread(str(source_paths[mid]), stop_before_pixels=True, force=True)
    assert str(src.ReferencedSOPInstanceUID) == str(mid_src.SOPInstanceUID)


def test_count_exportable_segment_labels_dedupes_and_skips_face(tmp_path: Path) -> None:
    series = tmp_path / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    cache = resolve_series_cache_dir(series)
    _write_annotation_volume(cache)
    session = load_annotate_session(cache)
    assert session is not None
    entry = add_user_label(session, "brain")
    stamp_brush(session.labels, slice_index=1, cy=8, cx=8, radius=2, value=entry.label_id)
    save_annotate_session(session)
    _write_ts_binary_mask(cache, "brain", y0=2, y1=8, x0=2, x1=8)
    _write_ts_binary_mask(cache, "frontal_lobe", y0=8, y1=14, x0=8, x1=14)
    _write_ts_binary_mask(cache, "face", y0=0, y1=4, x0=0, x1=4)

    # User "brain" + TS brain share one name; frontal_lobe adds one; face skipped.
    assert count_exportable_segment_labels(cache) == 2
    patient = tmp_path
    assert count_patient_exportable_segment_labels(patient) == 2


def test_count_patient_images_excluding_seg(tmp_path: Path) -> None:
    series = tmp_path / "PAT1" / "STUDY1" / "SERIES1"
    series.mkdir(parents=True)
    (series / "img1.dcm").write_bytes(b"x")
    (series / "img2.dcm").write_bytes(b"x")
    (series / ProjectController.ROI_SEG_FILENAME).write_bytes(b"seg")
    studies, series_n, images = _count_patient_images_excluding_seg(tmp_path / "PAT1")
    assert studies == 1
    assert series_n >= 1
    assert images == 2


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
