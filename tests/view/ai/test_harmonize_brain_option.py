"""Harmonize Description Dialog brain-structures prompt (CT Head only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pydicom import Dataset

from anonymizer.controller.ai.blur_face.pipeline import CachedRegionSignal
from anonymizer.view.ai.harmonize_results import (
    series_is_ct_head_candidate,
    should_prompt_brain_structures_for_series,
)


def _ds(*, modality: str = "CT", body_part: str = "HEAD", series: str = "BRAIN AX") -> Dataset:
    ds = Dataset()
    ds.Modality = modality
    ds.BodyPartExamined = body_part
    ds.SeriesDescription = series
    return ds


def test_series_is_ct_head_candidate_from_metadata(tmp_path: Path) -> None:
    series = tmp_path / "head"
    series.mkdir()
    assert series_is_ct_head_candidate(series, _ds()) is True


def test_series_is_ct_head_candidate_rejects_mr_and_chest_ct(tmp_path: Path) -> None:
    series = tmp_path / "chest"
    series.mkdir()
    assert series_is_ct_head_candidate(series, _ds(modality="MR")) is False
    assert series_is_ct_head_candidate(
        series,
        _ds(body_part="CHEST", series="CHEST CT W CONTRAST"),
    ) is False


def test_series_is_ct_head_candidate_ambiguous_anonymized_ct(tmp_path: Path) -> None:
    """Stripped PHI often leaves no HEAD tokens; still offer the optional prompt."""
    series = tmp_path / "anon_head"
    series.mkdir()
    ds = Dataset()
    ds.Modality = "CT"
    ds.SeriesDescription = "Bone  Vol. CECT 0.5"
    assert series_is_ct_head_candidate(series, ds) is True


def test_series_is_ct_head_candidate_uses_cached_head_signal(tmp_path: Path) -> None:
    series = tmp_path / "cached_head"
    series.mkdir()
    with patch(
        "anonymizer.controller.ai.blur_face.pipeline.cached_region_signal",
        return_value=CachedRegionSignal.HEAD,
    ):
        assert series_is_ct_head_candidate(series, _ds(body_part="CHEST")) is True


def test_should_prompt_brain_structures_ct_head_when_ready(tmp_path: Path) -> None:
    series = tmp_path / "head"
    series.mkdir()
    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=True,
    ):
        assert should_prompt_brain_structures_for_series(series, _ds()) is True


def test_should_prompt_brain_structures_rejects_mr_chest_and_missing_models(tmp_path: Path) -> None:
    series = tmp_path / "series"
    series.mkdir()
    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=True,
    ):
        assert should_prompt_brain_structures_for_series(series, _ds(modality="MR")) is False
        assert should_prompt_brain_structures_for_series(
            series,
            _ds(body_part="CHEST", series="CHEST CT W CONTRAST"),
        ) is False

    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=False,
    ):
        assert should_prompt_brain_structures_for_series(series, _ds()) is False
