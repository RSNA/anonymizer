"""Face blur status formatting and review constants."""

from __future__ import annotations

from pydicom import Dataset

from anonymizer.controller.ai.blur_face import FaceBlurMode, FaceBlurProgress, QaStats
from anonymizer.utils.translate import _

# BGR for OpenCV overlay compositing.
FACE_MASK_OVERLAY_COLOR = (0, 255, 0)
FACE_MASK_OVERLAY_ALPHA = 0.35
# CT window in Hounsfield units for reviewing blurred facial features.
FACE_REVIEW_WL_HU = -250.0
FACE_REVIEW_WW_HU = 2500.0

FACE_BLUR_MODE_LABELS: dict[FaceBlurMode, str] = {
    FaceBlurMode.GAUSSIAN: "Gaussian blur",
    FaceBlurMode.MEDIAN: "Median filter",
    FaceBlurMode.PIXELATE: "Pixelate",
    FaceBlurMode.FILL_NOISE: "Noise fill",
}


def face_blur_mode_menu_values() -> tuple[str, ...]:
    return tuple(_(label) for label in FACE_BLUR_MODE_LABELS.values())


def face_blur_mode_from_menu_label(label: str) -> FaceBlurMode:
    for mode, mode_label in FACE_BLUR_MODE_LABELS.items():
        if label == _(mode_label):
            return mode
    return FaceBlurMode.GAUSSIAN


def face_blur_mode_display_label(mode: FaceBlurMode) -> str:
    return _(FACE_BLUR_MODE_LABELS[mode])


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


def format_face_blur_progress_status(
    progress: FaceBlurProgress,
    *,
    include_pct: bool = True,
) -> str:
    pct_text = ""
    if include_pct:
        pct = min(100, max(0, int(round(progress.fraction * 100))))
        pct_text = f" ({pct}%)"
    stage_labels = {
        "mask": _("Resolving face segmentation mask"),
        "volume": _("Loading CT volume and aligning face mask"),
        "load_hu": _("Loading Hounsfield unit stack"),
        "blur": _("Applying in-mask face de-identification"),
        "qa": _("Checking pixels outside face mask"),
        "done": _("Ready"),
    }
    if progress.stage in stage_labels:
        return stage_labels[progress.stage] + "…" + pct_text
    message = (progress.message or "").strip()
    if message:
        return message + pct_text
    return _("Processing face blur") + "…" + pct_text
