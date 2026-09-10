"""Inference entry points for XR body-part classification."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from anonymizer.controller.ai.harmonize.xp_bodypart.cache import (
    XP_BODYPART_WEIGHT_PATH,
    xp_bodypart_ready,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.labels import XP_BODYPART_LABELS
from anonymizer.controller.ai.harmonize.xp_bodypart.model import XpBodypartNet, load_xp_bodypart_weights
from anonymizer.controller.ai.harmonize.xp_bodypart.preprocess import tensor_from_grayscale_array

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_cached_model: XpBodypartNet | None = None
_cached_path: Path | None = None


@dataclass(frozen=True)
class XpBodypartPrediction:
    """Softmax prediction from Xp-Bodypart-Checker."""

    label: str
    confidence: float
    probs: tuple[float, ...]

    @property
    def incomplete_chest(self) -> bool:
        return self.label == "Incomplete Chest"


def _get_model() -> XpBodypartNet:
    global _cached_model, _cached_path
    path = XP_BODYPART_WEIGHT_PATH.resolve()
    with _model_lock:
        if _cached_model is not None and _cached_path == path:
            return _cached_model
        if not path.is_file():
            raise FileNotFoundError(f"Xp bodypart weights missing: {path}")
        logger.info("Loading Xp bodypart weights from %s", path)
        _cached_model = load_xp_bodypart_weights(path)
        _cached_path = path
        return _cached_model


def clear_model_cache() -> None:
    """Drop in-memory weights (after remove/download)."""
    global _cached_model, _cached_path
    with _model_lock:
        _cached_model = None
        _cached_path = None


def predict_body_part_from_array(pixels: np.ndarray) -> XpBodypartPrediction:
    """Classify a 2-D (or single-frame) radiograph array."""
    if not xp_bodypart_ready():
        raise FileNotFoundError("Xp bodypart models are not installed")
    batch = tensor_from_grayscale_array(pixels)
    model = _get_model()
    with torch.no_grad():
        outputs = model(batch)
        logits = outputs["label_bodypart"]
        probs = F.softmax(logits, dim=1)[0].cpu().numpy()
    idx = int(probs.argmax())
    return XpBodypartPrediction(
        label=XP_BODYPART_LABELS[idx],
        confidence=float(probs[idx]),
        probs=tuple(float(p) for p in probs),
    )


def predict_body_part(pixels: np.ndarray) -> XpBodypartPrediction | None:
    """Classify pixels; return None on failure (caller falls back to DICOM)."""
    try:
        return predict_body_part_from_array(pixels)
    except Exception:
        logger.warning("Xp bodypart inference failed", exc_info=True)
        return None
