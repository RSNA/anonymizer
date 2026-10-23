"""DeidMethodCode enum, meanings, AT_INGEST, presets, and DICOM recording."""

import json

from pydicom import Dataset

from anonymizer.model.project import AT_INGEST, BASIC_OPTIONS, NOT_EXECUTED, RETAIN_OPTIONS
from anonymizer.utils.dicom import DeidMethodCode, deid_method_meaning, record_deid_method_codes


def test_every_member_is_int_with_meaning() -> None:
    """Each CID 7050 member is an int code with an English meaning."""
    assert len(DeidMethodCode) == 13
    for code in DeidMethodCode:
        assert type(code.value) is int
        assert deid_method_meaning(code)


def test_meaning_matches_cid_7050() -> None:
    """Spot-check exact CID 7050 code meanings."""
    assert deid_method_meaning(DeidMethodCode.BASIC) == "Basic Application Confidentiality Profile"
    assert deid_method_meaning(DeidMethodCode.SAFE_PRIVATE) == "Retain Safe Private Option"
    assert deid_method_meaning(DeidMethodCode.INSTITUTION_IDENTITY) == "Retain Institution Identity Option"
    assert deid_method_meaning(DeidMethodCode.RETAIN_UIDS) == "Retain UIDs Option"


def test_presets_and_ingest_split() -> None:
    """Basic is BASIC only; Retain adds modified dates, characteristics, safe private."""
    assert sorted(int(code) for code in BASIC_OPTIONS) == [113100]
    assert sorted(int(code) for code in RETAIN_OPTIONS) == [113100, 113107, 113108, 113111]
    assert DeidMethodCode.BASIC in AT_INGEST
    assert DeidMethodCode.CLEAN_PIXEL_DATA not in AT_INGEST
    assert sorted(int(code) for code in NOT_EXECUTED) == [113103]
    assert not (AT_INGEST & NOT_EXECUTED)


def test_options_round_trip_as_json_integers() -> None:
    """Selected options persist as JSON integers and decode back to members."""
    payload = json.dumps(sorted(int(code) for code in RETAIN_OPTIONS))
    decoded = frozenset(DeidMethodCode(value) for value in json.loads(payload))
    assert decoded == RETAIN_OPTIONS
    assert all(type(value) is int for value in json.loads(payload))


def test_record_creates_sequence_and_skips_duplicates() -> None:
    """record_deid_method_codes appends each executed code once, in order."""
    ds = Dataset()
    present = record_deid_method_codes(ds, [DeidMethodCode.BASIC, DeidMethodCode.SAFE_PRIVATE])
    assert present == (113100, 113111)
    present = record_deid_method_codes(ds, [DeidMethodCode.SAFE_PRIVATE, DeidMethodCode.CLEAN_PIXEL_DATA])
    assert present == (113100, 113111, 113101)
    items = ds.DeidentificationMethodCodeSequence
    assert [str(item.CodeValue) for item in items] == ["113100", "113111", "113101"]
    assert all(str(item.CodingSchemeDesignator) == "DCM" for item in items)
    assert str(items[1].CodeMeaning) == "Retain Safe Private Option"
