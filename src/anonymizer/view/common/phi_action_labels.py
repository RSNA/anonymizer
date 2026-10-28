"""Detect / Remove PHI toolbar labels shared by Metadata and Report Text Review.

Owned here (view/common) so Series Metadata and Report Text Review both import
this leaf — neither view module imports the other for button copy.
"""

from anonymizer.controller.ai.embedded_phi.ner.engine import REPLACE_MODE_VALUES, ReplaceMode
from anonymizer.utils.translate import _


def _replace_mode_display_label(mode: ReplaceMode) -> str:
    if mode == "synth":
        return _("Synthetic")
    return _("Blank")


def replace_mode_labels() -> dict[str, ReplaceMode]:
    """Display label → replace mode for Blank / Synthetic menus."""
    return {_replace_mode_display_label(mode): mode for mode in REPLACE_MODE_VALUES}


def detect_phi_button_label() -> str:
    """Localized Detect PHI button text."""
    return _("Detect PHI")


def remove_phi_button_label(mode: ReplaceMode) -> str:
    """Localized Remove / Replace PHI button text for the selected mode."""
    if mode == "synth":
        return _("Replace PHI")
    return _("Remove PHI")
