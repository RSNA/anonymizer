"""Single source of truth for Embedded PHI entity-class colors (six scored labels)."""

from __future__ import annotations

from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    METADATA_LABEL_SCORED_FAMILY,
)
from anonymizer.utils.translate import _

# Hex colors keyed by entity label. Keys must stay aligned with ``SCORED_LABELS``.
ENTITY_COLORS_HEX: dict[str, str] = {
    "NAME": "#e6550d",
    "LOCATION": "#2ca25f",
    "ID": "#3182bd",
    "PHONE": "#8856a7",
    "DATE": "#d9a400",
    "EMAIL": "#dd3497",
}

UNKNOWN_ENTITY_COLOR_HEX = "#888888"

assert tuple(ENTITY_COLORS_HEX) == SCORED_LABELS, "entity_colors keys must match SCORED_LABELS"


def entity_scored_family(label: str) -> str:
    """Map metadata DICOM keywords (PatientID, …) onto scored color families."""
    key = str(label).upper()
    return METADATA_LABEL_SCORED_FAMILY.get(key, key)


def entity_color_hex(label: str) -> str:
    """Return the ``#rrggbb`` color for ``label`` (grey for unknown labels)."""
    return ENTITY_COLORS_HEX.get(entity_scored_family(label), UNKNOWN_ENTITY_COLOR_HEX)


def entity_color_bgr(label: str) -> tuple[int, int, int]:
    """Return the OpenCV BGR tuple for ``label``."""
    h = entity_color_hex(label).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)


def entity_label_display(label: str) -> str:
    """Localized short display name for an entity label."""
    names = {
        "NAME": _("Name"),
        "LOCATION": _("Location"),
        "ID": _("ID"),
        "PHONE": _("Phone"),
        "DATE": _("Date"),
        "EMAIL": _("Email"),
    }
    return names.get(str(label).upper(), str(label))
