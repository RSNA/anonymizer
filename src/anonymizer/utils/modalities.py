"""DICOM modality catalog and Harmonize ContentClass routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from anonymizer.utils.translate import _

# see: https://dicom.nema.org/medical/dicom/current/output/chtml/part16/sect_CID_29.html


class Modality(StrEnum):
    """DICOM modality attribute values used by this project."""

    CR = "CR"
    DX = "DX"
    IO = "IO"
    MG = "MG"
    CT = "CT"
    MR = "MR"
    US = "US"
    PT = "PT"
    NM = "NM"
    SC = "SC"
    SR = "SR"
    PR = "PR"
    PDF = "PDF"
    OT = "OT"
    DOC = "DOC"

    @classmethod
    def from_code(cls, value: str | None) -> Self | None:
        """
        Return the member for a DICOM modality code, or None if unknown.

        Args:
            value: Exact DICOM modality code (e.g. from Series.modality).

        Returns:
            Matching ``Modality``, or None.
        """
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            return None


class ContentClass(StrEnum):
    """How a series is processed for Harmonize."""

    D2 = "2D"
    D3 = "3D"
    TEXT = "TEXT"


class StudyImagingComposition(StrEnum):
    """Makeup of a study's imaging series for LOINC path selection."""

    NONE = "NONE"
    D3 = "3D"
    D2 = "2D"
    MIXED = "MIXED"


@dataclass(frozen=True)
class ModalityCatalogEntry:
    """One row in ``get_modality_catalog()``."""

    description: str
    sop_class_uids: tuple[str, ...]
    content_class: ContentClass
    harmonize: bool


def get_modality_catalog() -> dict[Modality, ModalityCatalogEntry]:
    """Return modality → description, SOP Class UIDs, ContentClass, and Harmonize flag."""

    return {
        Modality.CR: ModalityCatalogEntry(
            _("Computed Radiography"),
            ("1.2.840.10008.5.1.4.1.1.1",),
            ContentClass.D2,
            True,
        ),
        Modality.DX: ModalityCatalogEntry(
            _("Digital X-Ray"),
            (
                "1.2.840.10008.5.1.4.1.1.1.1",
                "1.2.840.10008.5.1.4.1.1.1.1.1",
            ),
            ContentClass.D2,
            True,
        ),
        Modality.IO: ModalityCatalogEntry(
            _("Intra-oral Radiography"),
            (
                "1.2.840.10008.5.1.4.1.1.1.3",
                "1.2.840.10008.5.1.4.1.1.1.3.1",
            ),
            ContentClass.D2,
            False,
        ),
        Modality.MG: ModalityCatalogEntry(
            _("Mammography"),
            (
                "1.2.840.10008.5.1.4.1.1.1.2",
                "1.2.840.10008.5.1.4.1.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.13.1.3",
                "1.2.840.10008.5.1.4.1.1.13.1.4",
                "1.2.840.10008.5.1.4.1.1.13.1.5",
            ),
            ContentClass.D2,
            True,
        ),
        Modality.CT: ModalityCatalogEntry(
            _("Computer Tomography"),
            (
                "1.2.840.10008.5.1.4.1.1.2",
                "1.2.840.10008.5.1.4.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.2.2",
            ),
            ContentClass.D3,
            True,
        ),
        Modality.MR: ModalityCatalogEntry(
            _("Magnetic Resonance"),
            (
                "1.2.840.10008.5.1.4.1.1.4",
                "1.2.840.10008.5.1.4.1.1.4.1",
            ),
            ContentClass.D3,
            True,
        ),
        Modality.US: ModalityCatalogEntry(
            _("Ultrasound"),
            (
                "1.2.840.10008.5.1.4.1.1.6.1",
                "1.2.840.10008.5.1.4.1.1.6.2",
                "1.2.840.10008.5.1.4.1.1.3.1",
            ),
            ContentClass.D2,
            True,
        ),
        Modality.PT: ModalityCatalogEntry(
            _("Positron Emission Tomography"),
            (
                "1.2.840.10008.5.1.4.1.1.128",
                "1.2.840.10008.5.1.4.1.1.128.1",
                "1.2.840.10008.5.1.4.1.1.130",
            ),
            ContentClass.D3,
            False,
        ),
        Modality.NM: ModalityCatalogEntry(
            _("Nuclear Medicine"),
            ("1.2.840.10008.5.1.4.1.1.20",),
            ContentClass.D3,
            False,
        ),
        Modality.SC: ModalityCatalogEntry(
            _("Secondary Capture"),
            ("1.2.840.10008.5.1.4.1.1.7",),
            ContentClass.D2,
            False,
        ),
        Modality.SR: ModalityCatalogEntry(
            _("Structured Report"),
            (
                # DICOM PS3.4 Table B.5-1 — all Structured Reporting Storage SOP Classes.
                "1.2.840.10008.5.1.4.1.1.88.11",  # Basic Text SR
                "1.2.840.10008.5.1.4.1.1.88.22",  # Enhanced SR
                "1.2.840.10008.5.1.4.1.1.88.33",  # Comprehensive SR
                "1.2.840.10008.5.1.4.1.1.88.34",  # Comprehensive 3D SR
                "1.2.840.10008.5.1.4.1.1.88.35",  # Extensible SR
                "1.2.840.10008.5.1.4.1.1.88.40",  # Procedure Log
                "1.2.840.10008.5.1.4.1.1.88.50",  # Mammography CAD SR
                "1.2.840.10008.5.1.4.1.1.88.59",  # Key Object Selection Document
                "1.2.840.10008.5.1.4.1.1.88.65",  # Chest CAD SR
                "1.2.840.10008.5.1.4.1.1.88.67",  # X-Ray Radiation Dose SR
                "1.2.840.10008.5.1.4.1.1.88.68",  # Radiopharmaceutical Radiation Dose SR
                "1.2.840.10008.5.1.4.1.1.88.69",  # Colon CAD SR
                "1.2.840.10008.5.1.4.1.1.88.70",  # Implantation Plan SR
                "1.2.840.10008.5.1.4.1.1.88.71",  # Acquisition Context SR
                "1.2.840.10008.5.1.4.1.1.88.72",  # Simplified Adult Echo SR
                "1.2.840.10008.5.1.4.1.1.88.73",  # Patient Radiation Dose SR
                "1.2.840.10008.5.1.4.1.1.88.74",  # Planned Imaging Agent Administration SR
                "1.2.840.10008.5.1.4.1.1.88.75",  # Performed Imaging Agent Administration SR
                "1.2.840.10008.5.1.4.1.1.88.76",  # Enhanced X-Ray Radiation Dose SR
                "1.2.840.10008.5.1.4.1.1.88.77",  # Waveform Annotation SR
            ),
            ContentClass.TEXT,
            True,
        ),
        Modality.PR: ModalityCatalogEntry(
            _("Presentation State"),
            (
                "1.2.840.10008.5.1.4.1.1.11.1",
                "1.2.840.10008.5.1.4.1.1.11.2",
                "1.2.840.10008.5.1.4.1.1.11.3",
                "1.2.840.10008.5.1.4.1.1.11.4",
                "1.2.840.10008.5.1.4.1.1.11.5",
                "1.2.840.10008.5.1.4.1.1.11.6",
                "1.2.840.10008.5.1.4.1.1.11.7",
                "1.2.840.10008.5.1.4.1.1.11.8",
                "1.2.840.10008.5.1.4.1.1.11.9",
                "1.2.840.10008.5.1.4.1.1.11.10",
                "1.2.840.10008.5.1.4.1.1.11.11",
            ),
            ContentClass.TEXT,
            False,
        ),
        Modality.PDF: ModalityCatalogEntry(
            _("Encapsulated PDF"),
            ("1.2.840.10008.5.1.4.1.1.104.1",),
            ContentClass.TEXT,
            True,
        ),
        Modality.OT: ModalityCatalogEntry(
            _("Other"),
            (),
            ContentClass.TEXT,
            False,
        ),
        Modality.DOC: ModalityCatalogEntry(
            _("Document"),
            (),
            ContentClass.TEXT,
            True,
        ),
    }


DEFAULT_PROJECT_MODALITIES: tuple[Modality, ...] = (
    Modality.CR,
    Modality.DX,
    Modality.CT,
    Modality.MR,
)

# CR and DX share the same 2D Harmonize / LOINC XR treatment.
XR_MODALITIES: frozenset[Modality] = frozenset({Modality.CR, Modality.DX})
