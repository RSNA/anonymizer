"""Unit tests: series-level Metadata assessment consolidator."""

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

    assert date_shift_note("@hashdate(this,StudyDate)", covered=True) == "date delta (@hashdate)"
    assert date_shift_note("@lookup(this,dateoffset)", covered=True) == (
        "date delta (@lookup dateoffset)"
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
    assert "date delta (@hashdate)" in date_row.note


def test_date_shift_note_operands() -> None:
    assert date_shift_note("@incrementdate(this,-3670)", covered=True) == (
        "date delta (@incrementdate -3670)"
    )
    assert date_shift_note("@rebasedate(this,19600101)", covered=True) == (
        "date delta (@rebasedate 19600101)"
    )
    assert date_shift_note(None, covered=True) == "date delta by script"
    assert date_shift_note("@keep", covered=False) is None
    assert date_shift_note("@keep", covered=True) == "date delta (@keep)"


def test_consolidate_empty_and_sop_order_appends_missing() -> None:
    assert consolidate_series_metadata({}) == ()
    by_sop = {
        "sop-z": (_row("StudyDescription", text="Z"),),
        "sop-a": (_row("StudyDescription", text="A"),),
    }
    rows = consolidate_series_metadata(by_sop, sop_order=("sop-a",))
    # sop-a first for varies text; sop-z still counted
    assert rows[0].text == "A"
    assert rows[0].sop_count == 2
    assert rows[0].varies is True


def test_filter_matches_note_and_display_vr() -> None:
    rows = consolidate_series_metadata(
        {
            "s1": (_row("ReasonForVisit", text="phi", unexpected=True),),
            "s2": (
                _row(
                    "ContentSequence",
                    text="[History] fever",
                    vr=VR_SEQ_TEXT,
                    name="Content Sequence",
                    tag="0040,A730",
                ),
            ),
        }
    )
    by_note = filter_assessment_rows(rows, query="not in SOP Class IOD")
    assert [r.tag_path for r in by_note] == ["ReasonForVisit"]
    by_vr = filter_assessment_rows(rows, query="SEQ")
    assert any(r.display_vr == "SEQ" for r in by_vr)


def test_order_only_public_or_only_private_has_no_divider() -> None:
    public = consolidate_series_metadata({"s": (_row("StudyDescription", text="A"),)})
    ordered_pub = order_assessment_display_rows(public)
    assert None not in ordered_pub
    private = consolidate_series_metadata(
        {"s": (_row("(0009,1010)", private=True, text="priv"),)}
    )
    ordered_priv = order_assessment_display_rows(private)
    assert None not in ordered_priv
    assert ordered_priv[0].is_private


def test_multi_sop_varies_and_unexpected_or() -> None:
    """Two SOPs same path: different text → varies; unexpected ORs across SOPs."""
    by_sop = {
        "sop-1": (
            _row("SeriesDescription", text="AXIAL", unexpected=False),
            _row("ImageComments", text="see Jane Doe", unexpected=True),
        ),
        "sop-2": (
            _row("SeriesDescription", text="SAGITTAL", unexpected=False),
            _row("ImageComments", text="see Jane Doe", unexpected=False),
        ),
    }
    rows = consolidate_series_metadata(by_sop, sop_order=("sop-1", "sop-2"))
    by_path = {r.tag_path: r for r in rows}
    assert by_path["SeriesDescription"].varies is True
    assert "varies" in by_path["SeriesDescription"].note
    assert by_path["ImageComments"].varies is False
    assert by_path["ImageComments"].iod_unexpected is True
    assert "not in SOP Class IOD" in by_path["ImageComments"].note
