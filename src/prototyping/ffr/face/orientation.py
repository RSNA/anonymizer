from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import SimpleITK as sitk

# DICOM patient LPS basis vectors
_LPS_LEFT = np.array([1.0, 0.0, 0.0])
_LPS_POSTERIOR = np.array([0.0, 1.0, 0.0])
_LPS_SUPERIOR = np.array([0.0, 0.0, 1.0])


@dataclass(frozen=True)
class VolumeAxes:
    """Maps numpy array axes (Z, Y, X) = (0, 1, 2) to patient LPS directions."""

    lr: int
    ap: int
    si: int
    lr_sign: int
    ap_sign: int
    si_sign: int


def array_axis_spacing_mm(volume: sitk.Image, array_axis: int) -> float:
    """Physical spacing (mm) per step along array axis 0=Z, 1=Y, 2=X."""
    spacing = volume.GetSpacing()
    sitk_index = (2, 1, 0)[array_axis]
    return float(spacing[sitk_index])


def array_axis_physical_vector(volume: sitk.Image, array_axis: int) -> np.ndarray:
    """Unit step along array axis (0=Z, 1=Y, 2=X) in LPS mm."""
    delta_zyx = [0.0, 0.0, 0.0]
    delta_zyx[array_axis] = 1.0
    sitk_delta = (delta_zyx[2], delta_zyx[1], delta_zyx[0])
    origin = np.array(volume.TransformContinuousIndexToPhysicalPoint((0.0, 0.0, 0.0)))
    tip = np.array(volume.TransformContinuousIndexToPhysicalPoint(sitk_delta))
    return tip - origin


def classify_volume_axes(volume: sitk.Image) -> VolumeAxes:
    """
    Assign each array dimension to left–right, anterior–posterior, and superior–inferior.

    ``sign`` is +1 when increasing array index moves toward LPS +L, +P, or +S.
    """
    vectors = [array_axis_physical_vector(volume, axis) for axis in range(3)]
    norms = [float(np.linalg.norm(vector)) for vector in vectors]
    unit = [
        vector / norm if norm > 1e-8 else np.zeros(3, dtype=np.float64)
        for vector, norm in zip(vectors, norms, strict=True)
    ]

    lps_targets = (
        ("lr", _LPS_LEFT),
        ("ap", _LPS_POSTERIOR),
        ("si", _LPS_SUPERIOR),
    )
    remaining_axes = [0, 1, 2]
    assigned: dict[str, tuple[int, int]] = {}

    for label, target in lps_targets:
        best_axis = max(
            remaining_axes,
            key=lambda axis: abs(float(np.dot(unit[axis], target))),
        )
        dot = float(np.dot(unit[best_axis], target))
        sign = 1 if dot >= 0 else -1
        assigned[label] = (best_axis, sign)
        remaining_axes.remove(best_axis)

    lr_axis, lr_sign = assigned["lr"]
    ap_axis, ap_sign = assigned["ap"]
    si_axis, si_sign = assigned["si"]
    return VolumeAxes(
        lr=lr_axis,
        ap=ap_axis,
        si=si_axis,
        lr_sign=lr_sign,
        ap_sign=ap_sign,
        si_sign=si_sign,
    )


def array_index_to_physical(volume: sitk.Image, z: float, y: float, x: float) -> tuple[float, float, float]:
    """Map array indices (Z, Y, X) to LPS physical point."""
    point = volume.TransformContinuousIndexToPhysicalPoint((float(x), float(y), float(z)))
    return (float(point[0]), float(point[1]), float(point[2]))


def physical_points_from_array_indices(
    volume: sitk.Image,
    indices_zyx: np.ndarray,
) -> np.ndarray:
    """Convert Nx3 array indices (z, y, x) to Nx3 physical LPS coordinates."""
    out = np.empty_like(indices_zyx, dtype=np.float64)
    for row, (z, y, x) in enumerate(indices_zyx):
        out[row] = array_index_to_physical(volume, z, y, x)
    return out
