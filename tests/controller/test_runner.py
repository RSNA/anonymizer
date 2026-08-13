"""Tests for runner OCR path and DICOM windowing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pydicom
from pydicom.data import get_testdata_file

from anonymizer.controller.ai.remove_pixel_phi import OCRText, ocr_image_for_frame
from anonymizer.controller.runner import (
    Algorithm,
    OcrEditContext,
    RemovePixelPhiRunner,
    RunOptions,
    run_job,
)
from anonymizer.controller.work_state import WorkState
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.windowing import apply_windowing


def test_ocr_image_for_frame_uses_dicom_window_not_viewer_wl() -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frame = np.zeros((ds.Rows, ds.Columns), dtype=np.float32)
    wl, ww = get_wl_ww(ds)
    expected = apply_windowing(wl, ww, frame)
    actual = ocr_image_for_frame(ds, frame)
    assert np.array_equal(actual, expected)


@patch("anonymizer.controller.runner.RemovePixelPhiRunner.enter_models")
@patch("anonymizer.controller.runner.RemovePixelPhiRunner.exit_models")
@patch("anonymizer.controller.runner.detect_text")
@patch("anonymizer.controller.runner.ocr_image_for_frame")
def test_run_job_ocr_detect_uses_series_view_pixels_when_bound(
    mock_ocr_bgr: MagicMock,
    mock_detect: MagicMock,
    mock_exit: MagicMock,
    mock_enter: MagicMock,
) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((1, ds.Rows, ds.Columns), dtype=np.float32)
    ocr_pixels = np.zeros((1, ds.Rows, ds.Columns, 3), dtype=np.uint8)
    mock_enter.return_value = MagicMock(reader=MagicMock())
    mock_detect.return_value = [
        OCRText(text="ABC", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]

    ws = WorkState()
    ws.bind(ds, frames, (), get_wl_ww(ds), single_frame=True)
    ws.ocr_pixels = ocr_pixels
    options = RunOptions(edit_context=OcrEditContext.FRAME)
    run_job(Algorithm.REMOVE_PIXEL_PHI, ws, options=options)

    assert ws.done
    mock_detect.assert_called_once()
    assert mock_detect.call_args.kwargs["apply_noise_filter"] is False
    mock_ocr_bgr.assert_not_called()


@patch("anonymizer.controller.runner.RemovePixelPhiRunner.enter_models")
@patch("anonymizer.controller.runner.RemovePixelPhiRunner.exit_models")
@patch("anonymizer.controller.runner.detect_text")
@patch("anonymizer.controller.runner.ocr_image_for_frame")
def test_run_job_ocr_detect_series(
    mock_ocr_bgr: MagicMock,
    mock_detect: MagicMock,
    mock_exit: MagicMock,
    mock_enter: MagicMock,
) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((2, ds.Rows, ds.Columns), dtype=np.float32)
    mock_enter.return_value = MagicMock(reader=MagicMock())
    mock_ocr_bgr.return_value = np.zeros((ds.Rows, ds.Columns, 3), dtype=np.uint8)
    mock_detect.return_value = [
        OCRText(text="ABC", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]

    ws = WorkState()
    ws.bind(ds, frames, (), get_wl_ww(ds), single_frame=False)
    options = RunOptions(edit_context=OcrEditContext.SERIES)
    run_job(Algorithm.REMOVE_PIXEL_PHI, ws, options=options)

    assert ws.done
    assert ws.error is None
    assert mock_detect.call_count == 2
    mock_ocr_bgr.assert_called()
    mock_enter.assert_called_once()
    mock_exit.assert_called_once()


def test_remove_pixel_phi_runner_frame_context_single_index() -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((3, ds.Rows, ds.Columns), dtype=np.float32)
    ws = WorkState()
    ws.bind(ds, frames, (), get_wl_ww(ds), single_frame=True)
    ws.frame_index = 1
    runner = RemovePixelPhiRunner()
    with (
        patch.object(runner, "enter_models", return_value=MagicMock(reader=MagicMock())),
        patch.object(runner, "exit_models"),
        patch("anonymizer.controller.runner.detect_text", return_value=[]),
        patch("anonymizer.controller.runner.ocr_image_for_frame", return_value=np.zeros((1, 1, 3), dtype=np.uint8)),
    ):
        runner.process_series(
            ws,
            runner.enter_models(),
            options=RunOptions(edit_context=OcrEditContext.FRAME),
        )


@patch("anonymizer.controller.runner.load_modality_whitelist", return_value=["PORTABLE"])
@patch("anonymizer.controller.runner.detect_text")
@patch("anonymizer.controller.runner.ocr_image_for_frame")
def test_runner_cleared_whitelist_does_not_load_modality_defaults(
    mock_ocr_bgr: MagicMock,
    mock_detect: MagicMock,
    mock_load_wl: MagicMock,
) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((1, ds.Rows, ds.Columns), dtype=np.float32)
    mock_ocr_bgr.return_value = np.zeros((ds.Rows, ds.Columns, 3), dtype=np.uint8)
    mock_detect.return_value = [
        OCRText(text="Portable", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]

    ws = WorkState()
    ws.bind(ds, frames, (), get_wl_ww(ds), single_frame=True)
    runner = RemovePixelPhiRunner()
    with (
        patch.object(runner, "enter_models", return_value=MagicMock(reader=MagicMock())),
        patch.object(runner, "exit_models"),
    ):
        runner.process_series(
            ws,
            runner.enter_models(),
            options=RunOptions(edit_context=OcrEditContext.FRAME, whitelist=[], project_dir=MagicMock()),
        )

    mock_load_wl.assert_not_called()
    mock_detect.assert_called_once()
    assert mock_detect.call_args.kwargs["apply_noise_filter"] is False
    assert mock_detect.call_args.kwargs["whitelist"] == []


@patch("anonymizer.controller.runner.load_modality_whitelist", return_value=["PORTABLE"])
@patch("anonymizer.controller.runner.detect_text", return_value=[])
@patch("anonymizer.controller.runner.ocr_image_for_frame")
def test_runner_none_whitelist_loads_modality_defaults(
    mock_ocr_bgr: MagicMock,
    mock_detect: MagicMock,
    mock_load_wl: MagicMock,
) -> None:
    ds = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((1, ds.Rows, ds.Columns), dtype=np.float32)
    mock_ocr_bgr.return_value = np.zeros((ds.Rows, ds.Columns, 3), dtype=np.uint8)

    ws = WorkState()
    ws.bind(ds, frames, (), get_wl_ww(ds), single_frame=True)
    runner = RemovePixelPhiRunner()
    with (
        patch.object(runner, "enter_models", return_value=MagicMock(reader=MagicMock())),
        patch.object(runner, "exit_models"),
    ):
        runner.process_series(
            ws,
            runner.enter_models(),
            options=RunOptions(
                edit_context=OcrEditContext.FRAME,
                whitelist=None,
                project_dir=Path("/tmp/fake-project"),
            ),
        )

    mock_load_wl.assert_called_once_with(Path("/tmp/fake-project"), "CT")
    mock_detect.assert_called_once()
    assert mock_detect.call_args.kwargs["apply_noise_filter"] is False
    assert mock_detect.call_args.kwargs["whitelist"] == ["PORTABLE"]
