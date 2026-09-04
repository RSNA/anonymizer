"""Tests for harmonize TotalSegmentator task selection."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.tseg.model_cache import (
    _ensure_pretrained_weights,
    harmonize_anatomy_task_ids,
    harmonize_contrast_task_ids,
    harmonize_ts_task_ids,
    missing_harmonize_ts_task_ids,
    model_for_harmonize_task,
    resolve_harmonize_model_folder,
    trainer_for_harmonize_task,
    ts_task_download_label,
)


def _install_fake_totalsegmentator(
    *,
    get_output_folder: MagicMock | None = None,
    download_pretrained_weights: MagicMock | None = None,
) -> dict[str, types.ModuleType]:
    """Register lightweight totalsegmentator stubs so patches work without the package."""
    ts = types.ModuleType("totalsegmentator")
    ts_config = types.ModuleType("totalsegmentator.config")
    ts_config.setup_nnunet = MagicMock()
    ts_config.setup_totalseg = MagicMock()
    ts_nnunet = types.ModuleType("totalsegmentator.nnunet")
    ts_nnunet.get_output_folder = get_output_folder or MagicMock(return_value="/models/Dataset297")
    ts_libs = types.ModuleType("totalsegmentator.libs")
    ts_libs.download_pretrained_weights = download_pretrained_weights or MagicMock()
    return {
        "totalsegmentator": ts,
        "totalsegmentator.config": ts_config,
        "totalsegmentator.nnunet": ts_nnunet,
        "totalsegmentator.libs": ts_libs,
    }


def test_ts_task_download_label_uses_technical_model_id() -> None:
    """Controller progress uses task ids; clinician-friendly names live in the view layer."""
    assert ts_task_download_label(297) == "Model 297"
    assert ts_task_download_label(303) == "Model 303"
    assert ts_task_download_label(999) == "Model 999"


def test_harmonize_anatomy_task_ids_include_crop_model_for_3mm() -> None:
    from anonymizer.controller.ai.tseg import config as tseg_config

    tseg_config.clear_segmentation_mode_cache()
    try:
        tseg_config.set_ct_segmentation_mode("3mm")
        assert harmonize_anatomy_task_ids() == (297, 298)
    finally:
        tseg_config.clear_segmentation_mode_cache()


def test_harmonize_contrast_task_ids_include_headneck_vessels() -> None:
    assert harmonize_contrast_task_ids() == (776,)


def test_harmonize_ts_task_ids_combine_segmentation_and_contrast() -> None:
    from anonymizer.controller.ai.tseg import config as tseg_config

    tseg_config.clear_segmentation_mode_cache()
    try:
        tseg_config.set_ct_segmentation_mode("3mm")
        assert harmonize_ts_task_ids() == (297, 298, 776)
    finally:
        tseg_config.clear_segmentation_mode_cache()


def test_harmonize_modality_task_ids_are_separate() -> None:
    from anonymizer.controller.ai.tseg import config as tseg_config
    from anonymizer.controller.ai.tseg.model_cache import (
        face_task_ids,
        harmonize_feature_task_ids,
        mr_anatomy_task_ids,
        mr_face_task_ids,
    )

    tseg_config.clear_segmentation_mode_cache()
    try:
        tseg_config.set_ct_segmentation_mode("3mm")
        tseg_config.set_mr_segmentation_mode("3mm")
        assert harmonize_feature_task_ids() == (297, 298, 776)
        assert mr_anatomy_task_ids() == (852,)
        assert face_task_ids() == (303,)
        assert mr_face_task_ids() == (856,)
    finally:
        tseg_config.clear_segmentation_mode_cache()


def test_segmentation_mode_selects_ct_and_mr_task_packs() -> None:
    from anonymizer.controller.ai.tseg import config as tseg_config
    from anonymizer.controller.ai.tseg.model_cache import mr_anatomy_task_ids

    tseg_config.clear_segmentation_mode_cache()
    try:
        tseg_config.set_ct_segmentation_mode("6mm")
        assert harmonize_anatomy_task_ids() == (298,)
        tseg_config.set_ct_segmentation_mode("1.5mm")
        assert harmonize_anatomy_task_ids() == (291, 292, 293, 294, 295, 298)

        tseg_config.set_mr_segmentation_mode("6mm")
        assert mr_anatomy_task_ids() == (853,)
        tseg_config.set_mr_segmentation_mode("1.5mm")
        assert mr_anatomy_task_ids() == (850, 851, 852)
        tseg_config.set_mr_segmentation_mode("3mm")
        assert mr_anatomy_task_ids() == (852,)
    finally:
        tseg_config.clear_segmentation_mode_cache()


def test_harmonize_task_776_uses_high_resolution_model() -> None:
    assert trainer_for_harmonize_task(776) == "nnUNetTrainer_DASegOrd0_NoMirroring"
    assert model_for_harmonize_task(776) == "3d_fullres_high"


def test_mr_task_trainers_match_totalsegmentator_api() -> None:
    """MR readiness must use the same trainers as TS python_api (not CT 4000epochs / face NoMirroring)."""
    from anonymizer.controller.ai.tseg import model_cache as mc
    from anonymizer.controller.ai.tseg.readiness import _face_mr_task_spec

    assert trainer_for_harmonize_task(852) == "nnUNetTrainer_2000epochs_NoMirroring"
    assert trainer_for_harmonize_task(297) == "nnUNetTrainer_4000epochs_NoMirroring"
    assert mc._FACE_MR_TRAINER == "nnUNetTrainer_2000epochs_NoMirroring"
    assert _face_mr_task_spec() == (856, "nnUNetTrainer_2000epochs_NoMirroring", "3d_fullres")


def test_brain_structures_weights_match_totalsegmentator_api() -> None:
    """Readiness path must use the same trainer/model as TS python_api brain_structures."""
    from anonymizer.controller.ai.tseg import model_cache as mc
    from anonymizer.controller.ai.tseg.readiness import _brain_structures_task_spec

    assert mc._BRAIN_STRUCTURES_TASK_ID == 409
    assert mc._BRAIN_STRUCTURES_TRAINER == "nnUNetTrainer_DASegOrd0"
    assert mc._BRAIN_STRUCTURES_MODEL == "3d_fullres_high"
    assert _brain_structures_task_spec() == (409, "nnUNetTrainer_DASegOrd0", "3d_fullres_high")


def test_resolve_harmonize_model_folder_returns_path() -> None:
    expected = Path("/models/Dataset297_example")
    stubs = _install_fake_totalsegmentator(
        get_output_folder=MagicMock(return_value=str(expected)),
    )

    with patch.dict(sys.modules, stubs):
        assert resolve_harmonize_model_folder(297) == expected


def test_missing_harmonize_ts_task_ids_when_checkpoint_present(tmp_path: Path) -> None:
    model_folder = tmp_path / "Dataset297"
    (model_folder / "fold_0").mkdir(parents=True)
    (model_folder / "fold_0" / "checkpoint_final.pth").write_bytes(b"x")

    def _folder(task_id: int) -> Path | None:
        return model_folder if task_id == 297 else None

    with (
        patch(
            "anonymizer.controller.ai.tseg.model_cache.resolve_harmonize_model_folder",
            side_effect=_folder,
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache.harmonize_ts_task_ids",
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
    download = MagicMock()
    stubs = _install_fake_totalsegmentator(download_pretrained_weights=download)

    with (
        patch.dict(sys.modules, stubs),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._try_resolve_task_model_folder",
            return_value=model_folder,
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._task_checkpoint_ready",
            side_effect=[False, True],
        ),
    ):
        _ensure_pretrained_weights(297, trainer=trainer, model=model)

    assert not dataset_dir.exists()
    download.assert_called_once_with(297)


def test_ensure_pretrained_weights_skips_when_checkpoint_ready(tmp_path: Path) -> None:
    model_folder = tmp_path / "Dataset297" / "nnUNetTrainer__nnUNetPlans__3d_fullres"
    trainer = trainer_for_harmonize_task(297)
    model = model_for_harmonize_task(297)
    download = MagicMock()
    stubs = _install_fake_totalsegmentator(download_pretrained_weights=download)

    with (
        patch.dict(sys.modules, stubs),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._try_resolve_task_model_folder",
            return_value=model_folder,
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._task_checkpoint_ready",
            return_value=True,
        ),
    ):
        _ensure_pretrained_weights(297, trainer=trainer, model=model)

    download.assert_not_called()


def test_ensure_pretrained_weights_downloads_when_dataset_not_on_disk() -> None:
    trainer = trainer_for_harmonize_task(297)
    model = model_for_harmonize_task(297)
    download = MagicMock()
    stubs = _install_fake_totalsegmentator(download_pretrained_weights=download)

    with (
        patch.dict(sys.modules, stubs),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._try_resolve_task_model_folder",
            return_value=None,
        ),
        patch(
            "anonymizer.controller.ai.tseg.model_cache._task_checkpoint_ready",
            side_effect=[False, True],
        ),
    ):
        _ensure_pretrained_weights(297, trainer=trainer, model=model)

    download.assert_called_once_with(297)
