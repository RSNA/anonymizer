"""Live OpenMed characterization against curated MIDI-B / long-tail fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS, detect_entities
from tests.prototyping.midi_b.support import NER_ADVERSARIAL_JSONL

pytestmark = [
    pytest.mark.midi_b_integration,
    pytest.mark.prototyping,
]


def _load_rows() -> list[dict]:
    path = NER_ADVERSARIAL_JSONL
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


_ROWS = _load_rows()


@pytest.mark.parametrize("row", _ROWS, ids=lambda r: r.get("id", "row"))
def test_live_ner_must_detect_and_must_not(row: dict) -> None:
    if not ner_ready():
        pytest.skip("PHI NER model not downloaded")
    text = str(row["text"])
    ents = detect_entities(text, locale="en_US")
    covered = set()
    for ent in ents:
        covered.add(text[ent.start : ent.end])
        assert ent.label in SCORED_LABELS

    for needle in row.get("must_detect_substrings") or []:
        assert any(needle in frag or frag in needle for frag in covered) or any(
            needle in text[e.start : e.end] for e in ents
        ), f"residual PHI not detected: {needle!r} in {text!r}; ents={covered}"

    want_labels = set(row.get("must_labels") or [])
    if want_labels:
        got = {e.label for e in ents}
        assert want_labels <= got, f"missing labels {want_labels - got} for {text!r}"

    labeled_frags = [text[e.start : e.end] for e in ents]
    for keeper in row.get("must_not_detect_substrings") or []:
        # Fail when a clinical keeper is itself a labeled span (over-scrub).
        assert not any(frag.casefold() == keeper.casefold() for frag in labeled_frags), (
            f"over-scrub: clinical token {keeper!r} labeled as PHI in {text!r}; "
            f"spans={labeled_frags}"
        )


def test_ner_adversarial_catalog_nonempty() -> None:
    assert NER_ADVERSARIAL_JSONL.is_file()
    assert len(_ROWS) >= 4
