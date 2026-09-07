"""OS detection and window-grab dispatch for MkDocs help screenshots."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageGrab

from docs_help.platform import common
from docs_help.platform.common import (
    close_toplevel,
    display_scale,
    is_blank_capture,
    mean_brightness,
    normalize_for_docs,
    placeholder,
    save_docs_png,
    scaled_bbox,
    screen_capture_available,
    settle,
    to_logical_size,
    trim_transparent,
    union_logical_bbox,
    wait_mapped,
    widget_logical_bbox,
)

logger = logging.getLogger(__name__)

CaptureOs = Literal["macos", "windows"]

# Re-export shared helpers for callers that historically imported from grab.
DOCS_SHOT_MAX_WIDTH = common.DOCS_SHOT_MAX_WIDTH

__all__ = [
    "CaptureOs",
    "DOCS_SHOT_MAX_WIDTH",
    "close_toplevel",
    "detect_os",
    "display_scale",
    "grab_stacked_windows",
    "grab_widget",
    "grab_widgets_union",
    "normalize_for_docs",
    "require_host_platform",
    "screen_capture_available",
    "settle",
    "to_logical_size",
    "trim_transparent",
    "union_logical_bbox",
    "wait_mapped",
]


def detect_os() -> CaptureOs:
    """Return the capture OS key for this host."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    raise RuntimeError(
        f"Help screenshot capture supports macOS and Windows only (sys.platform={sys.platform!r})"
    )


def require_host_platform(requested: str | None) -> CaptureOs:
    """Resolve ``auto|macos|windows`` against the host; refuse cross-OS capture."""
    host = detect_os()
    if requested is None or requested == "auto":
        return host
    if requested not in {"macos", "windows"}:
        raise ValueError(f"Unknown platform {requested!r}")
    if requested != host:
        raise RuntimeError(
            f"Cannot capture platform={requested!r} on host={host!r}; "
            "run capture on the matching OS so window chrome is authentic."
        )
    return host


def _backend():
    host = detect_os()
    if host == "macos":
        from docs_help.platform import macos as backend
    else:
        from docs_help.platform import windows as backend
    return backend


def grab_widget(
    widget: Any,
    dest: Path,
    *,
    settle_ms: int = 400,
    allow_placeholder: bool = False,
    shot_id: str | None = None,
    geometry: str | None = None,
) -> Path:
    """Capture a Tk/CTk toplevel (or root) and write PNG (RGBA on macOS when possible)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    backend = _backend()
    try:
        widget.deiconify()
    except Exception:
        pass
    if geometry:
        try:
            widget.geometry(geometry)
        except Exception:
            pass
    try:
        widget.lift()
        widget.attributes("-topmost", True)
        widget.focus_force()
    except Exception:
        pass
    settle(widget, settle_ms)

    label = shot_id or dest.stem
    last_error: Exception | None = None
    image: Image.Image | None = None

    wait_mapped(widget, timeout_ms=max(settle_ms, 1000))
    settle(widget, settle_ms)

    try:
        for attempt in range(3):
            if attempt:
                settle(widget, settle_ms)
                try:
                    widget.lift()
                    widget.attributes("-topmost", True)
                    widget.focus_force()
                except Exception:
                    pass
            try:
                image = backend.capture_window(widget, dest, label)
                if image is not None and not is_blank_capture(image):
                    break

                logical = widget_logical_bbox(widget)
                x1, y1, x2, y2 = logical
                if x2 <= x1 or y2 <= y1:
                    raise RuntimeError(f"Invalid capture bbox for {widget}: {logical}")
                scale = display_scale(widget)
                bboxes = [logical]
                if scale > 1.05:
                    bboxes.append(scaled_bbox(logical, scale))
                candidate = None
                for bbox in bboxes:
                    logger.info(
                        "Grab %s attempt=%s bbox=%s scale=%.2f → %s",
                        label,
                        attempt + 1,
                        bbox,
                        scale,
                        dest,
                    )
                    candidate = backend.capture_bbox(bbox, dest)
                    if not is_blank_capture(candidate):
                        break
                    logger.warning(
                        "Blank/dark capture for %s bbox=%s (mean=%.1f)",
                        label,
                        bbox,
                        mean_brightness(candidate),
                    )
                if candidate is not None and not is_blank_capture(candidate):
                    image = candidate
                    break
                try:
                    full = None
                    if detect_os() == "macos":
                        from docs_help.platform.macos import capture_via_screencapture_cli

                        full = capture_via_screencapture_cli(dest)
                    if full is None:
                        full = ImageGrab.grab()
                    if full is not None and not is_blank_capture(full):
                        fx2, fy2 = full.size
                        crop = (
                            max(0, min(int(x1 * scale), fx2 - 1)),
                            max(0, min(int(y1 * scale), fy2 - 1)),
                            max(1, min(int(x2 * scale), fx2)),
                            max(1, min(int(y2 * scale), fy2)),
                        )
                        candidate = full.crop(crop)
                        if not is_blank_capture(candidate):
                            image = candidate
                            break
                except Exception as full_exc:
                    logger.warning("Full-screen fallback failed for %s: %s", label, full_exc)
                image = candidate
            except Exception as exc:
                last_error = exc
                logger.warning("Grab attempt %s failed for %s: %s", attempt + 1, label, exc)
    finally:
        try:
            widget.attributes("-topmost", False)
        except Exception:
            pass

    if image is None or is_blank_capture(image):
        if allow_placeholder:
            logger.warning("Writing placeholder PNG for %s", label)
            w = max(int(widget.winfo_width()), 320)
            h = max(int(widget.winfo_height()), 240)
            return placeholder(dest, label, size=(w, h))
        detail = f" last_error={last_error}" if last_error else ""
        raise RuntimeError(
            f"Screen capture produced a blank image for {label}.{detail} "
            "Grant screen capture permission, ensure the window is visible, then re-run."
        )

    scale = display_scale(widget)
    image = to_logical_size(image, scale)
    image = normalize_for_docs(image)
    logger.info(
        "Saved %s mode=%s size=%s (display_scale=%.2f) → %s",
        label,
        image.mode,
        image.size,
        scale,
        dest,
    )
    return save_docs_png(dest, image)


def grab_stacked_windows(
    base: Any,
    overlay: Any,
    dest: Path,
    *,
    settle_ms: int = 400,
    allow_placeholder: bool = False,
    shot_id: str | None = None,
    overlay_offset: tuple[int, int] = (80, 100),
) -> Path:
    """Capture two toplevels via window grabs and composite (no desktop bleed-through)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    backend = _backend()
    label = shot_id or dest.stem
    for widget in (base, overlay):
        try:
            widget.deiconify()
            widget.lift()
            widget.attributes("-topmost", True)
        except Exception:
            pass
    settle(base, settle_ms)
    settle(overlay, settle_ms // 2)

    base_img = backend.capture_window(base, dest, f"{label}:base")
    overlay_img = backend.capture_window(overlay, dest, f"{label}:overlay")
    if base_img is None or is_blank_capture(base_img):
        return grab_widget(
            base,
            dest,
            settle_ms=settle_ms,
            allow_placeholder=allow_placeholder,
            shot_id=shot_id,
        )
    if overlay_img is None or is_blank_capture(overlay_img):
        image = to_logical_size(base_img, display_scale(base))
        image = normalize_for_docs(image)
        return save_docs_png(dest, image)

    scale = display_scale(base)
    base_img = to_logical_size(base_img, scale)
    overlay_img = to_logical_size(overlay_img, scale)

    ox, oy = overlay_offset
    canvas_w = max(base_img.size[0], ox + overlay_img.size[0] + 12)
    canvas_h = max(base_img.size[1], oy + overlay_img.size[1] + 12)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (245, 245, 245, 255))
    if base_img.mode != "RGBA":
        base_img = base_img.convert("RGBA")
    if overlay_img.mode != "RGBA":
        overlay_img = overlay_img.convert("RGBA")
    canvas.alpha_composite(base_img, (0, 0))
    canvas.alpha_composite(overlay_img, (ox, oy))
    canvas = normalize_for_docs(canvas)
    logger.info("Saved stacked %s size=%s → %s", label, canvas.size, dest)
    for widget in (base, overlay):
        try:
            widget.attributes("-topmost", False)
        except Exception:
            pass
    return save_docs_png(dest, canvas)


def grab_widgets_union(
    widgets: list[Any],
    dest: Path,
    *,
    settle_ms: int = 400,
    allow_placeholder: bool = False,
    shot_id: str | None = None,
    pad_px: int = 12,
) -> Path:
    """Capture the screen region covering several stacked windows (parent + dialogs)."""
    live = [w for w in widgets if w is not None]
    if not live:
        raise RuntimeError("grab_widgets_union requires at least one widget")
    dest.parent.mkdir(parents=True, exist_ok=True)
    backend = _backend()
    primary = live[0]
    for widget in live:
        try:
            widget.deiconify()
            widget.lift()
        except Exception:
            pass
    settle(primary, settle_ms)
    for widget in live:
        wait_mapped(widget, timeout_ms=max(settle_ms, 1000))
    settle(primary, settle_ms)

    label = shot_id or dest.stem
    logical = union_logical_bbox(*live)
    x1, y1, x2, y2 = logical
    x1 = max(0, x1 - pad_px)
    y1 = max(0, y1 - pad_px)
    x2 = x2 + pad_px
    y2 = y2 + pad_px
    scale = display_scale(primary)
    bboxes = [(x1, y1, x2, y2)]
    if scale > 1.05:
        bboxes.append(scaled_bbox((x1, y1, x2, y2), scale))

    image: Image.Image | None = None
    last_error: Exception | None = None
    for attempt in range(3):
        if attempt:
            settle(primary, settle_ms)
        for bbox in bboxes:
            try:
                logger.info("Grab union %s attempt=%s bbox=%s → %s", label, attempt + 1, bbox, dest)
                candidate = backend.capture_bbox(bbox, dest)
                if not is_blank_capture(candidate):
                    image = candidate
                    break
                image = candidate
            except Exception as exc:
                last_error = exc
                logger.warning("Union grab failed for %s: %s", label, exc)
        if image is not None and not is_blank_capture(image):
            break

    if image is None or is_blank_capture(image):
        try:
            logger.warning("Union grab blank for %s — falling back to primary widget", label)
            return grab_widget(
                primary,
                dest,
                settle_ms=settle_ms,
                allow_placeholder=allow_placeholder,
                shot_id=shot_id,
            )
        except Exception as fallback_exc:
            if allow_placeholder:
                return placeholder(dest, label)
            detail = f" last_error={last_error} fallback={fallback_exc}"
            raise RuntimeError(f"Union screen capture blank for {label}.{detail}") from fallback_exc

    image = to_logical_size(image, scale)
    image = normalize_for_docs(image)
    logger.info("Saved union %s mode=%s size=%s → %s", label, image.mode, image.size, dest)
    return save_docs_png(dest, image)
