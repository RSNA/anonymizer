"""OCR integration tests on real burnt-in PHI CXR fixture (Davidson)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.remove_pixel_phi import ocr_models_ready
from anonymizer.controller.runner import Algorithm, OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.work_state import WorkState
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

DAVIDSON_CXR_SERIES_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"
DAVIDSON_CXR_DCM = DAVIDSON_CXR_SERIES_DIR / "davidson_cxr_monochrome1_uncompressed.dcm"


pytestmark = pytest.mark.skipif(
    not DAVIDSON_CXR_DCM.is_file(),
    reason="Davidson CXR fixture missing (copy to tests/controller/assets/test_dcm_files/davidson_cxr/)",
)


@pytest.fixture(scope="module")
def davidson_loaded():
    return load_series_frames(DAVIDSON_CXR_SERIES_DIR)


def test_davidson_cxr_loads_single_frame(davidson_loaded) -> None:
    assert davidson_loaded.is_single_frame
    assert davidson_loaded.frames.shape[0] == 1
    assert davidson_loaded.frames.ndim == 3


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_davidson_cxr_ocr_finds_burned_in_text(davidson_loaded) -> None:
    """Regression: MONOCHROME1 CXR must yield OCR boxes with an empty whitelist."""
    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
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
    assert 0 in ws.result
    assert len(ws.result[0]) > 0, "Expected burned-in text on Davidson CXR"
    texts = [t.text for t in ws.result[0]]
    assert any("portable" in t.lower() for t in texts), f"Expected Portable in OCR results, got {texts}"


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_davidson_cxr_ocr_hides_portable_with_whitelist(davidson_loaded) -> None:
    """Whitelist containing PORTABLE should filter burned-in Portable overlay text."""
    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(
                edit_context=OcrEditContext.FRAME,
                whitelist=["PORTABLE"],
            ),
        )
    finally:
        runner.exit_models(handle)

    texts = [t.text for t in ws.result[0]]
    assert not any("portable" in t.lower() for t in texts), f"Portable should be whitelisted, got {texts}"


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_davidson_cleared_whitelist_with_project_dir_finds_portable(davidson_loaded) -> None:
    """Cleared Series View whitelist must not reload modality defaults from project_dir."""
    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(
                edit_context=OcrEditContext.FRAME,
                whitelist=[],
                project_dir=Path("/tmp/fake-project"),
            ),
        )
    finally:
        runner.exit_models(handle)

    texts = [t.text for t in ws.result[0]]
    assert any("portable" in t.lower() for t in texts), f"Expected Portable after cleared whitelist, got {texts}"
