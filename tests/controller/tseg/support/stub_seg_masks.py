"""Stub ``seg/*.nii.gz`` files so mocked TotalSegmentator paths can finalize the cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.segment import series_cache_dir


def write_stub_overlay_masks(series_dir: Path, structure_voxels: dict[str, int]) -> None:
    """Write minimal latch masks for positive structure counts under the series cache."""
    seg_dir = series_cache_dir(series_dir) / "seg"
    seg_dir.mkdir(parents=True, exist_ok=True)
    for name, count in structure_voxels.items():
        if int(count) <= 0:
            continue
        array = np.zeros((2, 8, 8), dtype=np.uint8)
        flat = array.ravel()
        flat[: min(int(count), flat.size)] = 1
        sitk.WriteImage(sitk.GetImageFromArray(array), str(seg_dir / f"{name}.nii.gz"))
