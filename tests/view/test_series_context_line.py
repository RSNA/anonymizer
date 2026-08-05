"""Tests for Series View geometry context line and master-style viewer sizing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from anonymizer.controller.blur_face import (
    FaceBlurEligibility,
    FaceBlurGateDecision,
    FaceBlurGateReason,
)
from anonymizer.controller.tseg.dicom_geometry import format_series_view_geometry_line
from anonymizer.controller.tseg.runtime_status import set_ai_session
from anonymizer.model.anonymizer import SeriesProcessingStatus, format_series_processing_status
from anonymizer.view.image import ImageViewer
from anonymizer.view.series import SeriesView
from tests.controller.blur_face.test_face_blur_gate import _geometry


def test_series_context_line_is_geometry_only() -> None:
    series = SeriesView.__new__(SeriesView)
    geometry = _geometry()
    series._ensure_series_geometry = MagicMock(return_value=geometry)

    line = SeriesView._series_context_line(series)

    assert line == format_series_view_geometry_line(geometry)
    assert "chest or abdomen" not in line.lower()


def test_refresh_series_processing_status_formats_label() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    status = SeriesProcessingStatus(
        pixel_phi_applied_count=2,
        pixel_phi_total_count=5,
        harmonized_description="CT Chest",
        face_blur_algorithm=None,
    )
    series._anon_model.get_series_processing_status.return_value = status
    series._anon_model.series_has_face_blur.return_value = False
    series._face_blur_eligibility = MagicMock(
        return_value=FaceBlurEligibility(
            FaceBlurGateDecision.ALLOW,
            FaceBlurGateReason.METADATA_HEAD,
        ),
    )
    series._series_status_label = MagicMock()

    SeriesView._refresh_series_processing_status(series)

    series._series_status_label.configure.assert_called_once_with(
        text=format_series_processing_status(status),
    )


def test_refresh_series_processing_status_omits_face_blur_for_non_head() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    status = SeriesProcessingStatus(
        pixel_phi_applied_count=0,
        pixel_phi_total_count=3,
        harmonized_description="Ch Ax WO",
        face_blur_algorithm=None,
    )
    series._anon_model.get_series_processing_status.return_value = status
    series._anon_model.series_has_face_blur.return_value = False
    series._face_blur_eligibility = MagicMock(
        return_value=FaceBlurEligibility(
            FaceBlurGateDecision.BLOCK,
            FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        ),
    )
    series._series_status_label = MagicMock()

    SeriesView._refresh_series_processing_status(series)

    series._series_status_label.configure.assert_called_once_with(
        text=format_series_processing_status(status, include_face_blur=False),
    )


def test_refresh_series_processing_status_shows_face_blur_when_already_applied() -> None:
    series = SeriesView.__new__(SeriesView)
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    status = SeriesProcessingStatus(
        pixel_phi_applied_count=0,
        pixel_phi_total_count=3,
        harmonized_description="Ch Ax WO",
        face_blur_algorithm="gaussian",
    )
    series._anon_model.get_series_processing_status.return_value = status
    series._anon_model.series_has_face_blur.return_value = True
    series._face_blur_eligibility = MagicMock(
        return_value=FaceBlurEligibility(
            FaceBlurGateDecision.BLOCK,
            FaceBlurGateReason.CACHED_REGIONS_NON_HEAD,
        ),
    )
    series._series_status_label = MagicMock()

    SeriesView._refresh_series_processing_status(series)

    series._series_status_label.configure.assert_called_once_with(
        text=format_series_processing_status(status),
    )


def _enable_ai_session() -> None:
    set_ai_session(remove_pixel_phi=True, enable_harmonize=True, enable_face_blur=True)


def test_harmonize_button_visible_when_cache_exists_without_session_flag() -> None:
    series = SeriesView.__new__(SeriesView)
    set_ai_session(enable_harmonize=False, enable_face_blur=False)
    series._ds = SimpleNamespace(Modality="CT")
    series._series_path = MagicMock()
    with patch(
        "anonymizer.view.series.tseg_cache_summary",
        return_value=SimpleNamespace(exists=True),
    ):
        assert SeriesView._harmonize_button_visible(series) is True


def test_harmonize_button_state_uses_orm_metadata() -> None:
    series = SeriesView.__new__(SeriesView)
    _enable_ai_session()
    series._ds = SimpleNamespace(Modality="CT", SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    series._anon_model.series_is_harmonized.return_value = True

    with patch("anonymizer.view.series.harmonize_allowed", return_value=True):
        assert SeriesView._harmonize_button_state(series) == "disabled"
    series._anon_model.series_is_harmonized.assert_called_once_with("anon-series-1")


def test_set_series_interaction_enabled_restores_harmonize_from_model() -> None:
    series = SeriesView.__new__(SeriesView)
    series.winfo_exists = MagicMock(return_value=True)
    series.harmonize_button = MagicMock()
    series.blur_face_button = MagicMock()
    series.blur_face_mode_menu = MagicMock()
    series.clear_ts_cache_button = MagicMock()
    series.configure = MagicMock()
    series._refresh_harmonize_button = MagicMock()
    series._refresh_blur_face_ui = MagicMock()
    series._refresh_clear_ts_cache_button = MagicMock()

    SeriesView._set_series_interaction_enabled(series, True)

    series._refresh_harmonize_button.assert_called_once()
    series._refresh_blur_face_ui.assert_called_once()
    series._refresh_clear_ts_cache_button.assert_called_once()
    series.harmonize_button.configure.assert_not_called()


def test_on_series_description_updated_refreshes_processing_status() -> None:
    series = SeriesView.__new__(SeriesView)
    series._update_title = MagicMock()
    series._refresh_analysis_cache_ui = MagicMock()
    series._refresh_series_processing_status = MagicMock()

    SeriesView._on_series_description_updated(series)

    series._update_title.assert_called_once()
    series._refresh_analysis_cache_ui.assert_called_once()
    series._refresh_series_processing_status.assert_called_once()
    assert series._series_geometry is None
    assert series._face_blur_eligibility_cache is None
    assert series._face_blur_eligibility_geometry is None


def test_refresh_blur_face_ui_disabled_when_face_blur_applied() -> None:
    series = SeriesView.__new__(SeriesView)
    _enable_ai_session()
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    series._anon_model.series_has_face_blur.return_value = True
    series._face_blur_eligibility = MagicMock(
        return_value=SimpleNamespace(decision=FaceBlurGateDecision.ALLOW),
    )
    series.blur_face_button = MagicMock()
    series.blur_face_mode_menu = MagicMock()

    SeriesView._refresh_blur_face_ui(series)

    series.blur_face_button.configure.assert_called_once_with(state="disabled")
    series.blur_face_mode_menu.configure.assert_called_once_with(state="disabled")


def test_blur_face_button_state_disabled_when_face_blur_applied() -> None:
    series = SeriesView.__new__(SeriesView)
    _enable_ai_session()
    series._ds = SimpleNamespace(SeriesInstanceUID="anon-series-1")
    series._anon_model = MagicMock()
    series._anon_model.series_has_face_blur.return_value = True
    series._face_blur_eligibility = MagicMock(
        return_value=SimpleNamespace(decision=FaceBlurGateDecision.ALLOW),
    )

    assert SeriesView._blur_face_toolbar_state(series) == "disabled"


def test_apply_initial_viewer_display_calls_set_initial_size() -> None:
    series = SeriesView.__new__(SeriesView)
    series.update_idletasks = MagicMock()
    series._fit_window_to_content = MagicMock()
    viewer = MagicMock()
    viewer.detach_companion_stack = MagicMock()
    viewer._set_initial_size = MagicMock()
    viewer.sync_viewport_after_layout = MagicMock()
    series.image_viewer = viewer

    SeriesView._apply_initial_viewer_display(series)

    viewer.detach_companion_stack.assert_called_once()
    viewer._set_initial_size.assert_called_once()
    series._fit_window_to_content.assert_called_once()
    viewer.sync_viewport_after_layout.assert_called_once()
    assert viewer._resize_to_viewport_enabled is True


def test_on_series_configure_updates_wraplength_only() -> None:
    series = SeriesView.__new__(SeriesView)
    series._loading = False
    series._ui_rebuilding = False
    series._update_status_label_wraplength = MagicMock()
    series.image_viewer = MagicMock()

    SeriesView._on_series_configure(series, SimpleNamespace(widget=series))

    series._update_status_label_wraplength.assert_called_once()


def test_calculate_scaled_size_returns_native_when_image_fits_and_upscale_disabled() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512

    assert ImageViewer._calculate_scaled_size(viewer, 900, 700, allow_upscale=False) == (512, 512)


def test_calculate_scaled_size_upscales_when_viewport_is_larger() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512

    assert ImageViewer._calculate_scaled_size(viewer, 900, 700) == (700, 700)


def test_calculate_scaled_size_scales_down_large_images() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 1024
    viewer.image_height = 1024

    width, height = ImageViewer._calculate_scaled_size(viewer, 400, 300)

    assert width == 300
    assert height == 300


def test_set_initial_size_uses_screen_budget_and_loads_frame() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_image_index = 0
    viewer.companion_canvas = None
    viewer.MAX_SCREEN_PERCENTAGE = 0.7
    viewer.canvas = MagicMock()
    # Early layout can report ~155px; initial size must ignore canvas winfo.
    viewer.canvas.winfo_width = MagicMock(return_value=155)
    viewer.canvas.winfo_height = MagicMock(return_value=155)
    viewer.winfo_screenwidth = MagicMock(return_value=2000)
    viewer.winfo_screenheight = MagicMock(return_value=1000)
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer.histogram = None
    viewer.images = MagicMock()
    viewer._companion_cache = {}
    viewer._primary_label = None
    viewer._companion_label = None
    viewer.num_images = 1
    viewer.update_idletasks = MagicMock()

    ImageViewer._set_initial_size(viewer)

    assert viewer.current_size == (512, 512)
    viewer.canvas.config.assert_called_once_with(width=512, height=512)
    viewer.load_and_display_image.assert_called_once_with(0)


def test_set_initial_size_halves_budget_for_companion() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_image_index = 0
    viewer.companion_canvas = MagicMock()
    viewer.MAX_SCREEN_PERCENTAGE = 0.7
    viewer.canvas = MagicMock()
    viewer.winfo_screenwidth = MagicMock(return_value=2000)
    viewer.winfo_screenheight = MagicMock(return_value=1000)
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer.histogram = None
    viewer.images = MagicMock()
    viewer._companion_cache = {}
    viewer._primary_label = None
    viewer._companion_label = None
    viewer.num_images = 1
    viewer.update_idletasks = MagicMock()

    ImageViewer._set_initial_size(viewer)

    viewer.companion_canvas.config.assert_called_once_with(width=512, height=512)


def test_on_resize_preserves_aspect_ratio_in_viewport() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer._resize_to_viewport_enabled = True
    viewer.companion_canvas = None
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (512, 512)
    viewer.current_image_index = 2
    viewer.canvas_image_item = None
    viewer.num_images = 1
    viewer._primary_label = None
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=400)
    viewer.image_frame.winfo_height = MagicMock(return_value=300)
    viewer.canvas = MagicMock()
    viewer.canvas.winfo_width = MagicMock(return_value=400)
    viewer.canvas.winfo_height = MagicMock(return_value=300)
    viewer.canvas.config = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer.on_resize(viewer)

    assert viewer.current_size == (300, 300)
    viewer.canvas.config.assert_called_once_with(width=300, height=300)
    viewer.load_and_display_image.assert_called_once_with(2)
    viewer.update_status.assert_called_once()


def test_apply_viewport_size_keeps_native_when_viewport_within_layout_slop() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (512, 512)
    viewer.current_image_index = 0
    viewer.companion_canvas = None
    viewer._primary_label = None
    viewer.num_images = 1
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=510)
    viewer.image_frame.winfo_height = MagicMock(return_value=512)
    viewer.canvas = MagicMock()
    viewer.canvas_image_item = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer._apply_viewport_size(viewer)

    assert viewer.current_size == (512, 512)
    viewer.load_and_display_image.assert_not_called()


def test_apply_viewport_size_restores_native_after_grid_rounding() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (510, 512)
    viewer.current_image_index = 0
    viewer.companion_canvas = None
    viewer._primary_label = None
    viewer.num_images = 1
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=510)
    viewer.image_frame.winfo_height = MagicMock(return_value=512)
    viewer.canvas = MagicMock()
    viewer.canvas.config = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer._apply_viewport_size(viewer)

    assert viewer.current_size == (512, 512)
    viewer.canvas.config.assert_called_once_with(width=512, height=512)
    viewer.load_and_display_image.assert_called_once_with(0)
    viewer.update_status.assert_called_once()


def test_apply_viewport_size_scales_down_when_window_shrinks() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (512, 512)
    viewer.current_image_index = 0
    viewer.companion_canvas = None
    viewer._primary_label = None
    viewer.num_images = 1
    viewer.canvas_image_item = MagicMock()
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=400)
    viewer.image_frame.winfo_height = MagicMock(return_value=300)
    viewer.canvas = MagicMock()
    viewer.canvas.config = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer._apply_viewport_size(viewer)

    assert viewer.current_size == (300, 300)
    viewer.canvas.config.assert_called_once_with(width=300, height=300)
    viewer.load_and_display_image.assert_called_once_with(0)


def test_apply_viewport_size_upscales_when_window_grows() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (512, 512)
    viewer.current_image_index = 0
    viewer.companion_canvas = None
    viewer._primary_label = None
    viewer.num_images = 1
    viewer.canvas_image_item = MagicMock()
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=900)
    viewer.image_frame.winfo_height = MagicMock(return_value=700)
    viewer.canvas = MagicMock()
    viewer.canvas.config = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer._apply_viewport_size(viewer)

    assert viewer.current_size == (700, 700)
    viewer.canvas.config.assert_called_once_with(width=700, height=700)
    viewer.load_and_display_image.assert_called_once_with(0)


def test_on_resize_skips_before_viewport_resize_enabled() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer._resize_to_viewport_enabled = False
    viewer.canvas = MagicMock()
    viewer.canvas.winfo_width = MagicMock(return_value=155)
    viewer.canvas.winfo_height = MagicMock(return_value=155)
    viewer.load_and_display_image = MagicMock()

    ImageViewer.on_resize(viewer)

    viewer.load_and_display_image.assert_not_called()


def test_apply_viewport_size_preserves_aspect_ratio_for_companion_panes() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer.image_width = 512
    viewer.image_height = 512
    viewer.current_size = (600, 400)
    viewer.current_image_index = 0
    viewer.canvas_image_item = None
    viewer.num_images = 1
    viewer._primary_label = None
    viewer.update_idletasks = MagicMock()
    viewer.image_frame = MagicMock()
    viewer.image_frame.winfo_width = MagicMock(return_value=808)
    viewer.image_frame.winfo_height = MagicMock(return_value=300)
    viewer.canvas = MagicMock()
    viewer.companion_canvas = MagicMock()
    viewer.canvas.winfo_width = MagicMock(return_value=400)
    viewer.canvas.winfo_height = MagicMock(return_value=300)
    viewer.canvas.config = MagicMock()
    viewer.companion_canvas.config = MagicMock()
    viewer.load_and_display_image = MagicMock()
    viewer.update_status = MagicMock()
    viewer._companion_cache = {}

    ImageViewer._apply_viewport_size(viewer)

    assert viewer.current_size == (300, 300)
    viewer.load_and_display_image.assert_called_once_with(0)
    viewer.canvas.config.assert_called_once_with(width=300, height=300)
    viewer.companion_canvas.config.assert_called_once_with(width=300, height=300)


def test_on_resize_skips_when_disabled() -> None:
    viewer = ImageViewer.__new__(ImageViewer)
    viewer._resize_to_viewport_enabled = False
    viewer.load_and_display_image = MagicMock()

    ImageViewer.on_resize(viewer)

    viewer.load_and_display_image.assert_not_called()
