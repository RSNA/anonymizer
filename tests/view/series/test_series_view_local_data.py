"""Local Series View layout tests against developer MRI_TEST fixtures (not run in CI).

These exercise the real image_frame Configure → fit_to_viewport path on real 512×512
MRI data. Resize is driven only by ``geometry()`` / ``drag_window``.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView
from tests.view.series.support.layout_probes import (
    assert_aspect_preserved,
    assert_chrome_unclipped,
    assert_pixmap_matches_display,
    drag_window,
    open_series_view,
    pump,
    settle,
)

pytestmark = pytest.mark.view_dev

MRI_TEST_STUDY = Path(
    "/Users/michaelevans/Documents/RSNA Anonymizer/MRI_TEST/public/"
    "993241-000003/1.2.826.0.1.3680043.10.474.2.993241.2.87153661778703757233353464"
)
SEGMENTED_SERIES = MRI_TEST_STUDY / "1.2.826.0.1.3680043.10.474.2.993241.2.45986319822060102567882005"
UNSEGMENTED_SERIES = MRI_TEST_STUDY / "1.2.826.0.1.3680043.10.474.2.993241.2.57891753487013526847167725"

ALL_SERIES = {"segmented": SEGMENTED_SERIES, "unsegmented": UNSEGMENTED_SERIES}


@pytest.fixture(scope="module", autouse=True)
def _require_local_study() -> None:
    if not SEGMENTED_SERIES.is_dir() or not UNSEGMENTED_SERIES.is_dir():
        pytest.skip(f"local MRI_TEST study not found under {MRI_TEST_STUDY}")


@pytest.fixture(params=sorted(ALL_SERIES), ids=sorted(ALL_SERIES))
def local_view(request, tk_root: tk.Tk, mock_controller: MagicMock) -> SeriesView:
    view = open_series_view(tk_root, mock_controller, ALL_SERIES[request.param])
    yield view
    view.destroy()
    pump(tk_root)


def test_local_study_opens_native(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer
    assert (viewer.image_width, viewer.image_height) == (512, 512)
    assert viewer.view_matches_actual(), viewer.get_dimensions_text()
    assert viewer.current_size == (512, 512)
    assert_pixmap_matches_display(viewer)


def test_local_study_player_visible_after_startup(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer
    assert viewer.toggle_button is not None
    assert viewer._last_hist_canvas_height == ImageViewer.HISTOGRAM_CANVAS_HEIGHT
    assert_chrome_unclipped(viewer)


def test_local_study_player_visible_at_minimum_window_size(local_view: SeriesView) -> None:
    """The smallest allowed window must still show the whole playback row."""
    viewer = local_view.image_viewer
    min_w, min_h = local_view._minimum_window_size()

    local_view.geometry(f"{min_w}x{min_h}")
    settle(local_view)

    assert_chrome_unclipped(viewer)
    assert viewer.toggle_button is not None
    assert viewer.toggle_button.winfo_ismapped()


def test_local_study_drag_tracks_the_image_during_the_drag(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer
    start = viewer.current_size

    observed = drag_window(local_view, local_view._minimum_window_size())

    assert any(size != start for size in observed), f"image never resized during the drag (stuck at {start})"
    assert len(set(observed)) > 2, f"only {set(observed)} seen across the drag"


def test_local_study_drag_preserves_aspect_at_every_step(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer

    for size in drag_window(local_view, local_view._minimum_window_size()):
        assert size[0] == size[1], f"512x512 MRI must stay square while scaling, got {size}"
        assert size[0] <= viewer.image_width


def test_local_study_shrink_then_grow_upscales(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer
    hist_before = viewer._last_hist_canvas_height

    drag_window(local_view, local_view._minimum_window_size())
    settle(local_view)
    shrunk = viewer.current_size
    assert shrunk[0] < 512 or shrunk[1] < 512, f"expected shrink, got {shrunk}"
    assert_aspect_preserved(viewer)
    assert_pixmap_matches_display(viewer)
    assert viewer._last_hist_canvas_height == hist_before
    assert_chrome_unclipped(viewer)

    drag_window(local_view, (1600, 1000))
    settle(local_view)
    grown = viewer.current_size
    assert grown[0] > 512 or grown[1] > 512, f"expected upscale past native, got {grown}"
    assert_aspect_preserved(viewer)
    assert_pixmap_matches_display(viewer)
    assert viewer._last_hist_canvas_height == hist_before
    assert_chrome_unclipped(viewer)


def test_local_study_grow_past_native_upscales(local_view: SeriesView) -> None:
    viewer = local_view.image_viewer

    local_view.geometry("1800x1100")
    settle(local_view)

    assert viewer.current_size[0] > 512 or viewer.current_size[1] > 512, (
        f"expected upscale past native 512×512, got {viewer.current_size}"
    )
    assert_aspect_preserved(viewer)
    assert_pixmap_matches_display(viewer)
    assert_chrome_unclipped(viewer)


def test_local_segmented_series_loads_without_image_jump(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
) -> None:
    view = open_series_view(tk_root, mock_controller, SEGMENTED_SERIES)
    viewer = view.image_viewer
    before = viewer.current_size
    assert viewer.view_matches_actual()

    view._load_segmentation_chrome()
    settle(view)

    assert len(viewer._segmentation_buttons) > 0
    assert viewer.current_size == before
    assert viewer._last_hist_canvas_height == ImageViewer.HISTOGRAM_CANVAS_HEIGHT
    assert_chrome_unclipped(viewer)

    view.destroy()
    pump(tk_root)


def test_local_segmented_series_player_visible_at_minimum_after_chrome_load(
    tk_root: tk.Tk,
    mock_controller: MagicMock,
) -> None:
    """Segmentation buttons make the RHS tallest; minsize must still fit the player."""
    view = open_series_view(tk_root, mock_controller, SEGMENTED_SERIES)
    viewer = view.image_viewer

    view._load_segmentation_chrome()
    settle(view)
    min_w, min_h = view._minimum_window_size()
    view.geometry(f"{min_w}x{min_h}")
    settle(view)

    assert len(viewer._segmentation_buttons) > 0
    assert_chrome_unclipped(viewer)
    assert_aspect_preserved(viewer)

    view.destroy()
    pump(tk_root)
