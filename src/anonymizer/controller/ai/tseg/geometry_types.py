"""Shared geometry label types for tseg classification and DICOM geometry.

Split from dicom_geometry / series_classification so neither module imports the
other for type-only dependencies.

Public API
----------
PlaneLabel
    Axial / sagittal / coronal / oblique / unknown.

DimensionalityLabel
    Volume vs localizer vs single-slice vs projection classification.

ProvenanceLabel
    Original vs derived acquisition provenance.

StackMetrics
    Slice count, spacing, extent, and regularity along the stack direction.
"""

from dataclasses import dataclass
from typing import Literal

PlaneLabel = Literal["axial", "sagittal", "coronal", "oblique", "unknown"]
DimensionalityLabel = Literal[
    "volume_3d",
    "localizer_2d",
    "single_slice_2d",
    "multiframe_volume",
    "projection_2d",
    "unknown",
]
ProvenanceLabel = Literal[
    "original",
    "derived_reformat",
    "derived_3d_render",
    "derived_secondary",
    "unknown",
]


@dataclass(frozen=True)
class StackMetrics:
    """Slice count, spacing, extent, and regularity along the stack direction."""

    n_slices: int
    slice_spacing_mm: float | None
    through_plane_extent_mm: float | None
    spacing_regularity: float | None
