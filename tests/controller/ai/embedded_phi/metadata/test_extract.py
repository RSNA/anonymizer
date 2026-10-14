"""Unit tests: extract Clinical-kept free-text / date carriers that may hold PHI."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

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
from anonymizer.controller.ai.embedded_phi.metadata.tcia_kb import match_tcia_private

_REPO = Path(__file__).resolve().parents[5]
_CLINICAL_SCRIPT = _REPO / "src/anonymizer/assets/scripts/clinical-anonymizer.script"

# Flat free-text tags kept by Clinical script (TCIA Table 1 @keep + SR extras).
# Nested ContentSequence / TextValue covered in a separate test.
_FLAT_CLINICAL_TEXT_KEYWORDS: tuple[str, ...] = (
    "ProtocolName",
    "StudyDescription",
    "SeriesDescription",
    "CodeMeaning",
)

# One public keyword per TEXT_VR so extract is exercised for every text VR
# (Clinical keep list does not cover LT/ST/UT/SH/UC/UR/PN on its own).
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


def _clinical_keep_ops() -> dict[str, str]:
    """tag_hex → operation text for non-@remove Clinical script entries."""
    root = ET.parse(_CLINICAL_SCRIPT).getroot()
    out: dict[str, str] = {}
    for e in root.findall("e"):
        tag = (e.attrib.get("t") or "").upper().replace(",", "")
        op = (e.text or "").strip()
        if not tag or "XX" in tag or len(tag) != 8:
            continue
        if "@remove" in op:
            continue
        out[tag] = op
    return out


def test_clinical_script_keeps_sr_leaf_carriers() -> None:
    """CodeMeaning / ValueType / TextValue kept for @process() SQs."""
    root = ET.parse(_CLINICAL_SCRIPT).getroot()
    by_tag = {
        (e.attrib.get("t") or "").upper(): (e.text or "").strip() for e in root.findall("e")
    }
    for tag in ("00080104", "0040A040", "0040A160"):
        op = by_tag.get(tag, "@remove()")
        assert "@remove" not in op, tag


def test_extract_all_flat_clinical_kept_text_fields() -> None:
    """
    Flat Clinical-kept free-text tags extract with planted PHI; every TEXT_VR appears.
    """
    assert set(_TEXT_VR_COVERAGE_KEYWORDS) == TEXT_VRS

    keep_ops = _clinical_keep_ops()
    ds = _sc_dataset()
    expected: dict[str, str] = {}
    for keyword in _FLAT_CLINICAL_TEXT_KEYWORDS:
        tag = tag_for_keyword(keyword)
        assert tag is not None, keyword
        tag_hex = f"{int(Tag(tag)):08X}"
        assert tag_hex in keep_ops, f"{keyword} ({tag_hex}) not kept by clinical script"
        vr = dictionary_VR(Tag(tag)).split()[0]
        assert vr in TEXT_VRS, f"{keyword} VR {vr} not in TEXT_VRS"
        value = _planted(keyword, vr=vr)
        setattr(ds, keyword, value)
        expected[keyword] = value

    # Fill any TEXT_VR not already planted via Clinical keep keywords.
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
    """
    Clinical @process() ContentSequence + keep TextValue; PersonName is Table 1 remove
    but extract still surfaces nested PN when present for review/scrub.
    """
    keep_ops = _clinical_keep_ops()
    assert keep_ops.get("0040A730") == "@process()"
    assert "0040A160" in keep_ops  # TextValue (extra keep)
    assert "00080104" in keep_ops  # CodeMeaning (extra keep)

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
    assert str(ds.ContentSequence[0].ContentSequence[1].PersonName) == "Anon^Patient"
    again = extract_metadata_phi_rows(ds)
    seq = next(r for r in again if r.is_seq_text)
    assert "Anon^Patient" in seq.text
    assert "Davidson^Douglas" not in seq.text
    assert not any(s.leaf_text in {"DCM", "1"} for s in seq.spans)


def test_private_da_tcia_name_and_script_date_shift_coverage() -> None:
    """Private DA kept under TCIA ``o`` gets KB display name; coverage follows resolve_keep."""
    ds = _sc_dataset()
    # TCIAPrivateTagKB: GEMS_PETD_01 / (0009,xx05) → action o (Patient DateTime)
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
    assert row.tcia_action == "o"
    assert row.date_shift_covered is False

    keep[row.tag.replace(",", "")] = "@hashdate(this,StudyDate)"
    covered = next(
        r for r in extract_metadata_phi_rows(ds, resolve_keep=resolve) if r.is_private and r.is_date
    )
    assert covered.date_shift_covered is True
    assert covered.script_operation == "@hashdate(this,StudyDate)"


def test_match_tcia_private_kb() -> None:
    entry = match_tcia_private("00091005", creator="GEMS_PETD_01")
    assert entry is not None
    assert entry.action == "o"
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
