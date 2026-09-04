"""ImageViewer display sizing: aspect maths, repaint behaviour, and RHS chrome.

Widget-level invariants only. Window-driven resize behaviour lives in
``test_series_view_layout.py``, which drives real Configure events; asserting on a
directly invoked layout call here would not prove the handler ever runs.
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import numpy as np
import pytest

from anonymizer.view.series.image import ImageViewer
from tests.view.series.support.layout_probes import assert_pixmap_matches_display, pump

# Non-square shapes are essential: a square frame cannot detect a width/height
# transposition in the scaling maths.
FRAME_SHAPES = [(512, 512), (512, 256), (256, 512), (128, 128), (64, 64)]


def _viewer(
    tk_root: tk.Tk,
    *,
    width: int = 512,
    height: int = 512,
    slices: int = 3,
    show_data_panel: bool = False,
) -> ImageViewer:
    frames = np.zeros((slices, height, width), dtype=np.float32)
    return ImageViewer(
        tk_root,
        frames,
        40.0,
        400.0,
        add_to_whitelist_callback=MagicMock(),
        regenerate_series_projections_callback=MagicMock(),
        show_data_panel=show_data_panel,
    )


def _give_viewport(viewer: ImageViewer, *, width: int, height: int) -> None:
    """Force the image column to a known size without going through a window."""
    viewer.pack(fill="both", expand=True)
    viewer.image_frame.grid_propagate(False)
    viewer.image_frame.configure(width=width, height=height)
    viewer.update_idletasks()


@pytest.mark.parametrize(("width", "height"), FRAME_SHAPES)
def test_resolve_display_size_caps_at_native(tk_root: tk.Tk, width: int, height: int) -> None:
    viewer = _viewer(tk_root, width=width, height=height)
    assert viewer._resolve_display_size(2000, 2000) == (width, height)


@pytest.mark.parametrize(("width", "height"), FRAME_SHAPES)
def test_resolve_display_size_preserves_aspect_when_shrinking(tk_root: tk.Tk, width: int, height: int) -> None:
    viewer = _viewer(tk_root, width=width, height=height)
    native_aspect = width / height

    resolved = viewer._resolve_display_size(width // 2, height // 2)

    assert resolved is not None
    assert resolved != (width, height)
    assert resolved[0] <= width // 2
    assert resolved[1] <= height // 2
    assert resolved[0] / resolved[1] == pytest.approx(native_aspect, rel=0.02)


def test_resolve_display_size_fits_the_constraining_axis(tk_root: tk.Tk) -> None:
    """A wide frame in a tall viewport is limited by width, and vice versa."""
    wide = _viewer(tk_root, width=512, height=256)
    assert wide._resolve_display_size(256, 1000) == (256, 128)

    tall = _viewer(tk_root, width=256, height=512)
    assert tall._resolve_display_size(1000, 256) == (128, 256)


def test_resolve_display_size_upscales_only_when_asked(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=256)
    assert viewer._resolve_display_size(800, 400, allow_upscale=True) == (800, 400)
    assert viewer._resolve_display_size(800, 400, allow_upscale=False) == (512, 256)


def test_viewport_fits_native_requires_both_dimensions(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=256)
    assert viewer._viewport_fits_native(512, 256)
    assert viewer._viewport_fits_native(600, 256)
    assert not viewer._viewport_fits_native(511, 256)
    assert not viewer._viewport_fits_native(512, 255)


@pytest.mark.parametrize(("width", "height"), FRAME_SHAPES)
def test_fit_to_viewport_renders_native_in_a_generous_viewport(tk_root: tk.Tk, width: int, height: int) -> None:
    viewer = _viewer(tk_root, width=width, height=height, show_data_panel=True)
    _give_viewport(viewer, width=900, height=900)

    viewer.fit_to_viewport(force=True, fill_viewport=False)
    tk_root.update_idletasks()

    assert viewer.view_matches_actual(), viewer.get_dimensions_text()
    assert viewer.get_dimensions_text() == f"View[{width}x{height}] Actual[{width}x{height}]"
    assert_pixmap_matches_display(viewer)


@pytest.mark.parametrize(("width", "height"), FRAME_SHAPES)
def test_fit_to_viewport_upscales_to_fill_viewport(tk_root: tk.Tk, width: int, height: int) -> None:
    viewer = _viewer(tk_root, width=width, height=height)
    _give_viewport(viewer, width=900, height=700)

    viewer.fit_to_viewport(force=True, fill_viewport=True)

    display = viewer.current_size
    assert display[0] > width or display[1] > height
    assert display[0] / display[1] == pytest.approx(width / height, rel=0.02)
    assert_pixmap_matches_display(viewer)


def test_fit_to_viewport_falls_back_to_screen_budget_when_unmapped(tk_root: tk.Tk) -> None:
    """Startup runs before the frame has a size; the paint must still happen."""
    viewer = _viewer(tk_root, width=64, height=64)

    assert viewer.fit_to_viewport(force=True, fill_viewport=False) is True
    assert viewer.current_size == (64, 64)


def test_set_display_size_noop_when_unchanged(tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    viewer = _viewer(tk_root, width=256, height=256)
    _give_viewport(viewer, width=600, height=600)
    viewer.fit_to_viewport(force=True)
    calls: list[int] = []
    original = viewer.load_and_display_image
    monkeypatch.setattr(viewer, "load_and_display_image", lambda ndx: (calls.append(ndx), original(ndx))[1])

    assert viewer.set_display_size(viewer.current_size) is False
    assert calls == []


def test_set_display_size_repaints_when_changed(tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    viewer = _viewer(tk_root, width=256, height=256)
    _give_viewport(viewer, width=600, height=600)
    viewer.fit_to_viewport(force=True)
    calls: list[int] = []
    original = viewer.load_and_display_image
    monkeypatch.setattr(viewer, "load_and_display_image", lambda ndx: (calls.append(ndx), original(ndx))[1])

    assert viewer.set_display_size((128, 128)) is True
    assert calls == [0]
    assert viewer.current_size == (128, 128)
    tk_root.update_idletasks()
    assert_pixmap_matches_display(viewer)


def test_apply_fixed_chrome_keeps_histogram_at_declared_size(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512, show_data_panel=True)
    _give_viewport(viewer, width=600, height=600)

    viewer.apply_fixed_chrome(refresh_histogram=True)
    tk_root.update_idletasks()

    assert viewer._last_hist_canvas_height == ImageViewer.HISTOGRAM_CANVAS_HEIGHT
    assert not viewer._segmentation_button_meta
    assert viewer.chrome_fully_visible()


def test_apply_fixed_chrome_shows_segmentation_scroll_when_populated(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512, show_data_panel=True)
    _give_viewport(viewer, width=600, height=600)

    viewer.set_segmentation_structures([("brain", (0, 0, 255)), ("skull", (200, 200, 200))])
    tk_root.update_idletasks()

    assert viewer._segmentation_scroll_height == ImageViewer.SEGMENTATION_SCROLL_MAX_HEIGHT
    assert viewer.segmentation_buttons_frame is not None
    assert viewer.segmentation_buttons_frame.winfo_ismapped()
    assert viewer.chrome_fully_visible()


def test_rhs_panel_is_wide_enough_for_the_control_row(tk_root: tk.Tk) -> None:
    """The control row is wider than the histogram, so the panel must not be pinned.

    Regression: pinning data_frame to the histogram width clipped the playback
    controls and under-reported the viewer's requested width by that difference.
    """
    viewer = _viewer(tk_root, width=512, height=512, slices=11, show_data_panel=True)
    _give_viewport(viewer, width=600, height=600)
    tk_root.update_idletasks()

    assert viewer.data_frame is not None
    assert viewer.control_frame is not None
    assert viewer.data_frame.winfo_reqwidth() >= viewer.control_frame.winfo_reqwidth()
    assert viewer.data_frame.winfo_reqwidth() > ImageViewer.HISTOGRAM_CANVAS_WIDTH


def test_segmentation_buttons_do_not_change_display_size(tk_root: tk.Tk) -> None:
    """Populating segmentation latch buttons must not rescale the image canvas."""
    viewer = _viewer(tk_root, width=512, height=512, show_data_panel=True)
    _give_viewport(viewer, width=600, height=600)
    viewer._startup_complete = True
    viewer.fit_to_viewport(force=True)
    before = viewer.current_size

    items = [
        ("brain", (0, 0, 255)),
        ("frontal_lobe", (0, 128, 255)),
        ("parietal_lobe", (0, 128, 255)),
        ("temporal_lobe", (0, 128, 255)),
        ("cerebellum", (0, 128, 255)),
        ("skull", (200, 200, 200)),
        ("spine", (255, 128, 0)),
        ("ribs", (255, 128, 0)),
    ]
    viewer.set_segmentation_structures(items)
    tk_root.update_idletasks()

    assert viewer.current_size == before
    assert len(viewer._segmentation_buttons) == len(items)
    assert viewer.chrome_fully_visible()


def test_image_frame_configure_coalesces_pending_fit(tk_root: tk.Tk) -> None:
    """Repeated fit requests must coalesce into one idle callback."""
    viewer = _viewer(tk_root, width=256, height=256)
    _give_viewport(viewer, width=600, height=600)
    viewer._startup_complete = True
    viewer.fit_to_viewport(force=True, fill_viewport=False)

    viewer._viewport_fit_pending = False
    for _ in range(5):
        viewer._request_viewport_fit()
    assert viewer._viewport_fit_pending
    pump(tk_root, steps=20)
    assert not viewer._viewport_fit_pending


def test_dimensions_label_width_covers_the_longest_text(tk_root: tk.Tk) -> None:
    """A fixed label width stops the RHS shifting as the digit count changes."""
    viewer = _viewer(tk_root, width=512, height=512, show_data_panel=True)
    _give_viewport(viewer, width=600, height=600)
    viewer.apply_fixed_chrome()
    tk_root.update_idletasks()

    assert viewer.image_size_label is not None
    reserved = viewer.image_size_label.cget("width")
    assert reserved == viewer._dimensions_label_width()

    viewer.set_display_size((99, 99))
    tk_root.update_idletasks()
    assert viewer.image_size_label.cget("width") == reserved
