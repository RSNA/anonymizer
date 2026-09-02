"""Pixel PHI removal mode menu state and locale-safe parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    normalize_pixel_phi_removal_mode,
    pixel_phi_removal_mode_menu_labels,
    pixel_phi_removal_mode_menu_values,
    pixel_phi_removal_mode_option_label,
)
from anonymizer.utils.translate import language_to_code, set_language_code


def test_removal_mode_menu_values_are_language_agnostic() -> None:
    assert pixel_phi_removal_mode_menu_values() == (
        PixelPhiRemovalMode.BLACKOUT,
        PixelPhiRemovalMode.INPAINT,
    )


@pytest.mark.parametrize("lang_code", tuple(language_to_code.values()))
def test_normalize_removal_mode_accepts_internal_codes(
    monkeypatch: pytest.MonkeyPatch,
    lang_code: str,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code(lang_code)
    assert normalize_pixel_phi_removal_mode("blackout") is PixelPhiRemovalMode.BLACKOUT
    assert normalize_pixel_phi_removal_mode("inpaint") is PixelPhiRemovalMode.INPAINT


@pytest.mark.parametrize("lang_code", tuple(language_to_code.values()))
def test_menu_labels_match_normalize_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    lang_code: str,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code(lang_code)
    labels = pixel_phi_removal_mode_menu_labels()
    assert len(labels) == 2
    assert labels[0] == pixel_phi_removal_mode_option_label(PixelPhiRemovalMode.BLACKOUT)
    assert labels[1] == pixel_phi_removal_mode_option_label(PixelPhiRemovalMode.INPAINT)
    assert normalize_pixel_phi_removal_mode(labels[0]) is PixelPhiRemovalMode.BLACKOUT
    assert normalize_pixel_phi_removal_mode(labels[1]) is PixelPhiRemovalMode.INPAINT


def test_german_removal_mode_labels_are_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    set_language_code("de")
    blackout, inpaint = pixel_phi_removal_mode_menu_labels()
    assert blackout == "Text schwärzen"
    assert inpaint == "In den Hintergrund einblenden"
