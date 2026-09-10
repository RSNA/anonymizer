"""Preprocess radiograph pixels for Xp-Bodypart-Checker (256 pad + normalize)."""

from __future__ import annotations

import numpy as np
import torch
import torchvision.transforms as T
from PIL import Image

_IMAGE_SIZE = 256
_TO_TENSOR = T.Compose(
    [
        T.ToTensor(),
        T.Normalize(mean=(0.5,), std=(0.5,)),
    ]
)


def uint8_grayscale_from_array(pixels: np.ndarray) -> np.ndarray:
    """Convert DICOM/numpy pixels to 2-D uint8 grayscale."""
    arr = np.asarray(pixels)
    if arr.ndim == 3:
        # (frames, H, W) or (H, W, C)
        if arr.shape[-1] in {3, 4} and arr.shape[0] > 4:
            arr = arr[..., 0]
        elif arr.shape[0] in {3, 4} and arr.shape[-1] > 4:
            arr = arr[0]
        else:
            arr = arr[0]
    if arr.ndim != 2:
        raise ValueError(f"Expected 2-D radiograph pixels, got shape {arr.shape}")
    if arr.dtype == np.uint8:
        return arr
    flat = arr.astype(np.float64, copy=False)
    lo = float(np.min(flat))
    hi = float(np.max(flat))
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (flat - lo) / (hi - lo) * 255.0
    return scaled.astype(np.uint8)


def pad_to_square_256(image: Image.Image) -> Image.Image:
    """Longest side → 256; black-pad shorter side to 256×256 (paper preprocess)."""
    image = image.convert("L")
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Empty image")
    scale = _IMAGE_SIZE / float(max(width, height))
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    resized = image.resize((new_w, new_h), Image.Resampling.BILINEAR)
    canvas = Image.new("L", (_IMAGE_SIZE, _IMAGE_SIZE), color=0)
    left = (_IMAGE_SIZE - new_w) // 2
    top = (_IMAGE_SIZE - new_h) // 2
    canvas.paste(resized, (left, top))
    return canvas


def tensor_from_grayscale_array(pixels: np.ndarray) -> torch.Tensor:
    """Return batch tensor ``[1, 1, 256, 256]`` ready for EfficientNet-B4."""
    gray = uint8_grayscale_from_array(pixels)
    pil = pad_to_square_256(Image.fromarray(gray, mode="L"))
    return _TO_TENSOR(pil).unsqueeze(0)
