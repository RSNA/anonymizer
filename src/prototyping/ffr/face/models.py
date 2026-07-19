from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk


@dataclass(frozen=True)
class FaceVolumeData:
    """Aligned HU volumes and boolean face mask (Z, Y, X) in stack order."""

    hu_before: np.ndarray
    hu_after: np.ndarray
    mask: np.ndarray
    slice_paths: tuple[Path, ...]
    volume_img: sitk.Image


@dataclass(frozen=True)
class QaStats:
    max_abs_diff_outside: float
    n_violating_voxels: int
    n_outside_voxels: int
    n_face_voxels: int
    mean_abs_diff_inside: float

    @property
    def outside_clean(self) -> bool:
        return self.n_violating_voxels == 0
