"""Xp-Bodypart-Checker class labels and planar anatomy mapping."""

from __future__ import annotations

# Order must match MedicalAILabo HF Space / training head.
XP_BODYPART_LABELS: tuple[str, ...] = (
    "Head",
    "Neck",
    "Chest",
    "Incomplete Chest",
    "Abdomen",
    "Pelvis",
    "Extremities",
)

# Fine-grain planar labels that sit under the model's Extremities coarse class.
_EXTREMITY_FINE_LABELS: frozenset[str] = frozenset(
    {
        "Hand",
        "Wrist",
        "Elbow",
        "Shoulder",
        "Hip",
        "Knee",
        "Ankle",
        "Foot",
        "Upper extremity",
        "Lower extremity",
        "Extremities",
    }
)


def map_xp_label_to_planar_anatomy(xp_label: str) -> str:
    """Map model class to LOINC/Playbook planar anatomy (Incomplete Chest → Chest)."""
    if xp_label == "Incomplete Chest":
        return "Chest"
    if xp_label == "Extremities":
        return "Extremities"
    return xp_label


def coarse_region(label: str) -> str:
    """Collapse DICOM or pixel labels to a coarse region for agreement checks."""
    if label == "Incomplete Chest":
        return "Chest"
    if label in _EXTREMITY_FINE_LABELS:
        return "Extremities"
    return label


def is_extremity_fine_label(label: str) -> bool:
    return label in _EXTREMITY_FINE_LABELS and label != "Extremities"
