"""FALCON evaluation helpers: model-input visualization and artifact PNG export."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from prototyping.falcon.predict import (
    BODY_PART_MODEL_INPUT_Z_INDEX,
    _get_contrast_slices,
    extract_body_part_model_input_slice,
    extract_contrast_model_input_slice,
)

__all__ = (
    "BODY_PART_MODEL_INPUT_Z_INDEX",
    "contrast_model_input_z_index",
    "render_body_part_model_input_thumbnail",
    "render_model_input_slice_thumbnail",
    "save_body_part_model_input_png",
    "save_contrast_model_input_png",
    "save_model_input_slice_png",
)


def contrast_model_input_z_index(body_part: str) -> int:
    """Absolute z index in a preprocessed volume for the contrast model's 2D input."""
    slice_range, slice_idx = _get_contrast_slices(body_part)
    return slice_range.start + slice_idx


def _truncate_text_to_width(text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont, max_width: int) -> str:
    if not text:
        return text
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    trimmed = text
    while trimmed and draw.textlength(trimmed + ellipsis, font=font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + ellipsis) if trimmed else ellipsis


def _annotate_model_input_png(image: Image.Image, title: str) -> Image.Image:
    """Draw a compact top-left title that fits within the image width."""
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    margin = 4
    padding = 2
    line_spacing = 1
    max_text_width = image.width - (2 * margin) - (2 * padding)
    lines = [_truncate_text_to_width(line, font, max_text_width) for line in title.splitlines() if line]
    if not lines:
        return image

    line_heights = []
    line_widths = []
    for line in lines:
        text_bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(text_bbox[2] - text_bbox[0])
        line_heights.append(text_bbox[3] - text_bbox[1])

    box_width = max(line_widths) + (2 * padding)
    box_height = sum(line_heights) + ((len(lines) - 1) * line_spacing) + (2 * padding)
    box = (
        margin,
        margin,
        margin + box_width,
        margin + box_height,
    )
    draw.rectangle(box, fill=(0, 0, 0))

    text_y = margin + padding
    for line, line_height in zip(lines, line_heights, strict=True):
        draw.text((margin + padding, text_y), line, fill=(255, 220, 0), font=font)
        text_y += line_height + line_spacing

    return image


def render_model_input_slice_thumbnail(
    slice_2d: np.ndarray,
    *,
    title: str | None = None,
    size: int | None = None,
) -> Image.Image:
    """Render a normalized model-input slice as a thumbnail, optionally annotated."""
    png_pixels = (np.clip(slice_2d, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    if title:
        image = _annotate_model_input_png(Image.fromarray(png_pixels).convert("RGB"), title)
    else:
        image = Image.fromarray(png_pixels)
    if size is not None:
        image = image.resize((size, size))
    return image


def render_body_part_model_input_thumbnail(
    image_np: np.ndarray,
    *,
    title: str | None = None,
    size: int | None = None,
) -> Image.Image:
    """Render the body-part model's normalized 2D input as an annotated thumbnail."""
    return render_model_input_slice_thumbnail(
        extract_body_part_model_input_slice(image_np),
        title=title,
        size=size,
    )


def save_model_input_slice_png(
    slice_2d: np.ndarray,
    output_path: Path,
    *,
    title: str | None = None,
) -> Path:
    """Write a normalized model-input slice as PNG, optionally with a top-left title."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_model_input_slice_thumbnail(slice_2d, title=title).save(output_path)
    return output_path


def save_body_part_model_input_png(
    image_np: np.ndarray,
    output_path: Path,
    *,
    title: str | None = None,
) -> Path:
    """Write the body-part model's normalized 2D input as an 8-bit PNG."""
    return save_model_input_slice_png(
        extract_body_part_model_input_slice(image_np),
        output_path,
        title=title,
    )


def save_contrast_model_input_png(
    image_np: np.ndarray,
    body_part: str,
    output_path: Path,
    *,
    title: str | None = None,
) -> Path:
    """Write the contrast model's normalized 2D input as an 8-bit PNG."""
    return save_model_input_slice_png(
        extract_contrast_model_input_slice(image_np, body_part),
        output_path,
        title=title,
    )
