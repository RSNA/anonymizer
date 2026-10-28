"""Single source of truth for Embedded PHI entity-class colors (scored labels)."""

from anonymizer.controller.ai.embedded_phi.entity_labels import entity_label_display as entity_label_display
from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS
from anonymizer.controller.ai.embedded_phi.report.process_report_text import METADATA_LABEL_SCORED_FAMILY

# Hex colors keyed by entity label. Keys must stay aligned with SCORED_LABELS.
ENTITY_COLORS_HEX: dict[str, str] = {
    "FIRST_NAME": "#fd8d3c",
    "LAST_NAME": "#a63603",
    "LOCATION": "#2ca25f",
    "ID": "#3182bd",
    "PHONE": "#8856a7",
    "DATE": "#d9a400",
    "EMAIL": "#dd3497",
}

UNKNOWN_ENTITY_COLOR_HEX = "#888888"

assert tuple(ENTITY_COLORS_HEX) == SCORED_LABELS, "entity_colors keys must match SCORED_LABELS"


def entity_scored_family(label: str) -> str:
    """Map metadata DICOM keywords (PatientID, …) onto scored color families.

    The pixel path's collapsed NAME category shares the FIRST_NAME color.
    """
    key = str(label).upper()
    if key == "NAME":
        return "FIRST_NAME"
    return METADATA_LABEL_SCORED_FAMILY.get(key, key)


def entity_color_hex(label: str) -> str:
    """Return the #rrggbb color for label (grey for unknown labels)."""
    return ENTITY_COLORS_HEX.get(entity_scored_family(label), UNKNOWN_ENTITY_COLOR_HEX)


def entity_color_bgr(label: str) -> tuple[int, int, int]:
    """Return the OpenCV BGR tuple for label."""
    h = entity_color_hex(label).lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b, g, r)
