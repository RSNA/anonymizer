from __future__ import annotations

import logging
from pathlib import Path

from prototyping.ffr.face.blur import blur_face_hu_volume
from prototyping.ffr.face.config import DEFAULT_FACE_BLUR_SIGMA_MM
from prototyping.ffr.face.export_dicom import write_blurred_dicom_series
from prototyping.ffr.face.mask_source import resolve_face_mask_path
from prototyping.ffr.face.models import FaceVolumeData
from prototyping.ffr.face.qa import compute_qa_stats
from prototyping.ffr.face.report import write_report
from prototyping.ffr.face.viz import render_all_modes
from prototyping.ffr.face.volume import (
    align_mask_to_volume,
    face_slice_indices,
    load_hu_stack,
    mask_array_from_volume,
    read_reference_volume,
)

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_CENTER = 40.0
DEFAULT_WINDOW_WIDTH = 400.0


def run_face_viz_poc(series_directory: Path) -> Path:
    """
    Load series + face mask, blur in memory, render QA viz modes.

Face mask is read from ``<series>/0_TS_SEG/seg/face.nii.gz``.
    If missing, ``analyze_tseg_face`` runs when TotalSegmentator is available.

    Returns path to ``ts_seg/viz_poc/report.html``. Also writes blurred DICOM to
    ``<series>/face_blurred/``.
    """
    series_directory = Path(series_directory).resolve()
    mask_path = resolve_face_mask_path(series_directory)

    viz_dir = series_directory / "ts_seg" / "viz_poc"
    logger.info("Loading reference volume and mask …")
    volume_img, slice_paths = read_reference_volume(series_directory)
    mask_img = align_mask_to_volume(mask_path, volume_img)
    mask = mask_array_from_volume(mask_img)

    logger.info("Loading HU stack (%d slices) …", len(slice_paths))
    hu_before = load_hu_stack(slice_paths)

    if hu_before.shape != mask.shape:
        raise ValueError(
            f"HU stack shape {hu_before.shape} != mask shape {mask.shape} after alignment"
        )

    spacing = volume_img.GetSpacing()
    pixel_spacing_mm = (float(spacing[1]), float(spacing[0]))

    logger.info("Applying in-plane face blur (preview) …")
    hu_after = blur_face_hu_volume(
        hu_before,
        mask,
        sigma_mm=DEFAULT_FACE_BLUR_SIGMA_MM,
        pixel_spacing_mm=pixel_spacing_mm,
    )

    stats = compute_qa_stats(hu_before, hu_after, mask)
    logger.info(
        "QA outside mask: max|diff|=%.6g violating_voxels=%d / %d (%s)",
        stats.max_abs_diff_outside,
        stats.n_violating_voxels,
        stats.n_outside_voxels,
        "PASS" if stats.outside_clean else "FAIL",
    )

    if not stats.outside_clean:
        logger.warning("QA FAIL: blur changed voxels outside face mask")

    dicom_out = series_directory / "face_blurred"
    logger.info("Writing blurred DICOM series → %s", dicom_out)
    write_blurred_dicom_series(hu_after, slice_paths, dicom_out)

    data = FaceVolumeData(
        hu_before=hu_before,
        hu_after=hu_after,
        mask=mask,
        slice_paths=slice_paths,
        volume_img=volume_img,
    )
    slice_indices = face_slice_indices(mask)
    primary_z = slice_indices[len(slice_indices) // 2]

    logger.info("Rendering visualization modes → %s", viz_dir)
    rendered = render_all_modes(
        data,
        stats,
        viz_dir,
        slice_index=primary_z,
        window_center=DEFAULT_WINDOW_CENTER,
        window_width=DEFAULT_WINDOW_WIDTH,
    )

    report_path = write_report(viz_dir, rendered, stats, series_dir=series_directory)
    pdf_path = viz_dir / "report.pdf"
    logger.info("Report: %s", report_path)
    logger.info("Report PDF: %s", pdf_path)
    logger.info("Blurred DICOM: %s", dicom_out)
    return report_path
