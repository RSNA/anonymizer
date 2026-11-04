"""OCR toolbar / dialog menus for Series View and AI Batch.

View-only. Controller must not import this module.

Public API
----------
OcrEditContext
    FRAME | SERIES — Series View edit scope.

ocr_remove_mode_menu_values() -> tuple[OcrRemoveMode, ...]
ocr_remove_mode_display_label(mode: OcrRemoveMode) -> str
ocr_remove_mode_menu_labels() -> tuple[str, ...]
ocr_remove_mode_tooltip(mode: OcrRemoveMode) -> str
remove_text_button_label(mode: OcrRemoveMode) -> str
normalize_ocr_remove_mode(value: object | None, *, default: OcrRemoveMode=...) -> OcrRemoveMode

pixel_phi_removal_mode_menu_values() -> tuple[PixelPhiRemovalMode, ...]
pixel_phi_removal_mode_option_label(mode: PixelPhiRemovalMode) -> str
pixel_phi_removal_mode_menu_labels() -> tuple[str, ...]
normalize_pixel_phi_removal_mode(value: object | None, *, default: PixelPhiRemovalMode=...) -> PixelPhiRemovalMode
pixel_phi_removal_mode_from_menu_label(label: str) -> PixelPhiRemovalMode

match_mode_menu_labels() -> dict[str, PhiMatchMode]
match_mode_menu_label(mode: PhiMatchMode) -> str
match_mode_description(mode: PhiMatchMode) -> str

edit_context_menu_values() -> tuple[OcrEditContext, ...]
edit_context_display_label(context: OcrEditContext) -> str
normalize_edit_context(value: object | None, *, default: OcrEditContext=...) -> OcrEditContext
edit_context_toolbar_visible(*, single_frame: bool) -> bool
ocr_detect_tooltip(edit_context: OcrEditContext) -> str

collect_series_view_embedded_phi_texts(image_viewer) -> dict[int, list[str]]
    Collect OCR strings from Series View overlay by frame.
"""
from __future__ import annotations

from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import (
    PixelPhiRemovalMode,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import (
    normalize_pixel_phi_removal_mode as normalize_pixel_phi_removal_mode_code,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import (
    OcrEditContext,
    OcrRemoveMode,
    format_ocr_remove_mode,
)
from anonymizer.utils.translate import _


def ocr_remove_mode_menu_values() -> tuple[OcrRemoveMode, ...]:
    """Remove Scope picker codes."""
    return (
        OcrRemoveMode.NON_WHITELISTED,
        OcrRemoveMode.PHI_ONLY,
        OcrRemoveMode.ALL_TEXT,
    )


def ocr_remove_mode_display_label(mode: OcrRemoveMode) -> str:
    """Translated combobox label for Remove Scope."""
    return format_ocr_remove_mode(mode)


def ocr_remove_mode_menu_labels() -> tuple[str, ...]:
    """Translated Remove Scope labels in canonical order."""
    return tuple(ocr_remove_mode_display_label(member) for member in ocr_remove_mode_menu_values())


def ocr_remove_mode_tooltip(mode: OcrRemoveMode) -> str:
    """Tooltip for the selected Remove Scope."""
    if mode is OcrRemoveMode.PHI_ONLY:
        return _(
            "Named Entity Recognition (NER) labels only: names, dates, IDs, phones, emails. "
            "Unlabeled text and whitelist matches are left."
        )
    if mode is OcrRemoveMode.ALL_TEXT:
        return _("Remove every detected burnt-in text box; whitelist is ignored.")
    return _("Remove detected burnt-in text except whitelist matches and exclude areas.")


def remove_text_button_label(mode: OcrRemoveMode) -> str:
    """Primary Remove button caption for the selected Remove Scope."""
    if mode is OcrRemoveMode.PHI_ONLY:
        return _("Remove PHI")
    return _("Remove Text")


def normalize_ocr_remove_mode(
    value: object | None,
    *,
    default: OcrRemoveMode = OcrRemoveMode.NON_WHITELISTED,
) -> OcrRemoveMode:
    """Resolve combobox text or internal code to OcrRemoveMode."""
    text = str(value or "").strip()
    if not text:
        return default
    key = text.lower().replace(" ", "_").replace("-", "_")
    aliases = {
        OcrRemoveMode.NON_WHITELISTED.value: OcrRemoveMode.NON_WHITELISTED,
        "non_whitelisted_text": OcrRemoveMode.NON_WHITELISTED,
        "whitelist": OcrRemoveMode.NON_WHITELISTED,
        OcrRemoveMode.PHI_ONLY.value: OcrRemoveMode.PHI_ONLY,
        "phi": OcrRemoveMode.PHI_ONLY,
        "ner": OcrRemoveMode.PHI_ONLY,
        OcrRemoveMode.ALL_TEXT.value: OcrRemoveMode.ALL_TEXT,
        "all": OcrRemoveMode.ALL_TEXT,
    }
    if key in aliases:
        return aliases[key]
    for member in ocr_remove_mode_menu_values():
        if text == ocr_remove_mode_display_label(member):
            return member
    return default


def pixel_phi_removal_mode_menu_values() -> tuple[PixelPhiRemovalMode, ...]:
    """Language-agnostic internal codes for removal-mode picker state."""
    return (PixelPhiRemovalMode.BLACKOUT, PixelPhiRemovalMode.INPAINT)


def pixel_phi_removal_mode_option_label(mode: PixelPhiRemovalMode) -> str:
    """Translated combobox label for a removal mode."""
    if mode is PixelPhiRemovalMode.BLACKOUT:
        return _("Black out text")
    return _("Blend into background")


def pixel_phi_removal_mode_menu_labels() -> tuple[str, ...]:
    """Translated combobox labels in canonical order."""
    return tuple(pixel_phi_removal_mode_option_label(mode) for mode in pixel_phi_removal_mode_menu_values())


def normalize_pixel_phi_removal_mode(
    value: object | None,
    *,
    default: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
) -> PixelPhiRemovalMode:
    """Resolve combobox text or internal code to PixelPhiRemovalMode."""
    text = str(value or "").strip()
    if not text:
        return default
    for mode in pixel_phi_removal_mode_menu_values():
        if text == pixel_phi_removal_mode_option_label(mode):
            return mode
    return normalize_pixel_phi_removal_mode_code(value, default=default)


def pixel_phi_removal_mode_from_menu_label(label: str) -> PixelPhiRemovalMode:
    """Pixel phi removal mode from menu label."""
    return normalize_pixel_phi_removal_mode(label)


def match_mode_menu_labels() -> dict[str, PhiMatchMode]:
    """Map translated menu label → PhiMatchMode."""
    return {
        _("Exact"): PhiMatchMode.EXACT,
        _("Strict"): PhiMatchMode.STRICT,
        _("Standard"): PhiMatchMode.STANDARD,
        _("Lenient"): PhiMatchMode.LENIENT,
    }


def match_mode_menu_label(mode: PhiMatchMode) -> str:
    """Translated menu label for a PhiMatchMode."""
    reverse = {
        PhiMatchMode.EXACT: _("Exact"),
        PhiMatchMode.STRICT: _("Strict"),
        PhiMatchMode.STANDARD: _("Standard"),
        PhiMatchMode.LENIENT: _("Lenient"),
    }
    return reverse.get(mode, reverse[PhiMatchMode.STANDARD])


def match_mode_description(mode: PhiMatchMode) -> str:
    """Tooltip for a PhiMatchMode."""
    descriptions = {
        PhiMatchMode.EXACT: _("Only hide text identical to a whitelist entry."),
        PhiMatchMode.STRICT: _("Allow only very small OCR differences."),
        PhiMatchMode.STANDARD: _("Tolerates minor OCR errors (e.g. AXIL matches AXIAL)."),
        PhiMatchMode.LENIENT: _("More tolerance for noisy OCR and short markers."),
    }
    return descriptions.get(mode, "")


def edit_context_menu_values() -> tuple[OcrEditContext, ...]:
    """Internal codes for the Edit Context picker."""
    return (OcrEditContext.FRAME, OcrEditContext.SERIES)


def edit_context_display_label(context: OcrEditContext) -> str:
    """Translated combobox label for an edit context."""
    if context is OcrEditContext.FRAME:
        return _("FRAME")
    return _("SERIES")


def normalize_edit_context(
    value: object | None,
    *,
    default: OcrEditContext = OcrEditContext.FRAME,
) -> OcrEditContext:
    """Resolve combobox / legacy label text to OcrEditContext."""
    text = str(value or "").strip()
    if not text:
        return default
    lowered = text.lower().replace(" ", "")
    if lowered in (OcrEditContext.FRAME, "frame"):
        return OcrEditContext.FRAME
    if lowered in (OcrEditContext.SERIES, "series"):
        return OcrEditContext.SERIES
    for member in edit_context_menu_values():
        if text == edit_context_display_label(member):
            return member
    legacy = {
        "FRAME": OcrEditContext.FRAME,
        "SERIES": OcrEditContext.SERIES,
    }
    return legacy.get(text, default)


def edit_context_toolbar_visible(*, single_frame: bool) -> bool:
    """Show Edit Context only when the series has more than one frame."""
    return not single_frame


def ocr_detect_tooltip(edit_context: OcrEditContext) -> str:
    """Tooltip for Detect Text."""
    if edit_context is OcrEditContext.SERIES:
        return _(
            "Detect burnt-in text in all frames. Boxes show what Remove would delete "
            "for the selected Remove Scope; no pixels are changed."
        )
    return _(
        "Detect burnt-in text in the current frame. Boxes show what Remove would delete "
        "for the selected Remove Scope; no pixels are changed."
    )


def collect_series_view_embedded_phi_texts(image_viewer) -> dict[int, list[str]]:
    """
    Collect OCR text strings from a Series View overlay, keyed by frame index.

    Args:
        image_viewer: Series View image viewer with overlay_data.

    Returns:
        Frame index → deduped OCR strings.
    """
    texts_by_frame: dict[int, list[str]] = {}
    overlay_data = getattr(image_viewer, "overlay_data", None)
    if not overlay_data:
        return texts_by_frame
    for frame_index, overlay in overlay_data.items():
        seen: set[str] = set()
        deduped: list[str] = []
        for text in overlay.ocr_texts:
            stripped = text.text.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                deduped.append(stripped)
        if deduped:
            texts_by_frame[frame_index] = deduped
    return texts_by_frame
