"""Face blur status formatting and review constants for Series View."""

from __future__ import annotations

from pydicom import Dataset

from anonymizer.controller.blur_face import FaceBlurProgress, QaStats
from anonymizer.utils.translate import _

# BGR for OpenCV overlay compositing.
FACE_MASK_OVERLAY_COLOR = (0, 255, 0)
FACE_MASK_OVERLAY_ALPHA = 0.35
# Soft-tissue window in Hounsfield units for reviewing facial features on CT.
FACE_REVIEW_WL_HU = 40.0
FACE_REVIEW_WW_HU = 400.0


def face_review_wl_ww(ds: Dataset) -> tuple[float, float]:
    """Return WL/WW in stored-pixel space for soft-tissue face review on CT."""
    slope = float(getattr(ds, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
    if slope in (0, 0.0):
        slope = 1.0
    wl = (FACE_REVIEW_WL_HU - intercept) / slope
    ww = FACE_REVIEW_WW_HU / abs(slope)
    return wl, max(1.0, ww)


def format_face_blur_qa_summary(
    qa: QaStats | None,
    *,
    sigma_mm: float,
    slice_count: int,
) -> str:
    if qa is None:
        return _("Quality assurance pending.")
    if not qa.outside_clean:
        return (
            _("QA FAIL")
            + f" — {qa.n_violating_voxels} "
            + _("voxels changed outside the face mask")
            + f" ({qa.n_outside_voxels} "
            + _("outside voxels checked")
            + ")."
        )
    return (
        _("QA PASS")
        + f" — {qa.n_face_voxels:,} "
        + _("face voxels blurred")
        + f", {slice_count} "
        + _("slices")
        + f", σ={sigma_mm:.1f} mm."
    )


def format_face_blur_progress_status(progress: FaceBlurProgress) -> str:
    pct = min(100, max(0, int(round(progress.fraction * 100))))
    pct_text = f" ({pct}%)"
    stage_labels = {
        "mask": _("Resolving face segmentation mask"),
        "volume": _("Loading CT volume and aligning face mask"),
        "load_hu": _("Loading Hounsfield unit stack"),
        "blur": _("Applying in-mask Gaussian blur"),
        "qa": _("Checking pixels outside face mask"),
        "done": _("Ready"),
    }
    if progress.stage in stage_labels:
        return stage_labels[progress.stage] + "…" + pct_text
    message = (progress.message or "").strip()
    if message:
        return message + pct_text
    return _("Processing face blur") + "…" + pct_text
