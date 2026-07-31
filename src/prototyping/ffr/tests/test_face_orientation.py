"""Tests for volume axis classification."""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk

from prototyping.ffr.face.orientation import classify_volume_axes


def test_classify_standard_axial_identity_direction() -> None:
    image = sitk.GetImageFromArray(np.zeros((12, 24, 24), dtype=np.float32))
    image.SetSpacing((1.0, 1.0, 1.0))
    image.SetDirection((1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
    axes = classify_volume_axes(image)
    assert axes.si == 0
    assert axes.ap == 1
    assert axes.lr == 2
    assert axes.si_sign == 1
    assert axes.ap_sign == 1
    assert axes.lr_sign == 1
