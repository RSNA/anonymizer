"""Controller-pure Series View toolbar / OCR status helpers (no Tk).

Ported from tests/view/test_series_toolbar_gates.py so default testpaths collect them.
"""

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import make_annotate_whitelist
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrEditContext
from anonymizer.controller.series.series_overlay import (
    NerEvidence,
    OCRText,
    OcrEvidence,
    UserRectangle,
)
from anonymizer.controller.series.workspace import (
    blur_face_toolbar_visible,
    clear_cache_button_visible,
    edit_context_toolbar_visible,
    format_ocr_detection_complete_status,
    ocr_remove_enabled,
    ocr_results_available_for_edit_context,
)


def _ocr(
    text: str,
    *,
    phi_label: str | None = None,
    top_left: tuple[int, int] = (0, 0),
    bottom_right: tuple[int, int] = (10, 10),
) -> OCRText:
    ner = NerEvidence()
    if phi_label is not None:
        ner = NerEvidence(label=phi_label, entities=((phi_label, text),), score=1.0)
    return OCRText(
        text=text,
        top_left=top_left,
        bottom_right=bottom_right,
        ocr=OcrEvidence(prob=0.9),
        ner=ner,
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


def test_ocr_remove_enabled_only_with_results() -> None:
    assert ocr_remove_enabled(
        interaction_allowed=True,
        detecting=False,
        results_available=True,
    )
    assert not ocr_remove_enabled(
        interaction_allowed=True,
        detecting=True,
        results_available=True,
    )
    assert not ocr_remove_enabled(
        interaction_allowed=True,
        detecting=False,
        results_available=False,
    )
    assert not ocr_remove_enabled(
        interaction_allowed=False,
        detecting=False,
        results_available=True,
    )


def test_edit_context_toolbar_hidden_for_single_frame() -> None:
    assert not edit_context_toolbar_visible(single_frame=True)
    assert edit_context_toolbar_visible(single_frame=False)


def test_format_ocr_detection_complete_includes_ner_and_whitelist() -> None:
    boxes = make_annotate_whitelist(["PORTABLE", "AXILLA"])(
        [
            _ocr("DAVIDSON", phi_label="NAME"),
            _ocr("01.09.2012", phi_label="DATE"),
            _ocr("Portable"),
            _ocr("Semi-Upright"),
            # NER false positive: whitelist classification wins in status counts.
            _ocr("AXILLA", phi_label="NAME"),
        ]
    )
    status = format_ocr_detection_complete_status({0: boxes})
    assert "5 detections" in status
    assert "Name 1" in status
    assert "Date 1" in status
    assert "unlabeled 1" in status
    assert "2 whitelisted" in status
    assert "frames with text" not in status


def test_format_ocr_detection_complete_reports_excluded_not_as_unlabeled() -> None:
    status = format_ocr_detection_complete_status(
        {
            0: [
                _ocr("DAVIDSON", phi_label="NAME", top_left=(0, 0), bottom_right=(20, 20)),
                _ocr("VEL", top_left=(100, 100), bottom_right=(140, 120)),
                _ocr("cm/s", top_left=(110, 130), bottom_right=(150, 150)),
            ]
        },
        exclude_rects_by_frame={
            0: [UserRectangle(top_left=(90, 90), bottom_right=(200, 200))],
        },
    )
    assert "1 detections" in status
    assert "Name 1" in status
    assert "unlabeled" not in status
    assert "2 excluded" in status


def test_format_ocr_detection_complete_series_includes_frame_counts() -> None:
    status = format_ocr_detection_complete_status(
        {0: [_ocr("A", phi_label="NAME")], 2: [_ocr("B")]},
        frames_scanned=5,
    )
    assert "2 detections" in status
    assert "2/5 frames with text" in status
    assert "whitelisted" not in status


def test_clear_cache_button_visible_when_harmonized_or_masks() -> None:
    assert clear_cache_button_visible(modality="CT", already_harmonized=True)
    assert clear_cache_button_visible(modality="CT", already_harmonized=False, has_segment_masks=True)
    assert not clear_cache_button_visible(modality="CT", already_harmonized=False, has_segment_masks=False)
    assert clear_cache_button_visible(modality="MR", already_harmonized=True)
    assert not clear_cache_button_visible(modality=None, already_harmonized=True)


def test_blur_face_toolbar_visible_for_head_until_orm_applied() -> None:
    assert blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        is_head_series=True,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=False,
        is_head_series=False,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=True,
        face_blur_already_applied=True,
        is_head_series=True,
    )
    assert not blur_face_toolbar_visible(
        face_blur_models_ready=False,
        face_blur_already_applied=False,
        is_head_series=True,
    )
