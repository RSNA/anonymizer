"""Harmonize Description Dialog brain-structures offer (CT Head only)."""

from __future__ import annotations

from unittest.mock import patch

from pydicom import Dataset

from anonymizer.view.ai.harmonize_results import offer_brain_structures_for_series


def _ds(*, modality: str = "CT", body_part: str = "HEAD", series: str = "BRAIN AX") -> Dataset:
    ds = Dataset()
    ds.Modality = modality
    ds.BodyPartExamined = body_part
    ds.SeriesDescription = series
    return ds


def test_offer_brain_structures_ct_head_when_ready() -> None:
    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=True,
    ):
        assert offer_brain_structures_for_series(_ds()) is True


def test_offer_brain_structures_rejects_mr_and_chest() -> None:
    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=True,
    ):
        assert offer_brain_structures_for_series(_ds(modality="MR")) is False
        assert (
            offer_brain_structures_for_series(
                _ds(body_part="CHEST", series="CHEST CT W CONTRAST")
            )
            is False
        )


def test_offer_brain_structures_requires_models() -> None:
    with patch(
        "anonymizer.view.ai.harmonize_results.brain_structures_allowed",
        return_value=False,
    ):
        assert offer_brain_structures_for_series(_ds()) is False
