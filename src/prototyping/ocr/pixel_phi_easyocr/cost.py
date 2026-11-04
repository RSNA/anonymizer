"""Relative EasyOCR compute cost vs product defaults (efficiency gate)."""

from __future__ import annotations

from typing import Any, Mapping

# Product defaults from detect_text._easyocr_readtext (non-US).
PRODUCT_CANVAS_CAP = 1200
PRODUCT_MAG_RATIO = 1.0
PRODUCT_ROTATION_NON_US = (90, 270)


def relative_cost(
    overrides: Mapping[str, Any] | None,
    *,
    modality: str = "CR",
    image_max_side: int = PRODUCT_CANVAS_CAP,
) -> float:
    """
    Rough multiply vs a 1.0 reference (canvas=cap, mag=1, no rotation).

    Product non-US baseline is typically ~3.0 because rotation_info=[90,270]
    triples recognition work on each found box. Prefer configs with
    relative_cost <= product_baseline_cost, or the smallest cost that hits
    the accuracy target.

    Args:
        overrides: readtext kwargs merged after product defaults.
        modality: DICOM modality (US has no rotation by default).
        image_max_side: max(H, W) of the OCR frame before canvas clamp.

    Returns:
        Unitless cost estimate (CRAFT ~ canvas*mag^2; recog ~ 1+n_rot).
    """
    ov = dict(overrides or {})
    # Product clamps to OCR_CANVAS_SIZE_THRESHOLD unless overrides raise it.
    default_canvas = min(image_max_side, PRODUCT_CANVAS_CAP)
    canvas = int(ov["canvas_size"]) if "canvas_size" in ov else default_canvas
    canvas = min(image_max_side, max(1, canvas))
    mag = float(ov.get("mag_ratio", PRODUCT_MAG_RATIO))
    if "rotation_info" in ov:
        rot = list(ov.get("rotation_info") or [])
    elif str(modality or "").upper() == "US":
        rot = []
    else:
        rot = list(PRODUCT_ROTATION_NON_US)
    detect = (canvas / float(PRODUCT_CANVAS_CAP)) * (mag**2)
    recognize = 1.0 + float(len(rot))
    return detect * recognize


def product_baseline_cost(*, modality: str = "CR") -> float:
    """Cost of current product defaults on a large CR/DX frame (side ≥ canvas cap)."""
    return relative_cost({}, modality=modality, image_max_side=4000)
