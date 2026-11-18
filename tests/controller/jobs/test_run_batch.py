"""Unit tests for jobs.runner.run_batch (mocked load/process)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from anonymizer.controller.jobs.runner import BatchSpec, RunOptions, run_batch
from anonymizer.controller.jobs.work_state import Algorithm, WorkState


def _loaded():
    ds = MagicMock()
    ds.SeriesInstanceUID = "1.2.3"
    return SimpleNamespace(
        metadata=ds,
        frames=np.zeros((1, 8, 8), dtype=np.float32),
        slice_paths=(Path("a.dcm"),),
        default_window=(40.0, 400.0),
        is_single_frame=True,
    )


def test_run_batch_happy_path_and_callback(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    series.mkdir()
    ws = WorkState()
    starts: list[tuple[Path, Algorithm]] = []
    runner = MagicMock()
    runner.enter_models.return_value = MagicMock()

    with (
        patch(
            "anonymizer.controller.jobs.runner.RUNNERS",
            {Algorithm.REMOVE_PIXEL_PHI: runner},
        ),
        patch(
            "anonymizer.controller.jobs.runner.load_series_frames",
            return_value=_loaded(),
        ),
    ):
        summary = run_batch(
            ws,
            BatchSpec(
                series_paths=(series,),
                algorithms=(Algorithm.REMOVE_PIXEL_PHI,),
                options=RunOptions(),
            ),
            on_series_start=lambda path, algo: starts.append((path, algo)),
        )

    assert summary.processed == 1
    assert summary.cancelled is False
    assert starts == [(series, Algorithm.REMOVE_PIXEL_PHI)]
    runner.process_series.assert_called_once()
    runner.exit_models.assert_called_once()
    assert ws.done


def test_run_batch_cancel_before_algorithm(tmp_path: Path) -> None:
    ws = WorkState()
    ws.cancel_requested = True
    runner = MagicMock()
    with patch(
        "anonymizer.controller.jobs.runner.RUNNERS",
        {Algorithm.REMOVE_PIXEL_PHI: runner},
    ):
        summary = run_batch(
            ws,
            BatchSpec(
                series_paths=(tmp_path,),
                algorithms=(Algorithm.REMOVE_PIXEL_PHI,),
            ),
        )
    assert summary.cancelled is True
    assert summary.processed == 0
    runner.enter_models.assert_not_called()


def test_run_batch_cancel_mid_series(tmp_path: Path) -> None:
    s1 = tmp_path / "a"
    s2 = tmp_path / "b"
    s1.mkdir()
    s2.mkdir()
    ws = WorkState()
    runner = MagicMock()
    runner.enter_models.return_value = MagicMock()

    def process_and_cancel(*_args, **_kwargs) -> None:
        ws.cancel_requested = True

    runner.process_series.side_effect = process_and_cancel
    with (
        patch(
            "anonymizer.controller.jobs.runner.RUNNERS",
            {Algorithm.REMOVE_PIXEL_PHI: runner},
        ),
        patch(
            "anonymizer.controller.jobs.runner.load_series_frames",
            return_value=_loaded(),
        ),
    ):
        summary = run_batch(
            ws,
            BatchSpec(
                series_paths=(s1, s2),
                algorithms=(Algorithm.REMOVE_PIXEL_PHI,),
            ),
        )

    assert summary.cancelled is True
    assert summary.processed == 1
    runner.exit_models.assert_called_once()
    runner.process_series.assert_called_once()


def test_run_batch_skips_unimplemented_algorithm(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    series.mkdir()
    ws = WorkState()
    runner = MagicMock()
    runner.enter_models.return_value = MagicMock()

    with (
        patch(
            "anonymizer.controller.jobs.runner.RUNNERS",
            {Algorithm.HARMONIZE: runner},
        ),
        patch(
            "anonymizer.controller.jobs.runner.load_series_frames",
            return_value=_loaded(),
        ),
    ):
        summary = run_batch(
            ws,
            BatchSpec(
                series_paths=(series,),
                algorithms=(Algorithm.HARMONIZE,),
            ),
        )

    assert summary.processed == 1
    runner.process_series.assert_not_called()
    runner.exit_models.assert_called_once()
