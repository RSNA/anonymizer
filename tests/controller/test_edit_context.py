"""OCR edit-context menu state (language-agnostic internal codes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.runner import (
    OcrEditContext,
    edit_context_display_label,
    edit_context_menu_labels,
    edit_context_menu_values,
    normalize_edit_context,
)
from anonymizer.utils.translate import language_to_code, set_language_code


def test_edit_context_menu_values_are_language_agnostic() -> None:
    assert edit_context_menu_values() == (OcrEditContext.FRAME, OcrEditContext.SERIES)


@pytest.mark.parametrize("lang_code", tuple(language_to_code.values()))
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


@pytest.mark.parametrize("lang_code", tuple(language_to_code.values()))
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
