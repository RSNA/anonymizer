"""Tests for ImageViewer zoom/pan transforms and Shift+LMB pan vs paint."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from anonymizer.controller.series_overlay import PolygonPoint, Segmentation
from anonymizer.view.series.image import ImageViewer


def _viewer(tk_root: tk.Tk, *, width: int = 100, height: int = 80, slices: int = 2) -> ImageViewer:
    frames = np.zeros((slices, height, width), dtype=np.float32)
    viewer = ImageViewer(
        tk_root,
        frames,
        40.0,
        400.0,
        add_to_whitelist_callback=MagicMock(),
        regenerate_series_projections_callback=MagicMock(),
        show_data_panel=False,
    )
    viewer.current_size = (width, height)
    viewer._startup_complete = True
    return viewer


def test_view_image_coord_round_trip_at_identity(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    ix, iy = 40, 30
    vx, vy = viewer._image_to_view_coords(ix, iy)
    back_x, back_y = viewer._view_to_image_coords(vx, vy)
    assert abs(back_x - ix) <= 1
    assert abs(back_y - iy) <= 1


def test_view_image_coord_round_trip_with_zoom_and_pan(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    viewer._zoom = 2.0
    viewer._pan_x = -20.0
    viewer._pan_y = -10.0
    ix, iy = 40, 30
    vx, vy = viewer._image_to_view_coords(ix, iy)
    back_x, back_y = viewer._view_to_image_coords(vx, vy)
    assert abs(back_x - ix) <= 1
    assert abs(back_y - iy) <= 1


def test_cursor_centric_zoom_keeps_point_under_pointer(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    canvas_x, canvas_y = 50.0, 40.0
    fit_x = (canvas_x - viewer._pan_x) / viewer._zoom
    fit_y = (canvas_y - viewer._pan_y) / viewer._zoom
    viewer._zoom_at_canvas(canvas_x, canvas_y, 2.0)
    assert viewer._zoom == pytest.approx(2.0)
    assert (canvas_x - viewer._pan_x) / viewer._zoom == pytest.approx(fit_x)
    assert (canvas_y - viewer._pan_y) / viewer._zoom == pytest.approx(fit_y)


def test_reset_zoom_pan_restores_identity(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    viewer._zoom = 3.0
    viewer._pan_x = -40.0
    viewer._pan_y = 15.0
    viewer.reset_zoom_pan()
    assert viewer._zoom == 1.0
    assert viewer._pan_x == 0.0
    assert viewer._pan_y == 0.0


def test_zoom_clamped_to_range(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    viewer._zoom_at_canvas(10.0, 10.0, 100.0)
    assert viewer._zoom == viewer.ZOOM_MAX
    viewer._zoom_at_canvas(10.0, 10.0, 0.001)
    assert viewer._zoom == viewer.ZOOM_MIN


def test_shift_left_click_starts_pan_not_paint(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    viewer.set_annotate_enabled(True)
    viewer.set_annotate_mode("annotate")
    viewer.on_annotate_stroke = MagicMock()
    event = SimpleNamespace(x=10, y=12, state=0x1)  # Shift
    viewer._on_left_click(event)
    assert viewer._panning is True
    assert viewer._painting is False
    viewer.on_annotate_stroke.assert_not_called()


def test_plain_left_click_in_annotate_paints(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root)
    viewer.set_annotate_enabled(True)
    viewer.set_annotate_mode("annotate")
    viewer.set_paint_target("user:1")
    viewer.on_annotate_stroke = MagicMock()
    event = SimpleNamespace(x=10, y=12, state=0)
    viewer._on_left_click(event)
    assert viewer._painting is True
    assert viewer._panning is False
    viewer.on_annotate_stroke.assert_called()


def test_magnify_photo_uses_nearest_resampling(tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    viewer = _viewer(tk_root, width=32, height=32)
    viewer._zoom = 4.0
    recorded: list[object] = []
    original = Image.Image.resize

    def spy(self, size, resample=None, *args, **kwargs):
        recorded.append(resample)
        return original(self, size, resample=resample, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", spy)
    source = Image.new("RGB", (32, 32), (0, 0, 0))
    viewer._photo_from_source_pil(source)
    assert Image.Resampling.NEAREST in recorded


def test_nearest_upscale_keeps_pure_edge_color(tk_root: tk.Tk) -> None:
    """1px native outline stays unblended after NEAREST magnification."""
    viewer = _viewer(tk_root, width=32, height=32)
    arr = np.zeros((32, 32, 3), dtype=np.uint8)
    arr[:, 10] = (255, 0, 0)
    native = Image.fromarray(arr)
    viewer._native_pil = native
    viewer._zoom = 4.0
    viewer.current_size = (32, 32)
    zw, zh = viewer._zoomed_display_size()
    resized = native.resize((zw, zh), Image.Resampling.NEAREST)
    assert resized.getpixel((40, 16)) == (255, 0, 0)
    # Adjacent column is either the same block or empty — never a blended pink.
    neighbor = resized.getpixel((41, 16))
    assert neighbor in ((255, 0, 0), (0, 0, 0))


def test_set_segmentation_overlays_keeps_other_cached_frames(tk_root: tk.Tk) -> None:
    viewer = _viewer(tk_root, width=32, height=32, slices=3)
    for i in range(3):
        pil = Image.new("RGB", viewer.current_size, (i, i, i))
        viewer.image_cache[i] = (MagicMock(), pil, viewer.current_size)
    viewer.current_image_index = 1
    viewer._native_pil = Image.new("RGB", (32, 32), (0, 0, 0))
    viewer._fit_pil = Image.new("RGB", viewer.current_size, (0, 0, 0))
    segs = [
        Segmentation(
            points=[
                PolygonPoint(x=2, y=2),
                PolygonPoint(x=10, y=2),
                PolygonPoint(x=10, y=10),
                PolygonPoint(x=2, y=10),
            ],
            color_bgr=(0, 0, 255),
            structure_name="test",
        )
    ]
    viewer.set_segmentation_overlays({1: segs})
    assert 0 in viewer.image_cache
    assert 2 in viewer.image_cache
