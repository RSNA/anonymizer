"""OCR and AI batch integration tests on color (RGB) ultrasound with burnt-in overlays."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pydicom
import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    _ocr_rotation_angles,
    build_series_view_ocr_pixels,
    detect_text,
    filter_ocr_whitelist_only,
    ocr_image_for_frame,
)
from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, _apply_remove_pixel_phi_series
from anonymizer.controller.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.work_state import WorkState
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.storage import load_default_whitelist
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.pixel_phi_test_support import register_series_with_anonymizer
from tests.controller.support.us_rgb_fixtures import (
    US_RGB_BATCH_LOG_TOKENS,
    US_RGB_BATCH_OCR_TEXTS,
    US_RGB_BATCH_PIXELS_CHANGED,
    US_RGB_DCM,
    US_RGB_DIR,
    US_RGB_PROJECT_T2_DCM,
    US_RGB_PROJECT_T2_DIR,
    US_RGB_PROJECT_T2_SERIES_VIEW_OCR_TEXTS,
    US_RGB_SERIES_VIEW_OCR_TEXTS,
)
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT

ANONYMIZER_SCRIPT = DEFAULT_ANONYMIZER_SCRIPT
EXPECTED_OCR_TEXTS = US_RGB_SERIES_VIEW_OCR_TEXTS


def _series_view_texts(loaded) -> list[str]:
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


@pytest.fixture(scope="module")
def us_rgb_loaded():
    assert_dcm(US_RGB_DCM)
    return load_series_frames(US_RGB_DIR)


@pytest.fixture
def us_rgb_batch_series(tmp_path: Path) -> Path:
    assert_dcm(US_RGB_DCM)
    series_dir = tmp_path / "us_rgb_batch"
    series_dir.mkdir()
    shutil.copy(US_RGB_DCM, series_dir / US_RGB_DCM.name)
    return series_dir


@pytest.fixture
def anonymizer_model(tmp_path: Path) -> AnonymizerModel:
    db_path = tmp_path / "us_rgb_batch.db"
    return AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=ANONYMIZER_SCRIPT,
        db_url=f"sqlite:///{db_path}",
    )


def test_us_rgb_loads_color_single_frame(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
    assert loaded.is_single_frame
    assert loaded.frames.shape == (1, 600, 800, 3)
    assert loaded.frames.dtype == np.uint8
    assert str(loaded.metadata.PhotometricInterpretation).upper() == "RGB"


def test_ocr_rotation_angles_us_uses_horizontal_only() -> None:
    assert _ocr_rotation_angles("US") == [0]
    assert _ocr_rotation_angles("us") == [0]
    assert _ocr_rotation_angles("CT") == [0, 90]
    assert _ocr_rotation_angles(None) == [0, 90]


def test_ocr_image_for_frame_rgb_uint8_returns_bgr(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
    bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
    assert bgr.shape == (600, 800, 3)
    assert bgr.dtype == np.uint8
    rgb = loaded.frames[0]
    assert not np.array_equal(bgr, rgb)


def test_build_series_view_ocr_pixels_rgb_matches_ocr_image_for_frame(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
    snapshot = build_series_view_ocr_pixels(loaded.frames, loaded.metadata)
    assert snapshot.shape == (1, 600, 800, 3)
    expected = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
    assert np.array_equal(snapshot[0], expected)


def test_us_rgb_project_t2_fixture_differs_from_pristine(us_rgb_loaded) -> None:
    assert_dcm(US_RGB_PROJECT_T2_DCM)
    damaged = load_series_frames(US_RGB_PROJECT_T2_DIR)
    assert not np.array_equal(us_rgb_loaded.frames[0], damaged.frames[0])


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_ocr_detects_all_overlay_strings(us_rgb_loaded) -> None:
    texts = _series_view_texts(us_rgb_loaded)
    assert texts == EXPECTED_OCR_TEXTS, f"Expected {len(EXPECTED_OCR_TEXTS)} strings, got {len(texts)}: {texts}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_batch_noise_filter_drops_speckle_hits(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
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


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_batch_detect_matches_noise_filtered_expectations(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        results = detect_text(bgr, handle.reader, modality="US", apply_noise_filter=True) or []
        texts = [item.text for item in results]
    finally:
        runner.exit_models(handle)

    assert texts == US_RGB_BATCH_OCR_TEXTS


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_batch_ocr_regression_after_ct_veracity_guard(us_rgb_loaded) -> None:
    """US batch OCR token list must remain unchanged by CT-only single-char filter."""
    loaded = us_rgb_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        results = detect_text(bgr, handle.reader, modality="US", apply_noise_filter=True) or []
        texts = [item.text for item in results]
    finally:
        runner.exit_models(handle)

    assert texts == US_RGB_BATCH_OCR_TEXTS


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_project_t2_damaged_series_view_ocr(us_rgb_loaded) -> None:
    assert_dcm(US_RGB_PROJECT_T2_DCM)
    damaged = load_series_frames(US_RGB_PROJECT_T2_DIR)
    texts = _series_view_texts(damaged)
    assert texts == US_RGB_PROJECT_T2_SERIES_VIEW_OCR_TEXTS
    assert texts != EXPECTED_OCR_TEXTS


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_series_view_snapshot_matches_direct_ocr(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
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

    assert via_runner == direct == EXPECTED_OCR_TEXTS


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_display_whitelist_hides_anatomy_labels(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
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
    assert all_texts == EXPECTED_OCR_TEXTS
    us_wl = load_default_whitelist("US")
    displayed = [t.text for t in filter_ocr_whitelist_only(ws.result[0], whitelist=us_wl)]
    assert "26,05/2018" in displayed
    assert "LIVER" not in displayed
    assert "Dist" not in displayed


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_batch_blackout_preserves_rgb_dimensions(
    us_rgb_batch_series: Path,
    anonymizer_model: AnonymizerModel,
) -> None:
    register_series_with_anonymizer(us_rgb_batch_series, anonymizer_model)
    dcm_path = next(us_rgb_batch_series.glob("*.dcm"))
    before = pydicom.dcmread(dcm_path).pixel_array.copy()

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    log_lines: list[str] = []
    try:
        outcome = _apply_remove_pixel_phi_series(
            us_rgb_batch_series,
            anon_model=anonymizer_model,
            ocr_reader=handle.reader,
            on_log_detail=log_lines.append,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
        )
    finally:
        runner.exit_models(handle)

    assert outcome.status == "ok"
    assert outcome.algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI
    assert "pixels blacked out" in outcome.message
    assert "Modified 1/1" in outcome.message
    assert f"{US_RGB_BATCH_PIXELS_CHANGED:,} pixels blacked out" in outcome.message
    combined_logs = outcome.message + "\n" + "\n".join(log_lines)
    for token in US_RGB_BATCH_LOG_TOKENS:
        assert token in combined_logs

    ds = pydicom.dcmread(dcm_path)
    after = ds.pixel_array
    assert (int(ds.Rows), int(ds.Columns)) == (600, 800)
    assert after.shape == (600, 800, 3)
    assert after.max() > 0
    assert not (before == after).all()


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_batch_inpaint_preserves_rgb_dimensions(
    us_rgb_batch_series: Path,
    anonymizer_model: AnonymizerModel,
) -> None:
    register_series_with_anonymizer(us_rgb_batch_series, anonymizer_model)
    dcm_path = next(us_rgb_batch_series.glob("*.dcm"))
    before = pydicom.dcmread(dcm_path).pixel_array.copy()

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        outcome = _apply_remove_pixel_phi_series(
            us_rgb_batch_series,
            anon_model=anonymizer_model,
            ocr_reader=handle.reader,
            removal_mode=PixelPhiRemovalMode.INPAINT,
        )
    finally:
        runner.exit_models(handle)

    assert outcome.status == "ok"
    assert "pixels modified" in outcome.message

    ds = pydicom.dcmread(dcm_path)
    after = ds.pixel_array
    assert (int(ds.Rows), int(ds.Columns)) == (600, 800)
    assert after.shape == (600, 800, 3)
    assert after.max() > 0
    assert not (before == after).all()
