"""Series View load sequence tests using synthetic CT DICOM (no manual GUI).

The production startup path runs unstubbed: ``show_initial_frame`` and
``_ensure_series_geometry`` are the code most likely to regress sizing, so replacing
them with fast doubles would defeat the purpose of these tests.
"""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from anonymizer.controller.series_io import compute_series_projections, load_series_frames
from anonymizer.view.series import series as series_mod
from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView
from tests.controller.tseg.support.synthetic_ct import (
    DEFAULT_PHANTOM_SLICE_COUNT,
    FALCON_MIN_SLICES,
    build_synthetic_chest_ct_series,
    build_synthetic_ct_small_series,
    list_dcm_files,
)
from tests.view.series.support.layout_probes import (
    assert_chrome_unclipped,
    assert_pixmap_matches_display,
    drag_window,
    pump,
    settle,
    wait_for_viewer,
)


@pytest.fixture
def mock_controller() -> MagicMock:
    """Unharmonized series: segmentation chrome stays collapsed unless a test adds masks."""
    controller = MagicMock()
    controller.get_phi_by_anon_patient_id.return_value = None
    controller.get_series_processing_status.return_value = None
    controller.series_has_face_blur.return_value = False
    controller.series_is_harmonized.return_value = False
    controller.format_series_processing_status.return_value = ""
    return controller


def _open(tk_root: tk.Tk, controller: MagicMock, series_dir: Path, **kwargs) -> SeriesView:
    view = SeriesView(tk_root, controller=controller, series_path=series_dir, **kwargs)
    settle(view)
    return view


def _write_mask(path: Path, *, size: int = 8) -> None:
    """A readable segmentation mask, so voxel-counting probes see real data."""
    import SimpleITK as sitk

    path.parent.mkdir(parents=True, exist_ok=True)
    volume = np.zeros((size, size, size), dtype=np.uint8)
    volume[2:6, 2:6, 2:6] = 1
    sitk.WriteImage(sitk.GetImageFromArray(volume), str(path))


def test_load_series_data_reads_synthetic_chest_without_projection_prefix(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    dcm_count = len(list_dcm_files(series_dir))

    loaded, frames, projections, _geometry = SeriesView._load_series_data(series_dir)

    assert loaded.frames.shape[0] == dcm_count == FALCON_MIN_SLICES
    assert frames.shape == loaded.frames.shape
    assert np.shares_memory(frames, loaded.frames)
    assert projections is not None
    assert projections.minimum.shape == frames.shape[1:]
    assert projections.mean.shape == frames.shape[1:]
    assert projections.maximum.shape == frames.shape[1:]


def test_compute_series_projections_match_numpy_reducers(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    projections = compute_series_projections(loaded.frames)

    np.testing.assert_array_equal(projections.minimum, np.min(loaded.frames, axis=0))
    np.testing.assert_array_equal(projections.maximum, np.max(loaded.frames, axis=0))
    np.testing.assert_allclose(projections.mean, np.mean(loaded.frames, axis=0), rtol=0, atol=1e-5)


def test_finish_loading_preloaded_synthetic_chest_startup_sequence(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=DEFAULT_PHANTOM_SLICE_COUNT)
    loaded = load_series_frames(series_dir)
    slice_count = loaded.frames.shape[0]
    load_calls: list[int] = []
    original_load = series_mod.ImageViewer.load_and_display_image

    def _track_load(self, frame_ndx: int) -> None:
        load_calls.append(frame_ndx)
        return original_load(self, frame_ndx)

    monkeypatch.setattr(series_mod.ImageViewer, "load_and_display_image", _track_load)

    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)

    assert not view._loading
    assert view._frames is not None
    assert view._frames.shape[0] == slice_count
    assert view.image_viewer.num_images == slice_count
    assert view.image_viewer.images.shape[0] == slice_count
    assert view._projections is not None
    assert view.image_viewer._startup_complete
    assert view.image_viewer.view_matches_actual(), view.image_viewer.get_dimensions_text()
    assert load_calls.count(0) == 1, f"expected exactly one startup render at slice 0, got {load_calls}"
    assert all(index == 0 for index in load_calls), f"startup must not paint other slices: {load_calls}"

    view.destroy()
    pump(tk_root)


def test_finish_loading_emits_load_trace_steps(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)

    with caplog.at_level(logging.INFO):
        view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)

    messages = "\n".join(record.message for record in caplog.records)
    show_frame = messages.find("step=show_initial_frame")
    viewer_startup = messages.find("ImageViewer: step=startup_complete")
    series_startup = messages.find("SeriesView load: step=startup_complete")
    assert show_frame != -1
    assert viewer_startup != -1
    assert series_startup != -1
    assert show_frame < viewer_startup < series_startup, "startup_complete must follow show_initial_frame"
    for needle in (
        "SeriesView load: step=preloaded",
        "SeriesView load: step=finish_loading",
        "SeriesView load: step=build_ui_done",
        "SeriesView load: step=show_initial_frame",
        "SeriesView ImageViewer: step=apply_initial_layout",
        "SeriesView ImageViewer: step=startup_complete",
        "SeriesView load: step=startup_complete",
    ):
        assert needle in messages, f"missing trace: {needle}"

    view.destroy()
    pump(tk_root)


def test_async_worker_load_sequence_synthetic_chest(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    expected_slices = len(list_dcm_files(series_dir))

    view = SeriesView(tk_root, controller=mock_controller, series_path=series_dir)

    deadline = time.monotonic() + 15.0
    while view._loading and time.monotonic() < deadline:
        pump(tk_root, steps=10)
        time.sleep(0.01)

    assert not view._loading, "background worker did not finish within timeout"
    assert view._frames is not None
    assert view._frames.shape[0] == expected_slices
    assert wait_for_viewer(view)._startup_complete

    view.destroy()
    pump(tk_root)


def test_small_ct_series_displays_native_with_usable_chrome(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    """A 128x128 series is smaller than the RHS chrome, yet must still render native."""
    series_dir = build_synthetic_ct_small_series(tmp_path / "small", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    assert loaded.frames.shape[1:] == (128, 128)

    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)
    viewer = view.image_viewer

    assert not view._loading
    assert viewer.view_matches_actual()
    assert viewer.get_dimensions_text() == "View[128x128] Actual[128x128]"
    assert_pixmap_matches_display(viewer)
    assert_chrome_unclipped(viewer)

    view.destroy()
    pump(tk_root)


def test_series_view_without_segmentation_collapses_segmentation_chrome(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)

    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)
    viewer = view.image_viewer

    assert not viewer._segmentation_buttons
    assert viewer.segmentation_buttons_frame is not None
    assert not viewer.segmentation_buttons_frame.winfo_ismapped()
    assert viewer._last_hist_canvas_height == ImageViewer.HISTOGRAM_CANVAS_HEIGHT
    assert_chrome_unclipped(viewer)

    view.destroy()
    pump(tk_root)


def test_segmentation_chrome_adds_buttons_without_resizing_the_image(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred segmentation chrome must not disturb the image or clip the player."""
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    _write_mask(series_dir / "A_TS_SEG" / "seg" / "brain.nii.gz")
    loaded = load_series_frames(series_dir)
    monkeypatch.setattr(
        series_mod,
        "collect_primary_segment_voxels",
        lambda _seg_dir, min_voxels=1000: {"brain": 5000, "skull": 4000, "heart": 3000},
    )

    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)
    viewer = view.image_viewer
    before_size = viewer.current_size
    before_hist = viewer._last_hist_canvas_height

    view._load_segmentation_chrome()
    settle(view)

    assert len(viewer._segmentation_buttons) == 3
    assert viewer._segmentation_scroll_height == ImageViewer.SEGMENTATION_SCROLL_MAX_HEIGHT
    assert viewer.current_size == before_size
    assert viewer._last_hist_canvas_height == before_hist
    assert_chrome_unclipped(viewer)

    view.destroy()
    pump(tk_root)


def test_minimum_window_size_allows_shrink_below_native(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)

    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)

    min_w, min_h = view._minimum_window_size()
    # Height can already sit at the minimum: this 256px-tall frame is shorter than the
    # RHS stack, so window height is chrome-bound and shrinking is a width-only affair.
    assert min_w < view.winfo_width()
    assert min_h <= view.winfo_height()
    assert view.image_viewer.control_frame is not None

    view.destroy()
    pump(tk_root)


def test_configure_resize_shrinks_image_and_leaves_histogram_alone(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)
    viewer = view.image_viewer
    before_hist = viewer._last_hist_canvas_height
    before_size = viewer.current_size

    drag_window(view, view._minimum_window_size())
    settle(view)

    assert viewer.current_size[0] <= before_size[0]
    assert viewer.current_size[1] <= before_size[1]
    assert viewer._last_hist_canvas_height == before_hist
    assert_chrome_unclipped(viewer)

    view.destroy()
    pump(tk_root)


def test_fit_to_viewport_skips_repaint_when_size_is_unchanged(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    view = _open(tk_root, mock_controller, series_dir, preloaded=loaded)
    viewer = view.image_viewer
    assert viewer.view_matches_actual()

    paint_calls: list[tuple[int, int]] = []
    original_set = series_mod.ImageViewer.set_display_size

    def _track_set(self, size: tuple[int, int], *, refresh_histogram: bool = False) -> bool:
        paint_calls.append(size)
        return original_set(self, size, refresh_histogram=refresh_histogram)

    monkeypatch.setattr(series_mod.ImageViewer, "set_display_size", _track_set)

    assert viewer.fit_to_viewport() is False
    assert viewer.fit_to_viewport() is False
    assert paint_calls == []

    view.destroy()
    pump(tk_root)
