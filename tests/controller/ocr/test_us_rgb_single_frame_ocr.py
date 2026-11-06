"""OCR and AI batch integration tests on color (RGB) ultrasound with burnt-in overlays."""

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pydicom
import pytest

from anonymizer.controller.ai.batch_process import AiBatchAlgorithm, _apply_remove_pixel_phi_series
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    build_series_view_ocr_pixels,
    ocr_image_for_frame,
)
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    detect_text,
    filter_ocr_noise,
    make_annotate_whitelist,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrEditContext, OcrRemoveMode, texts_for_remove_mode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist
from anonymizer.controller.jobs.runner import RemovePixelPhiRunner, RunOptions
from anonymizer.controller.jobs.work_state import WorkState
from anonymizer.controller.script.paths import packaged_default_script_path
from anonymizer.controller.series.series_io import load_series_frames
from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.pixel_phi_test_support import register_series_with_anonymizer
from tests.controller.support.us_rgb_fixtures import (
    US_RGB_BATCH_LOG_TOKENS,
    US_RGB_BATCH_OCR_TEXTS,
    US_RGB_BATCH_REMOVED_TEXTS,
    US_RGB_DCM,
    US_RGB_DIR,
    US_RGB_SERIES_VIEW_OCR_TEXTS,
)
from tests.opened_anonymizer_model import opened_anonymizer_model

ANONYMIZER_SCRIPT = packaged_default_script_path()
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
def anonymizer_model(tmp_path: Path):
    db_path = tmp_path / "us_rgb_batch.db"
    with opened_anonymizer_model(f"sqlite:///{db_path}", script_path=ANONYMIZER_SCRIPT) as model:
        yield model



def test_detect_text_us_passes_no_rotation_to_easyocr() -> None:
    reader = MagicMock()
    reader.readtext.return_value = []
    detect_text(np.zeros((10, 10), dtype=np.uint8), reader, modality="US")
    assert reader.readtext.call_count == 1
    assert reader.readtext.call_args.kwargs["rotation_info"] == []


def test_detect_text_ct_passes_no_rotation_to_easyocr() -> None:
    reader = MagicMock()
    reader.readtext.return_value = []
    detect_text(np.zeros((10, 10), dtype=np.uint8), reader, modality="CT")
    assert reader.readtext.call_count == 1
    assert reader.readtext.call_args.kwargs["rotation_info"] == []


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
        unfiltered = detect_text(bgr, handle.reader, modality="US") or []
        filtered = filter_ocr_noise(detect_text(bgr, handle.reader, modality="US") or [], modality="US")
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
        results = filter_ocr_noise(
            detect_text(bgr, handle.reader, modality="US") or [],
            modality="US",
        )
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
        results = filter_ocr_noise(
            detect_text(bgr, handle.reader, modality="US") or [],
            modality="US",
        )
        texts = [item.text for item in results]
    finally:
        runner.exit_models(handle)

    assert texts == US_RGB_BATCH_OCR_TEXTS


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_series_view_snapshot_matches_direct_ocr(us_rgb_loaded) -> None:
    loaded = us_rgb_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        direct = [t.text for t in detect_text(bgr, handle.reader, modality="US") or []]

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
    annotated = make_annotate_whitelist(us_wl)(ws.result[0])
    displayed = [
        t.text
        for t in texts_for_remove_mode(
            annotated,
            OcrRemoveMode.NON_WHITELISTED,
            PhiMatchMode.STANDARD,
        )
    ]
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
    assert "PHI removed" in outcome.message
    assert "1/1 instance(s)" in outcome.message
    assert "pixels" not in outcome.message
    assert "text region" not in outcome.message
    combined_logs = outcome.message + "\n" + "\n".join(log_lines)
    for token in US_RGB_BATCH_LOG_TOKENS:
        assert token in combined_logs
    for phi_token in US_RGB_BATCH_REMOVED_TEXTS:
        assert phi_token not in combined_logs

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
    assert "PHI removed" in outcome.message
    assert "Blend into background" in outcome.message
    assert "pixels" not in outcome.message

    ds = pydicom.dcmread(dcm_path)
    after = ds.pixel_array
    assert (int(ds.Rows), int(ds.Columns)) == (600, 800)
    assert after.shape == (600, 800, 3)
    assert after.max() > 0
    assert not (before == after).all()
