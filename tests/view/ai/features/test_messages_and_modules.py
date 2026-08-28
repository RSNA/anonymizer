"""Tests for AI Features view strings and tseg module boundaries."""

from __future__ import annotations

from anonymizer.controller.ai.tseg import ml_env, readiness
from anonymizer.controller.ai.tseg.config import (
    clear_segmentation_mode_cache,
    get_ct_segmentation_mode,
    set_ct_segmentation_mode,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.availability import friendly_task_label
from anonymizer.view.ai.features.catalog import AiFeatureId, feature_title


def test_ml_env_and_readiness_modules_export_expected_symbols() -> None:
    assert callable(ml_env.sequential_ml_context)
    assert callable(readiness.anatomy_ct_ready)
    assert callable(readiness.weight_kind_ready)
    assert callable(readiness.download_segmentation_model)
    assert not hasattr(readiness, "get_runtime_status")
    assert readiness.TsWeightKind.ANATOMY.value == "anatomy"
    assert feature_title(AiFeatureId.HARMONIZE.value) == "Harmonize"


def test_feature_strings_use_gettext() -> None:
    assert _("Remove") == "Remove"
    assert _("Downloading. This may take several minutes.").startswith("Downloading")
    assert _(
        "The downloaded models for this tool will be removed from disk. Are you sure?"
    ).startswith("The downloaded models")
    assert friendly_task_label(297) == "CT anatomy 3 mm"
    assert friendly_task_label(856) == "MR face 1.5 mm"
    assert "total" not in friendly_task_label(852).lower()
    assert "face_mr" not in friendly_task_label(856)


def test_segmentation_modes_are_ephemeral() -> None:
    clear_segmentation_mode_cache()
    try:
        assert get_ct_segmentation_mode() == "3mm"
        set_ct_segmentation_mode("1.5mm")
        assert get_ct_segmentation_mode() == "1.5mm"
        set_ct_segmentation_mode("6mm")
        assert get_ct_segmentation_mode() == "6mm"
    finally:
        clear_segmentation_mode_cache()
