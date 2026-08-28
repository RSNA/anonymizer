"""AI Features: active workstation resolution drives Harmonize download need."""

from __future__ import annotations

from unittest.mock import patch

from anonymizer.controller.ai.tseg.config import clear_segmentation_mode_cache, set_ct_segmentation_mode
from anonymizer.view.ai.features.availability import (
    ai_feature_status_harmonize_ct,
    harmonize_ct_needs_download,
)


def test_harmonize_ct_needs_download_is_mode_aware() -> None:
    clear_segmentation_mode_cache()
    try:
        set_ct_segmentation_mode("3mm")
        with (
            patch("anonymizer.view.ai.features.availability.totalsegmentator_available", return_value=True),
            patch("anonymizer.view.ai.features.availability.xgboost_available", return_value=True),
            patch("anonymizer.view.ai.features.availability.anatomy_ct_ready", return_value=False) as ready,
        ):
            assert harmonize_ct_needs_download() is True
            ready.assert_called_with("3mm")

        with (
            patch("anonymizer.view.ai.features.availability.totalsegmentator_available", return_value=True),
            patch("anonymizer.view.ai.features.availability.xgboost_available", return_value=True),
            patch("anonymizer.view.ai.features.availability.anatomy_ct_ready", return_value=True),
        ):
            assert harmonize_ct_needs_download() is False
    finally:
        clear_segmentation_mode_cache()


def test_harmonize_ct_status_includes_active_resolution() -> None:
    clear_segmentation_mode_cache()
    try:
        set_ct_segmentation_mode("1.5mm")
        with (
            patch("anonymizer.view.ai.features.availability.totalsegmentator_available", return_value=True),
            patch("anonymizer.view.ai.features.availability.xgboost_available", return_value=True),
            patch(
                "anonymizer.view.ai.features.availability.installed_ct_segmentation_modes",
                return_value=("3mm", "1.5mm"),
            ),
        ):
            status = ai_feature_status_harmonize_ct()
        assert status == "Also installed: 3 mm."
        assert "•" not in status
    finally:
        clear_segmentation_mode_cache()
