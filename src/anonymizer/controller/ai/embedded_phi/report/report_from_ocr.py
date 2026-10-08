"""Build a Basic Text SR from cleansed OCR lines of a pixel-text report (research / ML derivative)."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydicom import Dataset, dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.ai.embedded_phi.ner.replace import replace_phi
from anonymizer.utils.storage import get_dcm_files

if TYPE_CHECKING:
    from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory

BASIC_TEXT_SR_SOP_CLASS_UID = "1.2.840.10008.5.1.4.1.1.88.11"

# Attributes inherited from the source image so the SR lands in the same patient/study.
_INHERIT_KEYWORDS = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientSex",
    "StudyInstanceUID",
    "StudyDate",
    "StudyTime",
    "AccessionNumber",
    "ReferringPhysicianName",
    "StudyID",
    "StudyDescription",
)


def _code(value: str, scheme: str, meaning: str) -> Dataset:
    item = Dataset()
    item.CodeValue = value
    item.CodingSchemeDesignator = scheme
    item.CodeMeaning = meaning
    return item


def build_basic_text_sr(
    source: Dataset,
    lines: Sequence[str],
    *,
    series_description: str = "OCR Report",
    series_number: int = 9000,
) -> Dataset:
    """Return an (unsaved) Basic Text SR whose body is one TEXT content item per non-empty line."""
    sr = Dataset()
    sr.file_meta = FileMetaDataset()
    sr.file_meta.MediaStorageSOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    sr.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    sr.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    sr.file_meta.ImplementationClassUID = generate_uid()

    for kw in _INHERIT_KEYWORDS:
        if kw in source:
            setattr(sr, kw, source[kw].value)
    sr.SOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    sr.SOPInstanceUID = sr.file_meta.MediaStorageSOPInstanceUID
    sr.SeriesInstanceUID = generate_uid()
    sr.Modality = "SR"
    sr.SeriesDescription = series_description
    sr.SeriesNumber = series_number
    sr.InstanceNumber = 1
    now = _dt.datetime.now()
    sr.ContentDate = now.strftime("%Y%m%d")
    sr.ContentTime = now.strftime("%H%M%S")
    sr.CompletionFlag = "PARTIAL"
    sr.VerificationFlag = "UNVERIFIED"
    sr.ValueType = "CONTAINER"
    sr.ConceptNameCodeSequence = DicomSequence([_code("11528-7", "LN", "Radiology Report")])
    sr.ContinuityOfContent = "SEPARATE"
    items = []
    for line in lines:
        text = str(line).strip()
        if not text:
            continue
        item = Dataset()
        item.RelationshipType = "CONTAINS"
        item.ValueType = "TEXT"
        item.ConceptNameCodeSequence = DicomSequence([_code("121071", "DCM", "Finding")])
        item.TextValue = text
        items.append(item)
    sr.ContentSequence = DicomSequence(items)
    return sr


def deid_transcript_lines(
    transcript_by_frame: Mapping[int, Sequence[str]],
    *,
    mode: Literal["blank", "synth"] = "blank",
    synth: SyntheticPhiFactory | None = None,
    locale: str = "en_US",
) -> list[str]:
    """Frame-ordered transcript lines with PHI blanked or replaced (ML sibling SR body)."""
    out: list[str] = []
    for frame in sorted(transcript_by_frame):
        for line in transcript_by_frame[frame]:
            cleansed, _entities = replace_phi(line, mode=mode, locale=locale, synth=synth)
            if cleansed.strip():
                out.append(cleansed.strip())
    return out


def cleansed_ocr_lines(transcript_by_frame: Mapping[int, Sequence[str]]) -> list[str]:
    """Frame-ordered OCR lines with detected PHI blanked (Blank mode)."""
    return deid_transcript_lines(transcript_by_frame, mode="blank")


def write_ocr_report_sr(source_series_path: Path, lines: Sequence[str]) -> Path | None:
    """
    Write a Basic Text SR next to the source series (same study dir, new series dir).

    Returns the SR file path, or ``None`` when there is no text or no readable source image.
    """
    if not any(str(ln).strip() for ln in lines):
        return None
    for dcm_path in sorted(get_dcm_files(source_series_path)):
        try:
            source = dcmread(dcm_path, stop_before_pixels=True)
        except Exception:  # noqa: BLE001 - try the next instance
            continue
        sr = build_basic_text_sr(source, lines)
        out_dir = Path(source_series_path).parent / str(sr.SeriesInstanceUID)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{sr.SOPInstanceUID}.dcm"
        sr.save_as(out, enforce_file_format=True)
        return out
    return None
