"""Unit tests: series-level Metadata assessment consolidator."""

from __future__ import annotations

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    VR_SEQ_TEXT,
    MetadataPhiRow,
    is_anonymizer_stamp_row,
)
from anonymizer.controller.ai.embedded_phi.metadata.series_assessment import (
    assessment_summary,
    consolidate_series_metadata,
    date_shift_note,
    display_metadata_vr,
    filter_assessment_rows,
    order_assessment_display_rows,
)


def _row(
    path: str,
    *,
    text: str = "x",
    private: bool = False,
    unexpected: bool = False,
    vr: str = "LO",
    name: str = "",
    tag: str = "0008,1030",
    date_shift_covered: bool = False,
    script_operation: str | None = None,
) -> MetadataPhiRow:
    return MetadataPhiRow(
        tag=tag,
        vr=vr,
        name=name or path,
        text=text,
        is_private=private,
        tag_path=path,
        iod_unexpected=unexpected,
        date_shift_covered=date_shift_covered,
        script_operation=script_operation,
    )


def test_display_metadata_vr_maps_seq_text() -> None:
    assert display_metadata_vr(VR_SEQ_TEXT) == "SEQ"
    assert display_metadata_vr("LO") == "LO"


def test_consolidate_marks_varies_and_unexpected() -> None:
    by_sop = {
        "sop-a": (
            _row("StudyDescription", text="CHEST"),
            _row("ReasonForVisit", text="note", unexpected=True),
        ),
        "sop-b": (
            _row("StudyDescription", text="ABDOMEN"),
            _row("ReasonForVisit", text="note", unexpected=False),
        ),
    }
    rows = consolidate_series_metadata(by_sop, sop_order=("sop-a", "sop-b"))
    by_path = {r.tag_path: r for r in rows}
    assert by_path["StudyDescription"].varies is True
    assert by_path["StudyDescription"].text == "CHEST"
    assert by_path["StudyDescription"].first_sop_uid == "sop-a"
    assert by_path["StudyDescription"].sop_count == 2
    assert by_path["ReasonForVisit"].varies is False
    assert by_path["ReasonForVisit"].iod_unexpected is True
    assert "not in SOP Class IOD" in by_path["ReasonForVisit"].note
    assert "varies" in by_path["StudyDescription"].note
    assert "2 slices" in by_path["StudyDescription"].note
    carriers, unexpected, varies = assessment_summary(rows)
    assert carriers == 2
    assert unexpected == 1
    assert varies == 1


def test_consolidate_seq_display_vr() -> None:
    by_sop = {
        "s1": (
            _row(
                "ContentSequence",
                text="[History] fever",
                vr=VR_SEQ_TEXT,
                name="Content Sequence",
                tag="0040,A730",
            ),
        ),
    }
    row = consolidate_series_metadata(by_sop)[0]
    assert row.display_vr == "SEQ"
    assert row.is_seq_text
    assert row.name == "Content Sequence"


def test_order_and_filter_assessment_rows() -> None:
    rows = consolidate_series_metadata(
        {
            "s1": (
                _row("(0009,1010)", private=True, text="priv"),
                _row("StudyDescription", text="A"),
                _row("ReasonForVisit", text="phi", unexpected=True),
                _row(
                    "DeidentificationMethod",
                    text="RSNA DICOM ANONYMIZER",
                    tag="0012,0063",
                ),
            ),
            "s2": (_row("StudyDescription", text="B"),),
        },
        sop_order=("s1", "s2"),
    )
    ordered = order_assessment_display_rows(rows)
    assert ordered[0].tag_path == "StudyDescription"
    assert any(r and r.tag_path == "ReasonForVisit" for r in ordered)
    assert None in ordered
    assert ordered[-1].is_private

    attn = filter_assessment_rows(rows, attention_only=True)
    assert {r.tag_path for r in attn} == {"StudyDescription", "ReasonForVisit"}
    hidden = filter_assessment_rows(rows, show_anonymizer_fields=False)
    assert all(not r.is_anonymizer_field for r in hidden)
    shown = filter_assessment_rows(rows, show_anonymizer_fields=True)
    assert any(r.tag_path == "DeidentificationMethod" for r in shown)
    assert [r.tag_path for r in filter_assessment_rows(rows, query="priv")] == [
        "(0009,1010)"
    ]


def test_anonymizer_stamp_detection_and_date_notes() -> None:
    stamp = _row(
        "DeidentificationMethod",
        text="RSNA DICOM ANONYMIZER",
        tag="0012,0063",
    )
    assert is_anonymizer_stamp_row(stamp)
    consolidated = consolidate_series_metadata({"s": (stamp,)})[0]
    assert consolidated.is_anonymizer_field
    assert "De-identification Method" in consolidated.note

    assert date_shift_note("@hashdate(this,StudyDate)", covered=True) == "date-shifted (@hashdate)"
    assert date_shift_note("@lookup(this,dateoffset)", covered=True) == (
        "date-shifted (@lookup dateoffset)"
    )
    date_row = consolidate_series_metadata(
        {
            "s": (
                _row(
                    "StudyDate",
                    text="20140315",
                    vr="DA",
                    tag="0008,0020",
                    date_shift_covered=True,
                    script_operation="@hashdate(this,StudyDate)",
                ),
            )
        }
    )[0]
    assert "date-shifted (@hashdate)" in date_row.note
