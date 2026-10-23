"""Deeper gold / negatives sanity checks (prototyping; not in CI)."""

from pathlib import Path

from prototyping.metadata_phi.eval import load_gold
from prototyping.metadata_phi.pipeline import analyze_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "en_US"


def test_deep_gold_size_and_labels() -> None:
    gold = load_gold(FIXTURES / "gold.jsonl")
    assert len(gold) >= 25
    labels = {s.label for ex in gold for s in ex.spans}
    assert {"NAME", "DATE", "LOCATION", "ID", "PHONE", "EMAIL"} <= labels


def test_mr_breast_still_clean_on_deep_engine() -> None:
    spans = analyze_text(
        "MR BREAST BILATERAL WITH AND WITHOUT CONTRAST",
        engine="regex_spacy",
        locale="en_US",
    )
    assert spans == []


def test_long_sr_paragraph_finds_core_phi() -> None:
    text = (
        "Patient: Mary Anne Cooper  DOB: 07/22/1975  MRN: MRN784512\n"
        "Phone: 512-555-0198  Email: m.cooper@email.example"
    )
    spans = analyze_text(text, engine="regex_spacy", locale="en_US")
    by_label = {s.label: text[s.start : s.end] for s in spans}
    assert by_label.get("NAME") == "Mary Anne Cooper"
    assert by_label.get("ID") == "MRN784512"
    assert by_label.get("PHONE") == "512-555-0198"
    assert by_label.get("EMAIL") == "m.cooper@email.example"
