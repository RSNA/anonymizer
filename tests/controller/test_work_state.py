"""Tests for WorkState."""

from __future__ import annotations

import numpy as np
import pytest
from pydicom.data import get_testdata_file
from pydicom import dcmread

from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState


@pytest.fixture
def sample_volume() -> tuple[object, np.ndarray, tuple]:
    ds = dcmread(get_testdata_file("CT_small.dcm"))
    frames = np.zeros((1, ds.Rows, ds.Columns), dtype=np.float32)
    return ds, frames, ()


def test_work_state_bind_and_frame_count(sample_volume) -> None:
    ds, frames, paths = sample_volume
    ws = WorkState()
    ws.bind(ds, frames, paths, (40.0, 400.0), single_frame=True)
    assert ws.frame_count(Algorithm.REMOVE_PIXEL_PHI) == 1
    assert ws.frame_at(0, Algorithm.REMOVE_PIXEL_PHI).shape == frames[0].shape


def test_work_state_multi_frame_uses_direct_slice_indices(sample_volume) -> None:
    ds, one, paths = sample_volume
    stack = np.zeros((4,) + one.shape[1:], dtype=np.float32)
    ws = WorkState()
    ws.bind(ds, stack, paths, (40.0, 400.0), single_frame=False)
    assert ws.frame_count(Algorithm.REMOVE_PIXEL_PHI) == 4
    assert ws.frame_count(Algorithm.HARMONIZE) == 4
    anatomical = ws.frame_at(2, Algorithm.HARMONIZE)
    assert np.shares_memory(anatomical, stack[2])


def test_work_state_snapshot_result_is_copy(sample_volume) -> None:
    ds, frames, paths = sample_volume
    ws = WorkState()
    ws.bind(ds, frames, paths, (1.0, 2.0), single_frame=True)
    live: dict[int, str] = {0: "a"}
    ws.result = live
    _idx, _status, _done, snap = ws.snapshot_progress()
    assert snap is not live
    assert snap == {0: "a"}
    snap[1] = "mutated-in-snapshot"
    assert live == {0: "a"}
    assert snap[1] == "mutated-in-snapshot"
    ws.result = {0: "a", 1: "b"}
    _idx, _status, _done, snap2 = ws.snapshot_progress()
    assert snap2 == {0: "a", 1: "b"}


def test_work_state_snapshot_safe_while_result_replaced(sample_volume) -> None:
    """UI can iterate a snapshot copy while worker replaces work_state.result."""
    ds, frames, paths = sample_volume
    ws = WorkState()
    ws.bind(ds, frames, paths, (1.0, 2.0), single_frame=True)
    ws.result = {0: ["frame0"]}
    _idx, _status, _done, snap = ws.snapshot_progress()
    assert isinstance(snap, dict)
    ws.result = {0: ["frame0"], 1: ["frame1"]}
    collected = list(snap.items())
    assert collected == [(0, ["frame0"])]


def test_work_state_set_progress_and_finish(sample_volume) -> None:
    ds, frames, paths = sample_volume
    ws = WorkState()
    ws.bind(ds, frames, paths, (1.0, 2.0), single_frame=True)
    ws.set_progress(0, "working")
    idx, status, done, result = ws.snapshot_progress()
    assert idx == 0 and status == "working" and not done
    ws.finish({"ok": True})
    _, _, done, result = ws.snapshot_progress()
    assert done and result == {"ok": True}


def test_work_state_cancel() -> None:
    ws = WorkState()
    assert not ws.should_cancel()
    ws.request_cancel()
    assert ws.should_cancel()
    ws.request_cancel()
    assert ws.should_cancel()


def test_work_state_update_job_progress_and_read_ui() -> None:
    ws = WorkState()
    ws.update_job_progress(status="working", fraction=0.42, detail={"stage": "geometry"})
    status, done, fraction, error, result, detail = ws.read_job_ui()
    assert status == "working"
    assert not done
    assert fraction == pytest.approx(0.42)
    assert error is None
    assert result is None
    assert detail == {"stage": "geometry"}


def test_work_state_prepare_job_clears_completion_fields() -> None:
    ws = WorkState()
    ws.finish("done")
    ws.prepare_job()
    status, done, fraction, error, result, _detail = ws.read_job_ui()
    assert not done
    assert status == ""
    assert fraction == 0.0
    assert error is None
    assert result is None


def test_work_state_batch_logs_append_and_drain() -> None:
    ws = WorkState()
    ws.append_log("line one")
    ws.append_log("line two")
    drained = ws.drain_logs()
    assert drained == ["line one", "line two"]
    assert ws.drain_logs() == []
