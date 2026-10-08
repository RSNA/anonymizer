"""Radiology lexicon NAME guard: sources, similarity, logging, no deny file."""

from __future__ import annotations

import logging
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import filter_spans
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import PhiEntity
from anonymizer.controller.ai.embedded_phi.ner.radiology_lexicon import (
    get_radiology_lexicon,
    name_matches_radiology_lexicon,
    radiology_lexicon_name_guard,
)
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match


def test_lexicon_includes_whitelist_radlex_loinc_tokens() -> None:
    get_radiology_lexicon.cache_clear()
    lex = get_radiology_lexicon("en_US")
    assert "axial" in lex.exact or "ax" in lex.exact
    assert "chest" in lex.exact
    assert "brain" in lex.exact
    assert "ct chest" in lex.exact  # common_protocol.txt migrate
    assert any("abdomen" in t for t in lex.exact)
    assert any(len(t) >= 4 for t in lex.fuzzy)


def test_no_radiology_deny_file() -> None:
    deny = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "anonymizer"
        / "controller"
        / "ai"
        / "embedded_phi"
        / "ner"
        / "locales"
        / "en_US"
        / "radiology_deny.txt"
    )
    assert not deny.is_file()


def test_exact_and_fuzzy_name_guard() -> None:
    get_radiology_lexicon.cache_clear()
    assert name_matches_radiology_lexicon("CT CHEST")
    assert name_matches_radiology_lexicon("without contrast")
    # One-char misspelling of a protocol phrase (above 0.85 similarity).
    fuzzy = radiology_lexicon_name_guard("withot contrast")
    assert fuzzy is not None and fuzzy.kind == "fuzzy"
    assert fuzzy.matched_term is not None
    assert radiology_lexicon_name_guard("Jonathan") is None
    assert radiology_lexicon_name_guard("Chesterton") is None
    assert similarity_term_match(
        "AXIAL",
        ["AXIAL", "CHEST"],
        threshold=0.85,
        min_length_ratio=0.75,
        min_term_len=4,
    ).matched


def test_filter_spans_logs_lexicon_guard(caplog) -> None:
    get_radiology_lexicon.cache_clear()
    person = "Alice"
    text = f"{person} CT CHEST"
    spans = [
        PhiEntity("NAME", 0, len(person), 0.95, "NAME"),
        PhiEntity("NAME", text.index("CT CHEST"), text.index("CT CHEST") + len("CT CHEST"), 0.9),
    ]
    with caplog.at_level(logging.INFO, logger="anonymizer.controller.ai.embedded_phi.ner"):
        kept = filter_spans(text, spans, locale="en_US")
    assert any(s.start == 0 and s.end == len(person) for s in kept)
    assert not any("ct chest" in text[s.start : s.end].casefold() for s in kept)
    msgs = "\n".join(r.getMessage() for r in caplog.records)
    assert "NAME guard: dropped OpenMed NAME" in msgs
    assert "ct chest" in msgs.casefold()
    assert "lexicon exact" in msgs.casefold()


def test_detect_phi_import_does_not_load_easyocr_pixel() -> None:
    import anonymizer.controller.ai.embedded_phi.ner.detect_phi as detect_mod

    assert "easyocr" not in detect_mod.__dict__
    # Pixel detect_text must not be imported at module level by detect_phi.
    assert "detect_text" not in detect_mod.__dict__
