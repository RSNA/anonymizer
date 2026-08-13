"""Nobulela: correlate Series View detect vs AI batch UX removal logs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from anonymizer.controller.ai_batch_process import (
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
)
from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    detect_text,
    ocr_image_for_frame,
    ocr_models_ready,
    remove_pixel_phi,
)
from anonymizer.controller.runner import RemovePixelPhiRunner
from anonymizer.controller.series_io import load_series_frames
from tests.controller.support.nobulela_us_rgb_fixtures import (
    NOBULELA_BATCH_PIXELS_CHANGED,
    NOBULELA_BATCH_REMOVED_TEXTS,
    NOBULELA_BATCH_UX_LOG_HIDDEN_TEXTS,
    NOBULELA_BATCH_UX_LOG_VISIBLE_TEXTS,
    NOBULELA_SERIES_VIEW_NOT_REMOVED_BY_BATCH,
    NOBULELA_SERIES_VIEW_OCR_TEXTS,
    NOBULELA_SERIES_VIEW_SURVIVORS_AFTER_BATCH,
    NOBULELA_US_DCM,
)

pytestmark = [
    pytest.mark.skipif(
        not NOBULELA_US_DCM.is_file(),
        reason="Nobulela RGB US fixture missing",
    ),
    pytest.mark.skipif(not ocr_models_ready(), reason="EasyOCR models not available"),
]


def test_nobulela_batch_removed_count_matches_ux_log() -> None:
    assert len(NOBULELA_BATCH_REMOVED_TEXTS) == 24
    assert len(NOBULELA_BATCH_UX_LOG_VISIBLE_TEXTS) == 8
    assert len(NOBULELA_BATCH_UX_LOG_HIDDEN_TEXTS) == 16
    assert NOBULELA_BATCH_UX_LOG_HIDDEN_TEXTS[0] == "DIKO"
    assert NOBULELA_BATCH_UX_LOG_HIDDEN_TEXTS[1] == "NOBULELA"


def test_nobulela_ux_log_lines_match_fixture() -> None:
    """Reconstruct the exact Study 2/3 workflow lines from locked expectations."""
    instance_line = format_remove_pixel_phi_instance_detail(
        instance_index=1,
        instance_total=1,
        modified=True,
        texts=NOBULELA_BATCH_REMOVED_TEXTS,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
        pixels_changed=NOBULELA_BATCH_PIXELS_CHANGED,
    )
    series_line = format_remove_pixel_phi_series_message(
        modified_count=1,
        total=1,
        texts_removed=NOBULELA_BATCH_REMOVED_TEXTS,
        pixels_changed=NOBULELA_BATCH_PIXELS_CHANGED,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )

    assert instance_line == (
        'Instance 1/1: blacked out "mindray", "KMR", "X-RAYS", "26,05/2018", "13.09:16", "MI 0.9", "TIS 0.3", "AP" '
        '(+16 more) (21,054 px)'
    )
    assert series_line == (
        'Modified 1/1 · removed: "mindray", "KMR", "X-RAYS", "26,05/2018", "13.09:16", "MI 0.9" '
        '(+18 more) · 21,054 pixels blacked out'
    )


def test_nobulela_series_view_detect_is_not_batch_removal_list() -> None:
    """Series View keeps 37 strings; batch removes 24 — different pipelines."""
    assert len(NOBULELA_SERIES_VIEW_OCR_TEXTS) == 37
    assert NOBULELA_BATCH_REMOVED_TEXTS != NOBULELA_SERIES_VIEW_OCR_TEXTS
    for text in NOBULELA_SERIES_VIEW_NOT_REMOVED_BY_BATCH:
        assert text not in NOBULELA_BATCH_REMOVED_TEXTS, f"{text!r} should be filtered before removal"


def test_nobulela_live_batch_removal_matches_ux_fixture(tmp_path: Path) -> None:
    os.chdir(Path(__file__).resolve().parents[2] / "src" / "anonymizer")
    dcm_path = tmp_path / "nobulela.dcm"
    shutil.copy(NOBULELA_US_DCM, dcm_path)

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        _modified, texts, pixels_changed = remove_pixel_phi(
            dcm_path,
            handle.reader,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
            modality="US",
        )
    finally:
        runner.exit_models(handle)

    assert texts == NOBULELA_BATCH_REMOVED_TEXTS
    assert pixels_changed == NOBULELA_BATCH_PIXELS_CHANGED


def test_nobulela_series_view_after_batch_shows_no_whitelist_display_survivors(tmp_path: Path) -> None:
    """After batch blackout, SV detect+default whitelist shows no green boxes."""
    from anonymizer.controller.ai.remove_pixel_phi import filter_ocr_detections
    from anonymizer.utils.storage import load_default_whitelist

    os.chdir(Path(__file__).resolve().parents[2] / "src" / "anonymizer")
    dcm_path = tmp_path / "nobulela.dcm"
    shutil.copy(NOBULELA_US_DCM, dcm_path)
    loaded = load_series_frames(NOBULELA_US_DCM.parent)

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

    assert display_texts == list(NOBULELA_SERIES_VIEW_SURVIVORS_AFTER_BATCH)
