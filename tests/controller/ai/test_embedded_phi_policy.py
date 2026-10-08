"""Non-GUI tests for Embedded PHI synth, classify, clinical compiler, XX keep."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory
from anonymizer.model.project import AnonymizationPolicy, ProjectModel

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS = _ROOT / "src" / "anonymizer" / "assets" / "scripts"
_CLINICAL = _SCRIPTS / "clinical-anonymizer.script"
_COMPILE = _SCRIPTS / "compile_clinical_script.py"


def test_synth_name_stable_and_shape() -> None:
    fac = SyntheticPhiFactory(project_id="p", anon_ptid="A1")
    a = fac.generate("NAME", ordinal=0, source_fragment="Doe^Jane")
    b = fac.generate("NAME", ordinal=0, source_fragment="Doe^Jane")
    assert a == b
    assert "^" in a
    phone = fac.generate("PHONE", ordinal=0, source_fragment="201-555-0100")
    assert phone.count("-") == 2
    loc = fac.generate("LOCATION", ordinal=0, source_fragment="90210")
    assert loc.isdigit() or "-" in loc


def test_classify_series_kinds() -> None:
    assert classify_series(".", modality="SR") is SeriesKind.NATIVE_SR
    assert classify_series(".", modality="PDF") is SeriesKind.NATIVE_PDF
    assert classify_series(".", modality="CT") is SeriesKind.IMAGING


def test_clinical_script_compiled_and_keeps_content() -> None:
    assert _CLINICAL.is_file()
    root = ET.parse(_CLINICAL).getroot()
    by_name = {e.attrib.get("n"): (e.text or "") for e in root.findall("e")}
    assert "@remove" not in by_name.get("ContentSeq", "@remove()")
    assert "@remove" not in by_name.get("TextValue", "@remove()")
    assert "@remove" not in by_name.get("EncapsulatedDocument", "@remove()")


def test_compile_clinical_check_ok() -> None:
    import runpy
    import sys

    sys.argv = [str(_COMPILE), "--check"]
    # Run as __main__
    ns = runpy.run_path(str(_COMPILE), run_name="not_main")
    rc = ns["compile_clinical"](check=True)
    assert rc == 0


def test_anonymization_policy_default_strict() -> None:
    m = ProjectModel()
    assert m.anonymization_policy is AnonymizationPolicy.STRICT
    m2 = ProjectModel(anonymization_policy="clinical")  # type: ignore[arg-type]
    assert m2.anonymization_policy is AnonymizationPolicy.CLINICAL


def test_resolve_tag_keep_xx(tmp_path: Path) -> None:
    from anonymizer.model.anonymizer import AnonymizerModel

    script = tmp_path / "s.script"
    script.write_text(
        '<?xml version="1.0"?><script>'
        '<e en="T" t="00100020" n="PatientID">@ptid</e>'
        '<e en="T" t="0019XX10" n="Priv">@keep</e>'
        "</script>",
        encoding="utf-8",
    )
    db = tmp_path / "a.db"
    model = AnonymizerModel("1", "1.2.3", script, f"sqlite:///{db}")
    assert model.resolve_tag_keep("00100020") == "@ptid"
    assert model.resolve_tag_keep("0019AB10") == "@keep"
    assert model.resolve_tag_keep("0019AB11") is None
