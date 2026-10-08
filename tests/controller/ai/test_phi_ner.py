"""Unit tests for product embedded_phi detect / replace."""

from __future__ import annotations

import pytest

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import detect_phi
from anonymizer.controller.ai.embedded_phi.ner.locale_registry import detect_locale_supported
from anonymizer.controller.ai.embedded_phi.ner.patterns import PatternsEngine
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SCORED_LABELS
from anonymizer.controller.ai.embedded_phi.ner.replace import replace_phi
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import SyntheticPhiFactory
from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series


def test_scored_labels_include_email() -> None:
    assert "EMAIL" in SCORED_LABELS
    assert len(SCORED_LABELS) == 6


def test_detect_locale_gate() -> None:
    assert detect_locale_supported("en_US")
    assert not detect_locale_supported("de")
    assert detect_phi("Patient Hans Mueller", locale="de") == []


def test_patterns_engine_phone_only() -> None:
    text = (
        "Patient Jane Doe DOB 03/14/1962 MRN: 4455667 "
        "Call (404) 555-0162 or email a.b@example.org"
    )
    spans = PatternsEngine().analyze(text, locale="en_US")
    assert spans
    assert all(s.label == "PHONE" for s in spans)
    assert any("(404) 555-0162" in text[s.start : s.end] for s in spans)


def test_detect_phi_phone_via_patterns() -> None:
    text = "Call (404) 555-0162 or email a.b@example.org"
    ents = detect_phi(text, locale="en_US")
    assert any(e.label == "PHONE" for e in ents)


def test_detect_phi_does_not_fracture_names_when_model_ready() -> None:
    """OpenMed B-* WordPieces must aggregate to whole tokens (not Mn/ika/thi)."""
    from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready

    if not ner_ready():
        pytest.skip("PHI NER model not downloaded")
    text = (
        "Patient: Mnikathi Mxolisi\n"
        "ID Number: 0008295650082\n"
        "Referring Doctor: Dr Molife\n"
        "DOB: 2000/08/29\n"
    )
    ents = detect_phi(text, locale="en_US")
    name_frags = [text[e.start : e.end] for e in ents if e.label == "NAME"]
    assert name_frags
    assert not any(f in {"Mn", "ika", "thi", "Mx", "olis", "life"} for f in name_frags)
    assert any("Mnikathi" in f for f in name_frags)
    id_frags = [text[e.start : e.end] for e in ents if e.label == "ID"]
    assert any("0008295650082" in f for f in id_frags)


def test_replace_blank_and_synth_stable() -> None:
    text = "Phone: (215) 555-0198"
    blank, ents = replace_phi(text, mode="blank", locale="en_US")
    assert ents
    assert "(215) 555-0198" not in blank
    synth_a, _ = replace_phi(
        text,
        mode="synth",
        locale="en_US",
        synth=SyntheticPhiFactory(project_id="p", anon_ptid="A1", locale="en_US"),
    )
    synth_b, _ = replace_phi(
        text,
        mode="synth",
        locale="en_US",
        synth=SyntheticPhiFactory(project_id="p", anon_ptid="A1", locale="en_US"),
    )
    assert synth_a == synth_b
    assert synth_a != text


def test_classify_series_kinds(tmp_path) -> None:
    assert classify_series(tmp_path) is SeriesKind.OTHER_PIXEL
