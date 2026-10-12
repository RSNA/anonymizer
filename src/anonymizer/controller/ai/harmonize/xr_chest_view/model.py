"""EfficientNet-B4 dual-head net matching MedicalAILabo CXp MultiNet checkpoint."""

from __future__ import annotations

import logging
from pathlib import Path

import torch
import torch.nn as nn
import torchvision.models as models

from anonymizer.controller.ai.harmonize.cxp_view.labels import (
    CXP_PROJECTION_LABELS,
    CXP_ROTATION_LABELS,
)

logger = logging.getLogger(__name__)


def _efficientnet_b4_classifier_meta() -> tuple[int, float]:
    probe = models.efficientnet_b4(weights=None)
    dropout_p = float(probe.classifier[0].p)
    in_features = int(probe.classifier[1].in_features)
    return in_features, dropout_p


def _head(in_features: int, dropout_p: float, num_outputs: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Dropout(p=dropout_p, inplace=False),
        nn.Linear(in_features, num_outputs),
    )


class CxpViewNet(nn.Module):
    """EfficientNet-B4 + projection (3) and rotation (4) heads, 1-channel input."""

    def __init__(self) -> None:
        super().__init__()
        in_features, dropout_p = _efficientnet_b4_classifier_meta()
        backbone = models.efficientnet_b4(weights=None)
        first = backbone.features[0][0]
        backbone.features[0][0] = nn.Conv2d(
            1,
            first.out_channels,
            kernel_size=first.kernel_size,
            stride=first.stride,
            padding=first.padding,
            bias=False,
        )
        backbone.classifier = nn.Identity()
        self.extractor_net = backbone
        self.multi_classifier = nn.ModuleDict(
            {
                "label_APorPA": _head(in_features, dropout_p, len(CXP_PROJECTION_LABELS)),
                "label_round": _head(in_features, dropout_p, len(CXP_ROTATION_LABELS)),
            }
        )

    def forward(self, image: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.extractor_net(image)
        return {name: head(features) for name, head in self.multi_classifier.items()}


def build_cxp_view_net() -> CxpViewNet:
    return CxpViewNet()


def load_cxp_view_weights(weight_path: Path, *, device: torch.device | None = None) -> CxpViewNet:
    """Build network and load ``cxp_projection_rotation.pt`` state dict."""
    device = device or torch.device("cpu")
    net = build_cxp_view_net()
    try:
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(weight_path, map_location="cpu")
    if not isinstance(state, dict):
        raise RuntimeError(f"Unexpected CXp view checkpoint type: {type(state)}")
    if any(k.startswith("network.") for k in state):
        state = {k.removeprefix("network."): v for k, v in state.items()}
    net.load_state_dict(state, strict=True)
    net.to(device)
    net.eval()
    logger.info("Loaded CXp view weights from %s", weight_path)
    return net
