"""Unit tests for TotalSegmentator predictor cache and preload (no live downloads)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.tseg import model_cache as mc


@pytest.fixture(autouse=True)
def _clear_predictor_cache() -> None:
    mc.clear_predictor_cache()
    yield
    mc.clear_predictor_cache()


def test_create_predictor_gpu_kwarg_vs_device_kwarg() -> None:
    nnunet = MagicMock()
    predictor_cls = MagicMock(return_value=MagicMock(name="predictor"))
    nnunet.supports_keyword_argument.return_value = True
    mc._create_predictor(
        step_size=0.5,
        disable_tta=True,
        device="cpu",
        quiet=True,
        nnunet_module=nnunet,
        nnUNetPredictor=predictor_cls,
    )
    kwargs = predictor_cls.call_args.kwargs
    assert kwargs.get("perform_everything_on_gpu") is True

    predictor_cls.reset_mock()
    nnunet.supports_keyword_argument.return_value = False
    mc._create_predictor(
        step_size=0.5,
        disable_tta=False,
        device="cpu",
        quiet=False,
        nnunet_module=nnunet,
        nnUNetPredictor=predictor_cls,
    )
    kwargs = predictor_cls.call_args.kwargs
    assert kwargs.get("perform_everything_on_device") is True
    assert kwargs.get("use_mirroring") is True


def test_get_or_create_predictor_reuses_cache() -> None:
    nnunet = MagicMock()
    nnunet.supports_keyword_argument.return_value = False
    predictor = MagicMock(name="predictor")
    predictor_cls = MagicMock(return_value=predictor)

    first = mc._get_or_create_predictor(
        model_folder="/models/Dataset297",
        folds=[0],
        checkpoint_name="checkpoint_final.pth",
        device="cpu",
        step_size=0.5,
        disable_tta=True,
        nnunet_module=nnunet,
        nnUNetPredictor=predictor_cls,
        quiet=True,
    )
    second = mc._get_or_create_predictor(
        model_folder="/models/Dataset297",
        folds=[0],
        checkpoint_name="checkpoint_final.pth",
        device="cpu",
        step_size=0.5,
        disable_tta=True,
        nnunet_module=nnunet,
        nnUNetPredictor=predictor_cls,
        quiet=True,
    )
    assert first is second is predictor
    predictor_cls.assert_called_once()
    predictor.initialize_from_trained_model_folder.assert_called_once()


def test_install_predictor_cache_patch_idempotent() -> None:
    fake_nnunet = MagicMock()
    fake_nnunet.nnUNetv2_predict = MagicMock(name="orig")
    with patch.object(mc, "nnunet_module", fake_nnunet):
        was = mc._patch_installed
        mc._patch_installed = False
        mc._original_nnUNetv2_predict = None
        try:
            mc._install_predictor_cache_patch()
            assert mc._patch_installed is True
            assert fake_nnunet.nnUNetv2_predict is mc._cached_nnUNetv2_predict
            patched = fake_nnunet.nnUNetv2_predict
            mc._install_predictor_cache_patch()
            assert fake_nnunet.nnUNetv2_predict is patched
        finally:
            mc._patch_installed = was


def test_cached_nnunet_predict_falls_back_without_session() -> None:
    orig = MagicMock(return_value="ok")
    with (
        patch.object(mc, "session_active", return_value=False),
        patch.object(mc, "_original_nnUNetv2_predict", orig),
    ):
        assert mc._cached_nnUNetv2_predict("/in", "/out", 297) == "ok"
    orig.assert_called_once()


def test_cached_nnunet_predict_uses_predictor_when_session_active(tmp_path: Path) -> None:
    predictor = MagicMock()
    out = tmp_path / "out"
    out.mkdir()
    (out / "s01.npz").write_bytes(b"n")
    (out / "s01.pkl").write_bytes(b"p")
    save = tmp_path / "probs.npz"

    with (
        patch.object(mc, "session_active", return_value=True),
        patch.object(mc, "_original_nnUNetv2_predict", MagicMock()),
        patch.object(mc, "get_output_folder", return_value="/models/Dataset297"),
        patch.object(mc, "_get_or_create_predictor", return_value=predictor),
        patch.object(mc, "nnunet_module") as nnunet,
        patch.object(mc.torch, "set_num_threads"),
    ):
        nnunet.supports_keyword_argument.return_value = False
        mc._cached_nnUNetv2_predict(
            tmp_path / "in",
            out,
            297,
            device="cpu",
            quiet=True,
            save_probabilities_path=str(save),
        )
    predictor.predict_from_files.assert_called_once()
    assert save.is_file()
    assert save.with_suffix(".pkl").is_file()


def test_preload_face_skips_without_license() -> None:
    with (
        patch.object(mc, "verify_face_license", return_value=(False, "no license")),
        patch.object(mc, "setup_nnunet") as setup,
    ):
        mc.preload_face_models(device="cpu")
    setup.assert_not_called()


def test_preload_face_success_path() -> None:
    with (
        patch.object(mc, "verify_face_license", return_value=(True, "")),
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "resolve_device", return_value="cpu"),
        patch.object(mc, "ct_face_models_ready", return_value=True),
        patch.object(mc, "mr_face_models_ready", return_value=False),
        patch.object(mc, "face_task_ids", return_value=(303,)),
        patch.object(mc, "download_pretrained_weights"),
        patch.object(mc, "get_output_folder", return_value="/models/face"),
        patch.object(mc, "_get_or_create_predictor") as get_pred,
        patch.object(mc, "nnunet_module", MagicMock()),
        patch.object(mc, "nnUNetPredictor", MagicMock()),
    ):
        mc.preload_face_models(device="cpu")
    get_pred.assert_called_once()


def test_preload_harmonize_skips_when_no_weights() -> None:
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "resolve_device", return_value="cpu"),
        patch.object(mc, "anatomy_models_ready", return_value=False),
        patch.object(mc, "mr_anatomy_models_ready", return_value=False),
        patch.object(mc, "download_pretrained_weights") as dl,
    ):
        mc.preload_harmonize_models(device="cpu")
    dl.assert_not_called()


def test_preload_harmonize_success_path() -> None:
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "resolve_device", return_value="cpu"),
        patch.object(mc, "anatomy_models_ready", return_value=True),
        patch.object(mc, "mr_anatomy_models_ready", return_value=False),
        patch.object(mc, "is_multi_model_segmentation_mode", return_value=False),
        patch.object(mc, "get_ct_segmentation_mode", return_value="3mm"),
        patch.object(mc, "harmonize_ts_task_ids", return_value=(297,)),
        patch.object(mc, "harmonize_anatomy_task_ids", return_value=(297,)),
        patch.object(mc, "harmonize_contrast_task_ids", return_value=()),
        patch.object(mc, "trainer_for_harmonize_task", return_value="nnUNetTrainer"),
        patch.object(mc, "model_for_harmonize_task", return_value="3d_fullres"),
        patch.object(mc, "download_pretrained_weights"),
        patch.object(mc, "get_output_folder", return_value="/models/297"),
        patch.object(mc, "_get_or_create_predictor") as get_pred,
        patch.object(mc, "nnunet_module", MagicMock()),
        patch.object(mc, "nnUNetPredictor", MagicMock()),
    ):
        mc.preload_harmonize_models(device="cpu")
    get_pred.assert_called_once()
