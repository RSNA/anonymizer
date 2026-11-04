"""Product Remove Scope and Series View edit context for burnt-in pixel text.

Controller-only. Menus live in view/ocr_ui.py.

Public API
----------
OcrEditContext
    FRAME | SERIES — Series View Detect/Remove frame scope.

OcrRemoveMode
    NON_WHITELISTED | PHI_ONLY | ALL_TEXT.

ocr_remove_mode_from_legacy_whitelist(*, use_modality_whitelist: bool) -> OcrRemoveMode
    Historic batch checkbox: True → NON_WHITELISTED, False → ALL_TEXT.

whitelist_arg_for_ocr_remove_mode(mode: OcrRemoveMode) -> list[str] | None
    None → load effective modality whitelist; [] → disable whitelist filtering.

texts_for_remove_mode(texts: Sequence[OCRText], remove_mode: OcrRemoveMode, match_mode: PhiMatchMode) -> list[OCRText]
    Select boxes for removal by Remove Scope + PhiMatchMode helpers.

format_ocr_remove_mode(mode: OcrRemoveMode) -> str
    Short translated label for batch/headless logs.
"""
from collections.abc import Sequence
from enum import StrEnum

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    is_whitelisted,
    phi_accepted,
)
from anonymizer.controller.series.series_overlay import OCRText
from anonymizer.utils.translate import _


class OcrEditContext(StrEnum):
    """Language-agnostic Series View OCR scope (combobox stores these codes)."""

    FRAME = "frame"
    SERIES = "series"


class OcrRemoveMode(StrEnum):
    """What Detect/Remove keeps: NER PHI, non-whitelisted OCR, or every OCR box."""

    NON_WHITELISTED = "non_whitelisted"
    PHI_ONLY = "phi_only"
    ALL_TEXT = "all_text"


def ocr_remove_mode_from_legacy_whitelist(*, use_modality_whitelist: bool) -> OcrRemoveMode:
    """Map historic batch checkbox: True = non-whitelisted, False = all text."""
    return OcrRemoveMode.NON_WHITELISTED if use_modality_whitelist else OcrRemoveMode.ALL_TEXT


def whitelist_arg_for_ocr_remove_mode(mode: OcrRemoveMode) -> list[str] | None:
    """
    None loads the effective modality whitelist; [] disables whitelist filtering.

    The whitelist is annotated in every scope except All text.
    """
    if mode is OcrRemoveMode.ALL_TEXT:
        return []
    return None


def texts_for_remove_mode(
    texts: Sequence[OCRText],
    remove_mode: OcrRemoveMode,
    match_mode: PhiMatchMode,
) -> list[OCRText]:
    """
    Select boxes for removal by Remove Scope + PhiMatchMode.

    Args:
        texts: Annotated OCR boxes.
        remove_mode: Product Remove Scope.
        match_mode: Whitelist / NER decide floors.

    Returns:
        Boxes to blackout or inpaint.
    """
    if remove_mode is OcrRemoveMode.ALL_TEXT:
        return list(texts)
    if remove_mode is OcrRemoveMode.PHI_ONLY:
        return [t for t in texts if phi_accepted(t, match_mode)]
    # Keep only chrome the whitelist actually overrides; PHI-accepted names leave.
    return [
        t
        for t in texts
        if phi_accepted(t, match_mode) or not is_whitelisted(t, match_mode)
    ]


def format_ocr_remove_mode(mode: OcrRemoveMode) -> str:
    """Short translated label for batch/headless logs."""
    if mode is OcrRemoveMode.PHI_ONLY:
        return _("PHI only")
    if mode is OcrRemoveMode.ALL_TEXT:
        return _("All text")
    return _("Non-whitelisted text")
