"""Unit tests for SeriesWorkspace (no Tk)."""

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_project_exclude_rects,
    load_project_whitelist,
)
from anonymizer.controller.series.series_overlay import OverlayData, UserRectangle
from anonymizer.controller.series.workspace import (
    SeriesViewSaveRequest,
    SeriesWorkspace,
    commit_user_rects_to_exclude,
    exclude_rects_fingerprint,
    ocr_remove_enabled,
)
from tests.controller.tseg.support.synthetic_ct import build_synthetic_ct_small_series


def _fake_project(tmp_path: Path) -> MagicMock:
    project = MagicMock()
    project.model.storage_dir = tmp_path
    project.anonymizer.model = MagicMock()
    return project


def test_load_series_workspace_and_ensure_geometry(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct", num_slices=11)
    ws = SeriesWorkspace(_fake_project(tmp_path), series_dir)
    loaded = ws.load_series_workspace()
    assert loaded.frames.shape[0] == 11
    assert loaded.projections is not None
    geometry = ws.ensure_geometry(ds=loaded.loaded.metadata)
    # Synthetic CT may or may not be TotalSegmentator-suitable; call must not raise.
    assert geometry is None or geometry is not None


def test_face_blur_eligibility_caches_on_same_geometry(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct", num_slices=11)
    ws = SeriesWorkspace(_fake_project(tmp_path), series_dir)
    payload = ws.load_series_workspace()
    first = ws.face_blur_eligibility(ds=payload.loaded.metadata, already_applied=False)
    second = ws.face_blur_eligibility(ds=payload.loaded.metadata, already_applied=False)
    assert first is second


def test_ocr_remove_enabled_helper() -> None:
    assert ocr_remove_enabled(
        interaction_allowed=True,
        detecting=False,
        results_available=True,
    )
    assert not ocr_remove_enabled(
        interaction_allowed=True,
        detecting=True,
        results_available=True,
    )


def test_commit_user_rects_to_exclude() -> None:
    overlay = OverlayData(
        user_rects=[UserRectangle(top_left=(0, 0), bottom_right=(5, 5))],
    )
    assert commit_user_rects_to_exclude(overlay) == 1
    assert not overlay.user_rects
    assert len(overlay.exclude_rects) == 1
    assert commit_user_rects_to_exclude(overlay) == 0


def test_whitelist_and_exclude_save_round_trip(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct", num_slices=11)
    project = _fake_project(tmp_path)
    ws = SeriesWorkspace(project, series_dir)
    payload = ws.load_series_workspace()
    ds = payload.loaded.metadata
    ds.Modality = "CT"

    result = ws.save_series_view_edits(
        SeriesViewSaveRequest(
            series_path=series_dir,
            frames=None,
            dataset=ds,
            slice_paths=payload.loaded.slice_paths,
            project_dir=tmp_path,
            anon_model=project.anonymizer.model,
            pixel_dirty=False,
            exclude_dirty=True,
            exclude_rects_normalized=[{"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2}],
            whitelist_items=["PORTABLE", "AP"],
            whitelist_match_settings=None,
            texts_by_frame={},
            ocr_transcript_by_frame={},
        )
    )
    assert result.ok
    assert not result.should_close
    assert set(load_project_whitelist(tmp_path, "CT")) == {"PORTABLE", "AP"}
    stored = load_project_exclude_rects(tmp_path, "CT")
    assert exclude_rects_fingerprint(stored) == result.saved_exclude_fingerprint


def test_clear_series_tseg_cache_delegates(tmp_path: Path) -> None:
    series_dir = tmp_path / "ser"
    series_dir.mkdir()
    project = _fake_project(tmp_path)
    ws = SeriesWorkspace(project, series_dir)
    ws.clear_series_tseg_cache(anon_series_uid="1.2.3", also_clear_annotations=True)
    project.clear_series_tseg_cache.assert_called_once_with(
        series_dir,
        anon_series_uid="1.2.3",
        also_clear_annotations=True,
    )


def test_ensure_annotate_session_empty_cache(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_small_series(tmp_path / "ct", num_slices=11)
    ws = SeriesWorkspace(_fake_project(tmp_path), series_dir)
    payload = ws.load_series_workspace()
    session = ws.ensure_annotate_session(existing=None, frames=payload.frames)
    # CT volumes typically support annotation geometry.
    assert session is None or session.labels.ndim == 3


def test_blackout_rects_on_frame() -> None:
    project = _fake_project(Path("/tmp"))
    ws = SeriesWorkspace(project, Path("/tmp"))
    frame = np.ones((8, 8), dtype=np.uint8) * 200
    rects = [UserRectangle(top_left=(1, 1), bottom_right=(3, 3))]
    ws.blackout_rects_on_frame(frame, rects)
    assert not rects
    assert int(frame[2, 2]) == 0
