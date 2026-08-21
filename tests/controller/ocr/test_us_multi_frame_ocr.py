"""OCR integration tests on multi-frame ultrasound with dense burnt-in overlays."""

from __future__ import annotations

import pytest

from anonymizer.controller.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.work_state import WorkState
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

US_MULTI_FRAME_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "us_multi_frame_grayscale"
US_MULTI_FRAME_DCM = US_MULTI_FRAME_DIR / "us_multi_frame_grayscale_JPG2000.dcm"


@pytest.fixture(scope="module")
def us_multi_frame_loaded():
    assert_dcm(US_MULTI_FRAME_DCM)
    return load_series_frames(US_MULTI_FRAME_DIR)


def test_us_multi_frame_loads_54_frames(us_multi_frame_loaded) -> None:
    loaded = us_multi_frame_loaded
    assert loaded.frames.shape == (54, 802, 1054)
    assert not loaded.is_single_frame
    assert str(loaded.metadata.Modality) == "US"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
@pytest.mark.parametrize(
    ("frame_index", "expected_tokens"),
    [
        (0, ("LOGIQ", "TRANS", "AXILLA")),
        (1, ("LOGIQ", "TRANS", "AXILLA")),
        (2, ("LOGIQ", "TRANS", "AXILLA")),
    ],
)
def test_us_multi_frame_sample_frames_have_overlay_text(
    us_multi_frame_loaded,
    frame_index: int,
    expected_tokens: tuple[str, ...],
) -> None:
    """Early US frames carry machine labels and anatomy markers used across the cine."""
    loaded = us_multi_frame_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=False,
    )
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
    texts = " ".join(t.text for t in ws.result[frame_index]).upper()
    for token in expected_tokens:
        assert token in texts, f"frame {frame_index}: expected {token!r} in {texts!r}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_multi_frame_series_ocr_populates_most_frames(us_multi_frame_loaded) -> None:
    """SERIES detect must populate OCR results across the cine, not only the last-polled frame."""
    loaded = us_multi_frame_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=False,
    )
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(edit_context=OcrEditContext.SERIES, whitelist=[]),
        )
    finally:
        runner.exit_models(handle)

    assert isinstance(ws.result, dict)
    assert len(ws.result) >= 50, f"Expected OCR on most frames, got {len(ws.result)}"
    for frame_index in (0, 1, 2, 10, 20, 30, 40):
        assert frame_index in ws.result, f"Missing OCR result for frame {frame_index}"
        assert len(ws.result[frame_index]) >= 3
