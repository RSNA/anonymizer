"""Probes for Series View layout tests.

These helpers exist so layout tests observe what a user would see. Two rules follow
from past regressions that the suite failed to catch:

1. Resize is driven only by ``geometry()`` plus event pumping, never by calling
   ``fit_to_viewport`` / ``_apply_image_layout`` directly. A test that invokes the
   layout method itself cannot detect a resize handler that never runs.
2. Assertions read the rendered pixmap and the *requested* sizes of chrome widgets.
   ``canvas.winfo_width()`` and ``current_size`` are both written by
   ``set_display_size``, so comparing them to each other proves nothing.
"""

from __future__ import annotations

import time
import tkinter as tk

import pytest

from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.series import SeriesView


def pump(root: tk.Misc, *, steps: int = 40) -> None:
    for _ in range(steps):
        root.update_idletasks()
        root.update()


def wait_for_viewer(view: SeriesView, *, timeout_s: float = 10.0) -> ImageViewer:
    """Pump until the deferred load builds the viewer and completes its first paint."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        pump(view, steps=10)
        viewer = getattr(view, "image_viewer", None)
        if viewer is not None and viewer._startup_complete:
            return viewer
        time.sleep(0.01)
    raise AssertionError(f"SeriesView never finished startup (loading={view._loading})")


def settle(view: SeriesView, *, timeout_s: float = 6.0) -> None:
    """Pump until the image size and window geometry stop changing."""
    slice_s = 0.04
    required_stable = 3
    viewer = wait_for_viewer(view)
    deadline = time.monotonic() + timeout_s
    stable = 0
    last: tuple | None = None
    while time.monotonic() < deadline:
        pump(view, steps=4)
        time.sleep(slice_s)
        pump(view, steps=4)
        current = (viewer.current_size, view.winfo_width(), view.winfo_height())
        if current == last:
            stable += 1
            if stable >= required_stable:
                return
        else:
            stable = 0
            last = current


def drag_window(
    view: SeriesView,
    target: tuple[int, int],
    *,
    steps: int = 24,
    step_delay_s: float = 0.01,
) -> list[tuple[int, int]]:
    """Resize in small increments like a real window-edge drag.

    Returns the display size observed after each increment. A single ``geometry()``
    jump emits one Configure and therefore cannot reproduce the starvation a
    cancel-and-re-arm debounce suffers when events arrive faster than its delay.
    """
    start_w, start_h = view.winfo_width(), view.winfo_height()
    target_w, target_h = target
    observed: list[tuple[int, int]] = []
    for step in range(1, steps + 1):
        fraction = step / steps
        width = round(start_w + (target_w - start_w) * fraction)
        height = round(start_h + (target_h - start_h) * fraction)
        view.geometry(f"{width}x{height}")
        pump(view, steps=2)
        time.sleep(step_delay_s)
        pump(view, steps=2)
        observed.append(view.image_viewer.current_size)
    return observed


def aspect(size: tuple[int, int]) -> float:
    return size[0] / size[1]


def native_size(viewer: ImageViewer) -> tuple[int, int]:
    return viewer.image_width, viewer.image_height


def assert_pixmap_matches_display(viewer: ImageViewer) -> None:
    """The rendered pixmap and the canvas widget must both match the display size.

    The pixmap check is the load-bearing one: ``canvas`` width/height and
    ``current_size`` are both written by ``set_display_size``, so comparing only those
    two would pass even when the painted frame is stale.
    """
    assert viewer.photo_image is not None, "no frame has been painted"
    pixmap = (viewer.photo_image.width(), viewer.photo_image.height())
    assert pixmap == viewer.current_size, f"stale pixmap {pixmap} for display {viewer.current_size}"
    # Requested size, which the canvas reports whether or not it has been mapped yet.
    requested = (viewer.canvas.winfo_reqwidth(), viewer.canvas.winfo_reqheight())
    assert requested == viewer.current_size, f"canvas {requested} does not match display {viewer.current_size}"
    if viewer.canvas.winfo_ismapped():
        allocated = (viewer.canvas.winfo_width(), viewer.canvas.winfo_height())
        assert allocated == viewer.current_size, f"mapped canvas {allocated} != display {viewer.current_size}"


def chrome_report(viewer: ImageViewer) -> str:
    if viewer.data_frame is None:
        return "no data_frame"
    panel = (viewer.data_frame.winfo_width(), viewer.data_frame.winfo_height())
    rows = [f"panel={panel[0]}x{panel[1]}"]
    for child in viewer._rhs_children():
        rows.append(
            f"{type(child).__name__} at ({child.winfo_x()},{child.winfo_y()}) "
            f"req={child.winfo_reqwidth()}x{child.winfo_reqheight()}"
        )
    return " | ".join(rows)


def assert_chrome_unclipped(viewer: ImageViewer) -> None:
    """Every RHS widget must fit inside the panel on BOTH axes.

    A height-only check passes while the playback controls are clipped horizontally.
    """
    assert viewer.chrome_fully_visible(), chrome_report(viewer)


def assert_aspect_preserved(viewer: ImageViewer, *, tol: float = 0.02) -> None:
    native = native_size(viewer)
    display = viewer.current_size
    assert aspect(display) == pytest.approx(aspect(native), rel=tol), (
        f"aspect {aspect(display):.4f} of {display} != native {aspect(native):.4f} of {native}"
    )


def open_series_view(tk_root: tk.Tk, controller, series_path) -> SeriesView:
    """Open a SeriesView through the production startup path and let it settle."""
    from anonymizer.controller.series_io import load_series_frames

    view = SeriesView(
        tk_root,
        controller=controller,
        series_path=series_path,
        preloaded=load_series_frames(series_path),
    )
    settle(view)
    return view
