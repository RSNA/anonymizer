"""Classify a series for Embedded PHI routing (Series View, Report Review, AI batch)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydicom import dcmread

SR_SOP_CLASS_PREFIX = "1.2.840.10008.5.1.4.1.1.88."
ENCAPSULATED_PDF_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.104.1"

# Series descriptions of secondary-capture pages that are really text reports (worksheets, dose pages, …).
_TEXT_REPORT_HINTS = ("report", "worksheet", "dose", "summary", "structured", "findings", "requisition")


class SeriesKind(StrEnum):
    """Embedded PHI processing / workspace route for a series."""

    IMAGING = "imaging_with_overlays"
    PIXEL_TEXT_REPORT = "pixel_text_report"
    NATIVE_SR = "native_sr"
    NATIVE_PDF = "native_pdf"
    OTHER_PIXEL = "other_pixel"


def _first_header(series_path: Path | str):
    """Header (no pixels) of the first readable DICOM file in a series directory, else ``None``."""
    path = Path(series_path)
    if not path.is_dir():
        return None
    for candidate in sorted(path.glob("*.dcm")):
        try:
            return dcmread(candidate, stop_before_pixels=True)
        except Exception:  # noqa: BLE001 - routing must never fail on a bad file
            continue
    return None


def classify_series(series_path: Path | str, *, modality: str | None = None) -> SeriesKind:
    """
    Classify a series for workspace routing.

    SOP Class (SR / Encapsulated PDF) wins when the header is readable; otherwise ``modality`` decides.
    SC/OT series whose description looks like a text report → ``PIXEL_TEXT_REPORT`` (Report View).
    """
    header = _first_header(series_path)
    mod = (modality or (str(header.get("Modality", "")) if header is not None else "")).strip().upper()
    sop_class = str(header.get("SOPClassUID", "")) if header is not None else ""
    if sop_class.startswith(SR_SOP_CLASS_PREFIX) or mod == "SR":
        return SeriesKind.NATIVE_SR
    if sop_class == ENCAPSULATED_PDF_SOP_CLASS_UID or mod in {"DOC", "PDF"}:
        return SeriesKind.NATIVE_PDF
    if mod in {"SC", "OT"} or not mod:
        description = str(header.get("SeriesDescription", "")).lower() if header is not None else ""
        if any(hint in description for hint in _TEXT_REPORT_HINTS):
            return SeriesKind.PIXEL_TEXT_REPORT
        return SeriesKind.OTHER_PIXEL
    return SeriesKind.IMAGING
