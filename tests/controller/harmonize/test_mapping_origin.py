"""Tests for succinct description-mapping Origin labels."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from anonymizer.controller.ai.harmonize.mapping_origin import (
    DESCRIPTION_MAPPING_ORIGIN_LOINC_RANK,
    series_mapping_origin,
)
from anonymizer.controller.ai.harmonize.pipeline import HarmonizedResult
from anonymizer.controller.ai.harmonize.playbook_planar import PlanarPlaybookAttributes
from anonymizer.controller.ai.tseg.config import set_ct_segmentation_mode


def test_series_mapping_origin_ts_with_brain() -> None:
    set_ct_segmentation_mode("1.5mm")
    result = HarmonizedResult(
        series_directory=Path("/tmp/s"),
        radlex_series_description="CT Head Ax",
        tseg=MagicMock(),
    )
    assert series_mapping_origin(result, modality="CT", include_brain_structures=True) == "TS 1.5mm+brain"
    assert series_mapping_origin(result, modality="CT", include_brain_structures=False) == "TS 1.5mm"


def test_series_mapping_origin_planar_pixel() -> None:
    planar = PlanarPlaybookAttributes(
        cohort="XR",
        body_part_label="Chest",
        body_part_source="pixel",
        view_source="fused",
    )
    result = HarmonizedResult(
        series_directory=Path("/tmp/s"),
        radlex_series_description="XR Chest AP",
        tseg=None,
        planar=planar,
    )
    assert series_mapping_origin(result) == "XR body+view"


def test_series_mapping_origin_dicom_tags_fallback() -> None:
    result = HarmonizedResult(
        series_directory=Path("/tmp/s"),
        radlex_series_description="CT Scout",
        tseg=None,
    )
    assert series_mapping_origin(result) == "DICOM tags"


def test_loinc_rank_constant() -> None:
    assert DESCRIPTION_MAPPING_ORIGIN_LOINC_RANK == "LOINC rank"
