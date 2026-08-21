"""OCR integration tests on real burnt-in PHI CXR fixture (Davidson)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    filter_ocr_whitelist_only,
    load_modality_whitelist,
)
from anonymizer.controller.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.work_state import WorkState
from anonymizer.utils.storage import load_modality_whitelist_match_settings
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

DAVIDSON_CXR_SERIES_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"
DAVIDSON_CXR_DCM = DAVIDSON_CXR_SERIES_DIR / "davidson_cxr_monochrome1_uncompressed.dcm"


@pytest.fixture(scope="module")
def davidson_loaded():
    assert_dcm(DAVIDSON_CXR_DCM)
    return load_series_frames(DAVIDSON_CXR_SERIES_DIR)


def test_davidson_cxr_loads_single_frame(davidson_loaded) -> None:
    assert davidson_loaded.is_single_frame
    assert davidson_loaded.frames.shape[0] == 1
    assert davidson_loaded.frames.ndim == 3


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
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


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
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


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
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


def test_davidson_overlay_draw_includes_portable_when_project_whitelist_omits_it(
    tmp_path: Path,
) -> None:
    """Detect-all + draw-filter: project cr.txt without PORTABLE must still draw Portable."""
    from anonymizer.controller.series_overlay import OCRText

    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("AXIAL\nCHEST\n", encoding="utf-8")

    detections = [
        OCRText(text="DAVIDSON", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="DOUGLAS [M]", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="01.09.2012", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Semi-Upright", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="DOB: 06.16.1976", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Portable", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]
    effective_whitelist = load_modality_whitelist(project_dir, "CR")
    match_settings = load_modality_whitelist_match_settings(project_dir, "CR")
    drawn = filter_ocr_whitelist_only(
        detections,
        whitelist=effective_whitelist,
        whitelist_match_settings=match_settings,
    )
    drawn_texts = [item.text for item in drawn]

    assert "Portable" in drawn_texts
    assert "DAVIDSON" in drawn_texts
