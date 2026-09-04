"""Unit tests for Series View toolbar presence helpers (no CTk window)."""

from __future__ import annotations

from anonymizer.controller.ai.blur_face import CachedRegionSignal
from anonymizer.controller.runner import OcrEditContext
from anonymizer.view.series.series import (
    blur_face_toolbar_visible,
    clear_cache_button_visible,
    harmonize_button_visible,
    ocr_results_available_for_edit_context,
)


def test_ocr_results_frame_requires_current_frame_detections() -> None:
    overlays = {0: ["a"], 1: ["b"]}
    assert ocr_results_available_for_edit_context(
        OcrEditContext.FRAME,
        current_frame_index=0,
        overlay_ocr_by_frame=overlays,
    )
    assert not ocr_results_available_for_edit_context(
        OcrEditContext.FRAME,
        current_frame_index=2,
        overlay_ocr_by_frame=overlays,
    )


def test_ocr_results_series_requires_any_frame_detections() -> None:
    assert ocr_results_available_for_edit_context(
        OcrEditContext.SERIES,
        current_frame_index=0,
        overlay_ocr_by_frame={1: ["x"]},
    )
    assert not ocr_results_available_for_edit_context(
        OcrEditContext.SERIES,
        current_frame_index=0,
        overlay_ocr_by_frame={},
    )


def test_clear_cache_button_visible_when_harmonized_or_masks() -> None:
    assert clear_cache_button_visible(modality="CT", already_harmonized=True)
    assert clear_cache_button_visible(modality="CT", already_harmonized=False, has_segment_masks=True)
    assert not clear_cache_button_visible(modality="CT", already_harmonized=False, has_segment_masks=False)
    assert clear_cache_button_visible(modality="MR", already_harmonized=True)
    assert not clear_cache_button_visible(modality=None, already_harmonized=True)


def test_harmonize_button_visible_once_until_cleared() -> None:
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CT",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CT",
        already_harmonized=True,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CT",
        already_harmonized=False,
        has_segment_masks=True,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="US",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=False,
        modality="CT",
        already_harmonized=False,
    )


def test_blur_face_toolbar_requires_head_cache_after_harmonize() -> None:
    assert blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        cached_signal=CachedRegionSignal.HEAD,
        eligibility_blocked=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        cached_signal=CachedRegionSignal.UNAVAILABLE,
        eligibility_blocked=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        cached_signal=CachedRegionSignal.NON_HEAD,
        eligibility_blocked=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        cached_signal=CachedRegionSignal.MULTI_REGION,
        eligibility_blocked=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=True,
        cached_signal=CachedRegionSignal.HEAD,
        eligibility_blocked=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        cached_signal=CachedRegionSignal.HEAD,
        eligibility_blocked=True,
    )
