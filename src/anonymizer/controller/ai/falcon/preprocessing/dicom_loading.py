"""Load stacked CT DICOM slices into a SimpleITK image."""

from __future__ import annotations

from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.ai.tseg.dicom_geometry import read_sitk_volume_from_dicom_paths, stackable_dicom_paths

MIN_DICOM_SLICES = 11


def get_sitk_from_dicom(dicom_dir: Path) -> sitk.Image:
    """
    Load a CT series using the same stack ordering as TotalSegmentator geometry.

    Slices are sorted along the slice normal derived from ``ImageOrientationPatient``,
    filtered to stackable image instances, then loaded with SimpleITK (pydicom fallback).
    """
    dicom_dir = Path(dicom_dir)
    slice_paths = stackable_dicom_paths(dicom_dir)
    if len(slice_paths) < MIN_DICOM_SLICES:
        raise ValueError(f"Found only {len(slice_paths)} slices; need at least {MIN_DICOM_SLICES}")

    image = read_sitk_volume_from_dicom_paths(slice_paths)

    if 0.0 in image.GetSpacing():
        raise ValueError(f"Zero spacing found for series: {image.GetSpacing()}")

    return image
