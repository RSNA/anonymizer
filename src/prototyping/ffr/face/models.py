from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.blur_face import QaStats


@dataclass(frozen=True)
class FaceVolumeData:
    """Aligned HU volumes and boolean face mask (Z, Y, X) — viz POC only."""

    hu_before: np.ndarray
    hu_after: np.ndarray
    mask: np.ndarray
    slice_paths: tuple[Path, ...]
    volume_img: sitk.Image


__all__ = ["FaceVolumeData", "QaStats"]
