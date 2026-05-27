"""Vendored ResNet9 architecture used by FALCON (from PrivateModelArchitectures 0.1.1)."""

import warnings
from collections.abc import Callable

import torch
from torch import nn


def conv_bn_act(
    in_channels: int,
    out_channels: int,
    *,
    pool: bool = False,
    act_func: Callable[[], nn.Module] = nn.Mish,
    num_groups: int | None = None,
) -> nn.Sequential:
    if num_groups is not None:
        warnings.warn("num_groups has no effect with BatchNorm", stacklevel=2)
    layers: list[nn.Module] = [
        nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
        nn.BatchNorm2d(out_channels),
        act_func(),
    ]
    if pool:
        layers.append(nn.MaxPool2d(2))
    return nn.Sequential(*layers)


def conv_gn_act(
    in_channels: int,
    out_channels: int,
    *,
    pool: bool = False,
    act_func: Callable[[], nn.Module] = nn.Mish,
    num_groups: int = 32,
) -> nn.Sequential:
    layers: list[nn.Module] = [
        nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1, bias=False),
        nn.GroupNorm(min(num_groups, out_channels), out_channels),
        act_func(),
    ]
    if pool:
        layers.append(nn.MaxPool2d(2))
    return nn.Sequential(*layers)


class ResNet9(nn.Module):
    def __init__(
        self,
        in_channels: int = 3,
        num_classes: int = 10,
        act_func: Callable[[], nn.Module] = nn.Mish,
        scale_norm: bool = True,
        norm_layer: str = "batch",
        num_groups: tuple[int, int, int, int] = (32, 32, 32, 32),
    ) -> None:
        super().__init__()

        if norm_layer == "batch":
            conv_block = conv_bn_act
        elif norm_layer == "group":
            conv_block = conv_gn_act
        else:
            raise ValueError("`norm_layer` must be `batch` or `group`")

        if not (isinstance(num_groups, tuple) and len(num_groups) == 4):
            raise ValueError("num_groups must be a tuple with 4 members")

        groups = num_groups
        self.conv1 = conv_block(in_channels, 64, act_func=act_func, num_groups=groups[0])
        self.conv2 = conv_block(64, 128, pool=True, act_func=act_func, num_groups=groups[0])
        self.res1 = nn.Sequential(
            conv_block(128, 128, act_func=act_func, num_groups=groups[1]),
            conv_block(128, 128, act_func=act_func, num_groups=groups[1]),
        )
        self.conv3 = conv_block(128, 256, pool=True, act_func=act_func, num_groups=groups[2])
        self.conv4 = conv_block(256, 256, pool=True, act_func=act_func, num_groups=groups[2])
        self.res2 = nn.Sequential(
            conv_block(256, 256, act_func=act_func, num_groups=groups[3]),
            conv_block(256, 256, act_func=act_func, num_groups=groups[3]),
        )
        self.MP = nn.AdaptiveMaxPool2d((2, 2))
        self.FlatFeats = nn.Flatten()
        self.classifier = nn.Linear(1024, num_classes)

        if scale_norm:
            self.scale_norm_1 = (
                nn.BatchNorm2d(128)
                if norm_layer == "batch"
                else nn.GroupNorm(min(num_groups[1], 128), 128)
            )
            self.scale_norm_2 = (
                nn.BatchNorm2d(256)
                if norm_layer == "batch"
                else nn.GroupNorm(min(groups[3], 256), 256)
            )
        else:
            self.scale_norm_1 = nn.Identity()
            self.scale_norm_2 = nn.Identity()

    def forward(self, xb: torch.Tensor) -> torch.Tensor:
        out = self.conv1(xb)
        out = self.conv2(out)
        out = self.res1(out) + out
        out = self.scale_norm_1(out)
        out = self.conv3(out)
        out = self.conv4(out)
        out = self.res2(out) + out
        out = self.scale_norm_2(out)
        out = self.MP(out)
        out_emb = self.FlatFeats(out)
        return self.classifier(out_emb)
