"""Synthetic SR / US / Encapsulated-PDF shells for deid_option_iod tests."""

from __future__ import annotations

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import (
    ExplicitVRLittleEndian,
    SecondaryCaptureImageStorage,
    generate_uid,
)

from anonymizer.controller.ai.embedded_phi.classify_series import (
    ENCAPSULATED_PDF_SOP_CLASS_UID,
)
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    BASIC_TEXT_SR_SOP_CLASS_UID,
)

# Ultrasound Multi-frame Image Storage
_US_MF_SOP = "1.2.840.10008.5.1.4.1.1.3.1"


def _file_meta(sop_class: str, sop_instance: str) -> FileMetaDataset:
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = sop_class
    meta.MediaStorageSOPInstanceUID = sop_instance
    return meta


def _common_identity(ds: Dataset, *, patient_id: str, modality: str) -> None:
    ds.PatientID = patient_id
    ds.PatientName = "DOE^JANE"
    ds.PatientSex = "F"
    ds.StudyDate = "20200115"
    ds.Manufacturer = "ACME-IOD"
    ds.InstitutionName = "IOD Hospital"
    ds.StudyDescription = "PHI Study for Jane Doe"
    ds.SeriesDescription = "PHI Series Jane"
    ds.Modality = modality
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()


def build_basic_text_sr(
    *,
    patient_id: str = "IOD-SR",
    finding_text: str = "Patient Jane Doe call 555-0162",
) -> Dataset:
    """
    Minimal Basic Text SR with one TEXT content item.

    Args:
        patient_id: PatientID value.
        finding_text: TextValue planted in Content Sequence.

    Returns:
        In-memory SR dataset (not written to disk).
    """
    sop = generate_uid()
    ds = Dataset()
    ds.file_meta = _file_meta(BASIC_TEXT_SR_SOP_CLASS_UID, sop)
    ds.SOPClassUID = BASIC_TEXT_SR_SOP_CLASS_UID
    ds.SOPInstanceUID = sop
    _common_identity(ds, patient_id=patient_id, modality="SR")
    item = Dataset()
    item.RelationshipType = "CONTAINS"
    item.ValueType = "TEXT"
    item.TextValue = finding_text
    ds.ContentSequence = DicomSequence([item])
    return ds


def build_ultrasound_shell(*, patient_id: str = "IOD-US") -> Dataset:
    """
    Minimal multi-frame US header shell (no pixel data).

    Args:
        patient_id: PatientID value.

    Returns:
        In-memory US dataset suitable for metadata anonymize smokes.
    """
    sop = generate_uid()
    ds = Dataset()
    ds.file_meta = _file_meta(_US_MF_SOP, sop)
    ds.SOPClassUID = _US_MF_SOP
    ds.SOPInstanceUID = sop
    _common_identity(ds, patient_id=patient_id, modality="US")
    ds.NumberOfFrames = "2"
    return ds


def build_encapsulated_pdf_shell(
    *,
    patient_id: str = "IOD-PDF",
    document_title: str = "Report for Jane Doe",
) -> Dataset:
    """
    Minimal Encapsulated PDF header (empty PDF bytes) for retain-tag smokes.

    Args:
        patient_id: PatientID value.
        document_title: DocumentTitle LO text.

    Returns:
        In-memory PDF SOP dataset.
    """
    sop = generate_uid()
    ds = Dataset()
    ds.file_meta = _file_meta(ENCAPSULATED_PDF_SOP_CLASS_UID, sop)
    ds.SOPClassUID = ENCAPSULATED_PDF_SOP_CLASS_UID
    ds.SOPInstanceUID = sop
    _common_identity(ds, patient_id=patient_id, modality="DOC")
    ds.DocumentTitle = document_title
    # Minimal PDF header bytes (not a valid renderable PDF; enough for tag walks).
    ds.EncapsulatedDocument = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    return ds


def build_secondary_capture_with_descriptions(
    *,
    patient_id: str = "IOD-SC",
    study_description: str = "CT CHEST Jane Doe MRN123",
    series_description: str = "AXIAL Jane",
) -> Dataset:
    """
    Secondary Capture with description PHI for Clean Descriptors tests.

    Args:
        patient_id: PatientID value.
        study_description: StudyDescription text.
        series_description: SeriesDescription text.

    Returns:
        In-memory SC dataset.
    """
    sop = generate_uid()
    ds = Dataset()
    ds.file_meta = _file_meta(SecondaryCaptureImageStorage, sop)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = sop
    _common_identity(ds, patient_id=patient_id, modality="OT")
    ds.StudyDescription = study_description
    ds.SeriesDescription = series_description
    return ds
