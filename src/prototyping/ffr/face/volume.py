"""Shim → ``anonymizer.controller.blur_face``."""

from anonymizer.controller.blur_face import (
    align_mask_to_volume,
    load_hu_stack,
    mask_array_from_volume,
    read_reference_volume,
)


def face_slice_indices(mask):
    """Slice indices where the mask is non-empty (viz helper; prototyping only)."""
    import numpy as np

    z_with_face = np.flatnonzero(mask.any(axis=(1, 2)))
    if z_with_face.size == 0:
        return (mask.shape[0] // 2,)
    z_min = int(z_with_face[0])
    z_max = int(z_with_face[-1])
    mid = int(z_with_face[len(z_with_face) // 2])
    q1 = int(z_with_face[len(z_with_face) // 4])
    q3 = int(z_with_face[(3 * len(z_with_face)) // 4])
    unique = sorted({z_min, q1, mid, q3, z_max})
    return tuple(unique)


__all__ = [
    "align_mask_to_volume",
    "face_slice_indices",
    "load_hu_stack",
    "mask_array_from_volume",
    "read_reference_volume",
]
