"""2D brush stamping and undo patches for annotation sessions."""

from __future__ import annotations

import numpy as np

from anonymizer.controller.annotations.store import AnnotateSession, PaintTargetKind, StrokeUndo

UNDO_LIMIT = 20


def _disk_coords(cy: int, cx: int, radius: int, h: int, w: int) -> tuple[slice, slice, np.ndarray]:
    r = max(1, int(radius))
    y0 = max(0, cy - r)
    y1 = min(h, cy + r + 1)
    x0 = max(0, cx - r)
    x1 = min(w, cx + r + 1)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r
    return slice(y0, y1), slice(x0, x1), mask


def stamp_brush(
    volume: np.ndarray,
    *,
    slice_index: int,
    cy: int,
    cx: int,
    radius: int,
    value: int,
) -> tuple[int, int, int, int] | None:
    """Stamp a disk onto ``volume[slice]``. Returns bbox or None if out of range."""
    if slice_index < 0 or slice_index >= volume.shape[0]:
        return None
    plane = volume[slice_index]
    h, w = plane.shape
    ys, xs, disk = _disk_coords(cy, cx, radius, h, w)
    if not np.any(disk):
        return None
    region = plane[ys, xs]
    region[disk] = value
    return ys.start, ys.stop, xs.start, xs.stop


def begin_stroke_capture(volume: np.ndarray, *, slice_index: int) -> np.ndarray:
    """Copy full slice for undo (simple, robust for Phase 1)."""
    if slice_index < 0 or slice_index >= volume.shape[0]:
        return np.zeros((0, 0), dtype=volume.dtype)
    return volume[slice_index].copy()


def commit_stroke_undo(
    session: AnnotateSession,
    *,
    kind: PaintTargetKind,
    structure_name: str | None,
    slice_index: int,
    before_slice: np.ndarray,
) -> None:
    if before_slice.size == 0:
        return
    h, w = before_slice.shape
    session.undo_stack.append(
        StrokeUndo(
            kind=kind,
            structure_name=structure_name,
            slice_index=slice_index,
            y0=0,
            y1=h,
            x0=0,
            x1=w,
            before=before_slice,
        )
    )
    if len(session.undo_stack) > UNDO_LIMIT:
        session.undo_stack.pop(0)
    session.dirty = True


def undo_last_stroke(session: AnnotateSession) -> bool:
    if not session.undo_stack:
        return False
    stroke = session.undo_stack.pop()
    if stroke.kind == "user":
        volume = session.labels
    else:
        name = stroke.structure_name or ""
        volume = session.ts_edits.get(name)
        if volume is None:
            return False
    if stroke.slice_index < 0 or stroke.slice_index >= volume.shape[0]:
        return False
    volume[stroke.slice_index, stroke.y0 : stroke.y1, stroke.x0 : stroke.x1] = stroke.before
    session.dirty = True
    return True
