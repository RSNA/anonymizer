"""Unit tests: IOD QC detect / series rollup / resolve (mocked validator)."""

from unittest.mock import MagicMock, patch

import pytest
from dicom_validator.validator.validation_result import DicomTag, ErrorCode, Status, TagError
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.iod_allowlist import (
    allowed_tags_for_sop_class,
    load_dicom_info,
)
from anonymizer.controller.ai.embedded_phi.metadata.iod_qc import (
    QcAction,
    QcErrorKind,
    QcInstanceReport,
    QcIssue,
    QcSeriesReport,
    QcSeverity,
    detect_iod_qc,
    detect_series_iod_qc,
    is_blocker,
    qc_chip_label,
    resolve_iod_qc,
)


def _sc_dataset(*, sop_uid: str | None = None) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    uid = sop_uid or generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = uid
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = uid
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    return ds


def _issue(
    *,
    sop: str = "1.2.3",
    kind: QcErrorKind = QcErrorKind.TAG_MISSING,
    tag_hex: str = "00100010",
    tag_path: str = "PatientName",
    dismissed: bool = False,
) -> QcIssue:
    severity = (
        QcSeverity.REVIEW
        if kind in {QcErrorKind.TAG_UNEXPECTED, QcErrorKind.TAG_NOT_ALLOWED}
        else QcSeverity.BLOCKER
    )
    return QcIssue(
        sop_instance_uid=sop,
        sop_class_uid=str(SecondaryCaptureImageStorage),
        severity=severity,
        kind=kind,
        tag_hex=tag_hex,
        tag_path=tag_path,
        module="Patient",
        message=f"{kind.value} · {tag_path}",
        dismissed=dismissed,
    )


def _patch_validate(*, status: Status, module_errors: dict | None = None):
    result = MagicMock()
    result.status = status
    result.module_errors = module_errors or {}
    return patch(
        "anonymizer.controller.ai.embedded_phi.metadata.iod_qc.IODValidator",
        return_value=MagicMock(validate=MagicMock(return_value=result)),
    )


def test_detect_iod_qc_missing_sop_class() -> None:
    ds = Dataset()
    ds.SOPInstanceUID = generate_uid()
    with _patch_validate(status=Status.MissingSOPClassUID):
        report = detect_iod_qc(ds, dicom_info=MagicMock())
    assert len(report.issues) == 1
    assert report.issues[0].kind is QcErrorKind.MISSING_SOP_CLASS
    assert is_blocker(report.issues[0])


def test_detect_iod_qc_unknown_sop_class() -> None:
    ds = Dataset()
    ds.SOPClassUID = "1.2.3.999.unknown"
    ds.SOPInstanceUID = generate_uid()
    with _patch_validate(status=Status.UnknownSOPClassUID):
        report = detect_iod_qc(ds, dicom_info=MagicMock())
    assert report.issues[0].kind is QcErrorKind.UNKNOWN_SOP_CLASS
    assert "1.2.3.999.unknown" in report.issues[0].message


def test_detect_iod_qc_maps_module_error_kinds() -> None:
    ds = _sc_dataset()
    module_errors = {
        "Patient": {
            DicomTag(0x00100010): TagError(code=ErrorCode.TagMissing),
            DicomTag(0x00081030): TagError(code=ErrorCode.TagUnexpected),
            DicomTag(0x00100020): TagError(code=ErrorCode.EnumValueNotAllowed),
            DicomTag(0x00100030): TagError(code=ErrorCode.NoError),
        }
    }
    with _patch_validate(status=Status.Failed, module_errors=module_errors):
        report = detect_iod_qc(ds, dicom_info=MagicMock())
    kinds = {i.kind for i in report.issues}
    assert QcErrorKind.TAG_MISSING in kinds
    assert QcErrorKind.TAG_UNEXPECTED in kinds
    assert QcErrorKind.ENUM_NOT_ALLOWED in kinds
    # ErrorCode.NoError is skipped by _kind_from_error_code
    assert QcErrorKind.OTHER not in kinds
    assert all(i.kind is not None for i in report.issues)
    assert len(report.blockers) >= 2
    assert len(report.reviews) >= 1


def test_detect_series_iod_qc_mapping_and_pairs_rewrite_sop_key() -> None:
    ds = _sc_dataset(sop_uid="1.2.840.real")
    module_errors = {
        "Patient": {DicomTag(0x00100010): TagError(code=ErrorCode.TagMissing)}
    }
    with _patch_validate(status=Status.Failed, module_errors=module_errors):
        as_map = detect_series_iod_qc({"caller-key": ds}, dicom_info=MagicMock())
        as_pairs = detect_series_iod_qc(
            [("caller-key", ds)], dicom_info=MagicMock()
        )
    assert set(as_map.by_sop) == {"caller-key"}
    assert set(as_pairs.by_sop) == {"caller-key"}
    for report in (as_map, as_pairs):
        inst = report.by_sop["caller-key"]
        assert inst.sop_instance_uid == "caller-key"
        assert all(i.sop_instance_uid == "caller-key" for i in inst.issues)


def test_qc_chip_label_and_active_blockers() -> None:
    empty = QcSeriesReport(by_sop={})
    assert qc_chip_label(empty) == ""

    sop_a = "1.2.a"
    sop_b = "1.2.b"
    issue_a = _issue(sop=sop_a)
    issue_b = _issue(sop=sop_b, tag_path="PatientID", tag_hex="00100020")
    dismissed = _issue(sop=sop_a, tag_path="Other", tag_hex="00100021", dismissed=True)
    report = QcSeriesReport(
        by_sop={
            sop_a: QcInstanceReport(sop_a, str(SecondaryCaptureImageStorage), (issue_a, dismissed)),
            sop_b: QcInstanceReport(sop_b, str(SecondaryCaptureImageStorage), (issue_b,)),
        }
    )
    assert len(report.active_blockers) == 2
    label = qc_chip_label(report)
    assert label.startswith("QC · 2 issues · 2 slices")

    excluded = QcSeriesReport(
        by_sop=report.by_sop,
        excluded_sop_uids=frozenset({sop_b}),
    )
    assert len(excluded.active_blockers) == 1
    assert qc_chip_label(excluded) == "QC · 1 issue · 1 slice"


def test_resolve_copy_dismiss_exclude_and_blank() -> None:
    ds = _sc_dataset()
    ds.PatientName = "Doe^Jane"
    issue = _issue(
        sop=str(ds.SOPInstanceUID),
        kind=QcErrorKind.ENUM_NOT_ALLOWED,
        tag_hex="00100010",
        tag_path="PatientName",
    )
    series = QcSeriesReport(
        by_sop={
            issue.sop_instance_uid: QcInstanceReport(
                issue.sop_instance_uid, issue.sop_class_uid, (issue,)
            )
        }
    )

    copied = resolve_iod_qc(ds, issue, QcAction.COPY_TAG_PATH, report=series)
    assert copied.ok and copied.message == "PatientName" and not copied.dataset_mutated

    no_report = resolve_iod_qc(ds, issue, QcAction.DISMISS, report=None)
    assert not no_report.ok

    dismissed = resolve_iod_qc(ds, issue, QcAction.DISMISS, report=series)
    assert dismissed.ok and dismissed.issue.dismissed
    assert dismissed.report is not None
    assert dismissed.report.active_blockers == ()

    excluded = resolve_iod_qc(ds, issue, QcAction.EXCLUDE_INSTANCE, report=series)
    assert excluded.ok and excluded.report is not None
    assert issue.sop_instance_uid in excluded.report.excluded_sop_uids

    blanked = resolve_iod_qc(ds, issue, QcAction.BLANK_VALUE, report=series)
    assert blanked.ok and blanked.dataset_mutated
    assert ds.PatientName is None or ds[0x00100010].value is None


def test_resolve_blank_rejects_non_blankable_and_bad_tag() -> None:
    ds = _sc_dataset()
    missing = _issue(kind=QcErrorKind.TAG_MISSING)
    bad = resolve_iod_qc(ds, missing, QcAction.BLANK_VALUE, report=None)
    assert not bad.ok
    assert "Cannot blank" in bad.message

    no_hex = _issue(kind=QcErrorKind.INVALID_VALUE, tag_hex="")
    assert not resolve_iod_qc(ds, no_hex, QcAction.BLANK_VALUE).ok

    bad_hex = _issue(kind=QcErrorKind.INVALID_VALUE, tag_hex="zz")
    assert not resolve_iod_qc(ds, bad_hex, QcAction.BLANK_VALUE).ok

    absent = _issue(kind=QcErrorKind.INVALID_VALUE, tag_hex="00100010", tag_path="PatientName")
    assert not resolve_iod_qc(ds, absent, QcAction.BLANK_VALUE).ok


def test_load_dicom_info_smoke_when_bundled() -> None:
    try:
        info = load_dicom_info()
    except FileNotFoundError:
        pytest.skip("Bundled DICOM edition JSON not present")
    allowed = allowed_tags_for_sop_class(info, str(SecondaryCaptureImageStorage))
    assert allowed is not None
    assert "00080060" in allowed or "00081030" in allowed or len(allowed) > 10
