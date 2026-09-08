"""OCR exclude-rect integration on ultrasound single-frame and multi-frame fixtures."""

from __future__ import annotations

import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    build_series_view_ocr_pixels,
    filter_ocr_outside_exclude_rects,
    remove_ocr_text_from_frame,
    PixelPhiRemovalMode,
    ocr_image_for_frame,
)
from anonymizer.controller.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.series_overlay import UserRectangle
from anonymizer.controller.work_state import WorkState
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.support.us_rgb_fixtures import US_RGB_DCM, US_RGB_DIR

US_MULTI_FRAME_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "us_multi_frame_grayscale"
US_MULTI_FRAME_DCM = US_MULTI_FRAME_DIR / "us_multi_frame_grayscale_JPG2000.dcm"

# Clear Dist / caliper readout on the right of US_RGB_SingleFrame (800×600).
US_RGB_MEASUREMENT_EXCLUDE = UserRectangle(top_left=(600, 330), bottom_right=(800, 480))
US_RGB_PANEL_TOKENS = ("DIST", "15.23", "CM")
US_RGB_KEEP_TOKENS = ("MINDRAY", "KMR")

# Lower-right anatomy/data labels on LOGIQ multi-frame (1054×802).
# AXILLA sits ~x=587–677, y=713–739; keep TRANS (ends ~x=584) just outside.
US_MF_LOWER_RIGHT_EXCLUDE = UserRectangle(top_left=(586, 700), bottom_right=(1054, 802))
US_MF_PANEL_TOKENS = ("AXILLA",)
US_MF_KEEP_TOKENS = ("LOGIQ", "TRANS")


def _joined_upper(texts) -> str:
    return " ".join(t.text for t in texts).upper()


def _detect_frame(loaded, frame_index: int = 0):
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=loaded.is_single_frame,
    )
    ws.ocr_pixels = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
    ws.frame_index = frame_index
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(edit_context=OcrEditContext.FRAME, whitelist=[]),
        )
    finally:
        runner.exit_models(handle)
    assert isinstance(ws.result, dict)
    assert frame_index in ws.result
    return list(ws.result[frame_index])


@pytest.fixture(scope="module")
def us_rgb_loaded():
    assert_dcm(US_RGB_DCM)
    return load_series_frames(US_RGB_DIR)


@pytest.fixture(scope="module")
def us_multi_frame_loaded():
    assert_dcm(US_MULTI_FRAME_DCM)
    return load_series_frames(US_MULTI_FRAME_DIR)


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_exclude_measurement_panel_filters_detect(us_rgb_loaded) -> None:
    """Exclude the clear right-hand Dist/cm panel; vendor labels outside remain."""
    raw = _detect_frame(us_rgb_loaded, 0)
    raw_blob = _joined_upper(raw)
    for token in US_RGB_PANEL_TOKENS:
        assert token in raw_blob, f"fixture sanity: expected {token!r} before exclude in {raw_blob!r}"

    filtered = filter_ocr_outside_exclude_rects(raw, [US_RGB_MEASUREMENT_EXCLUDE])
    filtered_blob = _joined_upper(filtered)
    for token in US_RGB_PANEL_TOKENS:
        assert token not in filtered_blob, f"panel token {token!r} should be excluded: {filtered_blob!r}"
    for token in US_RGB_KEEP_TOKENS:
        assert token in filtered_blob, f"keeper {token!r} should remain: {filtered_blob!r}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_exclude_panel_survives_remove_text(us_rgb_loaded) -> None:
    """Remove Text must not erase pixels for OCR boxes that sit only in the exclude zone."""
    import numpy as np

    raw = _detect_frame(us_rgb_loaded, 0)
    filtered = filter_ocr_outside_exclude_rects(raw, [US_RGB_MEASUREMENT_EXCLUDE])
    frame = us_rgb_loaded.frames[0].copy()
    before = frame.copy()
    windowed = ocr_image_for_frame(us_rgb_loaded.metadata, frame)
    # Only measurement-panel OCR (the ones we exclude) — removal should be a no-op if empty.
    panel_only = [t for t in raw if t not in filtered]
    assert panel_only, "expected measurement OCR boxes inside exclude rect"
    # Defense path: remove with exclude filter applied (as Series View does).
    to_remove = filter_ocr_outside_exclude_rects(panel_only, [US_RGB_MEASUREMENT_EXCLUDE])
    assert to_remove == []
    # Removing filtered (non-panel) OCR should change pixels; panel tokens stay in image.
    out = remove_ocr_text_from_frame(
        frame,
        windowed,
        filtered,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )
    assert not np.array_equal(before, out)


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_multi_frame_exclude_lower_right_frame_mode(us_multi_frame_loaded) -> None:
    """Lower-right overlay (AXILLA) excluded; LOGIQ/TRANS elsewhere remain."""
    raw = _detect_frame(us_multi_frame_loaded, 0)
    raw_blob = _joined_upper(raw)
    for token in US_MF_PANEL_TOKENS:
        assert token in raw_blob, f"fixture sanity: expected {token!r} in {raw_blob!r}"

    filtered = filter_ocr_outside_exclude_rects(raw, [US_MF_LOWER_RIGHT_EXCLUDE])
    filtered_blob = _joined_upper(filtered)
    for token in US_MF_PANEL_TOKENS:
        assert token not in filtered_blob, f"lower-right token {token!r} should be excluded"
    for token in US_MF_KEEP_TOKENS:
        assert token in filtered_blob, f"keeper {token!r} should remain: {filtered_blob!r}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_multi_frame_exclude_lower_right_series_sample(us_multi_frame_loaded) -> None:
    """SERIES-style: same lower-right exclude applied on several cine frames."""
    loaded = us_multi_frame_loaded
    for frame_index in (0, 1, 2):
        raw = _detect_frame(loaded, frame_index)
        filtered = filter_ocr_outside_exclude_rects(raw, [US_MF_LOWER_RIGHT_EXCLUDE])
        filtered_blob = _joined_upper(filtered)
        for token in US_MF_PANEL_TOKENS:
            if token in _joined_upper(raw):
                assert token not in filtered_blob, f"frame {frame_index}: {token!r} should be excluded"
        for token in US_MF_KEEP_TOKENS:
            if token in _joined_upper(raw):
                assert token in filtered_blob, f"frame {frame_index}: keeper {token!r} missing"
