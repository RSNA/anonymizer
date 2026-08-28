"""Series View load sequence tests using synthetic CT DICOM (no manual GUI)."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import tkinter as tk

from anonymizer.controller.series_io import (
    compute_series_projections,
    load_series_frames,
)
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

_THEME_PATH = (
    Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"
)


@pytest.fixture(scope="module", autouse=True)
def _init_customtkinter_theme() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme(str(_THEME_PATH))


@pytest.fixture
def tk_root() -> tk.Tk:
    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


@pytest.fixture
def mock_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_phi_by_anon_patient_id.return_value = None
    controller.get_series_processing_status.return_value = None
    controller.series_has_face_blur.return_value = False
    controller.series_is_harmonized.return_value = False
    controller.format_series_processing_status.return_value = ""
    return controller


def _pump_tk(root: tk.Misc, *, max_steps: int = 50) -> None:
    for _ in range(max_steps):
        root.update_idletasks()
        root.update()


def _fast_show_initial_frame(self) -> None:
    """Run startup paint synchronously in tests (production path calls this directly)."""
    self.apply_initial_layout()


@pytest.fixture(autouse=True)
def _stub_viewer_icon_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.view.series import image as image_mod
    from PIL import Image

    icon = Image.new("RGB", (28, 28), color=(0, 0, 0))
    monkeypatch.setattr(image_mod.Image, "open", lambda _path: icon)


@pytest.fixture(autouse=True)
def _fast_image_viewer_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        series_mod.ImageViewer,
        "show_initial_frame",
        _fast_show_initial_frame,
    )


def test_load_series_data_reads_synthetic_chest_without_projection_prefix(
    tmp_path: Path,
) -> None:
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
    np.testing.assert_allclose(
        projections.mean,
        np.mean(loaded.frames, axis=0),
        rtol=0,
        atol=1e-5,
    )


def test_finish_loading_preloaded_synthetic_chest_startup_sequence(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(
        tmp_path / "chest",
        num_slices=DEFAULT_PHANTOM_SLICE_COUNT,
    )
    loaded = load_series_frames(series_dir)
    slice_count = loaded.frames.shape[0]
    load_calls: list[int] = []

    original_load = series_mod.ImageViewer.load_and_display_image

    def _track_load(self, frame_ndx: int) -> None:
        load_calls.append(frame_ndx)
        return original_load(self, frame_ndx)

    monkeypatch.setattr(series_mod.ImageViewer, "load_and_display_image", _track_load)
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    _pump_tk(tk_root)

    assert not view._loading
    assert view._frames is not None
    assert view._frames.shape[0] == slice_count
    assert view.image_viewer.num_images == slice_count
    assert view.image_viewer.images.shape[0] == slice_count
    assert view._projections is not None
    assert view.image_viewer._startup_complete
    assert view.image_viewer.view_matches_actual(), view.image_viewer.get_dimensions_text()
    assert load_calls == [0], f"expected exactly one startup render at slice 0, got {load_calls}"

    view.destroy()
    _pump_tk(tk_root)


def test_finish_loading_emits_load_trace_steps(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    with caplog.at_level(logging.INFO):
        view = SeriesView(
            tk_root,
            controller=mock_controller,
            series_path=series_dir,
            preloaded=loaded,
        )
        _pump_tk(tk_root)

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
        "SeriesView load: step=window_mapped",
        "SeriesView load: step=show_initial_frame",
        "SeriesView ImageViewer: step=apply_initial_layout",
        "SeriesView ImageViewer: step=startup_complete",
        "SeriesView load: step=startup_complete",
    ):
        assert needle in messages, f"missing trace: {needle}"

    view.destroy()
    _pump_tk(tk_root)


def test_async_worker_load_sequence_synthetic_chest(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    expected_slices = len(list_dcm_files(series_dir))
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
    )

    deadline = time.monotonic() + 10.0
    while view._loading and time.monotonic() < deadline:
        _pump_tk(tk_root)
        time.sleep(0.01)

    assert not view._loading, "background worker did not finish within timeout"
    assert view._frames is not None
    assert view._frames.shape[0] == expected_slices
    assert view.image_viewer._startup_complete

    view.destroy()
    _pump_tk(tk_root)


def test_series_view_small_ct_slices_below_widget_threshold_display_native(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """128×128 CT_small-based series: image stays native; RHS panel uses minimum height."""
    from anonymizer.view.series.image import ImageViewer

    series_dir = build_synthetic_ct_small_series(tmp_path / "small", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    assert loaded.frames.shape[1:] == (128, 128)
    assert 128 < ImageViewer.DATA_PANEL_MIN_HEIGHT
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    _pump_tk(tk_root)

    assert not view._loading
    assert view.image_viewer.view_matches_actual()
    assert view.image_viewer.get_dimensions_text() == "View[128x128] Actual[128x128]"
    assert view.image_viewer._data_panel_target_height() == ImageViewer.DATA_PANEL_MIN_HEIGHT
    assert view.image_viewer.data_frame is not None
    assert view.image_viewer.data_frame.winfo_height() >= ImageViewer.DATA_PANEL_MIN_HEIGHT

    view.destroy()
    _pump_tk(tk_root)


def test_series_view_without_segmentation_reserves_histogram(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-harmonized series: segmentation area collapsed; histogram keeps usable height."""
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    _pump_tk(tk_root)

    viewer = view.image_viewer
    layout = viewer._compute_data_panel_layout()
    assert not layout.show_segmentation_buttons
    assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    assert viewer._last_hist_canvas_height is not None
    assert viewer._last_hist_canvas_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    assert not viewer._segmentation_buttons

    view.destroy()
    _pump_tk(tk_root)


def test_series_view_segmentation_chrome_shows_buttons_without_shrinking_histogram(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deferred segmentation chrome populates buttons inside a capped scroll area."""
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    seg_dir = series_dir / "A_TS_SEG" / "seg"
    seg_dir.mkdir(parents=True)
    (seg_dir / "brain.nii.gz").write_bytes(b"")
    loaded = load_series_frames(series_dir)
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)
    monkeypatch.setattr(
        series_mod,
        "collect_primary_segment_voxels",
        lambda _seg_dir, min_voxels=1000: {"brain": 5000, "skull": 4000, "heart": 3000},
    )

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    _pump_tk(tk_root)
    before_size = view.image_viewer.current_size

    view._load_segmentation_chrome()
    _pump_tk(tk_root)

    viewer = view.image_viewer
    layout = viewer._compute_data_panel_layout()
    assert layout.show_segmentation_buttons
    assert len(viewer._segmentation_buttons) == 3
    assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    assert layout.segmentation_buttons_height >= ImageViewer.SEGMENTATION_SCROLL_MIN_HEIGHT
    assert viewer.current_size == before_size

    view.destroy()
    _pump_tk(tk_root)


def test_minimum_window_size_allows_shrink_below_native(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest", num_slices=FALCON_MIN_SLICES)
    loaded = load_series_frames(series_dir)
    monkeypatch.setattr(series_mod.SeriesView, "_ensure_series_geometry", lambda self: None)

    view = SeriesView(
        tk_root,
        controller=mock_controller,
        series_path=series_dir,
        preloaded=loaded,
    )
    _pump_tk(tk_root)

    min_w, min_h = view._minimum_window_size()
    assert min_w < view.winfo_width()
    assert min_h < view.winfo_height()
    assert view.image_viewer.control_frame is not None

    view.destroy()
    _pump_tk(tk_root)
