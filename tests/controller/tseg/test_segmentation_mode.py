"""Tests for persisted CT/MR TotalSegmentator resolution modes (ephemeral process defaults)."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.ai.tseg.config import (
    clear_segmentation_mode_cache,
    default_installed_segmentation_mode,
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    installed_segmentation_mode_menu_values,
    normalize_segmentation_mode,
    segmentation_mode_display,
    segmentation_mode_for_modality,
    segmentation_mode_menu_values,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.utils.translate import language_to_code, set_language_code


def test_normalize_segmentation_mode_defaults() -> None:
    assert normalize_segmentation_mode(None) == "3mm"
    assert normalize_segmentation_mode("6 mm") == "6mm"
    assert normalize_segmentation_mode("1.5MM") == "1.5mm"
    assert normalize_segmentation_mode("1,5 mm") == "1.5mm"
    assert normalize_segmentation_mode("bogus") == "3mm"


@pytest.mark.parametrize("lang_code", tuple(language_to_code.values()))
def test_segmentation_mode_menu_values_are_language_agnostic(
    monkeypatch: pytest.MonkeyPatch,
    lang_code: str,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code(lang_code)
    assert segmentation_mode_menu_values() == ("1.5mm", "3mm", "6mm")
    for mode in segmentation_mode_menu_values():
        assert set_ct_segmentation_mode(mode) == mode
        assert get_ct_segmentation_mode() == mode


def test_modes_are_ephemeral_process_defaults() -> None:
    clear_segmentation_mode_cache()
    try:
        assert get_ct_segmentation_mode() == "3mm"
        assert get_mr_segmentation_mode() == "3mm"

        assert set_ct_segmentation_mode("1.5mm") == "1.5mm"
        assert set_mr_segmentation_mode("6mm") == "6mm"
        assert get_ct_segmentation_mode() == "1.5mm"
        assert get_mr_segmentation_mode() == "6mm"
    finally:
        clear_segmentation_mode_cache()


def test_segmentation_mode_display_is_fixed_ascii() -> None:
    assert segmentation_mode_display("1.5mm") == "1.5 mm"
    assert segmentation_mode_display("3mm") == "3 mm"
    assert segmentation_mode_display("6mm") == "6 mm"


def test_installed_mode_menu_helpers() -> None:
    assert default_installed_segmentation_mode(("1.5mm", "6mm")) == "1.5mm"
    assert default_installed_segmentation_mode(("6mm", "3mm")) == "3mm"
    assert default_installed_segmentation_mode(()) == "3mm"
    assert installed_segmentation_mode_menu_values(("1.5mm", "3mm")) == ("1.5mm", "3mm")
    assert installed_segmentation_mode_menu_values(("6mm",)) == ("6mm",)


def test_segmentation_mode_for_modality() -> None:
    clear_segmentation_mode_cache()
    try:
        set_ct_segmentation_mode("6mm")
        set_mr_segmentation_mode("1.5mm")
        assert segmentation_mode_for_modality("CT") == "6mm"
        assert segmentation_mode_for_modality("MRI") == "1.5mm"
    finally:
        clear_segmentation_mode_cache()
