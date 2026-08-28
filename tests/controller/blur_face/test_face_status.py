"""Tests for face blur status strings in the controller layer."""

from __future__ import annotations

from anonymizer.controller.ai.blur_face import (
    FaceBlurMode,
    FaceBlurProgress,
    FACE_BLUR_MODE_LABELS,
    face_blur_mode_display_label,
    format_face_blur_progress_status,
)


def test_face_blur_mode_display_label_translates_known_modes() -> None:
    assert face_blur_mode_display_label(FaceBlurMode.GAUSSIAN) == "Gaussian blur"
    assert len(FACE_BLUR_MODE_LABELS) == len(FaceBlurMode)


def test_format_face_blur_progress_status_uses_stage_labels() -> None:
    text = format_face_blur_progress_status(
        FaceBlurProgress(stage="blur", message="", fraction=0.5),
        include_pct=False,
    )
    assert "de-identification" in text
    assert "%" not in text

    with_pct = format_face_blur_progress_status(
        FaceBlurProgress(stage="done", message="", fraction=1.0),
    )
    assert "100%" in with_pct
    assert "Ready" in with_pct
