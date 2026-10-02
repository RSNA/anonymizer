"""Succinct Origin labels for description mappings (who/what decided the value)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anonymizer.controller.ai.harmonize.pipeline import HarmonizedResult

# Study LOINC auto-rank after series playbook descriptions are set.
DESCRIPTION_MAPPING_ORIGIN_LOINC_RANK = "LOINC rank"


def series_mapping_origin(
    result: HarmonizedResult | None,
    *,
    modality: object | None = None,
    include_brain_structures: bool = False,
) -> str:
    """
    Origin string for a series mapping produced by series Harmonize.

    Examples: ``TS 1.5mm``, ``TS 1.5mm+brain``, ``XR body+view``, ``DICOM tags``.
    """
    from anonymizer.controller.ai.tseg.config import segmentation_mode_for_modality

    if result is not None and result.tseg is not None:
        mode = segmentation_mode_for_modality(modality)
        label = f"TS {mode}"
        if include_brain_structures:
            label = f"{label}+brain"
        return label

    planar = getattr(result, "planar", None) if result is not None else None
    if planar is not None:
        cohort = str(getattr(planar, "cohort", "") or "XR").strip() or "XR"
        body_px = str(getattr(planar, "body_part_source", "") or "") in {"pixel", "fused"}
        view_px = str(getattr(planar, "view_source", "") or "") in {"pixel", "fused"}
        if body_px and view_px:
            return f"{cohort} body+view"
        if body_px:
            return f"{cohort} body"
        if view_px:
            return f"{cohort} view"
        return f"{cohort} tags"

    return "DICOM tags"
