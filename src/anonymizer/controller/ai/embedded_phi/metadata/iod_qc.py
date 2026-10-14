"""IOD QC for dataset curation — isolated from Metadata PHI extract / scrub.

Detect / resolve only. UI and series load must call this API; they must not
import ``dicom_validator.validator`` directly.

Public API
----------
``detect_iod_qc(ds, *, dicom_info=None)``
    Run a narrow ``IODValidator`` pass and classify each tag error as
    ``BLOCKER`` (structural) or ``REVIEW`` (unexpected / soft).

``detect_series_iod_qc(instances, *, dicom_info=None)``
    Per-SOP detect + series rollup (blocker/review counts, affected SOP UIDs).

``resolve_iod_qc(ds, issue, action, *, dismissed=None)``
    Apply one curation action. Returns ``QcResolveResult`` (may mutate ``ds``
    only for blankable value fixes). Missing Type 1 is never auto-filled.

``qc_chip_label(report)``
    Short series-chrome string, e.g. ``QC · 3 issues · 2 slices``.

``is_blocker`` / ``is_review``
    Severity helpers for filters.

PHI free-text unexpected highlighting stays in ``iod_allowlist.mark_iod_unexpected``;
this module does not scrub text or shift dates.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.iod_allowlist import load_dicom_info

if TYPE_CHECKING:
    from dicom_validator.validator.dicom_info import DicomInfo

logger = logging.getLogger(__name__)


class QcSeverity(str, Enum):
    """Curation severity for one IOD QC finding."""

    BLOCKER = "blocker"
    REVIEW = "review"


class QcErrorKind(str, Enum):
    """Normalized error kinds from dicom-validator ``ErrorCode``."""

    TAG_MISSING = "tag_missing"
    TAG_EMPTY = "tag_empty"
    TAG_UNEXPECTED = "tag_unexpected"
    TAG_NOT_ALLOWED = "tag_not_allowed"
    ENUM_NOT_ALLOWED = "enum_not_allowed"
    INVALID_VALUE = "invalid_value"
    INVALID_SEQUENCE = "invalid_sequence"
    UNKNOWN_SOP_CLASS = "unknown_sop_class"
    MISSING_SOP_CLASS = "missing_sop_class"
    OTHER = "other"


class QcAction(str, Enum):
    """Resolve actions the UI / batch may request."""

    # Soft: drop from Blocker rollup; keep visible under Review if desired.
    DISMISS = "dismiss"
    # Structural: mark instance excluded from export / AI batch (no DICOM write).
    EXCLUDE_INSTANCE = "exclude_instance"
    # Value fix when safe (invalid VR / enum on a present emptyable element).
    BLANK_VALUE = "blank_value"
    # Clipboard / logging aid — no dataset mutation.
    COPY_TAG_PATH = "copy_tag_path"


# Unexpected workflow tags are review-noise, not structural blockers.
_REVIEW_KINDS = frozenset(
    {
        QcErrorKind.TAG_UNEXPECTED,
        QcErrorKind.TAG_NOT_ALLOWED,
    }
)
_BLOCKER_KINDS = frozenset(
    {
        QcErrorKind.TAG_MISSING,
        QcErrorKind.TAG_EMPTY,
        QcErrorKind.ENUM_NOT_ALLOWED,
        QcErrorKind.INVALID_VALUE,
        QcErrorKind.INVALID_SEQUENCE,
        QcErrorKind.UNKNOWN_SOP_CLASS,
        QcErrorKind.MISSING_SOP_CLASS,
    }
)
# Actions that may clear/blank a data element.
_BLANKABLE_KINDS = frozenset(
    {
        QcErrorKind.ENUM_NOT_ALLOWED,
        QcErrorKind.INVALID_VALUE,
    }
)


@dataclass(frozen=True)
class QcIssue:
    """One curated IOD finding (single tag or SOP-level status)."""

    sop_instance_uid: str
    sop_class_uid: str
    severity: QcSeverity
    kind: QcErrorKind
    tag_hex: str
    tag_path: str
    module: str
    message: str
    dismissed: bool = False

    @property
    def issue_id(self) -> str:
        """Stable id for dismiss / exclude bookkeeping."""
        return f"{self.sop_instance_uid}|{self.kind.value}|{self.tag_path}|{self.module}"


@dataclass(frozen=True)
class QcInstanceReport:
    """QC findings for one SOP Instance."""

    sop_instance_uid: str
    sop_class_uid: str
    issues: tuple[QcIssue, ...] = ()

    @property
    def blockers(self) -> tuple[QcIssue, ...]:
        return tuple(i for i in self.issues if is_blocker(i))

    @property
    def reviews(self) -> tuple[QcIssue, ...]:
        return tuple(i for i in self.issues if is_review(i))


@dataclass(frozen=True)
class QcSeriesReport:
    """Series rollup over per-SOP instance reports."""

    by_sop: Mapping[str, QcInstanceReport] = field(default_factory=dict)
    excluded_sop_uids: frozenset[str] = field(default_factory=frozenset)

    @property
    def issues(self) -> tuple[QcIssue, ...]:
        out: list[QcIssue] = []
        for report in self.by_sop.values():
            out.extend(report.issues)
        return tuple(out)

    @property
    def active_blockers(self) -> tuple[QcIssue, ...]:
        return tuple(
            i
            for i in self.issues
            if is_blocker(i)
            and not i.dismissed
            and i.sop_instance_uid not in self.excluded_sop_uids
        )

    @property
    def active_reviews(self) -> tuple[QcIssue, ...]:
        return tuple(
            i
            for i in self.issues
            if is_review(i)
            and not i.dismissed
            and i.sop_instance_uid not in self.excluded_sop_uids
        )

    @property
    def affected_sop_uids(self) -> frozenset[str]:
        return frozenset(i.sop_instance_uid for i in self.active_blockers)


@dataclass(frozen=True)
class QcResolveResult:
    """Outcome of ``resolve_iod_qc``."""

    ok: bool
    action: QcAction
    issue: QcIssue
    message: str
    dataset_mutated: bool = False
    # Updated series bookkeeping when callers pass a prior report.
    report: QcSeriesReport | None = None


def is_blocker(issue: QcIssue) -> bool:
    return issue.severity is QcSeverity.BLOCKER


def is_review(issue: QcIssue) -> bool:
    return issue.severity is QcSeverity.REVIEW


def qc_chip_label(report: QcSeriesReport) -> str:
    """Series-chrome chip text; empty when no active blockers."""
    blockers = report.active_blockers
    if not blockers:
        return ""
    slices = len(report.affected_sop_uids)
    return f"QC · {len(blockers)} issue{'s' if len(blockers) != 1 else ''} · {slices} slice{'s' if slices != 1 else ''}"


def detect_iod_qc(
    ds: Dataset,
    *,
    dicom_info: DicomInfo | None = None,
) -> QcInstanceReport:
    """Detect curated IOD QC issues on one dataset (header-only is fine)."""
    from dicom_validator.validator.error_handler import NullValidationResultHandler
    from dicom_validator.validator.iod_validator import IODValidator
    from dicom_validator.validator.validation_result import Status

    info = dicom_info if dicom_info is not None else load_dicom_info()
    sop_uid = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
    sop_class = str(getattr(ds, "SOPClassUID", "") or "").strip()

    validator = IODValidator(
        ds,
        info,
        error_handler=NullValidationResultHandler(),
        suppress_vr_warnings=False,
    )
    result = validator.validate()

    issues: list[QcIssue] = []
    if result.status is Status.MissingSOPClassUID:
        issues.append(
            _issue(
                sop_uid=sop_uid,
                sop_class=sop_class,
                kind=QcErrorKind.MISSING_SOP_CLASS,
                tag_hex="",
                tag_path="SOPClassUID",
                module="",
                message="SOP Class UID is missing",
            )
        )
    elif result.status is Status.UnknownSOPClassUID:
        issues.append(
            _issue(
                sop_uid=sop_uid,
                sop_class=sop_class,
                kind=QcErrorKind.UNKNOWN_SOP_CLASS,
                tag_hex="",
                tag_path="SOPClassUID",
                module="",
                message=f"Unknown SOP Class UID {sop_class}",
            )
        )

    for module_name, tag_errors in (result.module_errors or {}).items():
        for dicom_tag, tag_error in tag_errors.items():
            kind = _kind_from_error_code(tag_error.code)
            if kind is None:
                continue
            tag_hex, tag_path = _format_dicom_tag(dicom_tag)
            message = _message_for(kind, tag_path, module_name)
            issues.append(
                _issue(
                    sop_uid=sop_uid,
                    sop_class=sop_class,
                    kind=kind,
                    tag_hex=tag_hex,
                    tag_path=tag_path,
                    module=str(module_name or ""),
                    message=message,
                )
            )

    return QcInstanceReport(
        sop_instance_uid=sop_uid,
        sop_class_uid=sop_class,
        issues=tuple(issues),
    )


def detect_series_iod_qc(
    instances: Iterable[tuple[str, Dataset]] | Mapping[str, Dataset],
    *,
    dicom_info: DicomInfo | None = None,
) -> QcSeriesReport:
    """
    Detect QC across a series.

    ``instances`` is ``(sop_instance_uid, dataset)`` pairs or a SOP→dataset map.
    Datasets may be header-only (``stop_before_pixels=True``).
    """
    info = dicom_info if dicom_info is not None else load_dicom_info()
    if isinstance(instances, Mapping):
        pairs: Iterable[tuple[str, Dataset]] = instances.items()
    else:
        pairs = instances

    by_sop: dict[str, QcInstanceReport] = {}
    for sop_uid, ds in pairs:
        report = detect_iod_qc(ds, dicom_info=info)
        key = sop_uid or report.sop_instance_uid
        if report.sop_instance_uid and report.sop_instance_uid != key:
            # Prefer caller key; rewrite issue SOP ids for stable join with LoadedSeries.
            report = QcInstanceReport(
                sop_instance_uid=key,
                sop_class_uid=report.sop_class_uid,
                issues=tuple(
                    replace(i, sop_instance_uid=key) for i in report.issues
                ),
            )
        elif not report.sop_instance_uid:
            report = QcInstanceReport(
                sop_instance_uid=key,
                sop_class_uid=report.sop_class_uid,
                issues=tuple(
                    replace(i, sop_instance_uid=key) for i in report.issues
                ),
            )
        by_sop[key] = report
    return QcSeriesReport(by_sop=by_sop)


def resolve_iod_qc(
    ds: Dataset,
    issue: QcIssue,
    action: QcAction,
    *,
    report: QcSeriesReport | None = None,
) -> QcResolveResult:
    """
    Apply a curation resolve action.

    - ``DISMISS``: mark the issue dismissed on ``report`` (required for bookkeeping).
    - ``EXCLUDE_INSTANCE``: add SOP to ``report.excluded_sop_uids``.
    - ``BLANK_VALUE``: clear the element when kind is blankable; never invent Type 1.
    - ``COPY_TAG_PATH``: success no-op (caller copies ``issue.tag_path``).
    """
    if action is QcAction.COPY_TAG_PATH:
        return QcResolveResult(
            ok=True,
            action=action,
            issue=issue,
            message=issue.tag_path,
            report=report,
        )

    if action is QcAction.DISMISS:
        if report is None:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message="dismiss requires a QcSeriesReport",
            )
        new_report = _map_issue(
            report, issue.issue_id, lambda i: replace(i, dismissed=True)
        )
        return QcResolveResult(
            ok=True,
            action=action,
            issue=replace(issue, dismissed=True),
            message="Dismissed (review-only)",
            report=new_report,
        )

    if action is QcAction.EXCLUDE_INSTANCE:
        if report is None:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message="exclude_instance requires a QcSeriesReport",
            )
        excluded = frozenset(set(report.excluded_sop_uids) | {issue.sop_instance_uid})
        new_report = replace(report, excluded_sop_uids=excluded)
        return QcResolveResult(
            ok=True,
            action=action,
            issue=issue,
            message=f"Excluded instance {issue.sop_instance_uid}",
            report=new_report,
        )

    if action is QcAction.BLANK_VALUE:
        if issue.kind not in _BLANKABLE_KINDS:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message=(
                    f"Cannot blank {issue.kind.value}; "
                    "missing Type 1 / structural gaps are not auto-filled"
                ),
                report=report,
            )
        if not issue.tag_hex:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message="No tag to blank",
                report=report,
            )
        try:
            tag_int = int(issue.tag_hex, 16)
        except ValueError:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message=f"Bad tag hex {issue.tag_hex!r}",
                report=report,
            )
        if tag_int not in ds:
            return QcResolveResult(
                ok=False,
                action=action,
                issue=issue,
                message=f"Tag {issue.tag_path} not present on dataset",
                report=report,
            )
        ds[tag_int].value = None
        return QcResolveResult(
            ok=True,
            action=action,
            issue=issue,
            message=f"Blanked {issue.tag_path}",
            dataset_mutated=True,
            report=report,
        )

    return QcResolveResult(
        ok=False,
        action=action,
        issue=issue,
        message=f"Unsupported action {action}",
        report=report,
    )


def _issue(
    *,
    sop_uid: str,
    sop_class: str,
    kind: QcErrorKind,
    tag_hex: str,
    tag_path: str,
    module: str,
    message: str,
) -> QcIssue:
    severity = (
        QcSeverity.BLOCKER if kind in _BLOCKER_KINDS else QcSeverity.REVIEW
    )
    if kind in _REVIEW_KINDS:
        severity = QcSeverity.REVIEW
    return QcIssue(
        sop_instance_uid=sop_uid,
        sop_class_uid=sop_class,
        severity=severity,
        kind=kind,
        tag_hex=tag_hex,
        tag_path=tag_path,
        module=module,
        message=message,
    )


def _kind_from_error_code(code: object) -> QcErrorKind | None:
    from dicom_validator.validator.validation_result import ErrorCode

    mapping = {
        ErrorCode.TagMissing: QcErrorKind.TAG_MISSING,
        ErrorCode.TagEmpty: QcErrorKind.TAG_EMPTY,
        ErrorCode.TagUnexpected: QcErrorKind.TAG_UNEXPECTED,
        ErrorCode.TagNotAllowed: QcErrorKind.TAG_NOT_ALLOWED,
        ErrorCode.EnumValueNotAllowed: QcErrorKind.ENUM_NOT_ALLOWED,
        ErrorCode.InvalidValue: QcErrorKind.INVALID_VALUE,
        ErrorCode.InvalidSequence: QcErrorKind.INVALID_SEQUENCE,
        ErrorCode.NoError: None,
    }
    return mapping.get(code, QcErrorKind.OTHER)


def _format_dicom_tag(dicom_tag: object) -> tuple[str, str]:
    """Return ``(GGGGEEEE, path)`` from a validator ``DicomTag``."""
    tag = getattr(dicom_tag, "tag", None)
    parents = getattr(dicom_tag, "parents", None) or []
    parts: list[str] = []
    for parent in parents:
        parts.append(_tag_token(parent))
    leaf = _tag_token(tag)
    parts.append(leaf)
    hex8 = ""
    if tag is not None:
        try:
            hex8 = f"{int(tag):08X}"
        except Exception:
            hex8 = ""
    return hex8, ".".join(p for p in parts if p)


def _tag_token(tag: object) -> str:
    if tag is None:
        return ""
    try:
        from pydicom.datadict import keyword_for_tag

        kw = keyword_for_tag(tag)
        if kw:
            return str(kw)
    except Exception:
        pass
    try:
        return f"({int(tag):04X},{int(tag) & 0xFFFF:04X})" if False else (
            f"({int(tag) >> 16:04X},{int(tag) & 0xFFFF:04X})"
        )
    except Exception:
        return str(tag)


def _message_for(kind: QcErrorKind, tag_path: str, module: str) -> str:
    mod = f" · {module}" if module else ""
    labels = {
        QcErrorKind.TAG_MISSING: f"Type 1/2 missing · {tag_path}{mod}",
        QcErrorKind.TAG_EMPTY: f"Type 1 empty · {tag_path}{mod}",
        QcErrorKind.TAG_UNEXPECTED: f"Unexpected tag · {tag_path}{mod}",
        QcErrorKind.TAG_NOT_ALLOWED: f"Not allowed by condition · {tag_path}{mod}",
        QcErrorKind.ENUM_NOT_ALLOWED: f"Enum not allowed · {tag_path}{mod}",
        QcErrorKind.INVALID_VALUE: f"Invalid VR value · {tag_path}{mod}",
        QcErrorKind.INVALID_SEQUENCE: f"Invalid sequence · {tag_path}{mod}",
    }
    return labels.get(kind, f"{kind.value} · {tag_path}{mod}")


def _map_issue(
    report: QcSeriesReport,
    issue_id: str,
    fn,
) -> QcSeriesReport:
    by_sop: dict[str, QcInstanceReport] = {}
    for sop, inst in report.by_sop.items():
        issues = tuple(fn(i) if i.issue_id == issue_id else i for i in inst.issues)
        by_sop[sop] = replace(inst, issues=issues)
    return replace(report, by_sop=by_sop)
