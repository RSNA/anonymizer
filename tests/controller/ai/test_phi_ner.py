"""Unit tests for product embedded_phi detect / replace (model-only NER)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.ner.cache import (
    MODEL_DIR,
    NerModelOptions,
    resolve_model_id,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import (
    SCORED_LABELS,
    SEGMENT_SEP,
    Entity,
    _format_entities_xml,
    detect_entities,
    detect_entities_in_segments,
    detect_locale_supported,
    replace_entities,
)


def test_ner_model_options_override_resolve() -> None:
    opts = NerModelOptions(model_id="org/custom-deid", cache_dir=Path("/tmp/ner-cache"))
    assert resolve_model_id(options=opts) == "org/custom-deid"
    default_id = resolve_model_id()
    assert default_id == "OpenMed/OpenMed-PII-ClinicalE5-Small-33M-v1" or Path(default_id).is_dir()
    assert MODEL_DIR.name == "model"


def test_scored_labels_include_email() -> None:
    assert "EMAIL" in SCORED_LABELS
    assert len(SCORED_LABELS) == 6


def test_detect_locale_gate() -> None:
    assert detect_locale_supported("en_US")
    assert not detect_locale_supported("de")
    assert detect_entities("Patient Hans Mueller", locale="de") == []


def test_format_entities_xml_for_logs() -> None:
    text = "Patient Jane Doe phone (404) 555-0162"
    ents = [
        Entity("NAME", 8, 16, 0.9, "PERSON"),
        Entity("PHONE", 23, 37, 0.9, "PHONE"),
    ]
    tagged = _format_entities_xml(text, ents)
    assert "<NAME>Jane Doe</NAME>" in tagged
    assert "<PHONE>(404) 555-0162</PHONE>" in tagged


def test_detect_entities_maps_model_output() -> None:
    text = "Patient Jane Doe"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [
            {
                "entity_group": "PERSON",
                "start": 8,
                "end": 16,
                "score": 0.99,
            }
        ]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")
    assert len(ents) == 1
    assert ents[0].label == "NAME"
    assert ents[0].text_of(text) == "Jane Doe"


def test_detect_entities_keeps_phone_from_model() -> None:
    text = "Call (404) 555-0162"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [{"entity_group": "PHONE", "start": 5, "end": 19, "score": 0.9}]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")
    assert any(e.label == "PHONE" for e in ents)


def test_detect_entities_does_not_fracture_names_when_model_ready() -> None:
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
    ents = detect_entities(text, locale="en_US")
    name_frags = [text[e.start : e.end] for e in ents if e.label == "NAME"]
    assert name_frags
    assert not any(f in {"Mn", "ika", "thi", "Mx", "olis", "life"} for f in name_frags)
    assert any("Mnikathi" in f for f in name_frags)


def test_detect_entities_in_segments_chunks_on_field_breaks() -> None:
    """Chunks may join fields but must start/end on field boundaries (never mid-field)."""
    seen: list[str] = []

    def scan(text: str) -> list[Entity]:
        seen.append(text)
        return []

    segs = [
        "ManufacturerModelName: GENESIS_SIGNA",
        "GEMS_IDEN_01: Product Id: SIGNA",
        "   ",
    ]
    out = detect_entities_in_segments(segs, max_chars=10_000, scan_fn=scan)
    assert len(seen) == 1
    assert seen[0] == SEGMENT_SEP.join(
        [
            "ManufacturerModelName: GENESIS_SIGNA",
            "GEMS_IDEN_01: Product Id: SIGNA",
        ]
    )
    assert out == [[], [], []]

    seen.clear()
    big = "A" * 100
    detect_entities_in_segments([big, "B"], max_chars=50, scan_fn=scan)
    assert seen == [big, "B"]


def test_replace_blank_and_synth_stable() -> None:
    text = "Phone: (215) 555-0198"
    ents = [Entity("PHONE", 7, 21, 1.0, "PHONE")]
    blank, used = replace_entities(text, ents, mode="blank", locale="en_US")
    assert used
    assert "(215) 555-0198" not in blank
    synth_a, _ = replace_entities(
        text,
        ents,
        mode="synth",
        locale="en_US",
        project_id="p",
        anon_ptid="A1",
    )
    synth_b, _ = replace_entities(
        text,
        ents,
        mode="synth",
        locale="en_US",
        project_id="p",
        anon_ptid="A1",
    )
    assert synth_a == synth_b
    assert "(215) 555-0198" not in synth_a


def test_classify_series_sr_pdf() -> None:
    assert classify_series(".", modality="SR") is SeriesKind.NATIVE_SR
    assert classify_series(".", modality="PDF") is SeriesKind.NATIVE_PDF
