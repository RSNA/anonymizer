"""Tests for RemovePixelPhiRunner model lifecycle (replaces OcrService)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.ai.remove_pixel_phi import _ocr_use_gpu
from anonymizer.controller.runner import RemovePixelPhiRunner


def test_ocr_use_gpu_follows_cuda_or_mps_availability() -> None:
    with (
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.cuda.is_available", return_value=True),
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.backends.mps.is_available", return_value=False),
    ):
        assert _ocr_use_gpu() is True
    with (
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.cuda.is_available", return_value=False),
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.backends.mps.is_available", return_value=True),
    ):
        assert _ocr_use_gpu() is True
    with (
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.cuda.is_available", return_value=False),
        patch("anonymizer.controller.ai.remove_pixel_phi.torch.backends.mps.is_available", return_value=False),
    ):
        assert _ocr_use_gpu() is False


@patch("anonymizer.controller.runner.Reader")
@patch("anonymizer.controller.runner.ocr_models_ready", return_value=True)
def test_remove_pixel_phi_runner_enter_exit_models(
    _mock_ready: MagicMock,
    mock_reader_cls: MagicMock,
) -> None:
    reader = MagicMock()
    mock_reader_cls.return_value = reader
    runner = RemovePixelPhiRunner()

    handle = runner.enter_models()
    assert handle.reader is reader
    runner.exit_models(handle)
    assert handle.reader is None


@patch("anonymizer.controller.runner.download_ocr_models")
@patch("anonymizer.controller.runner.ocr_models_ready", return_value=False)
def test_remove_pixel_phi_runner_downloads_when_models_missing(
    _mock_ready: MagicMock,
    mock_download: MagicMock,
) -> None:
    with patch("anonymizer.controller.runner.Reader", return_value=MagicMock()):
        runner = RemovePixelPhiRunner()
        handle = runner.enter_models()
        mock_download.assert_called_once()
        runner.exit_models(handle)
