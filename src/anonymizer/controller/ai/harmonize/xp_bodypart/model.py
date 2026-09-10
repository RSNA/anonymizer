"""Minimal EfficientNet-B4 multi-label head matching MedicalAILabo MultiNet."""

from __future__ import annotations

import logging
from pathlib import Path

import torch
import torch.nn as nn
import torchvision.models as models

from anonymizer.controller.ai.harmonize.xp_bodypart.labels import XP_BODYPART_LABELS

logger = logging.getLogger(__name__)


def _efficientnet_b4_classifier_meta() -> tuple[int, float]:
    probe = models.efficientnet_b4(weights=None)
    dropout_p = float(probe.classifier[0].p)
    in_features = int(probe.classifier[1].in_features)
    return in_features, dropout_p


class XpBodypartNet(nn.Module):
    """EfficientNet-B4 backbone + single 7-class body-part head (1-channel input)."""

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
                "label_bodypart": nn.Sequential(
                    nn.Dropout(p=dropout_p, inplace=False),
                    nn.Linear(in_features, len(XP_BODYPART_LABELS)),
                )
            }
        )

    def forward(self, image: torch.Tensor) -> dict[str, torch.Tensor]:
        features = self.extractor_net(image)
        return {name: head(features) for name, head in self.multi_classifier.items()}


def build_xp_bodypart_net() -> XpBodypartNet:
    return XpBodypartNet()


def load_xp_bodypart_weights(weight_path: Path, *, device: torch.device | None = None) -> XpBodypartNet:
    """Build network and load ``xp_bodypart.pt`` state dict (HF Space checkpoint)."""
    device = device or torch.device("cpu")
    net = build_xp_bodypart_net()
    try:
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
    except TypeError:
        state = torch.load(weight_path, map_location="cpu")
    if not isinstance(state, dict):
        raise RuntimeError(f"Unexpected Xp bodypart checkpoint type: {type(state)}")
    if any(k.startswith("network.") for k in state):
        state = {k.removeprefix("network."): v for k, v in state.items()}
    missing, unexpected = net.load_state_dict(state, strict=True)
    del missing, unexpected
    net.to(device)
    net.eval()
    logger.info("Loaded Xp bodypart weights from %s", weight_path)
    return net
