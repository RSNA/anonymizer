"""CXp projection + rotation class labels for chest XR Harmonize."""

from __future__ import annotations

# Order must match MedicalAILabo CXp-Projection-Rotation-Mislabel-Checker heads.
CXP_PROJECTION_LABELS: tuple[str, ...] = ("AP", "PA", "Lateral")
CXP_ROTATION_LABELS: tuple[str, ...] = (
    "Upright",
    "Inverted",
    "Left-rotation",
    "Right-rotation",
)

# Multi-view DICOM codes that pixel projection must never override.
_DICOM_MULTIVIEW_CODES: frozenset[str] = frozenset({"2V", "3V"})


def map_projection_to_playbook_view(projection: str) -> str:
    """Map model projection class to planar ``view_code`` (Lateral → Lat)."""
    if projection == "Lateral":
        return "Lat"
    return projection


def is_dicom_multiview(view_code: str | None) -> bool:
    return (view_code or "").strip() in _DICOM_MULTIVIEW_CODES


def normalize_rotation_label(label: str) -> str:
    """Normalize alternate spellings to canonical rotation labels."""
    compact = label.strip().lower().replace(" ", "-").replace("_", "-")
    aliases = {
        "upright": "Upright",
        "inverted": "Inverted",
        "left-rotation": "Left-rotation",
        "left-90": "Left-rotation",
        "left90": "Left-rotation",
        "left": "Left-rotation",
        "right-rotation": "Right-rotation",
        "right-90": "Right-rotation",
        "right90": "Right-rotation",
        "right": "Right-rotation",
    }
    return aliases.get(compact, label)
