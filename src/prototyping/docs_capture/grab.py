"""Window grab helpers for help screenshots.

On macOS, prefer ``screencapture -l`` (window ID) so PNGs keep the OS rounded
corners and a real alpha channel. Falls back to rectangular ImageGrab elsewhere.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageGrab, ImageStat

logger = logging.getLogger(__name__)

# Docs display: keep UI text readable by capping width after a crisp capture.
DOCS_SHOT_MAX_WIDTH = 1400
_MIN_MEAN_BRIGHTNESS = 12.0


def screen_capture_available() -> bool:
    """Return True when the OS allows a full-screen grab (macOS Screen Recording, etc.)."""
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


def _placeholder(dest: Path, label: str, size: tuple[int, int] = (960, 640)) -> Path:
    """Write a labeled stand-in PNG when real screen capture is unavailable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color=(245, 245, 245))
    draw = ImageDraw.Draw(image)
    text = f"PLACEHOLDER\n{label}\n(enable Screen Recording / DISPLAY)"
    draw.rectangle((20, 20, size[0] - 20, size[1] - 20), outline=(180, 40, 40), width=3)
    draw.multiline_text((40, 40), text, fill=(40, 40, 40), spacing=6)
    image.save(dest)
    return dest


def _display_scale(widget: Any) -> float:
    """Physical pixels per Tk point (≈2.0 on macOS Retina)."""
    try:
        screen_w = max(int(widget.winfo_screenwidth()), 1)
        full = ImageGrab.grab()
        if full is not None and full.size[0] > 0:
            return max(full.size[0] / float(screen_w), 1.0)
    except Exception as exc:
        logger.debug("display scale probe failed: %s", exc)
    return 1.0


def _widget_logical_bbox(widget: Any) -> tuple[int, int, int, int]:
    x1 = int(widget.winfo_rootx())
    y1 = int(widget.winfo_rooty())
    width = int(widget.winfo_width())
    height = int(widget.winfo_height())
    if width < 2 or height < 2:
        width = max(width, int(widget.winfo_reqwidth()))
        height = max(height, int(widget.winfo_reqheight()))
    return x1, y1, x1 + width, y1 + height


def _scaled_bbox(bbox: tuple[int, int, int, int], scale: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (
        int(round(x1 * scale)),
        int(round(y1 * scale)),
        int(round(x2 * scale)),
        int(round(y2 * scale)),
    )


def _mean_brightness(image: Image.Image) -> float:
    rgb = image.convert("RGB")
    stat = ImageStat.Stat(rgb)
    return float(sum(stat.mean) / 3.0)


def _is_blank_capture(image: Image.Image) -> bool:
    if image.size[0] < 8 or image.size[1] < 8:
        return True
    # Ignore fully transparent exterior when judging blankness.
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return True
        image = image.crop(bbox)
    return _mean_brightness(image) < _MIN_MEAN_BRIGHTNESS


def _trim_transparent(image: Image.Image) -> Image.Image:
    """Crop to the opaque content bbox so docs don’t get huge transparent padding."""
    if image.mode != "RGBA":
        return image
    bbox = image.getchannel("A").getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def _to_logical_size(image: Image.Image, scale: float) -> Image.Image:
    """Convert Retina/physical pixels to Tk logical points (1 PNG px ≈ 1 UI pt).

    Without this, a 2× capture displays ~2× larger than the live app in MkDocs.
    """
    if scale <= 1.05:
        return image
    w, h = image.size
    new_size = (max(1, int(round(w / scale))), max(1, int(round(h / scale))))
    if new_size == (w, h):
        return image
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _normalize_for_docs(image: Image.Image) -> Image.Image:
    """Cap extremely wide shots so help pages stay readable on typical viewports."""
    w, h = image.size
    if w <= DOCS_SHOT_MAX_WIDTH:
        return image
    ratio = DOCS_SHOT_MAX_WIDTH / float(w)
    new_size = (DOCS_SHOT_MAX_WIDTH, max(1, int(round(h * ratio))))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _capture_bbox(bbox: tuple[int, int, int, int]) -> Image.Image:
    x1, y1, x2, y2 = bbox
    try:
        image = ImageGrab.grab(bbox=bbox)
        if image is not None and not _is_blank_capture(image):
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


def _capture_macos_window(widget: Any, dest: Path, label: str) -> Image.Image | None:
    """Prefer OS window capture so rounded corners keep a real alpha channel."""
    if sys.platform != "darwin":
        return None
    try:
        from docs_capture.macos_window import resolve_cg_window_id, screencapture_window
    except Exception as exc:
        logger.debug("macos_window import failed: %s", exc)
        return None

    window_id = resolve_cg_window_id(widget)
    if window_id is None:
        return None

    tmp = dest.with_suffix(dest.suffix + ".macwin.tmp.png")
    try:
        screencapture_window(window_id, tmp, shadow=False)
        image = Image.open(tmp)
        image.load()
        image = _trim_transparent(image)
        if _is_blank_capture(image):
            logger.warning("macOS window capture blank for %s id=%s", label, window_id)
            return None
        logger.info(
            "Grab %s via screencapture -l %s mode=%s size=%s → %s",
            label,
            window_id,
            image.mode,
            image.size,
            dest,
        )
        return image
    except Exception as exc:
        logger.warning("macOS window capture failed for %s: %s", label, exc)
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


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
                image = _capture_macos_window(widget, dest, label)
                if image is not None and not _is_blank_capture(image):
                    break

                logical = _widget_logical_bbox(widget)
                x1, y1, x2, y2 = logical
                if x2 <= x1 or y2 <= y1:
                    raise RuntimeError(f"Invalid capture bbox for {widget}: {logical}")
                scale = _display_scale(widget)
                bboxes = [logical]
                if scale > 1.05:
                    bboxes.append(_scaled_bbox(logical, scale))
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
                    candidate = _capture_bbox(bbox)
                    if not _is_blank_capture(candidate):
                        break
                    logger.warning(
                        "Blank/dark capture for %s bbox=%s (mean=%.1f)",
                        label,
                        bbox,
                        _mean_brightness(candidate),
                    )
                if candidate is None or _is_blank_capture(candidate):
                    image = candidate
                    continue
                image = candidate
                break
            except Exception as exc:
                last_error = exc
                logger.warning("Grab attempt %s failed for %s: %s", attempt + 1, label, exc)
    finally:
        try:
            widget.attributes("-topmost", False)
        except Exception:
            pass

    if image is None or _is_blank_capture(image):
        if allow_placeholder:
            logger.warning("Writing placeholder PNG for %s", label)
            w = max(int(widget.winfo_width()), 320)
            h = max(int(widget.winfo_height()), 240)
            return _placeholder(dest, label, size=(w, h))
        detail = f" last_error={last_error}" if last_error else ""
        raise RuntimeError(
            f"Screen capture produced a blank image for {label}.{detail} "
            "On macOS, grant Screen Recording to Terminal/Cursor, ensure the window "
            "is visible on-screen, then re-run."
        )

    # Match on-screen app size in the manual (Retina grabs → logical points).
    scale = _display_scale(widget)
    image = _to_logical_size(image, scale)
    image = _normalize_for_docs(image)
    logger.info(
        "Saved %s mode=%s size=%s (display_scale=%.2f) → %s",
        label,
        image.mode,
        image.size,
        scale,
        dest,
    )
    # Keep RGBA so rounded corners stay transparent in the docs site.
    if image.mode == "RGBA":
        image.save(dest, format="PNG")
    else:
        image.save(dest)
    return dest


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
