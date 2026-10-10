"""Build a Basic Text SR from cleansed OCR lines of a pixel-text report (research / ML derivative)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydicom import dcmread

from anonymizer.controller.ai.embedded_phi.ner.ner import detect_entities
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    BASIC_TEXT_SR_SOP_CLASS_UID,
    build_basic_text_sr,
    remove_phi,
)
from anonymizer.utils.storage import get_dcm_files

__all__ = [
    "BASIC_TEXT_SR_SOP_CLASS_UID",
    "build_basic_text_sr",
    "cleansed_ocr_lines",
    "deid_transcript_lines",
    "write_ocr_report_sr",
]


def deid_transcript_lines(
    transcript_by_frame: Mapping[int, Sequence[str]],
    *,
    mode: Literal["blank", "synth"] = "blank",
    locale: str = "en_US",
    project_id: str = "default",
    anon_ptid: str = "ANON0000",
) -> list[str]:
    """
    Frame-ordered transcript lines with PHI blanked or replaced.

    Each line is passed through ``detect_entities`` then ``remove_phi``.

    Args:
        transcript_by_frame: OCR lines keyed by frame index.
        mode: ``blank`` or ``synth`` replacement style.
        locale: NER locale pack.
        project_id: Unused (kept for call-site compatibility).
        anon_ptid: Unused (kept for call-site compatibility).

    Returns:
        Non-empty cleansed lines in frame order.
    """
    del project_id, anon_ptid
    out: list[str] = []
    synthetic = mode == "synth"
    for frame in sorted(transcript_by_frame):
        for line in transcript_by_frame[frame]:
            body = str(line or "")
            entities = detect_entities(body, locale=locale)
            cleansed = remove_phi(body, entities, synthetic=synthetic)
            if cleansed.strip():
                out.append(cleansed.strip())
    return out


def cleansed_ocr_lines(transcript_by_frame: Mapping[int, Sequence[str]]) -> list[str]:
    """
    Frame-ordered OCR lines with detected PHI blanked (Blank mode).

    Args:
        transcript_by_frame: OCR lines keyed by frame index.

    Returns:
        Non-empty cleansed lines in frame order.
    """
    return deid_transcript_lines(transcript_by_frame, mode="blank")


def write_ocr_report_sr(source_series_path: Path, lines: Sequence[str]) -> Path | None:
    """
    Write a Basic Text SR next to the source series (same study dir, new series dir).

    Args:
        source_series_path: Series directory containing source DICOM instances.
        lines: Cleansed transcript lines for the SR body.

    Returns:
        SR file path, or ``None`` when there is no text or no readable source image.
    """
    if not any(str(ln).strip() for ln in lines):
        return None
    for dcm_path in sorted(get_dcm_files(source_series_path)):
        try:
            source = dcmread(dcm_path, stop_before_pixels=True)
        except Exception:  # noqa: BLE001 - try the next instance
            continue
        sr = build_basic_text_sr(source, lines, series_description="OCR Report")
        out_dir = Path(source_series_path).parent / str(sr.SeriesInstanceUID)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{sr.SOPInstanceUID}.dcm"
        sr.save_as(out, enforce_file_format=True)
        return out
    return None
