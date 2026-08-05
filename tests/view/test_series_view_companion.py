"""Tests for Series View single-pane startup and companion-stack lifecycle."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.view.image import ImageViewer
from anonymizer.view.series import SeriesView


@pytest.fixture
def sample_frames() -> np.ndarray:
    return np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)


def test_companion_cache_is_bounded() -> None:
    frames = np.arange(5 * 4 * 5, dtype=np.uint16).reshape(5, 4, 5)
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.CACHE_SIZE = 3
    viewer._companion_images = frames
    viewer.companion_canvas = MagicMock()
    viewer.companion_canvas_image_item = None
    viewer.current_size = (4, 5)
    viewer.current_wl = 40.0
    viewer.current_ww = 400.0
    viewer._companion_cache = {}

    with patch("anonymizer.view.image.apply_windowing", side_effect=lambda wl, ww, arr: arr.astype(np.uint8)):
        with patch("anonymizer.view.image.ImageTk.PhotoImage", side_effect=lambda img: f"photo-{id(img)}"):
            for index in range(5):
                ImageViewer._load_companion_display(viewer, index)

    assert len(viewer._companion_cache) == viewer.CACHE_SIZE
    assert set(viewer._companion_cache) == {2, 3, 4}


def test_attach_companion_stack_uses_tk_label_not_ctk_label(sample_frames: np.ndarray) -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.num_images = sample_frames.shape[0]
    viewer.image_frame = MagicMock()
    viewer.canvas = MagicMock()
    viewer.scrollbar = MagicMock()
    viewer.companion_canvas = None
    viewer.companion_canvas_image_item = None
    viewer._primary_label = None
    viewer._companion_label = None
    viewer._companion_images = None
    viewer._companion_cache = {}
    viewer.update_idletasks = MagicMock()
    viewer.detach_companion_stack = MagicMock()
    viewer._set_data_panel_visible = MagicMock()
    viewer.data_frame = MagicMock()

    with patch("anonymizer.view.image.ctk.CTkLabel") as mock_ctk_label:
        with patch("anonymizer.view.image.tk.Label") as mock_tk_label:
            mock_tk_label.side_effect = lambda *args, **kwargs: MagicMock()
            with patch("anonymizer.view.image.tk.Canvas", return_value=MagicMock()):
                ImageViewer.attach_companion_stack(
                    viewer,
                    sample_frames,
                    primary_label="Before",
                    companion_label="After",
                )

    mock_ctk_label.assert_not_called()
    assert mock_tk_label.call_count == 2
    mock_tk_label.assert_any_call(viewer.image_frame, text="Before", anchor="w")
    mock_tk_label.assert_any_call(viewer.image_frame, text="After", anchor="w")
    viewer._set_data_panel_visible.assert_called_once_with(False)


def test_attach_companion_stack_hides_histogram_and_playback(sample_frames: np.ndarray) -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.num_images = sample_frames.shape[0]
    viewer.playing = False
    viewer.PAD = ImageViewer.PAD
    viewer.image_frame = MagicMock()
    viewer.canvas = MagicMock()
    viewer.scrollbar = MagicMock()
    viewer.companion_canvas = None
    viewer.companion_canvas_image_item = None
    viewer._primary_label = None
    viewer._companion_label = None
    viewer._companion_images = None
    viewer._companion_cache = {}
    viewer.data_frame = MagicMock()
    viewer.update_idletasks = MagicMock()
    viewer.detach_companion_stack = MagicMock()
    viewer._stop_playback = MagicMock()
    viewer.grid_columnconfigure = MagicMock()

    with patch("anonymizer.view.image.tk.Label", return_value=MagicMock()):
        with patch("anonymizer.view.image.tk.Canvas", return_value=MagicMock()):
            ImageViewer.attach_companion_stack(viewer, sample_frames)

    viewer.data_frame.grid_remove.assert_called_once()
    viewer._stop_playback.assert_not_called()


def test_detach_companion_stack_restores_histogram_and_playback(sample_frames: np.ndarray) -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.num_images = sample_frames.shape[0]
    viewer.playing = False
    viewer.PAD = ImageViewer.PAD
    viewer._companion_images = sample_frames
    viewer.companion_canvas = MagicMock()
    viewer.companion_canvas_image_item = 1
    viewer._primary_label = MagicMock()
    viewer._companion_label = MagicMock()
    viewer._companion_cache = {0: ("cached", (4, 5))}
    viewer.image_frame = MagicMock()
    viewer.canvas = MagicMock()
    viewer.scrollbar = MagicMock()
    viewer.data_frame = MagicMock()
    viewer.update_idletasks = MagicMock()
    viewer._stop_playback = MagicMock()
    viewer.grid_columnconfigure = MagicMock()

    ImageViewer.detach_companion_stack(viewer)

    viewer.data_frame.grid.assert_called_once()
    viewer._stop_playback.assert_not_called()


def test_detach_companion_stack_resets_dual_column_layout(sample_frames: np.ndarray) -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.num_images = sample_frames.shape[0]
    viewer._companion_images = sample_frames
    viewer.companion_canvas = MagicMock()
    viewer.companion_canvas_image_item = 1
    viewer._primary_label = MagicMock()
    viewer._companion_label = MagicMock()
    viewer._companion_cache = {0: ("cached", (4, 5))}
    viewer.image_frame = MagicMock()
    viewer.canvas = MagicMock()
    viewer.scrollbar = MagicMock()
    viewer.update_idletasks = MagicMock()
    viewer.data_frame = MagicMock()
    viewer.playing = False
    viewer.PAD = ImageViewer.PAD
    viewer._stop_playback = MagicMock()
    viewer.grid_columnconfigure = MagicMock()

    ImageViewer.detach_companion_stack(viewer)

    assert viewer.companion_canvas is None
    assert viewer.companion_attached is False
    assert viewer._companion_images is None
    assert viewer._companion_cache == {}
    viewer.image_frame.grid_columnconfigure.assert_any_call(0, weight=1)
    viewer.image_frame.grid_columnconfigure.assert_any_call(1, weight=0)
    viewer.canvas.grid.assert_called_with(row=0, column=0, sticky="nsew", padx=0)


def test_clear_ts_cache_refreshes_ui_without_rebuild() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = MagicMock(Modality="CT", SeriesInstanceUID="anon-series-1")
    series._series_path = MagicMock()
    series._anon_model = MagicMock()
    series._schedule_rebuild_ui = MagicMock()
    series._refresh_analysis_cache_ui = MagicMock()
    series._refresh_series_processing_status = MagicMock()
    series._apply_ai_feature_visibility = MagicMock()
    series.update_status = MagicMock()
    series._widget_alive = MagicMock(return_value=True)
    series.after_idle = MagicMock(side_effect=lambda callback: callback())
    summary = SimpleNamespace(exists=True, size_bytes=1024 * 1024, file_count=3)

    with (
        patch("anonymizer.view.series.tseg_cache_summary", return_value=summary),
        patch("anonymizer.view.series.messagebox.askyesno", return_value=True),
        patch("anonymizer.view.series.clear_series_tseg_cache") as clear_cache,
    ):
        SeriesView.clear_ts_cache_button_clicked(series)

    clear_cache.assert_called_once_with(
        series._series_path,
        anon_model=series._anon_model,
        anon_series_uid="anon-series-1",
    )
    series._refresh_analysis_cache_ui.assert_called_once()
    series._apply_ai_feature_visibility.assert_called_once()
    series._schedule_rebuild_ui.assert_not_called()
    series.update_status.assert_called_once()
    series._refresh_series_processing_status.assert_called_once()


def test_blur_face_button_clicked_blocks_when_already_applied() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    series._anon_model.series_has_face_blur.return_value = True

    with patch("anonymizer.view.series.messagebox.showinfo") as showinfo:
        SeriesView.blur_face_button_clicked(series)

    showinfo.assert_called_once()


def test_clear_ts_cache_refresh_keeps_blur_disabled_when_applied() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = MagicMock(Modality="CT", SeriesInstanceUID="anon-series-1")
    series._series_path = MagicMock()
    series._anon_model = MagicMock()
    series._anon_model.series_has_face_blur.return_value = True
    series._schedule_rebuild_ui = MagicMock()
    series._refresh_harmonize_button = MagicMock()
    series._refresh_blur_face_ui = MagicMock()
    series._refresh_clear_ts_cache_button = MagicMock()
    series._show_default_context_line = MagicMock()
    series._refresh_series_processing_status = MagicMock()
    series.update_status = MagicMock()
    series._apply_ai_feature_visibility = MagicMock()
    series._widget_alive = MagicMock(return_value=True)
    series.after_idle = MagicMock(side_effect=lambda callback: callback())
    series._series_geometry = None
    series._face_blur_eligibility_cache = None
    series._face_blur_eligibility_geometry = None
    summary = SimpleNamespace(exists=True, size_bytes=1024 * 1024, file_count=3)

    with (
        patch("anonymizer.view.series.tseg_cache_summary", return_value=summary),
        patch("anonymizer.view.series.messagebox.askyesno", return_value=True),
        patch("anonymizer.view.series.clear_series_tseg_cache"),
    ):
        SeriesView.clear_ts_cache_button_clicked(series)

    series._refresh_blur_face_ui.assert_called_once()


def test_release_image_viewer_clears_resources_before_destroy() -> None:
    series = SeriesView.__new__(SeriesView)
    viewer = MagicMock()

    SeriesView._release_image_viewer(series, viewer, destroy_widget=True)

    viewer.release_resources.assert_called_once()
    viewer.destroy.assert_called_once()
