"""Tests for persisted CT/MR TotalSegmentator resolution modes (ephemeral process defaults)."""

from __future__ import annotations

from anonymizer.controller.ai.tseg.config import (
    clear_segmentation_mode_cache,
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    normalize_segmentation_mode,
    segmentation_mode_for_modality,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.view.ai.features.availability import (
    default_installed_segmentation_mode,
    installed_segmentation_mode_menu_values,
    segmentation_mode_from_menu_label,
    segmentation_mode_menu_label,
)


def test_normalize_segmentation_mode_defaults() -> None:
    assert normalize_segmentation_mode(None) == "3mm"
    assert normalize_segmentation_mode("6 mm") == "6mm"
    assert normalize_segmentation_mode("1.5MM") == "1.5mm"
    assert normalize_segmentation_mode("bogus") == "3mm"


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


def test_segmentation_mode_menu_round_trip() -> None:
    for mode in ("1.5mm", "3mm", "6mm"):
        label = segmentation_mode_menu_label(mode)
        assert segmentation_mode_from_menu_label(label) == mode


def test_installed_mode_menu_helpers() -> None:
    assert default_installed_segmentation_mode(("1.5mm", "6mm")) == "1.5mm"
    assert default_installed_segmentation_mode(("6mm", "3mm")) == "3mm"
    assert default_installed_segmentation_mode(()) == "3mm"
    labels = installed_segmentation_mode_menu_values(("1.5mm", "3mm"))
    assert all("mm" in label for label in labels)
    assert len(labels) == 2


def test_segmentation_mode_for_modality() -> None:
    clear_segmentation_mode_cache()
    try:
        set_ct_segmentation_mode("6mm")
        set_mr_segmentation_mode("1.5mm")
        assert segmentation_mode_for_modality("CT") == "6mm"
        assert segmentation_mode_for_modality("MRI") == "1.5mm"
    finally:
        clear_segmentation_mode_cache()
