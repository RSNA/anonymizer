"""Off-screen Series View PNG export when macOS Screen Recording returns black frames.

Builds a docs-faithful composite from the ImageViewer PIL cache (with overlays)
plus a latch-button strip, so Harmonize help shots can still ship without TCC.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from docs_help.platform import DOCS_SHOT_MAX_WIDTH
from docs_help.platform.common import normalize_for_docs as _normalize_for_docs

logger = logging.getLogger(__name__)

_BG = (246, 246, 246)
_PANEL = (236, 236, 236)
_TEXT = (40, 40, 40)
_ACCENT = (31, 106, 165)


def _font(size: int) -> ImageFont.ImageFont:
    for name in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _bgr_to_rgb(color_bgr: tuple[int, int, int]) -> tuple[int, int, int]:
    b, g, r = color_bgr
    return (r, g, b)


def _viewer_frame_pil(series_view: Any) -> Image.Image:
    viewer = series_view.image_viewer
    idx = int(viewer.current_image_index)
    # Force a fresh composite so overlays are in the cached PIL.
    viewer.clear_cache()
    viewer.load_and_display_image(idx)
    series_view.update_idletasks()
    series_view.update()
    if idx not in viewer.image_cache:
        raise RuntimeError(f"ImageViewer cache miss after display for frame {idx}")
    _photo, pil, _size = viewer.image_cache[idx]
    return pil.copy().convert("RGB")


def _draw_round_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    outline: tuple[int, int, int] | None = None,
    radius: int = 8,
    width: int = 2,
) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def export_series_view_docs_shot(series_view: Any, dest: Path) -> Path:
    """Write a Series View help screenshot without relying on Screen Recording."""
    from anonymizer.view.series.anatomy_overlay import (
        color_bgr_for_structure,
        structure_button_label,
    )

    dest.parent.mkdir(parents=True, exist_ok=True)
    viewer = series_view.image_viewer
    frame = _viewer_frame_pil(series_view)
    fw, fh = frame.size

    active = list(viewer.get_active_segmentation_names())
    meta = list(getattr(viewer, "_segmentation_button_meta", {}) or {})
    # Prefer active latches first (brain + detail), then any remaining buttons.
    ordered: list[str] = []
    for name in active:
        if name not in ordered:
            ordered.append(name)
    for name in meta:
        if name not in ordered:
            ordered.append(name)

    left_w = 168
    right_w = 220
    top_h = 36
    bottom_h = 52
    pad = 12
    canvas_w = left_w + fw + right_w + pad * 2
    canvas_h = top_h + max(fh, 420) + bottom_h + pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)
    draw = ImageDraw.Draw(canvas)
    font = _font(13)
    font_sm = _font(11)
    font_title = _font(14)

    title = str(getattr(series_view, "title", lambda: "Series View")())
    if callable(getattr(series_view, "title", None)):
        try:
            title = str(series_view.title())
        except Exception:
            title = "Series View"
    else:
        try:
            title = str(series_view.title()) if hasattr(series_view, "title") else "Series View"
        except Exception:
            title = "Series View"
    try:
        # CTkToplevel stores title via wm_title
        title = series_view.wm_title() or title
    except Exception:
        pass
    draw.text((pad, 10), title[:110], fill=_ACCENT, font=font_title)

    # Left whitelist stub
    _draw_round_rect(draw, (pad, top_h, pad + left_w - 8, canvas_h - bottom_h - 4), fill=_PANEL, outline=(210, 210, 210))
    draw.text((pad + 12, top_h + 10), "WHITELIST", fill=_ACCENT, font=font)
    y = top_h + 36
    for label in ("Defaults", "Clear", "Standard"):
        _draw_round_rect(draw, (pad + 12, y, pad + left_w - 20, y + 26), fill=_ACCENT, outline=None, radius=6)
        draw.text((pad + 22, y + 5), label, fill=(255, 255, 255), font=font_sm)
        y += 34

    # Center image
    img_x = pad + left_w
    img_y = top_h + (max(fh, 420) - fh) // 2
    canvas.paste(frame, (img_x, img_y))
    draw.rectangle((img_x - 1, img_y - 1, img_x + fw, img_y + fh), outline=(180, 180, 180))

    # Right segmentation latches
    rx0 = img_x + fw + 8
    _draw_round_rect(
        draw,
        (rx0, top_h, canvas_w - pad, canvas_h - bottom_h - 4),
        fill=_PANEL,
        outline=(210, 210, 210),
    )
    mode = getattr(viewer, "segmentation_mode", None) or "3mm"
    draw.text((rx0 + 10, top_h + 10), f"Segmentation [{mode}]", fill=_TEXT, font=font)
    by = top_h + 40
    bx = rx0 + 10
    max_x = canvas_w - pad - 10
    for name in ordered:
        label = structure_button_label(name)
        color = _bgr_to_rgb(color_bgr_for_structure(name))
        tw = max(52, len(label) * 7 + 16)
        if bx + tw > max_x:
            bx = rx0 + 10
            by += 32
        if by > canvas_h - bottom_h - 40:
            break
        is_on = name in active
        fill = (255, 255, 255) if is_on else (228, 228, 228)
        outline = color if is_on else (190, 190, 190)
        _draw_round_rect(draw, (bx, by, bx + tw, by + 24), fill=fill, outline=outline, radius=6, width=2)
        draw.text((bx + 8, by + 4), label, fill=_TEXT if is_on else (120, 120, 120), font=font_sm)
        bx += tw + 6

    # Bottom status
    n = int(getattr(viewer, "num_images", 0) or 0)
    idx = int(getattr(viewer, "current_image_index", 0) or 0)
    status = f"Pixel PHI: None removed | Harmonized: Brain Ax EarlyArt | Face blur: None"
    draw.text((pad, canvas_h - 34), status, fill=_TEXT, font=font_sm)
    draw.text((canvas_w - 120, canvas_h - 34), f"{idx + 1}/{n}" if n else "", fill=_TEXT, font=font_sm)

    image = _normalize_for_docs(canvas)
    if image.size[0] > DOCS_SHOT_MAX_WIDTH:
        ratio = DOCS_SHOT_MAX_WIDTH / float(image.size[0])
        image = image.resize(
            (DOCS_SHOT_MAX_WIDTH, max(1, int(round(image.size[1] * ratio)))),
            Image.Resampling.LANCZOS,
        )
    image.save(dest, format="PNG")
    logger.info(
        "Exported Series View off-screen shot size=%s segs=%d → %s",
        image.size,
        len(active),
        dest,
    )
    return dest
