"""ImageViewer display sizing: View vs Actual invariants."""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

import numpy as np
import pytest
import tkinter as tk

from anonymizer.controller.series_io import load_series_frames
from anonymizer.view.series import series as series_mod
from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView
from tests.controller.tseg.support.synthetic_ct import (
    FALCON_MIN_SLICES,
    build_synthetic_ct_small_series,
)

_THEME_PATH = (
    __import__("pathlib").Path(__file__).resolve().parents[3]
    / "src"
    / "anonymizer"
    / "assets"
    / "themes"
    / "rsna_theme.json"
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


@pytest.fixture(autouse=True)
def _stub_viewer_icon_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.view.series import image as image_mod
    from PIL import Image

    icon = Image.new("RGB", (28, 28), color=(0, 0, 0))
    monkeypatch.setattr(image_mod.Image, "open", lambda _path: icon)


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


def _layout_large_viewport(viewer: ImageViewer, *, width: int = 600, height: int = 600) -> None:
    panel_w = ImageViewer.HISTOGRAM_CANVAS_WIDTH + 4 * ImageViewer.DATA_PANEL_PAD + 80
    viewer.configure(
        width=width + panel_w,
        height=max(height, ImageViewer.DATA_PANEL_MIN_HEIGHT) + 200,
    )
    viewer.pack(fill="both", expand=True)
    viewer.image_frame.configure(width=width, height=height)
    viewer.update_idletasks()


def _viewer_with_panel(tk_root: tk.Tk, *, width: int, height: int, slices: int = 3) -> ImageViewer:
    return _viewer(tk_root, width=width, height=height, slices=slices, show_data_panel=True)


def test_resolve_display_size_snaps_to_native_when_viewport_fits(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512)
    resolved = viewer._resolve_display_size(800, 700, allow_upscale=False)
    assert resolved == (512, 512)


def test_resolve_display_size_upscales_beyond_native_when_viewport_larger(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512)
    resolved = viewer._resolve_display_size(800, 700)
    assert resolved == (700, 700)


def test_resolve_display_size_preserves_aspect_on_upscale(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=256)
    resolved = viewer._resolve_display_size(800, 400)
    assert resolved == (800, 400)


def test_resolve_display_size_scales_down_when_viewport_too_small(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512)
    resolved = viewer._resolve_display_size(256, 256)
    assert resolved is not None
    assert resolved[0] <= 256
    assert resolved[1] <= 256
    assert resolved != (512, 512)


def test_viewport_fits_native_requires_both_dimensions(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512)
    assert viewer._viewport_fits_native(512, 512)
    assert viewer._viewport_fits_native(600, 512)
    assert not viewer._viewport_fits_native(511, 512)
    assert not viewer._viewport_fits_native(512, 511)


def test_apply_initial_layout_view_matches_actual_above_threshold(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=256, height=256)
    _layout_large_viewport(viewer)

    viewer.apply_initial_layout()

    assert viewer.view_matches_actual()
    assert viewer.get_dimensions_text() == "View[256x256] Actual[256x256]"


@pytest.mark.parametrize(("width", "height"), [(64, 64), (128, 128)])
def test_small_slice_below_widget_threshold_keeps_native_view_size(
    tk_root: tk.Tk,
    width: int,
    height: int,
) -> None:
    """Slices shorter than DATA_PANEL_MIN_HEIGHT still render at native resolution."""
    assert height < ImageViewer.DATA_PANEL_MIN_HEIGHT
    viewer = _viewer_with_panel(tk_root, width=width, height=height)
    _layout_large_viewport(viewer)

    viewer.apply_initial_layout()

    assert viewer.view_matches_actual()
    assert viewer.get_dimensions_text() == f"View[{width}x{height}] Actual[{width}x{height}]"
    assert viewer.current_size == (width, height)


@pytest.mark.parametrize(("width", "height"), [(64, 64), (128, 128)])
def test_data_panel_target_height_floors_at_minimum_for_small_slices(
    tk_root: tk.Tk,
    width: int,
    height: int,
) -> None:
    viewer = _viewer_with_panel(tk_root, width=width, height=height)
    viewer.current_size = (width, height)

    assert viewer._data_panel_target_height() == ImageViewer.DATA_PANEL_MIN_HEIGHT


def test_data_panel_target_height_follows_image_when_above_widget_threshold(tk_root: tk.Tk) -> None:
    viewer = _viewer_with_panel(tk_root, width=512, height=512)
    viewer.current_size = (512, 512)

    assert viewer._data_panel_target_height() == 512


@pytest.mark.parametrize(("width", "height"), [(64, 64), (128, 128)])
def test_small_slice_layout_preserves_widget_panel_minimum(
    tk_root: tk.Tk,
    width: int,
    height: int,
) -> None:
    """RHS widgets stay usable: panel height is floored even when the image is tiny."""
    viewer = _viewer_with_panel(tk_root, width=width, height=height)
    _layout_large_viewport(viewer)
    assert viewer.data_frame is not None
    assert viewer.histogram is not None
    assert viewer.control_frame is not None

    viewer.apply_initial_layout()

    assert viewer.view_matches_actual()
    assert viewer._data_panel_target_height() == ImageViewer.DATA_PANEL_MIN_HEIGHT
    assert viewer._last_hist_canvas_height is not None
    panel_h = viewer.data_frame.winfo_height()
    if panel_h >= ImageViewer.DATA_PANEL_MIN_HEIGHT:
        assert viewer._last_hist_canvas_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    assert viewer.player_fits_data_panel()
    assert viewer.data_frame.winfo_height() >= ImageViewer.DATA_PANEL_MIN_HEIGHT or viewer.player_fits_data_panel()
    assert viewer.image_size_label is not None
    assert viewer.image_size_label.cget("text") == f"View[{width}x{height}] Actual[{width}x{height}]"


def test_small_slice_does_not_upscale_on_initial_layout(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=64, height=64)
    resolved = viewer._resolve_display_size(800, 700, allow_upscale=False)

    assert resolved == (64, 64)


def test_data_panel_layout_without_segmentation_prioritizes_histogram(tk_root: tk.Tk) -> None:
    viewer = _viewer_with_panel(tk_root, width=512, height=512)
    viewer.current_size = (512, 512)
    viewer.update_idletasks()

    layout = viewer._compute_data_panel_layout()

    assert not layout.show_segmentation_buttons
    assert layout.segmentation_buttons_height == ImageViewer.SEGMENTATION_EMPTY_HEIGHT
    assert layout.histogram_height == ImageViewer.HISTOGRAM_CANVAS_HEIGHT
    assert layout.panel_height == 512


def test_data_panel_layout_with_segmentation_caps_scroll_and_preserves_histogram(tk_root: tk.Tk) -> None:
    viewer = _viewer_with_panel(tk_root, width=512, height=512)
    viewer.current_size = (512, 512)
    viewer._segmentation_button_meta = {"brain": (0, 0, 255), "skull": (200, 200, 200)}
    viewer.update_idletasks()

    layout = viewer._compute_data_panel_layout()

    assert layout.show_segmentation_buttons
    assert ImageViewer.SEGMENTATION_SCROLL_MIN_HEIGHT <= layout.segmentation_buttons_height
    assert layout.segmentation_buttons_height <= ImageViewer.SEGMENTATION_SCROLL_MAX_HEIGHT
    assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT


def test_data_panel_layout_reserves_player_chrome(tk_root: tk.Tk) -> None:
    viewer = _viewer_with_panel(tk_root, width=512, height=512, slices=11)
    viewer.current_size = (512, 512)
    viewer._segmentation_button_meta = {"brain": (0, 0, 255)}
    viewer.update_idletasks()

    layout = viewer._compute_data_panel_layout()
    padding = 4 * ImageViewer.DATA_PANEL_PAD
    chrome = layout.histogram_height + layout.segmentation_buttons_height + padding
    chrome += ImageViewer.HISTOGRAM_WIDGET_CHROME
    chrome += viewer._control_chrome_height()

    assert layout.histogram_height >= ImageViewer.HISTOGRAM_CANVAS_MIN_HEIGHT
    assert chrome <= layout.panel_height + 4


def test_data_panel_available_height_tracks_image_column(tk_root: tk.Tk) -> None:
    viewer = _viewer_with_panel(tk_root, width=512, height=512, slices=11)
    _layout_large_viewport(viewer, width=600, height=400)
    viewer.current_size = (300, 300)
    viewer.update_idletasks()

    available = viewer._data_panel_available_height()

    assert available <= 400
    assert available >= ImageViewer.DATA_PANEL_MIN_HEIGHT


def test_segmentation_buttons_do_not_change_display_size(tk_root: tk.Tk) -> None:
    """Populating segmentation latch buttons must not rescale the image canvas."""
    viewer = _viewer_with_panel(tk_root, width=512, height=512)
    _layout_large_viewport(viewer)
    viewer._startup_complete = True
    viewer.apply_initial_layout()
    before = viewer.current_size
    assert before[0] > 0 and before[1] > 0

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
    viewer._sync_data_panel_to_image_height()
    tk_root.update_idletasks()

    assert viewer.current_size == before
    layout = viewer._compute_data_panel_layout()
    assert len(viewer._segmentation_buttons) == len(items)
    assert viewer.player_fits_data_panel()
    if viewer.data_frame.winfo_height() >= 360:
        assert layout.show_segmentation_buttons
        assert layout.segmentation_buttons_height >= ImageViewer.SEGMENTATION_SCROLL_MIN_HEIGHT


def test_apply_viewport_size_never_exceeds_native(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=512, height=512, show_data_panel=False)
    viewer.pack(fill="both", expand=True)
    viewer.image_frame.grid_propagate(False)
    viewer.image_frame.configure(width=900, height=900)
    tk_root.update_idletasks()
    viewer._startup_complete = True
    viewer._last_viewport_size = (100, 100)
    viewer._apply_viewport_size()
    assert viewer.current_size == (512, 512)
