"""Tests for RadLex Playbook+ series description formatting."""

from __future__ import annotations

import pytest

from anonymizer.controller.tseg.radlex import (
    falcon_body_part_to_region_token,
    falcon_body_part_to_regions_label,
    format_radlex_ct_series_description,
)


def test_single_region_head() -> None:
    assert format_radlex_ct_series_description("Head", False) == "CT Head+Neck Without Contrast"


def test_single_region_chest_with_contrast() -> None:
    assert format_radlex_ct_series_description("Chest", True) == "CT Chest With Contrast"


def test_multi_region() -> None:
    assert format_radlex_ct_series_description("Chest+Abdomen", True) == "CT Chest+Abdomen With Contrast"


def test_falcon_headneck_token() -> None:
    assert falcon_body_part_to_region_token("HeadNeck") == "Head"
    assert falcon_body_part_to_regions_label("HeadNeck") == "Head+Neck"


def test_empty_regions_raises() -> None:
    with pytest.raises(ValueError, match="body_parts_present is required"):
        format_radlex_ct_series_description("", False)
