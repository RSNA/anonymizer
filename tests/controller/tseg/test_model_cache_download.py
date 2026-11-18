"""Unit tests for TotalSegmentator model_cache download helpers (no live downloads)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.tseg import model_cache as mc
from anonymizer.controller.ai.tseg.ts_probe import TsWeightKind


def test_clear_predictor_cache_empties_store() -> None:
    sentinel = object()
    mc._predictor_cache[("k",)] = sentinel
    mc.clear_predictor_cache()
    assert mc._predictor_cache == {}


def test_resolve_totalseg_device_gpu_falls_back_to_cpu() -> None:
    with patch.object(mc.torch.cuda, "is_available", return_value=False):
        assert mc._resolve_totalseg_device("gpu") == "cpu"
    with patch.object(mc.torch.cuda, "is_available", return_value=True):
        assert mc._resolve_totalseg_device("gpu") == "cuda"


def test_download_face_raises_when_license_fails() -> None:
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "verify_face_license", return_value=(False, "no license")),
        patch.object(mc, "_ensure_pretrained_weights") as ensure,
    ):
        with pytest.raises(RuntimeError, match="no license"):
            mc.download_segmentation_model_weights(TsWeightKind.FACE)
    ensure.assert_not_called()


def test_download_anatomy_raises_when_still_missing() -> None:
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "harmonize_ts_task_ids", return_value=(297,)),
        patch.object(mc, "missing_harmonize_ts_task_ids", side_effect=[(297,), (297,)]),
        patch.object(mc, "_ensure_pretrained_weights"),
        patch.object(mc, "_track_segmentation_model_download") as track,
    ):
        track.return_value.__enter__ = MagicMock(return_value=None)
        track.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="still missing"):
            mc.download_segmentation_model_weights(TsWeightKind.ANATOMY)


def test_download_unknown_kind_raises() -> None:
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
    ):
        with pytest.raises(ValueError, match="Unknown segmentation model kind"):
            mc.download_segmentation_model_weights(object())  # type: ignore[arg-type]


def test_resolve_harmonize_model_folder_none_on_error() -> None:
    with (
        patch.object(mc, "setup_nnunet", side_effect=ImportError("no ts")),
    ):
        assert mc.resolve_harmonize_model_folder(297) is None
    with (
        patch.object(mc, "setup_nnunet"),
        patch.object(mc, "setup_totalseg"),
        patch.object(mc, "get_output_folder", side_effect=RuntimeError("boom")),
    ):
        assert mc.resolve_harmonize_model_folder(297) is None
