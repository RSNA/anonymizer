"""Unit tests for product embedded_phi detect / replace (model-only NER)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.entity_labels import entity_label_display
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
    _TO_SCORED,
    _format_entities_xml,
    _to_scored_label,
    detect_entities,
    detect_entities_in_segments,
    detect_locale_supported,
    replace_entities,
)
from anonymizer.controller.ai.embedded_phi.ner.synthetic_phi import generate_synthetic_phi
from anonymizer.view.reports.entity_colors import ENTITY_COLORS_HEX

_GOLDEN_SPANS_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "phi_text" / "ner_raw_spans.json"
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
    assert "entity_group=first_name" in log_text
    assert "entity_group=time" in log_text
    assert "<FIRST_NAME>Jane</FIRST_NAME>" in log_text
    assert "<LAST_NAME>Doe</LAST_NAME>" in log_text
    # No merging: first and last name remain the model's two spans.
    assert [e.label for e in ents] == ["FIRST_NAME", "LAST_NAME"]


def test_detect_entities_include_time_keeps_time_for_pixel_phi() -> None:
    """Pixel PHI path opts into TIME; metadata default still drops it."""
    text = "Jane Doe 10:00"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [
            {"entity_group": "first_name", "start": 0, "end": 4, "score": 0.9},
            {"entity_group": "last_name", "start": 5, "end": 8, "score": 0.9},
            {"entity_group": "time", "start": 9, "end": 14, "score": 0.9},
        ]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        without = detect_entities(text, locale="en_US")
        with_time = detect_entities(text, locale="en_US", include_time=True)

    assert [e.label for e in without] == ["FIRST_NAME", "LAST_NAME"]
    assert [e.label for e in with_time] == ["FIRST_NAME", "LAST_NAME", "TIME"]
    assert with_time[2].text_of(text) == "10:00"


def test_to_scored_label_time_gated_by_include_time() -> None:
    assert _to_scored_label("time") is None
    assert _to_scored_label("TIME", include_time=True) == "TIME"
    assert _to_scored_label("B-TIME", include_time=True) == "TIME"


def test_detect_entities_keeps_date_shaped_unmapped_label() -> None:
    """An ipv4 label on a dotted date is kept as DATE before the drop."""
    text = "DOB: 04.25.1937"

    def fake_run(_text: str, *, locale: str = "en_US"):
        start = text.index("04.25.1937")
        return [
            {
                "entity_group": "ipv4",
                "start": start,
                "end": start + len("04.25.1937"),
                "score": 0.73,
            }
        ]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")

    assert [(e.label, e.text_of(text), e.raw_label) for e in ents] == [
        ("DATE", "04.25.1937", "ipv4")
    ]


def test_detect_entities_keeps_clock_shaped_unmapped_label(caplog) -> None:
    """An unmapped label on a colon clock is kept; the raw group is logged."""
    text = "scan 10:00"

    def fake_run(_text: str, *, locale: str = "en_US"):
        start = text.index("10:00")
        return [
            {
                "entity_group": "ipv4",
                "start": start,
                "end": start + len("10:00"),
                "score": 0.4,
            }
        ]

    with (
        caplog.at_level("INFO", logger="anonymizer.controller.ai.embedded_phi.ner.engine"),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        without = detect_entities(text, locale="en_US")
        with_time = detect_entities(text, locale="en_US", include_time=True)

    assert [(e.label, e.text_of(text)) for e in without] == [("DATE", "10:00")]
    assert [(e.label, e.text_of(text)) for e in with_time] == [("TIME", "10:00")]
    assert "entity_group=ipv4" in caplog.text
    assert "no product label for raw label 'ipv4'" not in caplog.text


def test_detect_entities_drops_unmapped_label_that_is_not_a_date() -> None:
    """A non-date span with no product label is still dropped."""
    text = "EVANS"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [{"entity_group": "ipv4", "start": 0, "end": 5, "score": 0.8}]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")

    assert ents == []


def test_detect_entities_dob_dotted_date_raw_model_output_when_model_ready() -> None:
    """Live model: a dotted DOB stays a product label (DATE when the model
    calls it ipv4). Exact fragmentation is the model's own call."""
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


def test_replace_blank_preserves_protocol_caret() -> None:
    """Blank ID must not turn Abdomen^24ACRIN into Abdomen 24ACRIN."""
    text = "Abdomen^24ACRIN_Colo (Adult)"
    # Abdomen^ = 0:8, 24ACRIN = 8:15
    ents = [Entity("ID", 8, 15, 1.0, "ID")]
    blank, _ = replace_entities(text, ents, mode="blank", locale="en_US")
    assert "^" in blank
    assert blank.startswith("Abdomen^")
    assert "24ACRIN" not in blank


def test_replace_blank_strips_pn_caret_next_to_name() -> None:
    """PN separators adjacent to blanked names are removed; no global ^ wipe."""
    text = "DOE^JOHN"
    ents = [
        Entity("LAST_NAME", 0, 3, 1.0, "last_name"),
        Entity("FIRST_NAME", 4, 8, 1.0, "first_name"),
    ]
    blank, _ = replace_entities(text, ents, mode="blank", locale="en_US")
    assert "^" not in blank
    assert "DOE" not in blank and "JOHN" not in blank


def test_replace_blank_removes_for_before_name_or_id() -> None:
    """Leading 'for ' before blanked name/ID is removed; other 'for' kept."""
    text = "MRI BREAST BILAT CAD WWO for Amy Swanson"
    ents = [
        Entity("FIRST_NAME", text.index("Amy"), text.index("Amy") + 3, 1.0, "first_name"),
        Entity("LAST_NAME", text.index("Swanson"), text.index("Swanson") + 7, 1.0, "last_name"),
    ]
    blank, _ = replace_entities(text, ents, mode="blank", locale="en_US")
    assert blank == "MRI BREAST BILAT CAD WWO"
    assert "for" not in blank
    assert "BILAT" in blank

    id_text = "series for 689-96-0899 done"
    id_ents = [Entity("ID", id_text.index("689"), id_text.index("689") + 11, 1.0, "ID")]
    id_blank, _ = replace_entities(id_text, id_ents, mode="blank", locale="en_US")
    assert id_blank == "series done"

    # DATE blank must not strip a clinical 'for'
    clinical = "scan for metastasis on 20190524"
    date_ents = [Entity("DATE", clinical.index("20190524"), clinical.index("20190524") + 8, 1.0, "DATE")]
    clinical_blank, _ = replace_entities(clinical, date_ents, mode="blank", locale="en_US")
    assert "for" in clinical_blank
    assert "metastasis" in clinical_blank


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


def test_scored_labels_universe_matches_colors_display_and_synth() -> None:
    assert set(ENTITY_COLORS_HEX) == set(SCORED_LABELS)
    # Unknown labels fall through to the raw code; scored labels must resolve.
    assert entity_label_display("NOT_A_SCORED_LABEL") == "NOT_A_SCORED_LABEL"
    for label in SCORED_LABELS:
        display = entity_label_display(label)
        assert display
        assert entity_label_display(label.lower()) == display
        synth = generate_synthetic_phi(
            label,
            project_id="universe",
            anon_ptid="A1",
            ordinal=0,
            source_fragment="x",
        )
        assert synth
        assert synth != "REDACTED"


@pytest.mark.parametrize("raw_key", sorted(_TO_SCORED))
def test_to_scored_alias_maps_into_scored_labels(raw_key: str) -> None:
    mapped = _to_scored_label(raw_key)
    assert mapped is not None
    assert mapped in SCORED_LABELS
    assert mapped == _TO_SCORED[raw_key]


@pytest.mark.parametrize(
    "raw_group",
    ["B-FIRST_NAME", "I-LAST_NAME", "first_name", "EMAIL_ADDRESS", "MRN"],
)
def test_to_scored_label_normalizes_prefixes_and_aliases(raw_group: str) -> None:
    mapped = _to_scored_label(raw_group)
    assert mapped in SCORED_LABELS


def test_detect_entities_keeps_low_score_mapped_spans() -> None:
    """Product policy: no score threshold — low-confidence mapped spans are kept."""
    text = "Jane"

    def fake_run(_text: str, *, locale: str = "en_US"):
        return [{"entity_group": "FIRST_NAME", "start": 0, "end": 4, "score": 0.01}]

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")
    assert len(ents) == 1
    assert ents[0].label == "FIRST_NAME"
    assert ents[0].score == pytest.approx(0.01)


def test_replace_unsorted_and_overlapping_spans() -> None:
    text = "ABCDEF"
    # Overlap: [0,4) and [2,6); apply right-to-left after sorting by start.
    ents = [
        Entity("ID", 2, 6, 1.0, "ID"),
        Entity("ID", 0, 4, 1.0, "ID"),
    ]
    blank, used = replace_entities(text, ents, mode="blank", locale="en_US")
    assert len(used) == 2
    assert "A" not in blank or blank != text


def test_replace_empty_span_is_noop_for_that_entity() -> None:
    text = "keep me"
    ents = [Entity("ID", 4, 4, 1.0, "ID")]
    blank, used = replace_entities(text, ents, mode="blank", locale="en_US")
    assert used
    assert "keep" in blank


def test_replace_utf8_multibyte_offsets() -> None:
    text = "Name: José"
    # José is J o s é — é is one unicode char; offsets are unicode indices.
    start = text.index("José")
    end = start + len("José")
    ents = [Entity("FIRST_NAME", start, end, 1.0, "first_name")]
    blank, _ = replace_entities(text, ents, mode="blank", locale="en_US")
    assert "José" not in blank
    assert blank.startswith("Name:")


def test_replace_metadata_replacement_wins_over_blank_and_synth() -> None:
    text = "PatientID: MRN123"
    start = text.index("MRN123")
    end = start + len("MRN123")
    ents = [
        Entity(
            "PatientID",
            start,
            end,
            1.0,
            "ID",
            replacement="SITE-0001",
        )
    ]
    blank, _ = replace_entities(text, ents, mode="blank", locale="en_US")
    synth, _ = replace_entities(
        text, ents, mode="synth", locale="en_US", project_id="p", anon_ptid="A1"
    )
    assert "SITE-0001" in blank
    assert "MRN123" not in blank
    assert "SITE-0001" in synth
    assert "MRN123" not in synth


def test_replace_synth_deterministic_per_seed() -> None:
    text = "id=ABC12345"
    start = text.index("ABC12345")
    ents = [Entity("ID", start, start + 8, 1.0, "ID")]
    a, _ = replace_entities(
        text, ents, mode="synth", locale="en_US", project_id="p", anon_ptid="A1"
    )
    b, _ = replace_entities(
        text, ents, mode="synth", locale="en_US", project_id="p", anon_ptid="A1"
    )
    c, _ = replace_entities(
        text, ents, mode="synth", locale="en_US", project_id="p", anon_ptid="A2"
    )
    assert a == b
    assert a != c


def _load_golden_spans() -> list[dict]:
    return json.loads(_GOLDEN_SPANS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_golden_spans(), ids=lambda c: c["id"])
def test_detect_entities_from_recorded_raw_spans(case: dict) -> None:
    text = case["text"]
    raw = case["raw"]
    expect = case["expect"]

    def fake_run(_text: str, *, locale: str = "en_US"):
        del locale
        return list(raw)

    with (
        patch("anonymizer.controller.ai.embedded_phi.ner.engine.ner_ready", return_value=True),
        patch("anonymizer.controller.ai.embedded_phi.ner.engine._run_pipeline", side_effect=fake_run),
    ):
        ents = detect_entities(text, locale="en_US")

    assert [(e.label, e.start, e.end) for e in ents] == [
        (row["label"], row["start"], row["end"]) for row in expect
    ]
    assert all(e.label in SCORED_LABELS for e in ents)
