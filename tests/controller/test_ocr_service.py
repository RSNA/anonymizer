"""Tests for process-wide OcrService in remove_pixel_phi."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.remove_pixel_phi import OcrService, OCRText, _ocr_use_gpu, _OcrJob


@pytest.fixture(autouse=True)
def _reset_ocr_service():
    OcrService.reset_for_tests()
    yield
    OcrService.reset_for_tests()


def test_ocr_use_gpu_follows_cuda_availability() -> None:
    with patch("anonymizer.controller.remove_pixel_phi.torch.cuda.is_available", return_value=True):
        assert _ocr_use_gpu() is True
    with patch("anonymizer.controller.remove_pixel_phi.torch.cuda.is_available", return_value=False):
        assert _ocr_use_gpu() is False


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_process_dicom_path_dispatches_to_worker(mock_reader_cls: MagicMock) -> None:
    reader = MagicMock()
    mock_reader_cls.return_value = reader

    with patch(
        "anonymizer.controller.remove_pixel_phi.remove_pixel_phi",
        return_value=(True, ["PHI"], 128),
    ) as mock_remove:
        service = OcrService.instance()
        service.ensure_models = MagicMock()
        modified, texts, pixels_changed = service.process_dicom_path(Path("/tmp/test.dcm"))

    assert modified is True
    assert texts == ["PHI"]
    assert pixels_changed == 128
    mock_remove.assert_called_once()
    assert mock_remove.call_args.args[0] == Path("/tmp/test.dcm")
    assert mock_remove.call_args.args[1] is reader


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_detect_text_dispatches_to_worker(mock_reader_cls: MagicMock) -> None:
    reader = MagicMock()
    mock_reader_cls.return_value = reader
    expected = [OCRText(text="ABC", top_left=(0, 0), bottom_right=(10, 10), prob=0.9)]

    with patch(
        "anonymizer.controller.remove_pixel_phi.detect_text",
        return_value=expected,
    ) as mock_detect:
        service = OcrService.instance()
        service.ensure_models = MagicMock()
        pixels = np.zeros((32, 32), dtype=np.uint8)
        results = service.detect_text(pixels, draw_boxes=False)

    assert results == expected
    mock_detect.assert_called_once_with(pixels, reader, draw_boxes_and_text=False)


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_batch_session_preloads_reader_once(mock_reader_cls: MagicMock) -> None:
    mock_reader_cls.return_value = MagicMock()
    service = OcrService.instance()
    service.ensure_models = MagicMock()

    with service.batch_session():
        with service.batch_session():
            pass

    assert mock_reader_cls.call_count == 1


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_pending_count_includes_queued_jobs(mock_reader_cls: MagicMock) -> None:
    mock_reader_cls.return_value = MagicMock()
    service = OcrService.instance()
    service.ensure_models = MagicMock()
    assert service.pending_count() == 0
    service._queue.put(_OcrJob(preload_only=True))
    assert service.pending_count() == 1
    service._preload_reader()
    assert service.pending_count() == 0


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_shutdown_batch_releases_reader_and_clears_singleton(mock_reader_cls: MagicMock) -> None:
    mock_reader_cls.return_value = MagicMock()
    with patch(
        "anonymizer.controller.remove_pixel_phi.remove_pixel_phi",
        return_value=(False, []),
    ):
        service = OcrService.instance()
        service.ensure_models = MagicMock()
        service.process_dicom_path(Path("/tmp/test.dcm"))
    OcrService.shutdown_batch()
    assert OcrService._instance is None
    assert not service._worker.is_alive()


@patch("anonymizer.controller.remove_pixel_phi.Reader")
def test_run_propagates_worker_errors(mock_reader_cls: MagicMock) -> None:
    mock_reader_cls.return_value = MagicMock()
    service = OcrService.instance()

    def _fail(_reader):
        raise RuntimeError("ocr failed")

    with pytest.raises(RuntimeError, match="ocr failed"):
        service._run(_fail)
