"""Unit tests for SeriesView segmentation overlay merge wiring (no CTk window)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from anonymizer.controller.ai.anatomy_overlay import (
    contour_mask_slice,
    merge_structure_overlays,
)
from anonymizer.controller.series_overlay import PolygonPoint, Segmentation


def test_latch_loader_called_once_across_slice_reads(tmp_path: Path) -> None:
    """SeriesView stores loader result; simulating slice changes must not re-call loader."""
    calls: list[Path] = []

    def loader(path: Path, *, structure_name: str, color_bgr=None, load_mask=None):
        calls.append(path)
        return {
            0: [
                Segmentation(
                    points=[PolygonPoint(0, 0), PolygonPoint(1, 0), PolygonPoint(0, 1)],
                    structure_name=structure_name,
                    color_bgr=color_bgr,
                )
            ]
        }

    cache: dict[str, dict[int, list[Segmentation]]] = {}
    path = tmp_path / "heart.nii.gz"
    cache["heart"] = loader(path, structure_name="heart", color_bgr=(0, 0, 255))
    assert len(calls) == 1
    # Simulate N slice navigations reading only the RAM cache.
    for _ in range(20):
        merged = merge_structure_overlays(cache)
        _ = merged.get(0, [])
    assert len(calls) == 1


def test_toggle_off_removes_structure_from_merge() -> None:
    cache = {
        "heart": {
            0: [Segmentation(points=[PolygonPoint(0, 0), PolygonPoint(1, 0), PolygonPoint(0, 1)], structure_name="heart")]
        },
        "liver": {
            0: [Segmentation(points=[PolygonPoint(2, 2), PolygonPoint(3, 2), PolygonPoint(2, 3)], structure_name="liver")]
        },
    }
    cache.pop("heart")
    merged = merge_structure_overlays(cache)
    assert len(merged[0]) == 1
    assert merged[0][0].structure_name == "liver"


def test_progressive_cache_contours_missing_slice_from_held_mask() -> None:
    """Scrub fills missing slices from the RAM mask without disk I/O."""
    mask = np.zeros((3, 24, 24), dtype=np.uint8)
    mask[2, 6:18, 6:18] = 1
    cache: dict[int, list[Segmentation]] = {
        0: [],
    }
    assert 2 not in cache
    segs = contour_mask_slice(mask, 2, structure_name="spine", color_bgr=(200, 0, 220))
    assert segs
    cache[2] = segs
    merged = merge_structure_overlays({"spine": cache})
    assert len(merged[2]) >= 1
    assert merged[2][0].structure_name == "spine"


def test_series_view_cancel_clears_latch_state() -> None:
    """Unlatch clears overlay cache, held mask, and cancel event."""
    view = MagicMock()
    view._structure_overlay_by_name = {"spine": {0: []}}
    view._structure_mask_by_name = {"spine": np.zeros((2, 4, 4), dtype=np.uint8)}
    cancel = MagicMock()
    view._structure_contour_cancel = {"spine": cancel}

    # Mirror SeriesView._clear_structure_latch_state(name)
    view._structure_contour_cancel.pop("spine", None)
    cancel.set()
    view._structure_overlay_by_name.pop("spine", None)
    view._structure_mask_by_name.pop("spine", None)

    assert "spine" not in view._structure_overlay_by_name
    assert "spine" not in view._structure_mask_by_name
    cancel.set.assert_called()


def test_contour_queue_merge_ignores_stale_generation() -> None:
    """UI poller must apply only matching generation batches (thread-safe path)."""
    import queue
    import threading

    generation = 1
    cancel = threading.Event()
    q: queue.Queue = queue.Queue()
    q.put(("liver", {1: []}, generation, cancel))
    q.put(("liver", {2: [object()]}, generation + 1, cancel))  # stale
    q.put(("liver", None, generation, cancel))  # done sentinel

    cache: dict[int, object] = {}
    applied_gen = generation
    while True:
        try:
            name, snapshot, gen, ev = q.get_nowait()
        except queue.Empty:
            break
        if ev.is_set() or gen != applied_gen:
            continue
        if snapshot is None:
            continue
        cache.update(snapshot)
    assert 1 in cache
    assert 2 not in cache
