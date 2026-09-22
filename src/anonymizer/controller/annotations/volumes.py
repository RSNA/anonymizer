"""Millilitre volumes for user annotation labels (shared voxels_to_ml path)."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from anonymizer.controller.ai.tseg.seg_retention import read_mask_geometry, voxels_to_ml
from anonymizer.controller.annotations.store import (
    analytics_organ_key,
    labels_path,
    read_label_map,
)

logger = logging.getLogger(__name__)


def _spacing_for_cache(cache_dir: Path, labels_img: sitk.Image | None = None) -> list[float] | None:
    if labels_img is not None:
        try:
            return [float(v) for v in labels_img.GetSpacing()]
        except Exception:
            pass
    geometry = read_mask_geometry(cache_dir)
    spacing = geometry.get("spacing") if geometry else None
    if not spacing or len(spacing) < 3:
        return None
    try:
        return [float(spacing[0]), float(spacing[1]), float(spacing[2])]
    except (TypeError, ValueError):
        return None


def user_annotation_volumes_ml(cache_dir: Path) -> dict[str, float]:
    """Return analytics organ keys → ml for user labels with voxels.

    Matched labels use ``normative_organ``; custom use ``user:<slug>``.
    When several labels map to the same key, volumes are summed.
    """
    cache_dir = Path(cache_dir)
    labels_file = labels_path(cache_dir)
    if not labels_file.is_file():
        return {}
    label_map = read_label_map(cache_dir)
    if not label_map:
        return {}
    try:
        img = sitk.ReadImage(str(labels_file))
        labels = sitk.GetArrayFromImage(img).astype(np.uint16, copy=False)
    except RuntimeError as exc:
        logger.warning("Could not read annotation labels for volumes: %s", exc)
        return {}
    spacing = _spacing_for_cache(cache_dir, img)
    if spacing is None:
        return {}

    totals: dict[str, float] = {}
    for lid, entry in label_map.items():
        voxels = int((labels == int(lid)).sum())
        ml = voxels_to_ml(voxels, spacing)
        if ml is None or ml <= 0:
            continue
        key = analytics_organ_key(entry)
        totals[key] = totals.get(key, 0.0) + float(ml)
    return {k: v for k, v in totals.items() if v > 0}
