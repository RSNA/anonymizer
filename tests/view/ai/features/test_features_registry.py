"""Tests for AI Features catalog, labels, inventory, and download manager."""

from __future__ import annotations

import threading
from unittest.mock import patch

from anonymizer.controller.ai.feature_availability import harmonize_allowed, pixel_phi_allowed
from anonymizer.controller.ai.tseg.readiness import TsWeightKind
from anonymizer.view.ai.features.availability import (
    AiFeatureDownloadManager,
    DownloadCompleteEvent,
    collapse_inventory_labels,
    format_installed_inventory_status,
    friendly_task_label,
)
from anonymizer.view.ai.features.catalog import (
    AiModelGroupId,
    all_download_ids,
    all_model_groups,
    download_id_for_weight_kind,
    top_level_features,
)


def test_friendly_labels_have_no_ts_cli_abbreviations() -> None:
    forbidden = ("total_mr", "face_mr", "headneck_bones_vessels", " — ")
    for task_id in (291, 297, 298, 303, 409, 776, 850, 852, 856):
        label = friendly_task_label(task_id)
        lowered = label.lower()
        for bad in forbidden:
            assert bad not in lowered, label
        assert not lowered.startswith("total")
        assert not lowered.startswith("face")
        assert not lowered.startswith("brain_structures")


def test_collapse_inventory_labels_merges_ct_1_5_parts() -> None:
    labels = collapse_inventory_labels((291, 292, 293, 294, 295, 298, 776))
    assert "CT anatomy 1.5 mm (parts 1–5)" in labels
    assert "CT crop / 6 mm" in labels
    assert "CT contrast (head/neck)" in labels
    assert not any("part 1/5" in item for item in labels)


def test_registry_download_ids_unique_and_cover_weight_kinds() -> None:
    ids = all_download_ids()
    assert len(ids) == len(set(ids))
    for kind in TsWeightKind:
        assert download_id_for_weight_kind(kind) in ids
    assert len(top_level_features()) == 3
    assert {g.id for g in all_model_groups()} == set(AiModelGroupId)


def test_format_harmonize_inventory_includes_bullets() -> None:
    with patch(
        "anonymizer.view.ai.features.availability.installed_model_inventory",
        return_value=("CT anatomy 1.5 mm (parts 1–5)", "CT crop / 6 mm", "CT contrast (head/neck)"),
    ):
        text = format_installed_inventory_status(
            AiModelGroupId.HARMONIZE_CT,
            resolution_line="Installed: 1.5 mm.",
        )
    assert text.startswith("Installed: 1.5 mm.")
    assert "• CT anatomy 1.5 mm (parts 1–5)" in text
    assert "total" not in text
    assert "headneck" not in text


def test_download_manager_single_flight() -> None:
    manager = AiFeatureDownloadManager()
    started = threading.Event()
    release = threading.Event()
    completed: list[DownloadCompleteEvent] = []

    def worker() -> str:
        started.set()
        release.wait(timeout=2)
        return "ok"

    def on_complete(event: DownloadCompleteEvent) -> None:
        completed.append(event)

    assert manager.start("harmonize_ct_models", worker, on_complete=on_complete)
    assert started.wait(timeout=1)
    assert manager.busy()
    assert manager.start("face_ct_models", worker, on_complete=on_complete) is False
    release.set()
    manager._thread.join(timeout=2)  # noqa: SLF001 — test drains worker
    manager.clear_pending("harmonize_ct_models")
    assert not manager.busy()
    assert completed and completed[0].result == "ok"


def test_allowed_gates_are_readiness_only() -> None:
    with patch(
        "anonymizer.controller.ai.feature_availability.ocr_models_ready",
        return_value=True,
    ):
        assert pixel_phi_allowed() is True
    with (
        patch("anonymizer.controller.ai.feature_availability.totalsegmentator_available", return_value=True),
        patch("anonymizer.controller.ai.feature_availability.xgboost_available", return_value=True),
        patch(
            "anonymizer.controller.ai.feature_availability.installed_ct_segmentation_modes",
            return_value=("3mm",),
        ),
        patch(
            "anonymizer.controller.ai.feature_availability.installed_mr_segmentation_modes",
            return_value=(),
        ),
    ):
        assert harmonize_allowed() is True
