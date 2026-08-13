"""AI batch remove-pixel-PHI integration tests on Nobulela RGB US (same fixture as Series View)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pydicom
import pytest

from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, _apply_remove_pixel_phi_series
from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    detect_text,
    ocr_image_for_frame,
    ocr_models_ready,
)
from anonymizer.controller.runner import RemovePixelPhiRunner
from anonymizer.controller.series_io import load_series_frames
from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.controller.support.nobulela_us_rgb_fixtures import (
    NOBULELA_BATCH_OCR_TEXTS,
    NOBULELA_BATCH_PHI_LOG_TOKENS,
    NOBULELA_BATCH_PIXELS_CHANGED,
    NOBULELA_US_DCM,
    NOBULELA_US_DIR,
)
from tests.controller.support.pixel_phi_test_support import (
    register_series_with_anonymizer,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ANONYMIZER_SCRIPT = REPO_ROOT / "src/anonymizer/assets/scripts/default-anonymizer.script"

pytestmark = pytest.mark.skipif(
    not NOBULELA_US_DCM.is_file(),
    reason="Nobulela RGB US fixture missing under tests/controller/assets/test_dcm_files/nobulela_us_rgb",
)


@pytest.fixture(autouse=True)
def _anonymizer_assets_cwd() -> None:
    os.chdir(Path(__file__).resolve().parents[2] / "src" / "anonymizer")


@pytest.fixture(scope="module")
def nobulela_us_loaded():
    return load_series_frames(NOBULELA_US_DIR)


@pytest.fixture
def nobulela_batch_series(tmp_path: Path) -> Path:
    series_dir = tmp_path / "nobulela_batch"
    series_dir.mkdir()
    shutil.copy(NOBULELA_US_DCM, series_dir / NOBULELA_US_DCM.name)
    return series_dir


@pytest.fixture
def anonymizer_model(tmp_path: Path) -> AnonymizerModel:
    db_path = tmp_path / "nobulela_batch.db"
    return AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=ANONYMIZER_SCRIPT,
        db_url=f"sqlite:///{db_path}",
    )


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_batch_detect_matches_noise_filtered_expectations(nobulela_us_loaded) -> None:
    loaded = nobulela_us_loaded
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        bgr = ocr_image_for_frame(loaded.metadata, loaded.frames[0])
        results = detect_text(bgr, handle.reader, modality="US", apply_noise_filter=True) or []
        texts = [item.text for item in results]
    finally:
        runner.exit_models(handle)

    assert texts == NOBULELA_BATCH_OCR_TEXTS


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_batch_blackout_preserves_rgb_dimensions(
    nobulela_batch_series: Path,
    anonymizer_model: AnonymizerModel,
) -> None:
    register_series_with_anonymizer(nobulela_batch_series, anonymizer_model)
    dcm_path = next(nobulela_batch_series.glob("*.dcm"))
    before = pydicom.dcmread(dcm_path).pixel_array.copy()

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    log_lines: list[str] = []
    try:
        outcome = _apply_remove_pixel_phi_series(
            nobulela_batch_series,
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
    assert f"{NOBULELA_BATCH_PIXELS_CHANGED:,} pixels blacked out" in outcome.message
    combined_logs = outcome.message + "\n" + "\n".join(log_lines)
    for token in NOBULELA_BATCH_PHI_LOG_TOKENS:
        assert token in combined_logs

    ds = pydicom.dcmread(dcm_path)
    after = ds.pixel_array
    assert (int(ds.Rows), int(ds.Columns)) == (600, 800)
    assert after.shape == (600, 800, 3)
    assert after.max() > 0
    assert not (before == after).all()


@pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available")
def test_nobulela_batch_inpaint_preserves_rgb_dimensions(
    nobulela_batch_series: Path,
    anonymizer_model: AnonymizerModel,
) -> None:
    register_series_with_anonymizer(nobulela_batch_series, anonymizer_model)
    dcm_path = next(nobulela_batch_series.glob("*.dcm"))
    before = pydicom.dcmread(dcm_path).pixel_array.copy()

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        outcome = _apply_remove_pixel_phi_series(
            nobulela_batch_series,
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
