"""OCR integration tests on color (RGB) ultrasound with dense burnt-in overlays."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    build_series_view_ocr_pixels,
    detect_text,
    filter_ocr_detections,
    ocr_image_for_frame,
    ocr_models_ready,
    _ocr_rotation_angles,
)
from anonymizer.controller.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.work_state import WorkState
from tests.controller.support.nobulela_us_rgb_fixtures import (
    NOBULELA_PROJECT_T2_DCM,
    NOBULELA_PROJECT_T2_DIR,
    NOBULELA_SERIES_VIEW_OCR_TEXTS,
    NOBULELA_US_DIR,
    NOBULELA_US_DCM,
)

NOBULELA_EXPECTED_OCR_TEXTS = NOBULELA_SERIES_VIEW_OCR_TEXTS


def _nobulela_series_view_texts(loaded) -> list[str]:
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.ocr_pixels = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
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
    return [t.text for t in ws.result[0]]


pytestmark = pytest.mark.skipif(
    not NOBULELA_US_DCM.is_file(),
    reason="Nobulela RGB US fixture missing under tests/controller/assets/test_dcm_files/nobulela_us_rgb",
)


@pytest.fixture(scope="module")
def nobulela_us_loaded():
    return load_series_frames(NOBULELA_US_DIR)


def test_nobulela_us_rgb_loads_color_single_frame(nobulela_us_loaded) -> None:
    loaded = nobulela_us_loaded
    assert loaded.is_single_frame
    assert loaded.frames.shape == (1, 600, 800, 3)
    assert loaded.frames.dtype == np.uint8
    assert str(loaded.metadata.PhotometricInterpretation).upper() == "RGB"


def test_ocr_rotation_angles_us_uses_horizontal_only() -> None:
    assert _ocr_rotation_angles("US") == [0]
    assert _ocr_rotation_angles("us") == [0]
    assert _ocr_rotation_angles("CT") == [0, 90]
    assert _ocr_rotation_angles(None) == [0, 90]


def test_ocr_image_for_frame_rgb_uint8_returns_bgr(nobulela_us_loaded) -> None:
    loaded = nobulela_us_loaded
    bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
    assert bgr.shape == (600, 800, 3)
    assert bgr.dtype == np.uint8
    rgb = loaded.frames[0]
    assert not np.array_equal(bgr, rgb)


def test_build_series_view_ocr_pixels_rgb_matches_ocr_image_for_frame(nobulela_us_loaded) -> None:
    loaded = nobulela_us_loaded
    snapshot = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
    assert snapshot.shape == (1, 600, 800, 3)
    expected = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
    assert np.array_equal(snapshot[0], expected)


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_us_rgb_ocr_detects_all_overlay_strings(nobulela_us_loaded) -> None:
    """Series View detect keeps all EasyOCR hits (no noise filter)."""
    texts = _nobulela_series_view_texts(nobulela_us_loaded)
    assert texts == NOBULELA_EXPECTED_OCR_TEXTS, (
        f"Expected {len(NOBULELA_EXPECTED_OCR_TEXTS)} strings, got {len(texts)}: {texts}"
    )


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_batch_noise_filter_drops_speckle_hits(nobulela_us_loaded) -> None:
    """Batch path still applies noise filter and drops small numeric speckle."""
    loaded = nobulela_us_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        unfiltered = detect_text(bgr, handle.reader, modality="US", apply_noise_filter=False) or []
        filtered = detect_text(bgr, handle.reader, modality="US", apply_noise_filter=True) or []
    finally:
        runner.exit_models(handle)

    unfiltered_texts = [t.text for t in unfiltered]
    filtered_texts = [t.text for t in filtered]
    assert "1009" in unfiltered_texts
    assert "1009" not in filtered_texts
    assert len(filtered_texts) < len(unfiltered_texts)


@pytest.mark.skipif(
    not NOBULELA_PROJECT_T2_DCM.is_file(),
    reason="Nobulela t2 project damaged fixture missing",
)
@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_project_t2_fixture_differs_from_pristine(nobulela_us_loaded) -> None:
    """The t2 project copy had overlay pixels blacked out; it is not the pristine source."""
    damaged = load_series_frames(NOBULELA_PROJECT_T2_DIR)
    assert not np.array_equal(nobulela_us_loaded.frames[0], damaged.frames[0])


@pytest.mark.skipif(
    not NOBULELA_PROJECT_T2_DCM.is_file(),
    reason="Nobulela t2 project damaged fixture missing",
)
@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_project_t2_damaged_series_view_ocr(nobulela_us_loaded) -> None:
    """Regression: blacked-out project copy only retains a subset of overlay text."""
    damaged = load_series_frames(NOBULELA_PROJECT_T2_DIR)
    texts = _nobulela_series_view_texts(damaged)
    assert texts == [
        "26,05/2018",
        "1009",
        "TIS 0.3",
        "AP",
        "4-Abdomen",
        "4",
        "B1 FHS.0 /",
        "D17.2",
        "4",
        "B2 FHS.0 /",
        "D17.2 /",
        "Dist",
        "cm",
        "LIVER",
        "99,/99",
    ]
    assert texts != NOBULELA_EXPECTED_OCR_TEXTS


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_series_view_snapshot_matches_direct_ocr(nobulela_us_loaded) -> None:
    """Runner snapshot path must match direct ocr_image_for_frame + detect_text."""
    loaded = nobulela_us_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        direct = [
            t.text
            for t in detect_text(
                bgr,
                handle.reader,
                modality="US",
                apply_noise_filter=False,
            )
            or []
        ]

        ws = WorkState()
        ws.bind(
            loaded.metadata,
            loaded.frames,
            loaded.slice_paths,
            loaded.default_window,
            single_frame=True,
        )
        ws.ocr_pixels = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
        ws.frame_index = 0
        runner.process_series(
            ws,
            handle,
            options=RunOptions(edit_context=OcrEditContext.FRAME, whitelist=[]),
        )
        via_runner = [t.text for t in ws.result[0]]
    finally:
        runner.exit_models(handle)

    assert via_runner == direct == NOBULELA_EXPECTED_OCR_TEXTS


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_us_rgb_display_whitelist_hides_anatomy_not_phi(nobulela_us_loaded) -> None:
    """UI whitelist filters overlay display only; PHI must remain detectable in stored results."""
    from anonymizer.controller.ai.remove_pixel_phi import filter_ocr_whitelist_only
    from anonymizer.utils.storage import load_default_whitelist

    loaded = nobulela_us_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.ocr_pixels = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
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

    all_texts = [t.text for t in ws.result[0]]
    assert all_texts == NOBULELA_EXPECTED_OCR_TEXTS
    repo_root = Path(__file__).resolve().parents[2]
    os.chdir(repo_root / "src" / "anonymizer")
    us_wl = load_default_whitelist("US")
    displayed = [t.text for t in filter_ocr_whitelist_only(ws.result[0], whitelist=us_wl)]
    assert "NOBULELA" in displayed
    assert "8211080464089" in displayed
    assert "LIVER" not in displayed
