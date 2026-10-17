"""Tests for RemovePixelPhiRunner model lifecycle (replaces OcrService)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _ocr_use_gpu
from anonymizer.controller.jobs.runner import RemovePixelPhiRunner


def test_ocr_use_gpu_follows_cuda_or_mps_availability() -> None:
    with (
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.cuda.is_available", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.backends.mps.is_available", return_value=False),
    ):
        assert _ocr_use_gpu() is True
    with (
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.cuda.is_available", return_value=False),
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.backends.mps.is_available", return_value=True),
    ):
        assert _ocr_use_gpu() is True
    with (
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.cuda.is_available", return_value=False),
        patch("anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi.torch.backends.mps.is_available", return_value=False),
    ):
        assert _ocr_use_gpu() is False


@patch("anonymizer.controller.jobs.runner.Reader")
@patch("anonymizer.controller.jobs.runner.embedded_phi_has_models", return_value=True)
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


@patch("anonymizer.controller.jobs.runner.download_ocr_models")
@patch("anonymizer.controller.jobs.runner.download_ner_models")
@patch("anonymizer.controller.jobs.runner.embedded_phi_has_models", return_value=False)
def test_remove_pixel_phi_runner_downloads_when_models_missing(
    _mock_ready: MagicMock,
    mock_ner_download: MagicMock,
    mock_download: MagicMock,
) -> None:
    with patch("anonymizer.controller.jobs.runner.Reader", return_value=MagicMock()):
        runner = RemovePixelPhiRunner()
        handle = runner.enter_models()
        mock_download.assert_called_once()
        mock_ner_download.assert_called_once()
        runner.exit_models(handle)
