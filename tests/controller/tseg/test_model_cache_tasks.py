"""Tests for harmonize TotalSegmentator task selection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from anonymizer.controller.tseg.model_cache import (
    _ensure_pretrained_weights,
    harmonize_anatomy_task_ids,
    harmonize_contrast_task_ids,
    harmonize_ts_task_ids,
    missing_harmonize_ts_task_ids,
    model_for_harmonize_task,
    resolve_harmonize_model_folder,
    trainer_for_harmonize_task,
)


def test_harmonize_anatomy_task_ids_include_crop_model_for_3mm() -> None:
    assert harmonize_anatomy_task_ids() == (297, 298)


def test_harmonize_contrast_task_ids_include_headneck_vessels() -> None:
    assert harmonize_contrast_task_ids() == (776,)


def test_harmonize_ts_task_ids_combine_segmentation_and_contrast() -> None:
    assert harmonize_ts_task_ids() == (297, 298, 776)


def test_harmonize_task_776_uses_high_resolution_model() -> None:
    assert trainer_for_harmonize_task(776) == "nnUNetTrainer_DASegOrd0_NoMirroring"
    assert model_for_harmonize_task(776) == "3d_fullres_high"


def test_resolve_harmonize_model_folder_returns_path() -> None:
    expected = Path("/models/Dataset297_example")

    with (
        patch("totalsegmentator.config.setup_nnunet"),
        patch("totalsegmentator.config.setup_totalseg"),
        patch(
            "totalsegmentator.nnunet.get_output_folder",
            return_value=str(expected),
        ),
    ):
        assert resolve_harmonize_model_folder(297) == expected


def test_missing_harmonize_ts_task_ids_when_checkpoint_present(tmp_path: Path) -> None:
    model_folder = tmp_path / "Dataset297"
    (model_folder / "fold_0").mkdir(parents=True)
    (model_folder / "fold_0" / "checkpoint_final.pth").write_bytes(b"x")

    def _folder(task_id: int) -> Path | None:
        return model_folder if task_id == 297 else None

    with (
        patch(
            "anonymizer.controller.tseg.model_cache.resolve_harmonize_model_folder",
            side_effect=_folder,
        ),
        patch(
            "anonymizer.controller.tseg.model_cache.harmonize_ts_task_ids",
            return_value=(297, 298),
        ),
    ):
        assert missing_harmonize_ts_task_ids() == (298,)


def test_ensure_pretrained_weights_removes_empty_dataset_dir(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "Dataset297_TotalSegmentator_total_3mm_1559subj"
    dataset_dir.mkdir()
    model_folder = dataset_dir / "nnUNetTrainer_4000epochs_NoMirroring__nnUNetPlans__3d_fullres"
    trainer = trainer_for_harmonize_task(297)
    model = model_for_harmonize_task(297)

    with (
        patch(
            "anonymizer.controller.tseg.model_cache._resolve_task_model_folder",
            return_value=model_folder,
        ),
        patch(
            "anonymizer.controller.tseg.model_cache._task_checkpoint_ready",
            side_effect=[False, True],
        ),
        patch("totalsegmentator.libs.download_pretrained_weights") as download,
    ):
        _ensure_pretrained_weights(297, trainer=trainer, model=model)

    assert not dataset_dir.exists()
    download.assert_called_once_with(297)


def test_ensure_pretrained_weights_skips_when_checkpoint_ready(tmp_path: Path) -> None:
    model_folder = tmp_path / "Dataset297" / "nnUNetTrainer__nnUNetPlans__3d_fullres"
    trainer = trainer_for_harmonize_task(297)
    model = model_for_harmonize_task(297)

    with (
        patch(
            "anonymizer.controller.tseg.model_cache._resolve_task_model_folder",
            return_value=model_folder,
        ),
        patch(
            "anonymizer.controller.tseg.model_cache._task_checkpoint_ready",
            return_value=True,
        ),
        patch("totalsegmentator.libs.download_pretrained_weights") as download,
    ):
        _ensure_pretrained_weights(297, trainer=trainer, model=model)

    download.assert_not_called()
