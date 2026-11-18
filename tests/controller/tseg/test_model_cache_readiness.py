"""Unit tests for TotalSegmentator model_cache readiness helpers."""

from types import SimpleNamespace
from unittest.mock import patch

from anonymizer.controller.ai.tseg import model_cache as mc


def test_installed_ct_segmentation_modes_from_checkpoint_probe() -> None:
    def ready(task_id: int) -> bool:
        # 3mm pack: 297, 298 (+776 if contrast). Treat only 297/298/776 as ready.
        return task_id in {297, 298, 776}

    with (
        patch.object(mc, "ENABLE_TS_CONTRAST", True),
        patch.object(mc, "_harmonize_task_checkpoint_ready", side_effect=ready),
    ):
        # 6mm pack is only task 298 (+contrast); ready whenever 3mm's shared tasks are.
        assert mc.installed_ct_segmentation_modes() == ("3mm", "6mm")


def test_installed_mr_segmentation_modes_from_checkpoint_probe() -> None:
    def ready(task_id: int) -> bool:
        return task_id in {852, 853}

    with patch.object(mc, "_harmonize_task_checkpoint_ready", side_effect=ready):
        assert mc.installed_mr_segmentation_modes() == ("3mm", "6mm")


def test_missing_face_feature_task_ids_when_probe_false() -> None:
    with patch.object(mc, "_task_checkpoint_ready", return_value=False):
        assert mc.missing_face_feature_task_ids() == mc.face_task_ids()
        assert mc.missing_mr_face_task_ids() == mc.mr_face_task_ids()


def test_harmonize_and_face_feature_or_gates() -> None:
    with (
        patch.object(mc, "anatomy_models_ready", return_value=False),
        patch.object(mc, "mr_anatomy_models_ready", return_value=True),
        patch.object(mc, "ct_face_models_ready", return_value=False),
        patch.object(mc, "mr_face_models_ready", return_value=True),
    ):
        assert mc.harmonize_feature_models_ready() is True
        assert mc.face_feature_models_ready() is True
    with (
        patch.object(mc, "anatomy_models_ready", return_value=False),
        patch.object(mc, "mr_anatomy_models_ready", return_value=False),
        patch.object(mc, "ct_face_models_ready", return_value=False),
        patch.object(mc, "mr_face_models_ready", return_value=False),
    ):
        assert mc.harmonize_feature_models_ready() is False
        assert mc.face_feature_models_ready() is False


def test_profile_anatomy_and_face_weights_ready_route_by_modality() -> None:
    ct_profile = SimpleNamespace(modality="CT", anatomy_task_ids=(297,), face_task_id=303)
    mr_profile = SimpleNamespace(modality="MR", anatomy_task_ids=(852,), face_task_id=856)
    with (
        patch.object(mc, "anatomy_models_ready", return_value=True),
        patch.object(mc, "_face_task_checkpoint_ready", return_value=True),
        patch.object(mc, "_harmonize_task_checkpoint_ready", return_value=False),
        patch.object(mc, "_task_checkpoint_ready", return_value=False),
    ):
        assert mc.profile_anatomy_weights_ready(ct_profile) is True
        assert mc.profile_face_weights_ready(ct_profile) is True
        assert mc.profile_anatomy_weights_ready(mr_profile) is False
        assert mc.profile_face_weights_ready(mr_profile) is False
    with (
        patch.object(mc, "_harmonize_task_checkpoint_ready", return_value=True),
        patch.object(mc, "_task_checkpoint_ready", return_value=True),
    ):
        assert mc.profile_anatomy_weights_ready(mr_profile) is True
        assert mc.profile_face_weights_ready(mr_profile) is True
