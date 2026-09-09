"""Series View layout: startup geometry and aspect-preserving resize.

Resize is driven only through ``geometry()`` and event pumping, exactly as a user
drag would. Square and non-square series are both covered: a square frame cannot
detect width/height transposition in the aspect maths.
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from anonymizer.view.series.series import SeriesView
from tests.controller.tseg.support.synthetic_ct import (
    SYNTHETIC_VOLUME_MIN_SLICES,
    build_synthetic_chest_ct_series,
    build_synthetic_wide_ct_series,
)
from tests.view.series.support.layout_probes import (
    assert_aspect_preserved,
    assert_chrome_unclipped,
    assert_pixmap_matches_display,
    drag_window,
    open_series_view,
    pump,
    settle,
)

SERIES_BUILDERS = {
    "square_256": build_synthetic_chest_ct_series,
    "wide_256x512": build_synthetic_wide_ct_series,
}


@pytest.fixture(params=sorted(SERIES_BUILDERS), ids=sorted(SERIES_BUILDERS))
def series_view(request, tk_root: tk.Tk, mock_controller: MagicMock, tmp_path) -> SeriesView:
    """A mapped SeriesView for each frame geometry, closed after the test."""
    builder = SERIES_BUILDERS[request.param]
    series_dir = builder(tmp_path / request.param, num_slices=SYNTHETIC_VOLUME_MIN_SLICES)
    view = open_series_view(tk_root, mock_controller, series_dir)
    yield view
    view.destroy()
    pump(tk_root)


def test_startup_displays_native_resolution(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    assert viewer.view_matches_actual(), viewer.get_dimensions_text()
    assert viewer.current_size == (viewer.image_width, viewer.image_height)
    assert_pixmap_matches_display(viewer)


def test_startup_chrome_is_not_clipped(series_view: SeriesView) -> None:
    """The RHS control row is wider than the histogram; it must still fit."""
    viewer = series_view.image_viewer
    assert_chrome_unclipped(viewer)
    assert viewer.data_frame is not None
    assert viewer.data_frame.winfo_width() >= viewer.data_frame.winfo_reqwidth()


def test_startup_window_fits_native_viewport(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    viewport_w, viewport_h = viewer.viewport_size()
    assert viewport_w >= viewer.image_width
    assert viewport_h >= viewer.image_height


def test_drag_shrink_tracks_during_the_drag(series_view: SeriesView) -> None:
    """The image must resize while the drag is in progress, not only after it ends.

    Regression: a cancel-and-re-arm debounce is re-armed by every Configure, so the
    image stayed frozen at its old size for the whole drag while the surrounding
    grid-managed controls reflowed live.
    """
    viewer = series_view.image_viewer
    start = viewer.current_size
    min_w, min_h = series_view._minimum_window_size()

    observed = drag_window(series_view, (min_w, min_h))

    assert any(size != start for size in observed), (
        f"display size never changed during the drag (stuck at {start}); the resize handler is starving"
    )
    assert len({size for size in observed}) > 2, f"only {set(observed)} seen across the drag"


def test_drag_shrink_preserves_aspect_at_every_step(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    native_aspect = viewer.image_width / viewer.image_height
    min_w, min_h = series_view._minimum_window_size()

    for size in drag_window(series_view, (min_w, min_h)):
        assert size[0] / size[1] == pytest.approx(native_aspect, rel=0.03), (
            f"aspect broke mid-drag at {size} (native {viewer.image_width}x{viewer.image_height})"
        )
        assert size[0] <= viewer.image_width
        assert size[1] <= viewer.image_height


def test_shrink_then_settle_keeps_aspect_and_chrome(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    min_w, min_h = series_view._minimum_window_size()

    drag_window(series_view, (min_w, min_h))
    settle(series_view)

    shrunk = viewer.current_size
    assert shrunk[0] < viewer.image_width or shrunk[1] < viewer.image_height, f"expected shrink, got {shrunk}"
    assert_aspect_preserved(viewer)
    assert_pixmap_matches_display(viewer)
    assert_chrome_unclipped(viewer)


def test_grow_past_native_upscales_with_aspect(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    native_w, native_h = viewer.image_width, viewer.image_height

    drag_window(series_view, (1400, 950))
    settle(series_view)

    display = viewer.current_size
    assert display[0] > native_w or display[1] > native_h, f"expected upscale past native, got {display}"
    assert_aspect_preserved(viewer)
    assert_pixmap_matches_display(viewer)


def test_image_frame_configure_triggers_fit(series_view: SeriesView) -> None:
    """image_frame Configure must schedule a viewport fit without calling fit_to_viewport directly."""
    viewer = series_view.image_viewer
    settle(series_view)
    before = viewer.current_size
    frame_w, frame_h = viewer.viewport_size()
    shrunk_w = max(frame_w - 100, 140)
    shrunk_h = max(frame_h - 100, 140)

    event = tk.Event()
    event.widget = viewer.image_frame
    event.width = shrunk_w
    event.height = shrunk_h
    viewer._on_image_frame_configure(event)
    pump(series_view, steps=30)

    assert viewer.current_size != before, "image_frame Configure did not trigger a repaint"
    assert viewer.current_size[0] < before[0] or viewer.current_size[1] < before[1]
    assert_pixmap_matches_display(viewer)


def test_aspect_holds_across_a_sweep_of_window_sizes(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    min_w, min_h = series_view._minimum_window_size()

    for extra in (0, 90, 200, 340, 480):
        series_view.geometry(f"{min_w + extra}x{min_h + extra}")
        settle(series_view)
        assert_aspect_preserved(viewer)
        assert_pixmap_matches_display(viewer)
        assert_chrome_unclipped(viewer)


def test_resize_leaves_rhs_chrome_dimensions_untouched(series_view: SeriesView) -> None:
    """Only the image scales; the histogram and control stack are fixed chrome."""
    viewer = series_view.image_viewer
    assert viewer.data_frame is not None
    hist_before = viewer._last_hist_canvas_height
    panel_before = (viewer.data_frame.winfo_reqwidth(), viewer.data_frame.winfo_reqheight())
    min_w, min_h = series_view._minimum_window_size()

    drag_window(series_view, (min_w, min_h))
    settle(series_view)

    assert viewer._last_hist_canvas_height == hist_before
    assert (viewer.data_frame.winfo_reqwidth(), viewer.data_frame.winfo_reqheight()) == panel_before


def test_minimum_window_size_keeps_chrome_visible(series_view: SeriesView) -> None:
    viewer = series_view.image_viewer
    min_w, min_h = series_view._minimum_window_size()

    series_view.geometry(f"{min_w}x{min_h}")
    settle(series_view)

    assert_chrome_unclipped(viewer)
    assert viewer.current_size[0] >= 1
    assert viewer.current_size[1] >= 1


def test_image_column_absorbs_all_width_change(series_view: SeriesView) -> None:
    """The image column carries the grid weight; the RHS keeps its natural width."""
    viewer = series_view.image_viewer
    assert viewer.data_frame is not None
    column_before = viewer.image_frame.winfo_width()
    panel_before = viewer.data_frame.winfo_width()
    assert panel_before > 1

    series_view.geometry(f"{series_view.winfo_width() - 160}x{series_view.winfo_height()}")
    settle(series_view)

    assert viewer.image_frame.winfo_width() < column_before, "image column did not absorb the shrink"
    assert viewer.data_frame.winfo_width() == panel_before, "RHS width must not change with the window"


def test_growth_expands_display_size(series_view: SeriesView) -> None:
    """Extra window area scales the image up, not just the black surround."""
    viewer = series_view.image_viewer
    assert viewer.data_frame is not None
    display_before = viewer.current_size
    column_before = viewer.image_frame.winfo_width()
    panel_before = viewer.data_frame.winfo_width()

    series_view.geometry(f"{series_view.winfo_width() + 160}x{series_view.winfo_height()}")
    settle(series_view)

    assert viewer.image_frame.winfo_width() > column_before
    assert viewer.data_frame.winfo_width() == panel_before
    assert viewer.current_size[0] >= display_before[0]
    assert viewer.current_size[1] >= display_before[1]
