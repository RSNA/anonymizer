"""Shared entity colors."""

from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS
from anonymizer.view.reports.entity_colors import ENTITY_COLORS_HEX, entity_color_bgr, entity_color_hex


def test_entity_colors_cover_every_scored_label() -> None:
    assert set(ENTITY_COLORS_HEX) == set(SCORED_LABELS)
    assert len(set(ENTITY_COLORS_HEX.values())) == len(SCORED_LABELS)
    assert entity_color_hex("first_name") == ENTITY_COLORS_HEX["FIRST_NAME"]
    b, g, r = entity_color_bgr("FIRST_NAME")
    assert f"#{r:02x}{g:02x}{b:02x}" == ENTITY_COLORS_HEX["FIRST_NAME"]
