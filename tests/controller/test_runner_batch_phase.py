"""Tests for HarmonizeRunner and FaceBlurRunner batch phase lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.runner import FaceBlurRunner, HarmonizeRunner


@patch("anonymizer.controller.ai.tseg.contrast.release_working_memory")
@patch("anonymizer.controller.ai.tseg.model_cache.tseg_batch_session")
def test_harmonize_runner_exit_releases_tseg_session(
    mock_session: MagicMock,
    mock_release: MagicMock,
) -> None:
    cm = MagicMock()
    mock_session.return_value = cm
    runner = HarmonizeRunner()
    handle = runner.enter_models()
    runner.exit_models(handle)
    cm.__exit__.assert_called_once()
    mock_release.assert_called_once_with(stage="batch_after_harmonize_phase", preserve_accelerator=True)


@patch("anonymizer.controller.ai.tseg.contrast.release_working_memory")
@patch("anonymizer.controller.ai.tseg.model_cache.clear_predictor_cache")
@patch("anonymizer.controller.ai.tseg.model_cache.preload_face_models")
@patch("anonymizer.controller.ai.tseg.model_cache.tseg_batch_session")
def test_face_blur_runner_exit_releases_models(
    mock_session: MagicMock,
    _mock_preload: MagicMock,
    mock_clear: MagicMock,
    mock_release: MagicMock,
) -> None:
    cm = MagicMock()
    mock_session.return_value = cm
    runner = FaceBlurRunner()
    handle = runner.enter_models()
    runner.exit_models(handle)
    cm.__exit__.assert_called_once()
    mock_clear.assert_called_once()
    mock_release.assert_called_once_with(stage="batch_after_face_blur_phase", preserve_accelerator=True)
