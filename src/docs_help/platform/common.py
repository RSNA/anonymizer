"""Shared settle / normalize helpers for help screenshot grabs (OS-agnostic)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageGrab, ImageStat

logger = logging.getLogger(__name__)

# Docs display: keep UI text readable by capping width after a crisp capture.
DOCS_SHOT_MAX_WIDTH = 1400
_MIN_MEAN_BRIGHTNESS = 12.0


def screen_capture_available() -> bool:
    """Return True when the OS allows a full-screen grab."""
    try:
        image = ImageGrab.grab()
        return image is not None and image.size[0] > 0
    except Exception as exc:
        logger.warning("Screen capture probe failed: %s", exc)
        return False


def settle(widget: Any, ms: int = 400) -> None:
    """Pump Tk events so layout and paints complete before capture."""
    widget.update_idletasks()
    widget.update()
    deadline = time.monotonic() + (ms / 1000.0)
    while time.monotonic() < deadline:
        widget.update_idletasks()
        widget.update()
        time.sleep(0.02)


def wait_mapped(widget: Any, timeout_ms: int = 1500) -> None:
    """Wait briefly until a widget is mapped — never use Tk wait_visibility.

    ``wait_visibility`` can block forever on macOS/Tcl when VisibilityNotify
    never arrives for an already-mapped root or CTk toplevel.
    """
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        try:
            if int(widget.winfo_ismapped()) and int(widget.winfo_viewable()):
                return
        except Exception:
            return
        try:
            widget.update_idletasks()
            widget.update()
        except Exception:
            return
        time.sleep(0.02)


def placeholder(dest: Path, label: str, size: tuple[int, int] = (960, 640)) -> Path:
    """Write a labeled stand-in PNG when real screen capture is unavailable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color=(245, 245, 245))
    draw = ImageDraw.Draw(image)
    text = f"PLACEHOLDER\n{label}\n(enable Screen Recording / DISPLAY)"
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(180, 40, 40), width=3)
    draw.multiline_text((40, 40), text, fill=(40, 40, 40), spacing=6)
    image.save(dest)
    return dest


def display_scale(widget: Any) -> float:
    """Physical pixels per Tk point (≈2.0 on macOS Retina)."""
    try:
        screen_w = max(int(widget.winfo_screenwidth()), 1)
        full = ImageGrab.grab()
        if full is not None and full.size[0] > 0:
            return max(full.size[0] / float(screen_w), 1.0)
    except Exception as exc:
        logger.debug("display scale probe failed: %s", exc)
    return 1.0


def widget_logical_bbox(widget: Any) -> tuple[int, int, int, int]:
    x1 = int(widget.winfo_rootx())
    y1 = int(widget.winfo_rooty())
    width = int(widget.winfo_width())
    height = int(widget.winfo_height())
    if width < 2 or height < 2:
        width = max(width, int(widget.winfo_reqwidth()))
        height = max(height, int(widget.winfo_reqheight()))
    return x1, y1, x1 + width, y1 + height


def scaled_bbox(bbox: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 * scale)),
        int(round(y1 * scale)),
        int(round(x2 * scale)),
        int(round(y2 * scale)),
    )


def mean_brightness(image: Image.Image) -> float:
    rgb = image.convert("RGB")
    stat = ImageStat.Stat(rgb)
    return float(sum(stat.mean) / 3.0)


def is_blank_capture(image: Image.Image) -> bool:
    if image.size[0] < 8 or image.size[1] < 8:
        return True
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return True
        image = image.crop(bbox)
    return mean_brightness(image) < _MIN_MEAN_BRIGHTNESS


def trim_transparent(image: Image.Image) -> Image.Image:
    """Crop to the opaque content bbox so docs don’t get huge transparent padding."""
    if image.mode != "RGBA":
        return image
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def to_logical_size(image: Image.Image, scale: float) -> Image.Image:
    """Convert Retina/physical pixels to Tk logical points (1 PNG px ≈ 1 UI pt)."""
    if scale <= 1.05:
        return image
    w, h = image.size
    new_size = (max(1, int(round(w / scale))), max(1, int(round(h / scale))))
    if new_size == (w, h):
        return image
    return image.resize(new_size, Image.Resampling.LANCZOS)


def normalize_for_docs(image: Image.Image) -> Image.Image:
    """Cap extremely wide shots so help pages stay readable on typical viewports."""
    w, h = image.size
    if w <= DOCS_SHOT_MAX_WIDTH:
        return image
    ratio = DOCS_SHOT_MAX_WIDTH / float(w)
    new_size = (DOCS_SHOT_MAX_WIDTH, max(1, int(round(h * ratio))))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def capture_bbox_imagegrab(bbox: tuple[int, int, int, int]) -> Image.Image:
    """Rectangular grab via PIL ImageGrab (cross-platform fallback)."""
    x1, y1, x2, y2 = bbox
    try:
        image = ImageGrab.grab(bbox=bbox)
        if image is not None and not is_blank_capture(image):
            return image
    except Exception as exc:
        logger.debug("bbox grab failed %s: %s", bbox, exc)

    full = ImageGrab.grab()
    if full is None:
        raise RuntimeError("ImageGrab.grab() returned None")
    fx2, fy2 = full.size
    crop_box = (
        max(0, min(x1, fx2 - 1)),
        max(0, min(y1, fy2 - 1)),
        max(1, min(x2, fx2)),
        max(1, min(y2, fy2)),
    )
    return full.crop(crop_box)


def union_logical_bbox(*widgets: Any) -> tuple[int, int, int, int]:
    """Axis-aligned union of widget screen bboxes (Tk logical points)."""
    boxes = [widget_logical_bbox(w) for w in widgets if w is not None]
    if not boxes:
        raise RuntimeError("union_logical_bbox requires at least one widget")
    x1 = min(b[0] for b in boxes)
    y1 = min(b[1] for b in boxes)
    x2 = max(b[2] for b in boxes)
    y2 = max(b[3] for b in boxes)
    return x1, y1, x2, y2


def close_toplevel(widget: Any) -> None:
    """Best-effort close of a modal/non-modal toplevel after capture."""
    try:
        from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

        teardown_ctk_toplevel(widget, parent=getattr(widget, "master", None))
        return
    except Exception:
        pass
    try:
        widget.grab_release()
    except Exception:
        pass
    try:
        widget.destroy()
    except Exception:
        pass


def save_docs_png(dest: Path, image: Image.Image) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if image.mode == "RGBA":
        image.save(dest, format="PNG")
    else:
        image.save(dest)
    return dest
