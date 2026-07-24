"""Tests for face blur QA."""

from __future__ import annotations

import numpy as np

from anonymizer.controller.blur_face import blur_face_hu_volume, compute_qa_stats, face_mask_blend_weights


def test_qa_detects_outside_violation() -> None:
    before = np.zeros((2, 4, 4), dtype=np.float64)
    after = before.copy()
    mask = np.zeros((2, 4, 4), dtype=bool)
    mask[0, 1:3, 1:3] = True
    after[1, 3, 3] = 100.0

    stats = compute_qa_stats(before, after, mask)
    assert not stats.outside_clean
    assert stats.n_violating_voxels == 1


def test_qa_passes_when_only_inside_changes() -> None:
    before = np.full((2, 4, 4), -100.0)
    after = before.copy()
    mask = np.zeros((2, 4, 4), dtype=bool)
    mask[:, 1:3, 1:3] = True
    after[mask] = 50.0

    stats = compute_qa_stats(before, after, mask)
    assert stats.outside_clean
    assert stats.n_violating_voxels == 0


def test_blur_feathers_mask_edges() -> None:
    """Smoothed blend weights avoid a hard binary stair-step at the segmentation boundary."""
    size = 32
    hu = np.full((1, size, size), 100.0, dtype=np.float32)
    hu[0, 14:18, 14:18] = 1000.0
    mask = np.zeros((1, size, size), dtype=bool)
    mask[0, 14:18, 14:18] = True

    after = blur_face_hu_volume(
        hu,
        mask,
        sigma_mm=2.0,
        pixel_spacing_mm=(1.0, 1.0),
    )
    blend = face_mask_blend_weights(mask)[0]

    assert 0.0 < blend[14, 13] < 1.0
    assert abs(after[0, 14, 13] - hu[0, 14, 13]) > 1.0
    assert blend[0, 0] <= 1e-6
    assert after[0, 0, 0] == hu[0, 0, 0]
    assert compute_qa_stats(hu, after, mask).outside_clean
