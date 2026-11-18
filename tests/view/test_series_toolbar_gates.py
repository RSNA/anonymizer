"""Series View toolbar gate helpers that need the view layer (no CTk window).

Controller-pure helpers live in tests/controller/series/test_workspace_toolbar_gates.py.
"""

from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrEditContext
from anonymizer.controller.series.series_overlay import OverlayData, UserRectangle
from anonymizer.view.ai.harmonize_description import harmonize_button_visible
from anonymizer.view.series.series import SeriesView


class _FakeToolbarWidget:
    """Records the last configured state (stand-in for a CTk toolbar widget)."""

    def __init__(self) -> None:
        self.state: str | None = None

    def configure(self, *, state: str) -> None:
        self.state = state


def test_refresh_ocr_toolbar_buttons_enables_remove_only_with_results() -> None:
    view = SeriesView.__new__(SeriesView)
    view.remove_button = _FakeToolbarWidget()
    view.remove_text_mode_menu = _FakeToolbarWidget()
    view._ocr_detecting = False
    view._series_interaction_allowed = lambda: True

    view._ocr_results_available_for_edit_context = lambda: False
    SeriesView._refresh_ocr_toolbar_buttons(view)
    assert view.remove_button.state == "disabled"
    assert view.remove_text_mode_menu.state == "disabled"

    view._ocr_results_available_for_edit_context = lambda: True
    SeriesView._refresh_ocr_toolbar_buttons(view)
    assert view.remove_button.state == "normal"
    assert view.remove_text_mode_menu.state == "normal"


def test_remove_scope_change_keeps_remove_enabled_with_results() -> None:
    """Changing Remove Scope re-filters detections; it must not disable Remove."""
    view = SeriesView.__new__(SeriesView)
    view.remove_button = _FakeToolbarWidget()
    view.remove_text_mode_menu = _FakeToolbarWidget()
    view._ocr_detecting = False
    view._series_interaction_allowed = lambda: True
    view._ocr_results_available_for_edit_context = lambda: True
    view._redraw_text_overlays_if_detected = lambda: None

    SeriesView._on_ocr_remove_mode_changed(view, "PHI only")
    assert view.remove_button.state == "normal"
    assert view.remove_text_mode_menu.state == "normal"

    SeriesView._on_ocr_remove_mode_changed(view, "Non-whitelisted text")
    assert view.remove_button.state == "normal"


class _FakeBlackoutViewer:
    """Minimal ImageViewer stand-in recording cache clears and frame loads."""

    def __init__(self, *, num_images: int, overlay_data: dict) -> None:
        self.num_images = num_images
        self.overlay_data = overlay_data
        self.current_image_index = 0
        self.cleared = 0
        self.loaded: list[int] = []

    def clear_cache(self) -> None:
        self.cleared += 1

    def load_and_display_image(self, index: int) -> None:
        self.loaded.append(index)


def _blackout_view(viewer: _FakeBlackoutViewer) -> SeriesView:
    view = SeriesView.__new__(SeriesView)
    view.edit_context = OcrEditContext.SERIES
    view.image_viewer = viewer
    view.update = lambda: None
    view.regenerate_series_projections = lambda: None
    return view


def test_blackout_series_without_rects_is_noop() -> None:
    viewer = _FakeBlackoutViewer(
        num_images=3,
        overlay_data={0: OverlayData(), 1: OverlayData(), 2: OverlayData()},
    )
    view = _blackout_view(viewer)
    assert SeriesView.blackout_areas_in_series(view) == 0
    assert viewer.cleared == 0
    assert viewer.loaded == []


def test_blackout_button_series_without_rects_does_not_replay() -> None:
    viewer = _FakeBlackoutViewer(num_images=3, overlay_data={0: OverlayData()})
    view = _blackout_view(viewer)
    statuses: list[str] = []
    view.update_status = lambda message, **_kwargs: statuses.append(message)
    SeriesView.blackout_button_clicked(view)
    assert statuses == ["No blackout area(s) in series"]
    assert viewer.cleared == 0
    assert viewer.loaded == []


def test_blackout_series_with_rects_applies_and_replays() -> None:
    rect = UserRectangle(top_left=(0, 0), bottom_right=(5, 5))
    viewer = _FakeBlackoutViewer(
        num_images=2,
        overlay_data={0: OverlayData(user_rects=[rect]), 1: OverlayData()},
    )
    view = _blackout_view(viewer)
    applied_frames: list[int] = []

    def _apply(frame_index: int, user_rects: list) -> None:
        applied_frames.append(frame_index)
        user_rects.clear()

    view.blackout_areas_in_single_frame = _apply
    assert SeriesView.blackout_areas_in_series(view) == 1
    assert applied_frames == [0]
    assert viewer.loaded == [0, 1, 0]


def test_harmonize_button_visible_once_until_cleared() -> None:
    # Presence follows the series ORM flag only (plus models/modality readiness).
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CT",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CT",
        already_harmonized=True,
    )
    # Planar XR/US/MG Harmonize is metadata-only (no TS models required for the button).
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="US",
        already_harmonized=False,
    )
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CR",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="SC",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=False,
        modality="CT",
        already_harmonized=False,
    )


def test_image_viewer_nav_keys_return_break_to_stop_toplevel_bind() -> None:
    """Arrow handlers must return break so SeriesView does not advance a second time."""
    from anonymizer.view.series.image import ImageViewer

    viewer = ImageViewer.__new__(ImageViewer)
    viewer.current_image_index = 2
    viewer.num_images = 10
    viewer._startup_complete = True
    viewer._interaction_enabled = True
    viewer.images = object()
    viewer._suppress_callbacks = True
    viewer.on_slice_index_changed = None
    loads: list[int] = []

    def _load(index: int) -> None:
        loads.append(index)
        viewer.current_image_index = index

    viewer.load_and_display_image = _load

    assert ImageViewer.next_image(viewer, None) == "break"
    assert loads == [3]
    assert viewer.current_image_index == 3
    assert ImageViewer.prev_image(viewer, None) == "break"
    assert loads == [3, 2]
    assert viewer.current_image_index == 2


def test_series_view_skips_nav_key_when_event_from_image_viewer() -> None:
    """SeriesView must not re-dispatch arrows that ImageViewer already handled."""
    view = SeriesView.__new__(SeriesView)
    view._focus_is_text_input = lambda: False
    calls: list[str] = []

    class _Viewer:
        def __str__(self) -> str:
            return ".!seriesview.!imageviewer"

        def next_image(self, _event) -> str:
            calls.append("next")
            return "break"

    view.image_viewer = _Viewer()

    class _Event:
        widget = type("W", (), {"__str__": lambda self: ".!seriesview.!imageviewer.!canvas"})()

    assert SeriesView._on_slice_navigation_key(view, _Event(), "next_image") == "break"
    assert calls == []

    class _ToolbarEvent:
        widget = type("W", (), {"__str__": lambda self: ".!seriesview.!button"})()

    assert SeriesView._on_slice_navigation_key(view, _ToolbarEvent(), "next_image") == "break"
    assert calls == ["next"]
