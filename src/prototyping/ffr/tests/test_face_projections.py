"""Tests for face projection helpers."""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk

from prototyping.ffr.face.projections import build_face_projections


def _identity_volume(shape: tuple[int, int, int]) -> sitk.Image:
    array = np.zeros(shape, dtype=np.float32)
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    return image


def test_build_face_projections_shapes() -> None:
    hu = np.zeros((10, 20, 20), dtype=np.float64)
    mask = np.zeros((10, 20, 20), dtype=bool)
    mask[3:8, 6:14, 6:14] = True
    hu[mask] = 40.0
    hu_after = hu.copy()
    hu_after[mask] = 80.0

    proj = build_face_projections(
        hu,
        hu_after,
        mask,
        _identity_volume(hu.shape),
        margin_voxels=1,
        crop_margin=2,
    )
    assert len(proj.frontal_slabs) == 3
    assert len(proj.side_slabs) == 3
    for slab in (*proj.frontal_slabs, *proj.side_slabs):
        assert slab.before.ndim == 2
        assert slab.mask.shape == slab.before.shape
        assert slab.after.shape == slab.before.shape
        assert slab.mask.any()
        assert slab.label

    coronal_shapes = {slab.before.shape for slab in proj.frontal_slabs}
    sagittal_shapes = {slab.before.shape for slab in proj.side_slabs}
    assert len(coronal_shapes) == 1
    assert len(sagittal_shapes) == 1
    assert proj.frontal_slabs[1].label.endswith("mid")
