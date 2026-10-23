"""Anatomy region helpers: mask voxel counts and dominant body-region summaries (leaf; no pipeline deps).

Public API
----------
RegionResult
    RegionResult type.

count_mask_voxels(mask_path: Path) -> int
    Count mask voxels.

collect_structure_voxels_from_masks(segmentation_dir: Path, structures: list[str]) -> dict[str, int]
    Collect structure voxels from masks.

region_from_structure(name: str, *, structure_to_region: dict[str, str] | None=None) -> str | None
    Region from structure.

dominant_region_from_voxels(structure_voxels: dict[str, int], *, min_voxels: int=MIN_STRUCTURE_VOXELS, structure_to_region: dict[str, str] | None=None) -> RegionResult
    Pick the region with the largest summed structure voxel count.

body_parts_present(region_voxels: dict[str, int], *, min_fraction: float=MIN_REGION_FRACTION, min_voxels: int=MIN_STRUCTURE_VOXELS) -> str
    Regions with substantial voxel mass, joined as e.g. Chest+Abdomen.

is_multi_region(body_parts_present_label: str) -> bool
    Is multi region.
"""
from dataclasses import dataclass
from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.ai.tseg.config import (
    BODY_PARTS,
    MIN_REGION_FRACTION,
    MIN_STRUCTURE_VOXELS,
    STRUCTURE_TO_REGION,
)


@dataclass(frozen=True)
class RegionResult:
    dominant_region: str
    region_voxels: dict[str, int]
    structures_present: dict[str, int]
    region_fraction: float


def count_mask_voxels(mask_path: Path) -> int:
    image = sitk.ReadImage(str(mask_path))
    try:
        array = sitk.GetArrayFromImage(image)
        return int((array > 0).sum())
    finally:
        del image


def collect_structure_voxels_from_masks(segmentation_dir: Path, structures: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for structure in structures:
        mask_path = segmentation_dir / f"{structure}.nii.gz"
        if not mask_path.is_file():
            counts[structure] = 0
            continue
        counts[structure] = count_mask_voxels(mask_path)
    return counts


def region_from_structure(
    name: str,
    *,
    structure_to_region: dict[str, str] | None = None,
) -> str | None:
    mapping = structure_to_region if structure_to_region is not None else STRUCTURE_TO_REGION
    return mapping.get(name)


def dominant_region_from_voxels(
    structure_voxels: dict[str, int],
    *,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
    structure_to_region: dict[str, str] | None = None,
) -> RegionResult:
    """Pick the region with the largest summed structure voxel count."""
    region_voxels = {region: 0 for region in BODY_PARTS}
    structures_present: dict[str, int] = {}

    for structure, count in structure_voxels.items():
        if count < min_voxels:
            continue
        region = region_from_structure(structure, structure_to_region=structure_to_region)
        if region is None:
            continue
        structures_present[structure] = count
        region_voxels[region] += count

    ranked = sorted(region_voxels.items(), key=lambda item: (-item[1], BODY_PARTS.index(item[0])))
    top_region, top_count = ranked[0]
    second_count = ranked[1][1]
    total = sum(region_voxels.values())

    if total == 0:
        return RegionResult(
            dominant_region="",
            region_voxels=region_voxels,
            structures_present=structures_present,
            region_fraction=0.0,
        )

    dominant_region = top_region if top_count > 0 else ""
    region_fraction = float(top_count / total) if dominant_region else 0.0
    if dominant_region and top_count == second_count:
        region_fraction = 0.5

    return RegionResult(
        dominant_region=dominant_region,
        region_voxels=region_voxels,
        structures_present=structures_present,
        region_fraction=region_fraction,
    )


def body_parts_present(
    region_voxels: dict[str, int],
    *,
    min_fraction: float = MIN_REGION_FRACTION,
    min_voxels: int = MIN_STRUCTURE_VOXELS,
) -> str:
    """Regions with substantial voxel mass, joined as e.g. Chest+Abdomen."""
    total = sum(region_voxels.values())
    if total == 0:
        return ""
    present = [
        region
        for region in BODY_PARTS
        if region_voxels.get(region, 0) >= min_voxels and region_voxels[region] / total >= min_fraction
    ]
    return "+".join(present)


def is_multi_region(body_parts_present_label: str) -> bool:
    return "+" in body_parts_present_label
