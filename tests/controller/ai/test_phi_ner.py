"""Unit tests for product embedded_phi detect / replace (model-only NER)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.ner.cache import (
    MODEL_DIR,
    NerModelOptions,
    ner_ready,
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
    assert "FIRST_NAME" in SCORED_LABELS
    assert "LAST_NAME" in SCORED_LABELS
    assert "NAME" not in SCORED_LABELS
    assert len(SCORED_LABELS) == 7


def test_detect_locale_gate() -> None:
    assert detect_locale_supported("en_US")
    assert not detect_locale_supported("de")
    assert detect_entities("Patient Hans Mueller", locale="de") == []


def test_format_entities_xml_for_logs() -> None:
    text = "Patient Jane Doe phone (404) 555-0162"
    ents = [
        Entity("FIRST_NAME", 8, 12, 0.9, "first_name"),
        Entity("LAST_NAME", 13, 16, 0.9, "last_name"),
        Entity("PHONE", 23, 37, 0.9, "PHONE"),
    ]
    tagged = _format_entities_xml(text, ents)
    assert "<FIRST_NAME>Jane</FIRST_NAME>" in tagged
    assert "<LAST_NAME>Doe</LAST_NAME>" in tagged
    assert "<PHONE>(404) 555-0162</PHONE>" in tagged


def test_detect_entities_maps_model_output() -> None:
    """First and last names stay separate model classes (never collapsed/merged)."""
    text = "Patient Jane Doe"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [
            {"entity_group": "first_name", "start": 8, "end": 12, "score": 0.99},
            {"entity_group": "last_name", "start": 13, "end": 16, "score": 0.98},
        ]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")
    assert [e.label for e in ents] == ["FIRST_NAME", "LAST_NAME"]
    assert [e.text_of(text) for e in ents] == ["Jane", "Doe"]


def test_detect_entities_logs_key_steps(caplog) -> None:
    """INFO log shows steps 1-4 in order, dropped labels with reasons."""
    text = "Jane Doe 10:00"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [
            {"entity_group": "first_name", "start": 0, "end": 4, "score": 0.9},
            {"entity_group": "last_name", "start": 5, "end": 8, "score": 0.9},
            {"entity_group": "time", "start": 9, "end": 14, "score": 0.4},
        ]

    with (
        caplog.at_level("INFO", logger="anonymizer.controller.ai.embedded_phi.ner.engine"),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")

    log_text = caplog.text
    for step in ("step 1/4 input", "step 2/4 model raw spans", "step 3/4 label map",
                 "step 4/4 tagged result"):
        assert step in log_text
    assert "no product label for raw label 'time'" in log_text
    assert "<FIRST_NAME>Jane</FIRST_NAME>" in log_text
    assert "<LAST_NAME>Doe</LAST_NAME>" in log_text
    # No merging: first and last name remain the model's two spans.
    assert [e.label for e in ents] == ["FIRST_NAME", "LAST_NAME"]


def test_detect_entities_dob_dotted_date_raw_model_output_when_model_ready() -> None:
    """Documented raw behaviour (davidson_cxr): used as-is, the model may
    fragment ``DOB: 06.16.1976`` (the middle token can win ipv4, which has
    no product label and is dropped). No suppression or merging corrects it;
    the pixel path relies on whole-frame context instead (fixture gate)."""
    if not ner_ready():
        pytest.skip("PHI NER model not downloaded")
    text = "DOB: 06.16.1976"
    ents = detect_entities(text, locale="en_US")
    assert ents  # model returns something; exact fragmentation is its own call
    assert all(e.label in SCORED_LABELS for e in ents)


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
    if not ner_ready():
        pytest.skip("PHI NER model not downloaded")
    text = (
        "Patient: Mnikathi Mxolisi\n"
        "ID Number: 0008295650082\n"
        "Referring Doctor: Dr Molife\n"
        "DOB: 2000/08/29\n"
    )
    ents = detect_entities(text, locale="en_US")
    name_frags = [text[e.start : e.end] for e in ents if e.label in {"FIRST_NAME", "LAST_NAME"}]
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


def test_replace_synth_first_and_last_names_separately() -> None:
    """Reports: FIRST_NAME → synthetic first name, LAST_NAME → synthetic last."""
    text = "Patient Jane Doe"
    ents = [
        Entity("FIRST_NAME", 8, 12, 1.0, "first_name"),
        Entity("LAST_NAME", 13, 16, 1.0, "last_name"),
    ]
    synth, used = replace_entities(
        text, ents, mode="synth", locale="en_US", project_id="p", anon_ptid="A1"
    )
    assert len(used) == 2
    assert "Jane" not in synth and "Doe" not in synth
    parts = synth.removeprefix("Patient ").split(" ")
    assert len(parts) == 2 and all(parts)


def test_classify_series_sr_pdf() -> None:
    assert classify_series(".", modality="SR") is SeriesKind.NATIVE_SR
    assert classify_series(".", modality="PDF") is SeriesKind.NATIVE_PDF
