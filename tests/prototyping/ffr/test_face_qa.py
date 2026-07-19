"""Tests for face blur QA helpers (prototyping)."""

from __future__ import annotations

import numpy as np

from prototyping.ffr.face.qa import compute_qa_stats


def test_qa_detects_outside_violation() -> None:
    before = np.zeros((2, 4, 4), dtype=np.float64)
    after = before.copy()
    mask = np.zeros((2, 4, 4), dtype=bool)
    mask[0, 1:3, 1:3] = True
    after[0, 0, 0] = 1.0

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
