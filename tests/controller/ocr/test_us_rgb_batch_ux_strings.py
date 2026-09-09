"""Correlate Series View detect vs AI batch UX removal logs for RGB US single-frame."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    detect_text,
    filter_ocr_detections,
    ocr_image_for_frame,
    remove_pixel_phi,
)
from anonymizer.controller.ai_batch_process import (
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
)
from anonymizer.controller.runner import RemovePixelPhiRunner
from anonymizer.controller.series_io import load_series_frames
from anonymizer.utils.storage import load_default_whitelist
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.us_rgb_fixtures import (
    US_RGB_BATCH_PIXELS_CHANGED,
    US_RGB_BATCH_REMOVED_TEXTS,
    US_RGB_DCM,
    US_RGB_SERIES_VIEW_NOT_REMOVED_BY_BATCH,
    US_RGB_SERIES_VIEW_OCR_TEXTS,
    US_RGB_SERIES_VIEW_SURVIVORS_AFTER_BATCH,
)


def test_us_rgb_ux_log_lines_match_fixture() -> None:
    instance_line = format_remove_pixel_phi_instance_detail(
        instance_index=1,
        instance_total=1,
        modified=True,
        texts=US_RGB_BATCH_REMOVED_TEXTS,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
        pixels_changed=US_RGB_BATCH_PIXELS_CHANGED,
    )
    series_line = format_remove_pixel_phi_series_message(
        modified_count=1,
        total=1,
        texts_removed=US_RGB_BATCH_REMOVED_TEXTS,
        pixels_changed=US_RGB_BATCH_PIXELS_CHANGED,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert instance_line == (
        'Instance 1/1: blacked out "mindray", "KMR", "X-RAYS", "26,05/2018", "13.09:16", "MI 0.9", "TIS 0.3", "AP" '
        "(+13 more) (18,316 px)"
    )
    assert series_line == (
        'Modified 1/1 · removed: "mindray", "KMR", "X-RAYS", "26,05/2018", "13.09:16", "MI 0.9" '
        "(+15 more) · 18,316 pixels blacked out"
    )


def test_us_rgb_series_view_detect_is_not_batch_removal_list() -> None:
    assert len(US_RGB_SERIES_VIEW_OCR_TEXTS) == 34
    assert US_RGB_BATCH_REMOVED_TEXTS != US_RGB_SERIES_VIEW_OCR_TEXTS
    for text in US_RGB_SERIES_VIEW_NOT_REMOVED_BY_BATCH:
        assert text not in US_RGB_BATCH_REMOVED_TEXTS, f"{text!r} should be filtered before removal"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_series_view_after_batch_shows_no_whitelist_display_survivors(
    tmp_path: Path,
) -> None:
    assert_dcm(US_RGB_DCM)
    dcm_path = tmp_path / "us_rgb.dcm"
    shutil.copy(US_RGB_DCM, dcm_path)
    loaded = load_series_frames(US_RGB_DCM.parent)

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        remove_pixel_phi(
            dcm_path,
            handle.reader,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
            modality="US",
        )
        import pydicom

        ds = pydicom.dcmread(dcm_path)
        bgr_after = ocr_image_for_frame(loaded.metadata, ds.pixel_array)
        after_all = detect_text(bgr_after, handle.reader, modality="US", apply_noise_filter=False) or []
        us_wl = [item.upper() for item in load_default_whitelist("US")]
        after_display = filter_ocr_detections(after_all, whitelist=us_wl)
        display_texts = [item.text for item in after_display]
    finally:
        runner.exit_models(handle)

    assert display_texts == list(US_RGB_SERIES_VIEW_SURVIVORS_AFTER_BATCH)
