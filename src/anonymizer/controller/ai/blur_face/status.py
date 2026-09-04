"""Face blur batch and progress status strings (controller layer)."""

from __future__ import annotations

from anonymizer.controller.ai.blur_face.pipeline import FaceBlurMode, FaceBlurProgress
from anonymizer.utils.translate import _

FACE_BLUR_MODE_LABELS: dict[FaceBlurMode, str] = {
    FaceBlurMode.GAUSSIAN: "Gaussian blur",
    FaceBlurMode.MEDIAN: "Median filter",
    FaceBlurMode.PIXELATE: "Pixelate",
    FaceBlurMode.FILL_NOISE: "Noise fill",
}


def face_blur_mode_display_label(mode: FaceBlurMode) -> str:
    return _(FACE_BLUR_MODE_LABELS[mode])


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
