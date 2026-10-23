"""Create tiny synthetic SR and Encapsulated PDF DICOMs with fake PHI (no real PHI)."""

from datetime import datetime
from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import (
    ComprehensiveSRStorage,
    EncapsulatedPDFStorage,
    ExplicitVRLittleEndian,
    generate_uid,
)

from prototyping.metadata_phi.scrub import text_pdf_bytes


def _base_file_meta(sop_class_uid: str) -> FileMetaDataset:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = sop_class_uid
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    return meta


def _common_patient(ds: Dataset) -> None:
    ds.PatientName = "Fake^Patient"
    ds.PatientID = "FAKE-MRN-001"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = "120000"
    ds.StudyDescription = "MR BREAST BILATERAL WITH AND WITHOUT CONTRAST"
    ds.SeriesDescription = "Synthetic PHI text fixture"
    ds.AccessionNumber = "ACCFAKE001"
    ds.ReferringPhysicianName = "Smith^Alice"
    ds.InstitutionName = "Example General Hospital"
    ds.InstitutionAddress = "100 Main Street, Springfield, IL 62701"


def _text_item(meaning: str, text: str, code: str = "121060") -> Dataset:
    item = Dataset()
    item.RelationshipType = "CONTAINS"
    item.ValueType = "TEXT"
    item.TextValue = text
    concept = Dataset()
    concept.CodeValue = code
    concept.CodingSchemeDesignator = "DCM"
    concept.CodeMeaning = meaning
    item.ConceptNameCodeSequence = Sequence([concept])
    return item


def make_basic_text_sr(path: Path) -> Path:
    ds = Dataset()
    ds.file_meta = _base_file_meta(ComprehensiveSRStorage)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = ComprehensiveSRStorage
    ds.Modality = "SR"
    _common_patient(ds)

    header = _text_item(
        "Report",
        "Patient Jane Doe DOB 03/14/1962. MRN: 4455667. "
        "Phone (555) 123-4567. Email jane.doe@example.org.",
    )
    findings = _text_item(
        "Findings",
        "Exam MR BREAST BILATERAL WITH AND WITHOUT CONTRAST. "
        "No suspicious mass. Left breast BI-RADS 2. Protocol 14 Series 6.",
    )
    impression = _text_item(
        "Impression",
        "Benign. Address on file: 12 Oak Street, Boston, MA 02108. "
        "Signed Dr. Alice Smith.",
    )

    root = Dataset()
    root.ValueType = "CONTAINER"
    root.ContinuityOfContent = "SEPARATE"
    root_concept = Dataset()
    root_concept.CodeValue = "18782-3"
    root_concept.CodingSchemeDesignator = "LN"
    root_concept.CodeMeaning = "Radiology Report"
    root.ConceptNameCodeSequence = Sequence([root_concept])
    root.ContentSequence = Sequence([header, findings, impression])
    ds.ContentSequence = Sequence([root])

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True)
    return path


def make_encapsulated_pdf(path: Path) -> Path:
    ds = Dataset()
    ds.file_meta = _base_file_meta(EncapsulatedPDFStorage)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = EncapsulatedPDFStorage
    ds.Modality = "DOC"
    _common_patient(ds)
    ds.MIMETypeOfEncapsulatedDocument = "application/pdf"
    ds.EncapsulatedDocument = text_pdf_bytes(
        "CONFIDENTIAL PATIENT SUMMARY\n"
        "Name: John Roe\n"
        "MRN 1122334 SSN 111-22-3333\n"
        "email john.roe@example.com tel 555-222-3333\n"
        "Home: 2200 Market Street, Philadelphia, PA 19103\n"
        "Attached: PORTABLE AP CHEST; CT CHEST WITHOUT CONTRAST."
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(path, enforce_file_format=True)
    return path


def main() -> None:
    root = Path(__file__).parent
    sr = make_basic_text_sr(root / "synthetic_sr_phi.dcm")
    pdf = make_encapsulated_pdf(root / "synthetic_pdf_phi.dcm")
    print(f"Wrote {sr}")
    print(f"Wrote {pdf}")


if __name__ == "__main__":
    main()
