"""Unit tests: IOD unexpected flags for public text/date metadata rows."""

from __future__ import annotations

from dicom_validator.validator.dicom_info import DicomInfo
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.extract import extract_metadata_phi_rows
from anonymizer.controller.ai.embedded_phi.metadata.iod_allowlist import (
    allowed_tags_for_sop_class,
    mark_iod_unexpected,
    normalize_iod_tag_key,
)

_SC_UID = str(SecondaryCaptureImageStorage)


def _sc_dataset() -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    return ds


def _tiny_sc_dicom_info() -> DicomInfo:
    """Minimal DicomInfo: Secondary Capture allows Study/Series Description only."""
    return DicomInfo(
        dictionary={},
        iods={
            _SC_UID: {
                "modules": {
                    "General Study": {"ref": "mod_study", "use": "M"},
                    "General Series": {"ref": "mod_series", "use": "M"},
                },
                "group_macros": {},
            }
        },
        modules={
            "mod_study": {
                "(0008,1030)": {"type": "3", "name": "Study Description"},
            },
            "mod_series": {
                "(0008,103E)": {"type": "3", "name": "Series Description"},
            },
        },
    )


def test_normalize_iod_tag_key() -> None:
    assert normalize_iod_tag_key("(0008,1030)") == "00081030"
    assert normalize_iod_tag_key("00081030") == "00081030"
    assert normalize_iod_tag_key("(0008,103E)") == "0008103E"
    assert normalize_iod_tag_key("not-a-tag") is None


def test_allowed_tags_for_sop_class_union() -> None:
    info = _tiny_sc_dicom_info()
    allowed = allowed_tags_for_sop_class(info, _SC_UID)
    assert allowed == frozenset({"00081030", "0008103E"})
    assert allowed_tags_for_sop_class(info, "1.2.3.unknown") is None


def test_mark_iod_unexpected_public_text_and_date() -> None:
    """
    In-IOD StudyDescription stays clean; extra public text/DA are unexpected;
    private DA is never flagged as IOD-unexpected.
    """
    info = _tiny_sc_dicom_info()
    ds = _sc_dataset()
    ds.StudyDescription = "XR CHEST"  # in IOD
    ds.SeriesDescription = "NA"  # in IOD
    ds.ReasonForVisit = "PHI visit note"  # not in tiny IOD
    ds.AcquisitionDate = "20140315"  # DA not in tiny IOD
    block = ds.private_block(0x0009, "GEMS_IDEN_01", create=True)
    block.add_new(0x10, "DA", "20140315")

    rows = extract_metadata_phi_rows(ds)
    flagged = mark_iod_unexpected(rows, _SC_UID, dicom_info=info)
    by_path = {r.tag_path: r for r in flagged}

    assert by_path["StudyDescription"].iod_unexpected is False
    assert by_path["SeriesDescription"].iod_unexpected is False
    assert by_path["ReasonForVisit"].iod_unexpected is True
    assert by_path["AcquisitionDate"].iod_unexpected is True

    private = [r for r in flagged if r.is_private and r.is_date]
    assert len(private) == 1
    assert private[0].iod_unexpected is False


def test_mark_iod_unexpected_unknown_sop_leaves_clean() -> None:
    info = _tiny_sc_dicom_info()
    ds = _sc_dataset()
    ds.ReasonForVisit = "extra"
    rows = extract_metadata_phi_rows(ds)
    flagged = mark_iod_unexpected(rows, "1.2.840.10008.5.1.4.1.1.2", dicom_info=info)
    # CT Image Storage not in tiny info → no flagging
    assert all(r.iod_unexpected is False for r in flagged)


def test_mark_iod_unexpected_seq_text_root() -> None:
    """SEQ(text) row is unexpected when its root SQ tag is absent from the IOD."""
    from pydicom.sequence import Sequence

    info = _tiny_sc_dicom_info()
    ds = _sc_dataset()
    item = Dataset()
    item.TextValue = "nested phi"
    ds.ContentSequence = Sequence([item])

    rows = extract_metadata_phi_rows(ds)
    seq = next(r for r in rows if r.is_seq_text)
    flagged = mark_iod_unexpected([seq], _SC_UID, dicom_info=info)
    assert flagged[0].iod_unexpected is True
