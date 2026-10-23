"""Unit tests: extract free-text / date carriers that may hold PHI."""

from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    TEXT_VRS,
    VR_SEQ_TEXT,
    apply_text_at_path,
    extract_metadata_phi_rows,
    scrub_span_in_row,
)
from anonymizer.controller.private_tags import PrivateTagAction, lookup_private_tag

# Flat free-text tags for extract coverage.

# Nested ContentSequence / TextValue covered in a separate test.
_FLAT_TEXT_KEYWORDS: tuple[str, ...] = (
    "ProtocolName",
    "StudyDescription",
    "SeriesDescription",
    "CodeMeaning",
)

# One public keyword per TEXT_VR so extract is exercised for every text VR
# (default keep list does not cover LT/ST/UT/SH/UC/UR/PN on its own).
_TEXT_VR_COVERAGE_KEYWORDS: dict[str, str] = {
    "LO": "ProtocolName",
    "LT": "ImageComments",
    "ST": "UnformattedTextValue",
    "UT": "TextValue",
    "SH": "AccessionNumber",
    "UC": "StrainDescription",
    "UR": "RetrieveURL",
    "PN": "OperatorsName",
}


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


def _code_item(meaning: str) -> Dataset:
    code = Dataset()
    code.CodeValue = "1"
    code.CodingSchemeDesignator = "DCM"
    code.CodeMeaning = meaning
    item = Dataset()
    item.ConceptNameCodeSequence = Sequence([code])
    return item


def _planted(keyword: str, *, vr: str | None = None) -> str:
    """Planted PHI marker; keep SH within VR length 16."""
    if vr == "SH":
        return "PHI-SH-Doug1"
    return f"PHI-{keyword}-DouglasDavidson"


def test_extract_all_flat_text_fields() -> None:
    """Flat free-text tags extract with planted PHI; every TEXT_VR appears."""
    assert set(_TEXT_VR_COVERAGE_KEYWORDS) == TEXT_VRS

    ds = _sc_dataset()
    expected: dict[str, str] = {}
    for keyword in _FLAT_TEXT_KEYWORDS:
        tag = tag_for_keyword(keyword)
        assert tag is not None, keyword
        vr = dictionary_VR(Tag(tag)).split()[0]
        assert vr in TEXT_VRS, f"{keyword} VR {vr} not in TEXT_VRS"
        value = _planted(keyword, vr=vr)
        setattr(ds, keyword, value)
        expected[keyword] = value

    for vr, keyword in _TEXT_VR_COVERAGE_KEYWORDS.items():
        tag = tag_for_keyword(keyword)
        assert tag is not None, keyword
        assert dictionary_VR(Tag(tag)).split()[0] == vr, keyword
        if keyword in expected:
            continue
        value = _planted(keyword, vr=vr)
        setattr(ds, keyword, value)
        expected[keyword] = value

    rows = extract_metadata_phi_rows(ds)
    by_path = {r.tag_path: r for r in rows}
    missing = [kw for kw in expected if kw not in by_path]
    assert not missing, f"extract missed text tags: {missing}"
    for keyword, value in expected.items():
        row = by_path[keyword]
        assert row.text == value
        assert row.vr in TEXT_VRS
        assert not row.is_private
        assert not row.is_seq_text

    flat_vrs = {by_path[kw].vr for kw in expected}
    assert flat_vrs == TEXT_VRS, f"missing TEXT_VRs in extract: {TEXT_VRS - flat_vrs}"


def test_extract_content_sequence_textvalue_and_personname() -> None:
    """Extract surfaces nested TextValue and PersonName in ContentSequence for review/scrub."""
    ds = _sc_dataset()
    history = _code_item("Patient History")
    history.ValueType = "TEXT"
    history.TextValue = _planted("TextValue")
    pname = _code_item("Observer")
    pname.ValueType = "PNAME"
    pname.PersonName = "Davidson^Douglas"
    root = _code_item("Radiology Report")
    root.ValueType = "CONTAINER"
    root.ContentSequence = Sequence([history, pname])
    ds.ContentSequence = Sequence([root])

    rows = extract_metadata_phi_rows(ds)
    seq_rows = [r for r in rows if r.is_seq_text]
    assert len(seq_rows) == 1
    row = seq_rows[0]
    assert row.vr == VR_SEQ_TEXT
    assert row.tag == "0040,A730"
    assert str(row.name or "").strip()
    assert row.name != "—"
    assert _planted("TextValue") in row.text
    assert "Davidson^Douglas" in row.text
    assert "[Patient History]" in row.text
    assert "[Observer]" in row.text
    nested_vrs = {
        dictionary_VR(Tag(tag_for_keyword(kw))).split()[0]
        for kw in ("TextValue", "PersonName")
    }
    assert nested_vrs == {"UT", "PN"}
    assert any(s.tag_path.endswith("TextValue") for s in row.spans)
    assert any(s.tag_path.endswith("PersonName") for s in row.spans)

    text_span = next(s for s in row.spans if _planted("TextValue") in s.leaf_text)
    assert "TextValue" in text_span.tag_path
    rebuilt = scrub_span_in_row(ds, row, text_span.start, text_span.end, "REDACTED")
    assert "REDACTED" in rebuilt
    assert _planted("TextValue") not in rebuilt
    assert ds.ContentSequence[0].ContentSequence[0].TextValue == "REDACTED"

    pname_span = next(s for s in row.spans if s.tag_path.endswith("PersonName"))
    assert "Davidson^Douglas" in pname_span.leaf_text
    apply_text_at_path(ds, pname_span.tag_path, "Anon^Patient")
    # Plain ``GGGG,EEEE`` path segments (keyword-less tags) resolve too.
    apply_text_at_path(ds, "0008,0060", "XX")
    assert str(ds.Modality) == "XX"
    assert str(ds.ContentSequence[0].ContentSequence[1].PersonName) == "Anon^Patient"
    again = extract_metadata_phi_rows(ds)
    seq = next(r for r in again if r.is_seq_text)
    assert "Anon^Patient" in seq.text
    assert "Davidson^Douglas" not in seq.text
    assert not any(s.leaf_text in {"DCM", "1"} for s in seq.spans)


def test_private_da_tcia_name_and_script_date_delta_coverage() -> None:
    """Private DA under TCIA DATE_DELTA gets KB display name; coverage follows resolve_keep."""
    ds = _sc_dataset()
    # TCIAPrivateTagKB: GEMS_PETD_01 / (0009,xx05) → DATE_DELTA (Patient DateTime)
    block = ds.private_block(0x0009, "GEMS_PETD_01", create=True)
    block.add_new(0x05, "DA", "20140315")

    keep: dict[str, str | None] = {}

    def resolve(tag: str) -> str | None:
        return keep.get(tag.upper())

    rows = extract_metadata_phi_rows(ds, resolve_keep=resolve)
    private_dates = [r for r in rows if r.is_private and r.is_date]
    assert len(private_dates) == 1
    row = private_dates[0]
    assert row.text == "20140315"
    assert row.name == "GEMS_PETD_01: Patient DateTime"
    assert row.name.casefold() != "private"
    assert row.tcia_action == PrivateTagAction.DATE_DELTA.value
    assert row.date_shift_covered is False

    keep[row.tag.replace(",", "")] = "@hashdate(this,StudyDate)"
    covered = next(
        r for r in extract_metadata_phi_rows(ds, resolve_keep=resolve) if r.is_private and r.is_date
    )
    assert covered.date_shift_covered is True
    assert covered.script_operation == "@hashdate(this,StudyDate)"


def test_lookup_private_tag_kb() -> None:
    entry = lookup_private_tag(creator="GEMS_PETD_01", group=0x0009, element_suffix=0x05)
    assert entry is not None
    assert entry.action is PrivateTagAction.DATE_DELTA
    assert entry.display_name == "GEMS_PETD_01: Patient DateTime"


def test_private_name_never_bare_private() -> None:
    """Unmatched private LO still shows creator + tag, never bare ``Private``."""
    ds = _sc_dataset()
    block = ds.private_block(0x7777, "ACME_VENDOR", create=True)
    block.add_new(0x10, "LO", "secret-label")
    rows = extract_metadata_phi_rows(ds)
    priv = [r for r in rows if r.is_private and r.text == "secret-label"]
    assert len(priv) == 1
    assert priv[0].name.casefold() != "private"
    assert "ACME_VENDOR" in priv[0].name
