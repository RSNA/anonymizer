"""Non-GUI tests for Embedded PHI synth, classify, clinical script, private KB."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import generate_synthetic_phi
from anonymizer.controller.private_tags import private_tag_operation
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.model.project import RETAIN_OPTIONS, BASIC_OPTIONS, ProjectModel
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT

_DEFAULT = DEFAULT_ANONYMIZER_SCRIPT


def test_synth_name_stable_and_shape() -> None:
    # First and last names are replaced separately, each from its own pool.
    a = generate_synthetic_phi(
        "FIRST_NAME", project_id="p", anon_ptid="A1", ordinal=0, source_fragment="Jane"
    )
    b = generate_synthetic_phi(
        "FIRST_NAME", project_id="p", anon_ptid="A1", ordinal=0, source_fragment="Jane"
    )
    assert a == b
    assert a and " " not in a and "^" not in a and "," not in a
    last = generate_synthetic_phi(
        "LAST_NAME", project_id="p", anon_ptid="A1", ordinal=0, source_fragment="Doe"
    )
    assert last and " " not in last
    phone = generate_synthetic_phi(
        "PHONE", project_id="p", anon_ptid="A1", ordinal=0, source_fragment="201-555-0100"
    )
    assert phone.count("-") == 2
    loc = generate_synthetic_phi(
        "LOCATION", project_id="p", anon_ptid="A1", ordinal=0, source_fragment="90210"
    )
    assert loc.isdigit() or "-" in loc


def test_classify_series_kinds() -> None:
    assert classify_series(".", modality="SR") is SeriesKind.NATIVE_SR
    assert classify_series(".", modality="PDF") is SeriesKind.NATIVE_PDF
    assert classify_series(".", modality="CT") is SeriesKind.IMAGING


def test_default_script_has_no_private_rows() -> None:
    assert _DEFAULT.is_file()
    root = ET.parse(_DEFAULT).getroot()
    by_tag = {e.attrib.get("t", "").upper(): (e.text or "").strip() for e in root.findall("e")}
    for tag in by_tag:
        assert "XX" not in tag, tag
        if len(tag) >= 4:
            assert int(tag[:4], 16) % 2 == 0, tag


def test_confidentiality_options_default_basic() -> None:
    m = ProjectModel()
    assert m.confidentiality_options == BASIC_OPTIONS
    m2 = ProjectModel(confidentiality_options=RETAIN_OPTIONS)
    assert m2.confidentiality_options == RETAIN_OPTIONS

def test_script_tag_keep_exact_match(tmp_path: Path) -> None:
    """Public script tags resolve from ``_tag_keep``; unknown public tags remove."""
    script = tmp_path / "s.script"
    script.write_text(
        '<?xml version="1.0"?><script>'
        '<e en="T" t="00100020" n="PatientID">@ptid</e>'
        '<e en="T" t="00181010" n="Secondary">@keep</e>'
        "</script>",
        encoding="utf-8",
    )
    model = AnonymizerModel("1", "1.2.3", script, f"sqlite:///{tmp_path / 'a.db'}")
    from tests.opened_anonymizer_model import load_model_script

    load_model_script(model, script)
    assert model._tag_keep.get("00100020") == "@ptid"
    assert model._tag_keep.get("00181010") == "@keep"
    assert "0018AB11" not in model._tag_keep


def test_private_tag_operation_kb_resolution() -> None:
    """KB keep → ``@keep``; unknown private slot → ``@remove()``."""
    ds = Dataset()
    ds.add_new(0x00090010, "LO", "GEMS_PETD_01")
    ds.add_new(0x0009100F, "LO", "KEEPME")
    ds.add_new(0x00110010, "LO", "ACME")
    ds.add_new(0x00111001, "LO", "SECRET")
    keep_elem = ds[0x0009100F]
    unknown_elem = ds[0x00111001]

    assert (
        private_tag_operation(ds, keep_elem, retain_uids=False, date_delta=-1) == "@keep"
    )
    assert (
        private_tag_operation(ds, unknown_elem, retain_uids=False, date_delta=-1)
        == "@remove()"
    )
