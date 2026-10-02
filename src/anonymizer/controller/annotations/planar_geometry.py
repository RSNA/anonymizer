"""Pixel-space annotation grids for planar CR/DX/US/MG (no stackable IOP/IPP)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from pydicom import Dataset, dcmread
from pydicom.errors import InvalidDicomError

from anonymizer.controller.ai.tseg.seg_retention import (
    MASK_GEOMETRY_FILENAME,
    mask_geometry_from_image,
)

logger = logging.getLogger(__name__)

PLANAR_PIXEL_SPACE = "planar_pixel_space"
GRID_KEY = "grid"


def frames_to_grayscale_zyx(frames: np.ndarray) -> np.ndarray:
    """Convert Series View frames to a grayscale ``(Z, Y, X)`` array for SITK volume."""
    arr = np.asarray(frames)
    if arr.ndim == 3:
        return arr.astype(np.float32, copy=False)
    if arr.ndim == 4 and arr.shape[-1] >= 3:
        # Rec. 601 luminance; ignore alpha if present.
        rgb = arr[..., :3].astype(np.float32, copy=False)
        return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    if arr.ndim == 4 and arr.shape[-1] == 1:
        return arr[..., 0].astype(np.float32, copy=False)
    raise ValueError(f"Unsupported frame shape for planar annotation volume: {arr.shape}")


def _row_col_spacing_mm(metadata: Dataset) -> tuple[float, float]:
    for attr in ("PixelSpacing", "ImagerPixelSpacing"):
        values = getattr(metadata, attr, None)
        if values is None:
            continue
        try:
            row_mm, col_mm = float(values[0]), float(values[1])
            if row_mm > 0 and col_mm > 0:
                return row_mm, col_mm
        except (TypeError, ValueError, IndexError):
            continue
    return 1.0, 1.0


def _slice_spacing_mm(metadata: Dataset) -> float:
    for attr in ("SpacingBetweenSlices", "SliceThickness"):
        value = getattr(metadata, attr, None)
        if value is None:
            continue
        try:
            spacing = float(value)
            if spacing > 0:
                return spacing
        except (TypeError, ValueError):
            continue
    return 1.0


def build_planar_sitk_volume(metadata: Dataset, frames: np.ndarray) -> sitk.Image:
    """Build a pixel-space SimpleITK volume aligned to Series View frame stack."""
    gray = frames_to_grayscale_zyx(frames)
    if gray.ndim != 3 or gray.shape[0] < 1:
        raise ValueError(f"Expected non-empty grayscale stack (Z,Y,X), got {gray.shape}")

    image = sitk.GetImageFromArray(gray)
    row_mm, col_mm = _row_col_spacing_mm(metadata)
    image.SetSpacing((col_mm, row_mm, _slice_spacing_mm(metadata)))

    ipp = getattr(metadata, "ImagePositionPatient", None)
    iop = getattr(metadata, "ImageOrientationPatient", None)
    if ipp is not None and iop is not None and len(iop) >= 6:
        try:
            image.SetOrigin([float(v) for v in ipp])
            row_dir = [float(v) for v in iop[:3]]
            col_dir = [float(v) for v in iop[3:6]]
            # Slice direction = row × col (LPS).
            slice_dir = [
                row_dir[1] * col_dir[2] - row_dir[2] * col_dir[1],
                row_dir[2] * col_dir[0] - row_dir[0] * col_dir[2],
                row_dir[0] * col_dir[1] - row_dir[1] * col_dir[0],
            ]
            # ITK direction columns = DICOM row, column, slice.
            image.SetDirection(
                (
                    row_dir[0],
                    col_dir[0],
                    slice_dir[0],
                    row_dir[1],
                    col_dir[1],
                    slice_dir[1],
                    row_dir[2],
                    col_dir[2],
                    slice_dir[2],
                )
            )
            return image
        except (TypeError, ValueError, IndexError):
            logger.debug("Planar volume falling back to identity patient space", exc_info=True)

    image.SetOrigin((0.0, 0.0, 0.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    return image


def write_planar_annotation_geometry(cache_dir: Path, volume: sitk.Image) -> Path:
    """Persist ``volume.nii.gz`` and ``mask_geometry.json`` marked as planar pixel space."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(volume, str(cache_dir / "volume.nii.gz"), True)
    payload = mask_geometry_from_image(volume)
    payload[GRID_KEY] = PLANAR_PIXEL_SPACE
    geometry_path = cache_dir / MASK_GEOMETRY_FILENAME
    geometry_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return geometry_path


def is_planar_pixel_space_geometry(cache_dir: Path) -> bool:
    """True when ``mask_geometry.json`` was created for planar CR/DX/US/MG annotation."""
    from anonymizer.controller.ai.tseg.seg_retention import read_mask_geometry

    geometry = read_mask_geometry(Path(cache_dir))
    if not geometry:
        return False
    return str(geometry.get(GRID_KEY, "") or "") == PLANAR_PIXEL_SPACE


def _instance_number_sort_key(path: Path) -> int:
    try:
        header = dcmread(str(path), stop_before_pixels=True, force=True)
        return int(header.get("InstanceNumber", 999999))
    except (ValueError, TypeError, InvalidDicomError, OSError):
        return 999999


def annotation_source_dicom_paths(series_dir: Path) -> list[Path]:
    """DICOM paths in Series View frame order (one entry per display frame).

    Prefers stackable slice listing when available; otherwise expands multi-frame
    instances the same way ``load_series_frames`` does.
    """
    from anonymizer.controller.ai.tseg.dicom_geometry import stackable_dicom_paths
    from anonymizer.utils.storage import get_dcm_files

    series_dir = Path(series_dir)
    try:
        return stackable_dicom_paths(series_dir)
    except ValueError:
        pass

    try:
        paths = sorted(get_dcm_files(series_dir), key=_instance_number_sort_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list DICOM files in %s: %s", series_dir, exc)
        return []

    expanded: list[Path] = []
    for path in paths:
        try:
            header = dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception:  # noqa: BLE001
            continue
        frames = int(getattr(header, "NumberOfFrames", 1) or 1)
        if frames < 1:
            frames = 1
        expanded.extend([Path(path)] * frames)
    return expanded
