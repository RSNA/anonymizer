"""OCR edit-context menu state (language-agnostic internal codes)."""

from pathlib import Path

import pytest

from anonymizer.controller.jobs.runner import (
    OcrEditContext,
    OcrRemoveMode,
    edit_context_menu_labels,
    edit_context_menu_values,
    normalize_edit_context,
    ocr_detect_tooltip,
    ocr_remove_mode_tooltip,
)
from anonymizer.utils.translate import set_language_code


def test_edit_context_menu_values_are_language_agnostic() -> None:
    assert edit_context_menu_values() == (OcrEditContext.FRAME, OcrEditContext.SERIES)


def test_detect_tooltip_describes_detect_not_remove_target() -> None:
    # Detect shows boxes and changes no pixels; it is not the Remove-target text.
    for mode in OcrRemoveMode:
        assert ocr_detect_tooltip(OcrEditContext.FRAME) != ocr_remove_mode_tooltip(mode)
        assert ocr_detect_tooltip(OcrEditContext.SERIES) != ocr_remove_mode_tooltip(mode)
    assert "current frame" in ocr_detect_tooltip(OcrEditContext.FRAME)
    assert "all frames" in ocr_detect_tooltip(OcrEditContext.SERIES)
    assert "no pixels are changed" in ocr_detect_tooltip(OcrEditContext.FRAME)
    assert "Remove Scope" in ocr_detect_tooltip(OcrEditContext.FRAME)
    assert "Remove target" not in ocr_detect_tooltip(OcrEditContext.SERIES)


@pytest.mark.parametrize("lang_code", ("en_US", "de"))
def test_normalize_edit_context_accepts_internal_codes(
    monkeypatch: pytest.MonkeyPatch,
    lang_code: str,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code(lang_code)
    assert normalize_edit_context("frame") is OcrEditContext.FRAME
    assert normalize_edit_context("series") is OcrEditContext.SERIES


def test_german_edit_context_labels_are_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code("de")
    frame_label, series_label = edit_context_menu_labels()
    assert frame_label == "EINZELBILD"
    assert series_label == "SERIE"
    assert normalize_edit_context(frame_label) is OcrEditContext.FRAME
    assert normalize_edit_context(series_label) is OcrEditContext.SERIES


@pytest.mark.parametrize("lang_code", ("en_US", "de"))
def test_menu_labels_match_normalize_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    lang_code: str,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code(lang_code)
    labels = edit_context_menu_labels()
    assert len(labels) == 2
    assert normalize_edit_context(labels[0]) is OcrEditContext.FRAME
    assert normalize_edit_context(labels[1]) is OcrEditContext.SERIES
