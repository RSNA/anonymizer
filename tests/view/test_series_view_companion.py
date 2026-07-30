"""Tests for Series View single-pane startup and companion-stack lifecycle."""

from __future__ import annotations

import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.controller.blur_face import FaceBlurMode
from anonymizer.controller.remove_pixel_phi import LayerType
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

    ImageViewer.detach_companion_stack(viewer)

    assert viewer.companion_canvas is None
    assert viewer.companion_attached is False
    assert viewer._companion_images is None
    assert viewer._companion_cache == {}
    viewer.image_frame.grid_columnconfigure.assert_any_call(0, weight=1)
    viewer.image_frame.grid_columnconfigure.assert_any_call(1, weight=0)
    viewer.canvas.grid.assert_called_with(row=0, column=0, sticky="nsew", padx=0)


def test_poll_blur_worker_ignores_stale_done_after_cancel() -> None:
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = False
    series._blur_worker_queue = queue.Queue()
    series._blur_worker_queue.put(("done", SimpleNamespace(error=None)))
    series._show_blur_review = MagicMock()
    series.after = MagicMock()

    SeriesView._poll_blur_worker(series)

    series._show_blur_review.assert_not_called()
    series.after.assert_called_once()


def test_poll_blur_worker_processes_done_while_running() -> None:
    preview = SimpleNamespace(error=None)
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = True
    series._blur_worker_queue = queue.Queue()
    series._blur_worker_queue.put(("done", preview))
    series._stop_blur_review_deferred = MagicMock()
    series.after_idle = MagicMock()
    series.after = MagicMock()

    SeriesView._poll_blur_worker(series)

    series._stop_blur_review_deferred.assert_called_once()
    series.after_idle.assert_called_once()
    assert series._blur_running is True
    series.after.assert_not_called()


def test_show_blur_review_layouts_dual_pane_window(sample_frames: np.ndarray) -> None:
    preview = SimpleNamespace(
        mask=np.zeros((3, 4, 5), dtype=np.uint8),
        blurred_slice_frames=sample_frames.astype(np.float32),
        qa_stats={},
        sigma_mm=1.0,
        slice_count=3,
        blur_mode=FaceBlurMode.GAUSSIAN,
    )
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._ds = MagicMock()
    series._frames = sample_frames
    series._blur_review_saved = None
    series._log_series_memory = MagicMock()
    series.update_idletasks = MagicMock()
    series.update_status = MagicMock()
    series.save_button = MagicMock()
    series.blur_face_button = MagicMock()
    series._refresh_blur_face_ui = MagicMock()
    series._slice_stack = MagicMock(return_value=sample_frames)
    viewer = MagicMock()
    viewer.playing = False
    viewer.attach_companion_stack = MagicMock()
    viewer.set_wlww_sync = MagicMock()
    viewer.set_segmentation_overlays = MagicMock()
    viewer.active_layers = set()
    viewer.overlay_data = {}
    viewer._set_initial_size = MagicMock()
    series.image_viewer = viewer

    with patch("anonymizer.view.series.mask_slice_segmentations", return_value=[]):
        with patch("anonymizer.view.series.face_review_wl_ww", return_value=(40.0, 400.0)):
            with patch("anonymizer.view.series.format_face_blur_qa_summary", return_value="QA"):
                SeriesView._show_blur_review(series, preview)

    viewer.attach_companion_stack.assert_called_once()
    viewer._set_initial_size.assert_called_once()
    assert viewer._resize_to_viewport_enabled is True


def test_complete_blur_review_shows_review_and_clears_running() -> None:
    preview = SimpleNamespace(error=None)
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = True
    series._ui_rebuilding = False
    series._show_blur_review = MagicMock()
    series._set_series_interaction_enabled = MagicMock()
    series._refresh_blur_face_ui = MagicMock()
    series._flush_pending_rebuild_ui = MagicMock()

    SeriesView._complete_blur_review(series, preview)

    series._show_blur_review.assert_called_once_with(preview)
    assert series._blur_running is False
    series._set_series_interaction_enabled.assert_called_once_with(True)
    series._flush_pending_rebuild_ui.assert_called_once()


def test_schedule_rebuild_ui_defers_while_blur_running() -> None:
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = True
    series._blur_preview = None
    series._rebuild_pending = False
    series._stop_rebuild_ui = MagicMock()
    series.after_idle = MagicMock()

    SeriesView._schedule_rebuild_ui(series)

    assert series._rebuild_pending is True
    series.after_idle.assert_not_called()


def test_launch_blur_worker_copies_slice_stack(sample_frames: np.ndarray) -> None:
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series._blur_running = True
    series._frames = sample_frames
    series._ds = MagicMock()
    series._slice_paths = (MagicMock(),)
    series._series_path = MagicMock()
    series._slice_stack = MagicMock(return_value=sample_frames)
    series._ensure_series_geometry = MagicMock(return_value=None)
    captured: dict[str, np.ndarray] = {}

    def _capture_context(**kwargs):
        captured["slice_frames"] = kwargs["slice_frames"]
        return SimpleNamespace()

    series._blur_worker_queue = queue.Queue()
    series.after = MagicMock()
    with (
        patch("anonymizer.view.series.copy.deepcopy", side_effect=lambda value: value),
        patch("anonymizer.view.series.SeriesVolumeContext", side_effect=_capture_context),
        patch("anonymizer.view.series.threading.Thread") as thread_cls,
    ):
        SeriesView._launch_blur_worker(series, FaceBlurMode.GAUSSIAN)

    assert captured["slice_frames"] is not sample_frames
    assert np.array_equal(captured["slice_frames"], sample_frames)
    thread_cls.assert_called_once()
    series.after.assert_called_once()


def test_blur_worker_uses_prebuilt_volume_context() -> None:
    series = SeriesView.__new__(SeriesView)
    series._series_path = MagicMock()
    volume_context = SimpleNamespace()
    series._blur_worker_queue = queue.Queue()
    with patch("anonymizer.view.series.preview_face_blur", return_value=SimpleNamespace(error="stop")) as preview:
        SeriesView._blur_worker(series, FaceBlurMode.GAUSSIAN, volume_context)

    preview.assert_called_once()
    assert preview.call_args.kwargs["volume_context"] is volume_context


def test_save_after_blur_review_uses_teardown_not_rebuild() -> None:
    series = SeriesView.__new__(SeriesView)
    series._frames = np.zeros((4, 8, 8), dtype=np.float32)
    series._ds = MagicMock()
    series._series_path = MagicMock()
    series._anon_model = MagicMock()
    series.single_frame = True
    series._whitelist_changed = False
    series._blur_preview = SimpleNamespace(
        error=None,
        slice_count=1,
        qa_stats=None,
        blur_mode=FaceBlurMode.GAUSSIAN,
    )
    series._apply_face_blur_preview = MagicMock()
    series._teardown_blur_review = MagicMock()
    series._schedule_rebuild_ui = MagicMock()
    series.get_whitelist_set = MagicMock(return_value=[])
    series.save_button = MagicMock()
    series.update_status = MagicMock()
    series.image_viewer = MagicMock()

    with (
        patch("anonymizer.view.series.save_series_frames", return_value=True),
        patch("anonymizer.view.series.apply_series_face_blur_metadata") as apply_metadata,
        patch("anonymizer.view.series.collect_series_view_pixel_phi_texts", return_value={}),
    ):
        SeriesView.save_series_button_clicked(series)

    apply_metadata.assert_called_once()

    series._teardown_blur_review.assert_called_once_with(
        keep_applied_frames=True,
        restore_dicom_wl=True,
    )
    series._schedule_rebuild_ui.assert_not_called()


def test_teardown_blur_review_restores_single_pane_layout() -> None:
    series = SeriesView.__new__(SeriesView)
    series._frames = np.zeros((176, 512, 512), dtype=np.float32)
    series.single_frame = False
    series._ds = MagicMock()
    series._dicom_wl = 40.0
    series._dicom_ww = 400.0
    series._blur_preview = SimpleNamespace(error=None)
    series._blur_review_saved = {
        "images": np.zeros((173, 512, 512), dtype=np.float32),
        "num_images": 173,
        "image_height": 512,
        "image_width": 512,
        "small_jump": 1,
        "large_jump": 17,
        "overlay_data": {},
        "active_layers": set(),
        "segmentation_overlay_color": (0, 255, 0),
        "segmentation_overlay_alpha": 0.35,
        "current_image_index": 5,
    }
    series.winfo_x = MagicMock(return_value=100)
    series.winfo_y = MagicMock(return_value=200)
    viewer = SimpleNamespace(
        num_images=173,
        active_layers={LayerType.SEGMENTATIONS},
        overlay_data={},
        current_image_index=0,
        _resize_to_viewport_enabled=False,
        SMALL_JUMP_PERCENTAGE=ImageViewer.SMALL_JUMP_PERCENTAGE,
        LARGE_JUMP_PERCENTAGE=ImageViewer.LARGE_JUMP_PERCENTAGE,
        detach_companion_stack=MagicMock(),
        clear_cache=MagicMock(),
        set_wlww_sync=MagicMock(),
    )
    series.image_viewer = viewer
    series._apply_initial_viewer_display = MagicMock()
    series._refresh_blur_face_ui = MagicMock()
    series._flush_pending_rebuild_ui = MagicMock()
    series._log_series_memory = MagicMock()

    SeriesView._teardown_blur_review(series, keep_applied_frames=True, restore_dicom_wl=True)

    viewer.detach_companion_stack.assert_called()
    assert viewer.current_image_index == 8
    assert LayerType.SEGMENTATIONS not in viewer.active_layers
    series._apply_initial_viewer_display.assert_called_once()
    assert series._blur_preview is None
    assert series._blur_review_saved is None


def test_stop_blur_worker_poll_cancels_after() -> None:
    series = SeriesView.__new__(SeriesView)
    series._blur_poll_after_id = "after-1"
    series.after_cancel = MagicMock()

    SeriesView._stop_blur_worker_poll(series)

    series.after_cancel.assert_called_once_with("after-1")
    assert series._blur_poll_after_id is None


def test_drain_blur_worker_queue_discards_pending_messages() -> None:
    worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    worker_queue.put(("progress", object()))
    worker_queue.put(("done", object()))

    SeriesView._drain_blur_worker_queue(worker_queue)

    assert worker_queue.empty()
