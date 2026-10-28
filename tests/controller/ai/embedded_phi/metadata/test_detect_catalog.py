"""Catalog-driven metadata PHI detect (mocked NER; public + private carriers)."""

from unittest.mock import patch

import pytest

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_phi_in_texts
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity, SCORED_LABELS
from tests.controller.ai.embedded_phi.metadata.support_phi_catalog import (
    assert_private_names_include_creators,
    build_dataset_for_id,
    catalog_by_id,
    extract_public_private,
    load_metadata_phi_catalog,
    ner_items_from_dataset,
    resolve_plant_rows,
)


def _rows_with_expect_labels() -> list[dict]:
    return [
        row
        for row in load_metadata_phi_catalog()
        if row.get("expect_labels") and row.get("scope") in {"public", "private"}
    ]


def _fake_entities_for_text(ner_text: str, labels: list[str], needles: list[str]) -> list[Entity]:
    """Place one span per label on successive needles found in ner_text."""
    ents: list[Entity] = []
    search_from = 0
    for label, needle in zip(labels, needles, strict=False):
        idx = ner_text.find(needle, search_from)
        if idx < 0:
            idx = ner_text.find(needle)
        if idx < 0:
            continue
        ents.append(
            Entity(
                label=label,
                start=idx,
                end=idx + len(needle),
                score=0.99,
                raw_label=label.lower(),
            )
        )
        search_from = idx + len(needle)
    # If fewer needles than labels, still emit remaining labels on first needle.
    while len(ents) < len(labels) and needles:
        needle = needles[min(len(ents), len(needles) - 1)]
        idx = ner_text.find(needle)
        if idx < 0:
            break
        ents.append(
            Entity(
                label=labels[len(ents)],
                start=idx,
                end=idx + len(needle),
                score=0.9,
                raw_label=labels[len(ents)].lower(),
            )
        )
    return ents


@pytest.mark.parametrize("row", _rows_with_expect_labels(), ids=lambda r: r["id"])
def test_catalog_extract_scope_and_detect_labels(row: dict) -> None:
    """Each public/private plant extracts with correct scope and remaps mocked labels."""
    ds = build_dataset_for_id(row["id"])
    public_rows, private_rows = extract_public_private(ds)
    if row["scope"] == "public":
        match = [r for r in public_rows if r.text == row["text"]]
        assert match, f"public text missing for {row['id']}: {[r.text for r in public_rows]}"
        assert not match[0].is_private
    else:
        match = [r for r in private_rows if r.text == row["text"]]
        assert match, f"private text missing for {row['id']}"
        assert match[0].is_private
        assert_private_names_include_creators(match, [str(row["private_creator"])])

    expect = list(row["expect_labels"])
    assert all(label in SCORED_LABELS for label in expect)
    needles = list(row.get("assert_unmasked") or [])
    if not needles:
        needles = [row["text"]]

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        return _fake_entities_for_text(text, expect, needles)

    items = ner_items_from_dataset(ds)
    whitelist = list(row.get("whitelist") or [])
    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(ds=ds, items=items, whitelist=whitelist)

    assert row["text"] in out, f"detect missed original text for {row['id']}: keys={list(out)}"
    labels_found = {e.label for e in out[row["text"]]}
    assert set(expect) <= labels_found, f"{row['id']}: expected {expect}, got {labels_found}"


def test_combo_public_and_private_in_one_detect() -> None:
    """One Dataset plants public StudyDescription and private contact; detect scores both."""
    by_id = catalog_by_id()
    combo = by_id["combo_public_private"]
    plants = resolve_plant_rows(combo, by_id=by_id)
    assert len(plants) == 2
    assert {p["scope"] for p in plants} == {"public", "private"}

    ds = build_dataset_for_id("combo_public_private")
    public_rows, private_rows = extract_public_private(ds)
    public_texts = {r.text for r in public_rows}
    private_texts = {r.text for r in private_rows}
    for plant in plants:
        if plant["scope"] == "public":
            assert plant["text"] in public_texts
        else:
            assert plant["text"] in private_texts
            assert_private_names_include_creators(
                [r for r in private_rows if r.text == plant["text"]],
                [str(plant["private_creator"])],
            )

    public_plant = next(p for p in plants if p["scope"] == "public")
    private_plant = next(p for p in plants if p["scope"] == "private")

    def _fake_detect(text: str, *, locale: str = "en_US") -> list[Entity]:
        del locale
        ents: list[Entity] = []
        for label, needle in (
            ("FIRST_NAME", "Jane"),
            ("LAST_NAME", "Doe"),
            ("EMAIL", "jane.doe@hospital.org"),
            ("PHONE", "(404) 555-0162"),
        ):
            idx = text.find(needle)
            if idx >= 0:
                ents.append(
                    Entity(label=label, start=idx, end=idx + len(needle), score=0.99, raw_label=label.lower())
                )
        return ents

    with patch(
        "anonymizer.controller.ai.embedded_phi.metadata.detect.detect_entities",
        side_effect=_fake_detect,
    ):
        out = detect_phi_in_texts(
            ds=ds,
            items=ner_items_from_dataset(ds),
            whitelist=[],
        )

    assert public_plant["text"] in out
    assert private_plant["text"] in out
    public_labels = {e.label for e in out[public_plant["text"]]}
    private_labels = {e.label for e in out[private_plant["text"]]}
    assert {"FIRST_NAME", "LAST_NAME"} <= public_labels
    assert {"EMAIL", "PHONE"} <= private_labels


def test_catalog_covers_all_scored_labels() -> None:
    """Union of catalog expect_labels includes every product SCORED_LABEL."""
    seen: set[str] = set()
    for row in load_metadata_phi_catalog():
        seen.update(row.get("expect_labels") or [])
    assert set(SCORED_LABELS) <= seen
