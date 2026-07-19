from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk
from pydicom import dcmread

from anonymizer.controller.tseg.dicom_geometry import sorted_dicom_paths


def read_reference_volume(series_directory: Path) -> tuple[sitk.Image, tuple[Path, ...]]:
    """Build 3D SimpleITK volume in stack order (same ordering as tseg)."""
    series_directory = Path(series_directory).resolve()
    paths = tuple(sorted_dicom_paths(series_directory))
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames([str(path) for path in paths])
    volume = reader.Execute()
    return volume, paths


def align_mask_to_volume(mask_path: Path, volume: sitk.Image) -> sitk.Image:
    mask_path = Path(mask_path).resolve()
    mask = sitk.ReadImage(str(mask_path))
    same_geometry = (
        mask.GetSize() == volume.GetSize()
        and mask.GetSpacing() == volume.GetSpacing()
        and mask.GetOrigin() == volume.GetOrigin()
        and mask.GetDirection() == volume.GetDirection()
    )
    if same_geometry:
        return mask

    resampler = sitk.ResampleImageFilter()
    resampler.SetReferenceImage(volume)
    resampler.SetInterpolator(sitk.sitkNearestNeighbor)
    resampler.SetDefaultPixelValue(0)
    return resampler.Execute(mask)


def mask_array_from_volume(mask_image: sitk.Image) -> np.ndarray:
    array = sitk.GetArrayFromImage(mask_image)
    return array > 0


def load_hu_stack(slice_paths: tuple[Path, ...]) -> np.ndarray:
    """Load per-slice HU in the same order as ``sorted_dicom_paths``."""
    slices: list[np.ndarray] = []
    for path in slice_paths:
        ds = dcmread(str(path))
        pixels = ds.pixel_array.astype(np.float64)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        slices.append(pixels * slope + intercept)
    return np.stack(slices, axis=0)


def face_slice_indices(mask: np.ndarray) -> tuple[int, ...]:
    """Slice indices where the mask is non-empty, plus quartiles for thumbnails."""
    z_with_face = np.flatnonzero(mask.any(axis=(1, 2)))
    if z_with_face.size == 0:
        return (mask.shape[0] // 2,)
    z_min = int(z_with_face[0])
    z_max = int(z_with_face[-1])
    mid = int(z_with_face[len(z_with_face) // 2])
    q1 = int(z_with_face[len(z_with_face) // 4])
    q3 = int(z_with_face[(3 * len(z_with_face)) // 4])
    unique = sorted({z_min, q1, mid, q3, z_max})
    return tuple(unique)
