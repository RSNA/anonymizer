"""Inference for CXR projection + rotation."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from anonymizer.controller.ai.harmonize.cxp_view.cache import CXP_VIEW_WEIGHT_PATH, cxp_view_ready
from anonymizer.controller.ai.harmonize.cxp_view.labels import (
    CXP_PROJECTION_LABELS,
    CXP_ROTATION_LABELS,
    map_projection_to_playbook_view,
)
from anonymizer.controller.ai.harmonize.cxp_view.model import CxpViewNet, load_cxp_view_weights
from anonymizer.controller.ai.harmonize.cxp_view.preprocess import (
    tensor_from_grayscale_array,
    upright_array,
)

logger = logging.getLogger(__name__)

_HIGH_ROT_CONF = 0.8

_model_lock = threading.Lock()
_cached_model: CxpViewNet | None = None
_cached_path: Path | None = None


@dataclass(frozen=True)
class CxpViewPrediction:
    """Softmax prediction from CXp-Projection-Rotation-Checker."""

    projection: str
    projection_confidence: float
    rotation: str
    rotation_confidence: float
    projection_probs: tuple[float, ...]
    rotation_probs: tuple[float, ...]

    @property
    def playbook_view_code(self) -> str:
        return map_projection_to_playbook_view(self.projection)


def _get_model() -> CxpViewNet:
    global _cached_model, _cached_path
    path = CXP_VIEW_WEIGHT_PATH.resolve()
    with _model_lock:
        if _cached_model is not None and _cached_path == path:
            return _cached_model
        if not path.is_file():
            raise FileNotFoundError(f"CXp view weights missing: {path}")
        logger.info("Loading CXp view weights from %s", path)
        _cached_model = load_cxp_view_weights(path)
        _cached_path = path
        return _cached_model


def clear_model_cache() -> None:
    global _cached_model, _cached_path
    with _model_lock:
        _cached_model = None
        _cached_path = None


def _infer_once(pixels: np.ndarray) -> CxpViewPrediction:
    batch = tensor_from_grayscale_array(pixels)
    model = _get_model()
    with torch.no_grad():
        outputs = model(batch)
        probs_proj = F.softmax(outputs["label_APorPA"], dim=1)[0].cpu().numpy()
        probs_rot = F.softmax(outputs["label_round"], dim=1)[0].cpu().numpy()
    idx_proj = int(probs_proj.argmax())
    idx_rot = int(probs_rot.argmax())
    return CxpViewPrediction(
        projection=CXP_PROJECTION_LABELS[idx_proj],
        projection_confidence=float(probs_proj[idx_proj]),
        rotation=CXP_ROTATION_LABELS[idx_rot],
        rotation_confidence=float(probs_rot[idx_rot]),
        projection_probs=tuple(float(p) for p in probs_proj),
        rotation_probs=tuple(float(p) for p in probs_rot),
    )


def predict_cxp_view_from_array(pixels: np.ndarray) -> CxpViewPrediction:
    """Classify projection + rotation; upright in-memory and re-predict projection when needed."""
    if not cxp_view_ready():
        raise FileNotFoundError("CXp view models are not installed")
    first = _infer_once(pixels)
    if first.rotation == "Upright" or first.rotation_confidence < _HIGH_ROT_CONF:
        return first
    corrected = upright_array(pixels, first.rotation)
    second = _infer_once(corrected)
    # Keep original rotation evidence; use upright-corrected projection.
    return CxpViewPrediction(
        projection=second.projection,
        projection_confidence=second.projection_confidence,
        rotation=first.rotation,
        rotation_confidence=first.rotation_confidence,
        projection_probs=second.projection_probs,
        rotation_probs=first.rotation_probs,
    )


def predict_cxp_view(pixels: np.ndarray) -> CxpViewPrediction | None:
    try:
        return predict_cxp_view_from_array(pixels)
    except Exception:
        logger.warning("CXp view inference failed", exc_info=True)
        return None
