"""Inference entry points for XR body-part classification.

Public API
----------
XpBodypartPrediction
    Softmax prediction from Xp-Bodypart-Checker.

predict_body_part_from_array(pixels: np.ndarray) -> XpBodypartPrediction
    Classify a 2-D (or single-frame) radiograph array.

predict_body_part(pixels: np.ndarray) -> XpBodypartPrediction | None
    Classify pixels; return None on failure (caller falls back to DICOM).
"""
import logging
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F

from anonymizer.controller.ai.harmonize.xp_bodypart.cache import MODEL_SLOT, XP_BODYPART_WEIGHT_PATH, xp_bodypart_ready
from anonymizer.controller.ai.harmonize.xp_bodypart.labels import XP_BODYPART_LABELS
from anonymizer.controller.ai.harmonize.xp_bodypart.model import XpBodypartNet, load_xp_bodypart_weights
from anonymizer.controller.ai.harmonize.xp_bodypart.preprocess import tensor_from_grayscale_array

logger = logging.getLogger(__name__)



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
    return MODEL_SLOT.get(XP_BODYPART_WEIGHT_PATH.resolve(), load_xp_bodypart_weights)


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
