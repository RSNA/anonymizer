"""Metadata Content PHI detect (imaging metadata — not Report View).

Explicit workflow
-----------------
1. Collect Content cells (``MetadataNerItem`` or plain strings).
2. Pre-NER filter → keep only prose; wrap as ``Field Name: value.``.
3. Run NER on the filtered text only.
4. Remap spans back onto original Content (no post-NER FP/FN screens).

Does not use Report View (``entities_from_study_phi`` / ``detect_phi_in_text``).
Does not consult OCR modality whitelists (pixel hide-text only).

Public API: ``detect_phi_in_texts``, ``entity_count_by_label``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.ner.engine import (
    Entity,
    detect_entities,
    detect_entities_in_segments,
)
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    MetadataNerItem,
    collect_anonymized_values,
    prepare_metadata_ner_segments,
    remap_ner_entities_to_original,
)

logger = logging.getLogger(__name__)


def detect_phi_in_texts(
    texts: Iterable[str] | None = None,
    ds: Dataset | None = None,
    *,
    items: Iterable[MetadataNerItem] | None = None,
    locale: str = "en_US",
    whitelist: Sequence[str] | None = None,
    whitelist_match_settings: object | None = None,
    project_dir: Path | None = None,
    modality: str | None = None,
) -> dict[str, tuple[Entity, ...]]:
    """Run the metadata PHI workflow; return original Content → NER entities.

    ``whitelist`` / ``whitelist_match_settings`` / ``project_dir`` / ``modality``
    are accepted for call-site compatibility but ignored — OCR whitelists are
    not applied to metadata NER.
    """
    del whitelist, whitelist_match_settings, project_dir, modality
    if ds is None:
        raise TypeError("detect_phi_in_texts requires ds")

    # --- 1. Collect cells -------------------------------------------------
    cells = _coerce_items(texts=texts, items=items)
    logger.info("metadata detect step1 collect cells=%d", len(cells))
    if not cells:
        return {}

    # --- 2. Pre-NER filter (prose only, field-wrapped; no OCR whitelist) ---
    prepared = prepare_metadata_ner_segments(
        cells,
        whitelist=(),
        anon_values=collect_anonymized_values(ds),
        log_context="metadata",
    )
    logger.info(
        "metadata detect step2 filter keep=%d skip=%d",
        len(prepared),
        len(cells) - len(prepared),
    )
    if not prepared:
        return {}

    # --- 3. NER on filtered text only -------------------------------------
    per_seg = detect_entities_in_segments(
        [p.ner_text for p in prepared],
        locale=locale,
        scan_fn=lambda joined: detect_entities(joined, locale=locale),
    )
    logger.info("metadata detect step3 ner segments=%d", len(prepared))

    # --- 4. Remap only ----------------------------------------------------
    out: dict[str, tuple[Entity, ...]] = {}
    for prep, ner_ents in zip(prepared, per_seg, strict=True):
        mapped = remap_ner_entities_to_original(ner_ents, prep)
        if mapped:
            out[prep.original_text] = tuple(mapped)

    logger.info(
        "metadata detect step4 done with_phi=%d locale=%s",
        len(out),
        locale,
    )
    return out


def entity_count_by_label(
    entities_by_text: Mapping[str, Sequence[Entity]],
) -> dict[str, int]:
    """Count entity labels across a detect_phi_in_texts result."""
    counts: dict[str, int] = {}
    for ents in entities_by_text.values():
        for ent in ents:
            key = str(ent.label or "").strip() or "?"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _coerce_items(
    *,
    texts: Iterable[str] | None,
    items: Iterable[MetadataNerItem] | None,
) -> list[MetadataNerItem]:
    if items is not None:
        return [item for item in items if str(item.text or "").strip()]
    return [
        MetadataNerItem(text=text)
        for raw in texts or ()
        if (text := str(raw or "").strip())
    ]
