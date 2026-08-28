"""Face blur review UI helpers and constants."""

from __future__ import annotations

from pydicom import Dataset

from anonymizer.controller.ai.blur_face import (
    FACE_BLUR_MODE_LABELS,
    FaceBlurMode,
    FaceBlurProgress,
    QaStats,
    face_blur_mode_display_label,
    format_face_blur_progress_status,
)
from anonymizer.utils.translate import _

# BGR for OpenCV overlay compositing.
FACE_MASK_OVERLAY_COLOR = (0, 255, 0)
FACE_MASK_OVERLAY_ALPHA = 0.35
# CT window in Hounsfield units for reviewing blurred facial features.
FACE_REVIEW_WL_HU = -250.0
FACE_REVIEW_WW_HU = 2500.0


def face_blur_mode_menu_values() -> tuple[str, ...]:
    return tuple(_(label) for label in FACE_BLUR_MODE_LABELS.values())


def face_blur_mode_from_menu_label(label: str) -> FaceBlurMode:
    for mode, mode_label in FACE_BLUR_MODE_LABELS.items():
        if label == _(mode_label):
            return mode
    return FaceBlurMode.GAUSSIAN


def proposed_face_blur_companion_label(mode: FaceBlurMode) -> str:
    return _("Proposed face blur using") + f" {face_blur_mode_display_label(mode)}"


def face_review_wl_ww(ds: Dataset) -> tuple[float, float]:
    """Return WL/WW in the same units as Series View CT frames (modality-LUT / HU space)."""
    _ = ds
    return FACE_REVIEW_WL_HU, max(1.0, FACE_REVIEW_WW_HU)


def format_face_blur_qa_summary(
    qa: QaStats | None,
    *,
    sigma_mm: float,
    slice_count: int,
    blur_mode: FaceBlurMode = FaceBlurMode.GAUSSIAN,
) -> str:
    mode_label = face_blur_mode_display_label(blur_mode)
    if qa is None:
        return _("Quality assurance pending.")
    if not qa.outside_clean:
        return _("QA FAIL") + " — " + _("pixels changed outside the face mask") + "."
    return _("QA PASS") + f" ({mode_label})" + f", {slice_count} " + _("slices") + f", σ={sigma_mm:.1f} mm."


__all__ = [
    "FACE_BLUR_MODE_LABELS",
    "FACE_MASK_OVERLAY_ALPHA",
    "FACE_MASK_OVERLAY_COLOR",
    "FACE_REVIEW_WL_HU",
    "FACE_REVIEW_WW_HU",
    "FaceBlurMode",
    "FaceBlurProgress",
    "QaStats",
    "face_blur_mode_display_label",
    "face_blur_mode_from_menu_label",
    "face_blur_mode_menu_values",
    "face_review_wl_ww",
    "format_face_blur_progress_status",
    "format_face_blur_qa_summary",
    "proposed_face_blur_companion_label",
]
