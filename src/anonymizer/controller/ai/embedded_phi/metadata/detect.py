"""Clean Descriptors metadata PHI detect (imaging metadata — not Report View).

Explicit workflow (steps 1–5; scrub continues 6–7)
-------------------------------------------------
1. Collect text + IS/DS cells; honor @safe and anonymizer stamps.
2. Compile NER input (frozen): Tag Name: value. lines (drop non-printable only) — see ner_compile.py.
3. One OpenMed call on that string (chunk only if over model char cap).
4. Remap spans via the compile offset map onto original Content.
5. Post-NER only: whitelist drop (always includes DICOM VR codes), anon drop,
   for/caret expand, date fill.

Public API
----------
detect_phi_in_texts(texts: Iterable[str] | None=None, ds: Dataset | None=None, *, items: Iterable[MetadataNerItem] | None=None, locale: str='en_US', whitelist: Sequence[str] | None=None, whitelist_match_settings: object | None=None, project_dir: Path | None=None, modality: str | None=None, script_operations: Mapping[str, str] | None=None) -> dict[str, tuple[Entity, ...]]
    Run Clean Descriptors detect steps 1–5; return original Content → entities.

entity_count_by_label(entities_by_text: Mapping[str, Sequence[Entity]]) -> dict[str, int]
    Count entity labels across a detect_phi_in_texts result.
"""
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    DICOM_VR_CODES,
    NER_INPUT_VRS,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    compile_ner_input,
    remap_entities_via_offset_map,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import (
    Entity,
    detect_entities,
    expand_entities_for_remove,
    format_tagged_entities,
)
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import (
    MetadataNerItem,
    collect_anonymized_values,
    date_time_pattern_entities,
    is_anon_identity_tag,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    OcrWhitelistMatchSettings,
    load_modality_whitelist,
    load_modality_whitelist_match_settings,
    resolve_whitelist_match,
)
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match
from anonymizer.controller.script.compile import project_script_operations
from anonymizer.controller.script.operands import is_safe_operation

logger = logging.getLogger(__name__)

_TAG_HEX = re.compile(r"[^0-9A-Fa-f]")
# Same cap as engine segment packing; applied to the single compiled string.
_NER_CHUNK_CHARS = 1600


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
    script_operations: Mapping[str, str] | None = None,
) -> dict[str, tuple[Entity, ...]]:
    """Run Clean Descriptors detect steps 1–5; return original Content → entities.

    Args:
        texts: Plain Content strings (used when items is omitted).
        ds: Dataset whose anonymized header values must not be re-scored.
        items: Content cells with field/VR context (preferred over texts).
        locale: NER locale pack.
        whitelist: Effective whitelist terms. None loads the modality
            whitelist for project_dir + modality (pixel SSOT);
            an explicit list (including empty) is used as given.
        whitelist_match_settings: Pixel whitelist matching preset/settings;
            None loads the per-modality sidecar for project_dir.
        project_dir: Project storage dir holding per-modality whitelists
            and the compiled *-anonymizer.script (@safe skip).
        modality: DICOM Modality code selecting the whitelist (e.g. US).
        script_operations: Optional tag→operand map; else loaded from
            project_dir when present.

    Returns:
        Mapping of original Content text to its detected entities (NER plus
        post-NER whitelist/date/expand processing).
    """
    if ds is None:
        raise TypeError("detect_phi_in_texts requires ds")

    effective_whitelist = _with_dicom_vr_allow_terms(
        list(whitelist)
        if whitelist is not None
        else load_modality_whitelist(project_dir, modality)
    )
    if isinstance(whitelist_match_settings, OcrWhitelistMatchSettings):
        match_settings = whitelist_match_settings
    elif whitelist_match_settings is None:
        match_settings = load_modality_whitelist_match_settings(project_dir, modality)
    else:
        match_settings = None
    similarity, min_length_ratio = resolve_whitelist_match(match_settings)

    ops = (
        {str(k).upper(): str(v) for k, v in script_operations.items()}
        if script_operations is not None
        else project_script_operations(project_dir)
    )

    # --- 1. Collect ---------------------------------------------------------
    cells = _coerce_items(texts=texts, items=items)
    if ops:
        cells = [_with_script_operation(item, ops) for item in cells]
    ner_items, skip_notes = _select_ner_cells(cells)
    logger.info(
        "Clean Descriptors step 1/7 collect cells=%d ner=%d skipped=%d %s",
        len(cells),
        len(ner_items),
        len(skip_notes),
        "; ".join(skip_notes[:12]) + ("…" if len(skip_notes) > 12 else ""),
    )
    if not ner_items:
        return {}

    # --- 2. Compile NER input (frozen) --------------------------------------
    # Same Content on several tags: concat once (scrub still writes every tag).
    compile_cells: list[NerCompileCell] = []
    seen_text: set[str] = set()
    for idx, item in enumerate(ner_items):
        if item.text in seen_text:
            continue
        seen_text.add(item.text)
        tag_path = str(item.tag_path or item.tag or item.field_name or "").strip()
        if not tag_path:
            tag_path = f"text:{idx}"
        compile_cells.append(
            NerCompileCell(
                text=item.text,
                field_name=str(item.field_name or "") or "field",
                tag=str(item.tag or ""),
                vr=str(item.vr or "").upper(),
                tag_path=tag_path,
            )
        )
    compiled = compile_ner_input(compile_cells)
    logger.info(
        "Clean Descriptors step 2/7 compile NER input chars=%d cells=%d\n<<<\n%s\n>>>",
        len(compiled.ner_text),
        len(compiled.cells),
        compiled.ner_text,
    )
    if not compiled.ner_text:
        return {}

    # --- 3. OpenMed once ----------------------------------------------------
    raw_ents = _detect_on_compiled(compiled.ner_text, locale=locale)
    logger.info(
        "Clean Descriptors step 3/7 OpenMed entities=%d locale=%s\n<<< raw\n%s\n>>>",
        len(raw_ents),
        locale,
        _format_raw_spans(compiled.ner_text, raw_ents),
    )

    # --- 4. Remap via offset map --------------------------------------------
    by_text = remap_entities_via_offset_map(raw_ents, compiled)
    remap_lines = [
        f"{_field_for_text(compiled, text)}: {format_tagged_entities(text, ents)}"
        for text, ents in by_text.items()
        if ents
    ]
    logger.info(
        "Clean Descriptors step 4/7 remap tags=%d\n<<<\n%s\n>>>",
        len(remap_lines),
        "\n".join(remap_lines) if remap_lines else "(none)",
    )

    # --- 5. Post-NER processing only ----------------------------------------
    anon = collect_anonymized_values(ds)
    out: dict[str, tuple[Entity, ...]] = {}
    whitelist_dropped = 0
    anon_dropped = 0
    expanded = 0
    pattern_added = 0
    for text, ents in by_text.items():
        kept, w_drop, a_drop = _drop_whitelist_and_anon(
            text,
            ents,
            whitelist=effective_whitelist,
            anon_values=anon,
            similarity=similarity,
            min_length_ratio=min_length_ratio,
        )
        whitelist_dropped += w_drop
        anon_dropped += a_drop
        before_expand = [(e.start, e.end) for e in kept]
        kept = expand_entities_for_remove(text, kept)
        expanded += sum(
            1
            for (a0, a1), e in zip(before_expand, kept, strict=True)
            if a0 != e.start or a1 != e.end
        )
        pattern = date_time_pattern_entities(text)
        merged = _merge_ner_then_patterns(kept, pattern)
        if len(merged) > len(kept):
            pattern_added += len(merged) - len(kept)
        if merged:
            out[text] = tuple(merged)

    # Cells with no NER hit may still get pattern DATE fills.
    for cell in compiled.cells:
        text = cell.text
        if text in out:
            continue
        pattern = date_time_pattern_entities(text)
        if not pattern:
            continue
        pattern_added += len(pattern)
        out[text] = tuple(pattern)

    logger.info(
        "Clean Descriptors step 5/7 post-NER whitelist_drop=%d anon_drop=%d "
        "expand=%d pattern_date_fills=%d with_phi=%d "
        "whitelist_terms=%d similarity=%.2f",
        whitelist_dropped,
        anon_dropped,
        expanded,
        pattern_added,
        len(out),
        len(effective_whitelist),
        similarity,
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


def _detect_on_compiled(ner_text: str, *, locale: str) -> list[Entity]:
    """One OpenMed pass; chunk the compiled string only when over the char cap."""
    if len(ner_text) <= _NER_CHUNK_CHARS:
        logger.info("Clean Descriptors step 3/7 OpenMed chunks=1")
        return detect_entities(ner_text, locale=locale)

    chunks = 0
    out: list[Entity] = []
    for start in range(0, len(ner_text), _NER_CHUNK_CHARS):
        chunk = ner_text[start : start + _NER_CHUNK_CHARS]
        chunks += 1
        for ent in detect_entities(chunk, locale=locale):
            out.append(
                Entity(
                    label=ent.label,
                    start=ent.start + start,
                    end=ent.end + start,
                    score=ent.score,
                    raw_label=ent.raw_label,
                    replacement=ent.replacement,
                )
            )
    logger.info("Clean Descriptors step 3/7 OpenMed chunks=%d", chunks)
    return out


def _select_ner_cells(
    cells: Sequence[MetadataNerItem],
) -> tuple[list[MetadataNerItem], list[str]]:
    """Pick cells for frozen NER concat; record skip reasons for the log."""
    kept: list[MetadataNerItem] = []
    notes: list[str] = []
    for item in cells:
        field = str(item.field_name or item.tag or "field").strip() or "field"
        vr = str(item.vr or "").upper()
        if item.is_anonymizer_field:
            notes.append(f"{field}:stamp")
            continue
        if is_anon_identity_tag(
            tag_path=str(item.tag_path or ""),
            tag=str(item.tag or ""),
            field_name=str(item.field_name or ""),
        ):
            notes.append(f"{field}:identity")
            continue
        if item.is_date or vr in {"DA", "DT"}:
            notes.append(f"{field}:date")
            continue
        if is_safe_operation(item.script_operation or ""):
            notes.append(f"{field}:@safe")
            continue
        if vr == "UI":
            notes.append(f"{field}:UI")
            continue
        if vr in NER_INPUT_VRS or not vr:
            # Empty VR: plain-text call path (texts=). IS/DS are in NER_INPUT_VRS.
            kept.append(item)
            continue
        notes.append(f"{field}:vr={vr or '?'}")
    return kept, notes


def _with_dicom_vr_allow_terms(whitelist: Sequence[str]) -> list[str]:
    """Append DICOM VR codes so post-NER always allows spans that are only a VR.

    Args:
        whitelist: Modality / caller whitelist terms (may already include some VRs).

    Returns:
        Whitelist plus any missing two-letter DICOM VR codes (sorted).
    """
    seen = {str(t).strip().upper() for t in whitelist if str(t).strip()}
    out = [str(t).strip() for t in whitelist if str(t).strip()]
    for vr in sorted(DICOM_VR_CODES):
        if vr not in seen:
            out.append(vr)
            seen.add(vr)
    return out


def _drop_whitelist_and_anon(
    text: str,
    ents: Sequence[Entity],
    *,
    whitelist: Sequence[str],
    anon_values: Sequence[str] | set[str] | frozenset[str],
    similarity: float,
    min_length_ratio: float,
) -> tuple[list[Entity], int, int]:
    """Drop post-NER spans that match whitelist terms or anon header surfaces."""
    anon = frozenset(str(v).strip() for v in anon_values if str(v).strip())
    terms = [str(t).strip() for t in whitelist if str(t).strip()]
    kept: list[Entity] = []
    w_drop = 0
    a_drop = 0
    for ent in ents:
        span = text[ent.start : ent.end].strip()
        if not span:
            continue
        if span in anon:
            a_drop += 1
            logger.info(
                "Clean Descriptors step 5/7 drop anon field_span=%r",
                span[:60],
            )
            continue
        if terms:
            hit = similarity_term_match(
                span,
                terms,
                threshold=similarity,
                min_length_ratio=min_length_ratio,
            )
            if hit.matched:
                w_drop += 1
                logger.info(
                    "Clean Descriptors step 5/7 drop whitelist span=%r term=%r",
                    span[:60],
                    hit.term,
                )
                continue
        kept.append(ent)
    return kept, w_drop, a_drop


def _merge_ner_then_patterns(
    ner_ents: Sequence[Entity],
    pattern_ents: Sequence[Entity],
) -> list[Entity]:
    """NER first; add pattern DATE only where it does not overlap NER."""
    merged = list(ner_ents)
    occupied = [(e.start, e.end) for e in merged]
    for ent in pattern_ents:
        if any(ent.start < b and ent.end > a for a, b in occupied):
            continue
        merged.append(ent)
        occupied.append((ent.start, ent.end))
    merged.sort(key=lambda e: (e.start, e.end))
    return merged


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


def _tag_hex8(tag: str) -> str:
    """Normalize (GGGG,EEEE) or GGGGEEEE to eight uppercase hex digits."""
    return _TAG_HEX.sub("", str(tag or "")).upper()


def _with_script_operation(
    item: MetadataNerItem,
    ops: Mapping[str, str],
) -> MetadataNerItem:
    """Fill script_operation from ops when the item does not already set one."""
    if item.script_operation:
        return item
    op = ops.get(_tag_hex8(item.tag), "")
    if not op:
        return item
    return replace(item, script_operation=op)


def _field_for_text(compiled, text: str) -> str:
    for cell in compiled.cells:
        if cell.text == text:
            return cell.field_name or cell.tag_path or "field"
    return "field"


def _format_raw_spans(ner_text: str, ents: Sequence[Entity]) -> str:
    if not ents:
        return "(none)"
    parts = [
        f"{e.label}[{e.start}:{e.end}]={ner_text[e.start:e.end]!r}"
        for e in ents
    ]
    return "\n".join(parts)
