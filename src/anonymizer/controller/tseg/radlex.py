"""RadLex Playbook+ CT series description formatting."""

from __future__ import annotations

_REGION_RADLEX_LABELS: dict[str, str] = {
    "Head": "Head+Neck",
    "Chest": "Chest",
    "Abdomen": "Abdomen",
}

_FALCON_TO_TSEG_REGION: dict[str, str] = {
    "HeadNeck": "Head",
    "Chest": "Chest",
    "Abdomen": "Abdomen",
}


def falcon_body_part_to_region_token(body_part: str) -> str:
    """Map a single FALCON body-part class to an internal region token."""
    region = _FALCON_TO_TSEG_REGION.get(body_part)
    if region is None:
        raise ValueError(f"Unsupported FALCON body part for RadLex description: {body_part}")
    return region


def falcon_body_part_to_regions_label(body_part: str) -> str:
    """Map a single FALCON body-part class to a Playbook+ region label."""
    return _REGION_RADLEX_LABELS[falcon_body_part_to_region_token(body_part)]


def format_radlex_ct_series_description(
    body_parts_present: str,
    iv_contrast: bool,
    modality: str = "CT",
) -> str:
    """
    Build a RadLex Playbook+ CT series description from anatomy and contrast results.

    ``body_parts_present`` uses internal region tokens joined by ``+`` (e.g. ``Chest+Abdomen``).
    """
    if not body_parts_present.strip():
        raise ValueError("body_parts_present is required for RadLex description")

    regions = body_parts_present.split("+")
    labels = []
    for region in regions:
        label = _REGION_RADLEX_LABELS.get(region.strip())
        if label is None:
            raise ValueError(f"Unsupported body region for RadLex description: {region!r}")
        labels.append(label)

    body_label = "+".join(labels)
    contrast_label = "With Contrast" if iv_contrast else "Without Contrast"
    return f"{modality} {body_label} {contrast_label}"
