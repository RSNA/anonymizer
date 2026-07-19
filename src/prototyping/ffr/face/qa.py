from __future__ import annotations

import numpy as np

from prototyping.ffr.face.models import QaStats


def compute_qa_stats(hu_before: np.ndarray, hu_after: np.ndarray, mask: np.ndarray) -> QaStats:
    """Quantify whether any voxels outside the face mask changed."""
    face = mask.astype(bool)
    outside = ~face
    diff = np.abs(hu_after.astype(np.float64) - hu_before.astype(np.float64))

    outside_diff = diff[outside]
    inside_diff = diff[face]

    n_violating = int(np.sum(outside_diff > 0)) if outside_diff.size else 0
    max_outside = float(outside_diff.max()) if outside_diff.size else 0.0
    mean_inside = float(inside_diff.mean()) if inside_diff.size else 0.0

    return QaStats(
        max_abs_diff_outside=max_outside,
        n_violating_voxels=n_violating,
        n_outside_voxels=int(outside.sum()),
        n_face_voxels=int(face.sum()),
        mean_abs_diff_inside=mean_inside,
    )
