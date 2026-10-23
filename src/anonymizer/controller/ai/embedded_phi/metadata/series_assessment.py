"""Series-level consolidation of per-SOP metadata PHI rows for assessment UI.

Public API
----------
DISPLAY_VR_SEQ
    Display vr seq (default 'SEQ').

SeriesMetadataAssessmentRow
    One series-consolidated Metadata assessment row.

display_metadata_vr(vr: str) -> str
    Map internal VR for UI columns (SEQ(text) → SEQ).

date_shift_note(operation: str | None, *, covered: bool) -> str | None
    Human-readable date-delta note from script keep operand.

anonymizer_field_note(tag_hex: str, tag_path: str) -> str
    Short note for anonymizer stamp / added fields.

build_assessment_note(row: SeriesMetadataAssessmentRow) -> str
    Compose Note column: anonymizer / IOD / varies / date-delta explanations.

consolidate_series_metadata(metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]], *, sop_order: Sequence[str] | None=None) -> tuple[SeriesMetadataAssessmentRow, ...]
    Collapse per-SOP extract rows into one series assessment list.

order_assessment_display_rows(rows: Sequence[SeriesMetadataAssessmentRow]) -> list[SeriesMetadataAssessmentRow | None]
    Public rows, optional Private divider (None), then private rows.

filter_assessment_rows(rows: Sequence[SeriesMetadataAssessmentRow], *, query: str='', attention_only: bool=False, show_anonymizer_fields: bool=False) -> list[SeriesMetadataAssessmentRow]
    Filter assessment rows.

assessment_summary(rows: Sequence[SeriesMetadataAssessmentRow]) -> tuple[int, int, int]
    Return (carriers, unexpected_count, varies_count).
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from anonymizer.controller.ai.embedded_phi.metadata.extract import VR_SEQ_TEXT, MetadataPhiRow, is_anonymizer_stamp_row
from anonymizer.controller.dates import (
    incrementdate_days,
    is_date_delta_operation,
    rebasedate_origin,
)
from anonymizer.controller.script.operands import OperandId, operand_id_for_operation

# UI label for compiled sequence free-text carriers (internal VR stays SEQ(text)).
DISPLAY_VR_SEQ = "SEQ"

_NOTE_UNEXPECTED = "not in SOP Class IOD"
_NOTE_VARIES = "varies"


@dataclass(frozen=True)
class SeriesMetadataAssessmentRow:
    """One series-consolidated Metadata assessment row."""

    tag: str
    vr: str
    name: str
    text: str
    is_private: bool
    tag_path: str
    iod_unexpected: bool
    varies: bool
    sop_count: int
    first_sop_uid: str
    is_anonymizer_field: bool = False
    date_shift_covered: bool = False
    script_operation: str | None = None
    tcia_action: str | None = None

    @property
    def is_seq_text(self) -> bool:
        return self.vr == VR_SEQ_TEXT

    @property
    def is_date(self) -> bool:
        return self.vr in {"DA", "DT"}

    @property
    def display_vr(self) -> str:
        return display_metadata_vr(self.vr)

    @property
    def attention(self) -> bool:
        return self.iod_unexpected or self.varies

    @property
    def note(self) -> str:
        return build_assessment_note(self)


def display_metadata_vr(vr: str) -> str:
    """Map internal VR for UI columns (SEQ(text) → SEQ)."""
    return DISPLAY_VR_SEQ if vr == VR_SEQ_TEXT else str(vr or "")


def date_shift_note(operation: str | None, *, covered: bool) -> str | None:
    """Human-readable date-delta note from script keep operand."""
    op = str(operation or "").strip()
    if not covered and not is_date_delta_operation(op):
        return None
    if not op:
        return "date delta by script" if covered else None
    oid = operand_id_for_operation(op)
    lower = op.lower()
    if oid == OperandId.HASHDATE or "@hashdate" in lower:
        return "date delta (@hashdate)"
    if oid == OperandId.LOOKUP_DATEOFFSET or "dateoffset" in lower:
        return "date delta (@lookup dateoffset)"
    if oid == OperandId.INCREMENTDATE:
        days = incrementdate_days(op)
        if days is not None:
            return f"date delta (@incrementdate {days})"
        return "date delta (@incrementdate)"
    if oid == OperandId.REBASEDATE:
        origin = rebasedate_origin(op)
        if origin:
            return f"date delta (@rebasedate {origin})"
        return "date delta (@rebasedate)"
    return f"date delta ({op})"


def anonymizer_field_note(tag_hex: str, tag_path: str) -> str:
    """Short note for anonymizer stamp / added fields."""
    hex8 = str(tag_hex or "").replace(",", "").upper()
    root = str(tag_path or "").split("[", 1)[0].split(".", 1)[0]
    if hex8 == "00120062" or root == "PatientIdentityRemoved":
        return "anonymizer stamp (Patient Identity Removed)"
    if hex8 == "00120063" or root in {"DeidentificationMethod", "DeIdentificationMethod"}:
        return "anonymizer stamp (De-identification Method)"
    if hex8 == "00120064" or "DeidentificationMethodCode" in root or "DeIdentificationMethodCode" in root:
        return "anonymizer stamp (method code sequence)"
    if hex8.startswith("0013"):
        return "anonymizer private (site / project)"
    return "anonymizer field"


def build_assessment_note(row: SeriesMetadataAssessmentRow) -> str:
    """Compose Note column: anonymizer / IOD / varies / date-delta explanations."""
    parts: list[str] = []
    if row.is_anonymizer_field:
        parts.append(anonymizer_field_note(row.tag.replace(",", ""), row.tag_path))
    if row.iod_unexpected:
        parts.append(_NOTE_UNEXPECTED)
    if row.varies:
        if row.sop_count > 1:
            parts.append(f"{_NOTE_VARIES} ({row.sop_count} slices)")
        else:
            parts.append(_NOTE_VARIES)
    if row.is_date:
        shifted = date_shift_note(row.script_operation, covered=row.date_shift_covered)
        if shifted:
            parts.append(shifted)
        elif row.script_operation and not row.date_shift_covered:
            parts.append(f"kept ({row.script_operation})")
    return " · ".join(parts)


@dataclass
class _Agg:
    tag: str
    vr: str
    name: str
    text: str
    is_private: bool
    tag_path: str
    iod_unexpected: bool
    texts: set[str]
    sop_uids: list[str]
    first_sop_uid: str
    is_anonymizer_field: bool
    date_shift_covered: bool
    script_operation: str | None
    tcia_action: str | None


def consolidate_series_metadata(
    metadata_by_sop: Mapping[str, Sequence[MetadataPhiRow]],
    *,
    sop_order: Sequence[str] | None = None,
) -> tuple[SeriesMetadataAssessmentRow, ...]:
    """
    Collapse per-SOP extract rows into one series assessment list.

    Order: first-seen tag_path while walking sop_order (or dict order).
    text is the first-seen value; varies when later SOPs differ.
    iod_unexpected if any SOP flags the path.
    """
    if not metadata_by_sop:
        return ()

    order = list(sop_order) if sop_order is not None else list(metadata_by_sop.keys())
    for sop in metadata_by_sop:
        if sop not in order:
            order.append(sop)

    agg: dict[tuple[str, bool], _Agg] = {}
    path_order: list[tuple[str, bool]] = []

    for sop in order:
        rows = metadata_by_sop.get(sop) or ()
        for row in rows:
            key = (row.tag_path, row.is_private)
            bucket = agg.get(key)
            if bucket is None:
                bucket = _Agg(
                    tag=row.tag,
                    vr=row.vr,
                    name=row.name,
                    text=row.text,
                    is_private=row.is_private,
                    tag_path=row.tag_path,
                    iod_unexpected=row.iod_unexpected,
                    texts={row.text},
                    sop_uids=[sop],
                    first_sop_uid=sop,
                    is_anonymizer_field=is_anonymizer_stamp_row(row),
                    date_shift_covered=row.date_shift_covered,
                    script_operation=row.script_operation,
                    tcia_action=row.tcia_action,
                )
                agg[key] = bucket
                path_order.append(key)
                continue
            bucket.texts.add(row.text)
            if sop not in bucket.sop_uids:
                bucket.sop_uids.append(sop)
            if row.iod_unexpected:
                bucket.iod_unexpected = True
            if row.date_shift_covered:
                bucket.date_shift_covered = True
            if is_anonymizer_stamp_row(row):
                bucket.is_anonymizer_field = True
            if not bucket.script_operation and row.script_operation:
                bucket.script_operation = row.script_operation
            if not bucket.tcia_action and row.tcia_action:
                bucket.tcia_action = row.tcia_action
            if _name_is_blank_or_private(bucket.name) and not _name_is_blank_or_private(row.name):
                bucket.name = row.name

    out: list[SeriesMetadataAssessmentRow] = []
    for key in path_order:
        bucket = agg[key]
        out.append(
            SeriesMetadataAssessmentRow(
                tag=bucket.tag,
                vr=bucket.vr,
                name=bucket.name,
                text=bucket.text,
                is_private=bucket.is_private,
                tag_path=bucket.tag_path,
                iod_unexpected=bucket.iod_unexpected,
                varies=len(bucket.texts) > 1,
                sop_count=len(bucket.sop_uids),
                first_sop_uid=bucket.first_sop_uid,
                is_anonymizer_field=bucket.is_anonymizer_field,
                date_shift_covered=bucket.date_shift_covered,
                script_operation=bucket.script_operation,
                tcia_action=bucket.tcia_action,
            )
        )
    return tuple(out)


def _name_is_blank_or_private(name: str) -> bool:
    text = str(name or "").strip()
    return not text or text.casefold() == "private"


def order_assessment_display_rows(
    rows: Sequence[SeriesMetadataAssessmentRow],
) -> list[SeriesMetadataAssessmentRow | None]:
    """Public rows, optional Private divider (None), then private rows."""
    public = [r for r in rows if not r.is_private]
    private = [r for r in rows if r.is_private]
    if public and private:
        return [*public, None, *private]
    return [*public, *private]


def filter_assessment_rows(
    rows: Sequence[SeriesMetadataAssessmentRow],
    *,
    query: str = "",
    attention_only: bool = False,
    show_anonymizer_fields: bool = False,
) -> list[SeriesMetadataAssessmentRow]:
    needle = str(query or "").strip().lower()
    out: list[SeriesMetadataAssessmentRow] = []
    for row in rows:
        if not show_anonymizer_fields and row.is_anonymizer_field:
            continue
        if attention_only and not row.attention:
            continue
        if needle:
            hay = " ".join(
                (
                    row.tag,
                    row.display_vr,
                    row.name,
                    row.text,
                    row.tag_path,
                    row.note,
                )
            ).lower()
            if needle not in hay:
                continue
        out.append(row)
    return out


def assessment_summary(rows: Sequence[SeriesMetadataAssessmentRow]) -> tuple[int, int, int]:
    """Return (carriers, unexpected_count, varies_count)."""
    unexpected = sum(1 for r in rows if r.iod_unexpected)
    varies = sum(1 for r in rows if r.varies)
    return len(rows), unexpected, varies
