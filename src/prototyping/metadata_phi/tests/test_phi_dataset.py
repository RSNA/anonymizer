"""Definitive phi_text_eval schema checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototyping.metadata_phi.dataset_schema import (
    SCORED_LABELS,
    example_from_dict,
    length_class_for,
    load_dataset,
    validate_spans,
)

DATASET = (
    Path(__file__).resolve().parents[1] / "fixtures" / "en_US" / "dataset" / "phi_text_eval.jsonl"
)


def test_scored_labels() -> None:
    assert SCORED_LABELS == ("NAME", "LOCATION", "ID", "PHONE", "DATE", "EMAIL")


def test_length_class_boundaries() -> None:
    assert length_class_for("x" * 64) == "short"
    assert length_class_for("x" * 65) == "medium"
    assert length_class_for("x" * 400) == "medium"
    assert length_class_for("x" * 401) == "long"


def test_validate_spans_ok_and_bad() -> None:
    text = "Helen Park"
    assert validate_spans(text, [{"label": "NAME", "start": 0, "end": 10}]) == []
    assert validate_spans(text, [{"label": "NAME", "start": 0, "end": 99}]) != []


def test_example_rejects_bad_span() -> None:
    with pytest.raises(ValueError):
        example_from_dict(
            {
                "id": "bad",
                "text": "abc",
                "spans": [{"label": "NAME", "start": 0, "end": 10}],
            }
        )


def test_dataset_file_if_present() -> None:
    if not DATASET.is_file():
        pytest.skip("phi_text_eval.jsonl not built")
    rows = load_dataset(DATASET)
    assert len(rows) == 1200
    assert sum(1 for r in rows if r.spans) == 600
    by_len = {"short": 0, "medium": 0, "long": 0}
    for r in rows:
        by_len[r.length_class] += 1
        for s in r.spans:
            assert s.label in SCORED_LABELS
            assert r.text[s.start : s.end]
    assert by_len == {"short": 300, "medium": 450, "long": 450}
    # First line schema
    obj = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    assert set(obj) >= {"id", "length_class", "text", "spans"}
