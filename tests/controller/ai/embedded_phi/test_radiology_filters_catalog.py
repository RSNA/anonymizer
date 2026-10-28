"""Catalog-driven pre-NER radiology filter regressions (synthetic metadata PHI)."""

from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    DEFAULT_WHITELIST_SIMILARITY,
    collect_anonymized_values,
    mask_text_for_ner,
    prepare_metadata_ner_segments,
)
from tests.controller.ai.embedded_phi.metadata.support_phi_catalog import (
    build_dataset_for_id,
    catalog_by_id,
    ner_items_from_dataset,
)


def test_scott_vs_scout_unmasked_at_default_similarity() -> None:
    """SCOTT vs SCOUT (0.80) stays below STANDARD 0.85 — first name reaches NER."""
    row = catalog_by_id()["scott_vs_scout"]
    body = str(row["text"])
    result = mask_text_for_ner(
        body,
        whitelist=list(row["whitelist"]),
        similarity=DEFAULT_WHITELIST_SIMILARITY,
        log_context="test",
    )
    assert len(result.text) == len(body)
    for token in row["assert_unmasked"]:
        assert token in result.text, f"expected unmasked {token!r} in {result.text!r}"
    for token in row["assert_masked"]:
        assert token not in result.text, f"expected masked {token!r} still in {result.text!r}"
    # Explicit near-miss: SCOUT must not blank Scott at the product default.
    assert DEFAULT_WHITELIST_SIMILARITY == 0.85
    assert "Scott" in result.text
    assert "Kaufman" in result.text


def test_anon_surface_id_masked_via_prepare() -> None:
    """PatientID already on ds is blanked in StudyDescription before NER."""
    row = catalog_by_id()["anon_surface_id"]
    ds = build_dataset_for_id("anon_surface_id")
    items = ner_items_from_dataset(ds)
    study_items = [i for i in items if i.text == row["text"]]
    assert len(study_items) == 1
    prepared = prepare_metadata_ner_segments(
        study_items,
        anon_values=collect_anonymized_values(ds),
        whitelist=[],
        log_context="test",
    )
    assert len(prepared) == 1
    value = prepared[0].ner_text[prepared[0].value_start : prepared[0].value_end]
    for token in row["assert_masked"]:
        assert token not in value
    for token in row["assert_unmasked"]:
        assert token in value
