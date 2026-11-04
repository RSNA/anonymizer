"""Clean Descriptors metadata PHI detect (imaging metadata — not Report View).

Explicit workflow (steps 1–5; scrub continues 6–7)
-------------------------------------------------
1. Collect text + IS/DS cells; honor @safe and anonymizer stamps.
2. Compile NER input (Tag Name: value + separators) — see ner_compile.py.
3. OpenMed on that string (chunk with optional overlap when over char cap).
4. Remap spans via the compile offset map onto original Content.
5. Post-NER only: whitelist drop (always includes DICOM VR codes), anon drop,
   drop whole-cell pure-numeric false IDs, for/caret/Dr. expand, date +
   descriptor PHI pattern fill (IDs, SSN-like, at/by sites, phone, Dr.).

Public API
----------
NerDetectOptions
    Compile layout + OpenMed chunk size / overlap for format experiments.

DEFAULT_NER_DETECT_OPTIONS
    Product defaults (newline + full stop; 1600-char chunks, 200 overlap).

detect_phi_in_texts(texts: Iterable[str] | None=None, ds: Dataset | None=None, *, items: Iterable[MetadataNerItem] | None=None, locale: str='en_US', whitelist: Sequence[str] | None=None, match_mode: PhiMatchMode | None=None, project_dir: Path | None=None, modality: str | None=None, script_operations: Mapping[str, str] | None=None, detect_options: NerDetectOptions | None=None) -> dict[str, tuple[Entity, ...]]
    Run Clean Descriptors detect steps 1–5; return original Content → entities.

entity_count_by_label(entities_by_text: Mapping[str, Sequence[Entity]]) -> dict[str, int]
    Count entity labels across a detect_phi_in_texts result.
"""

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    DICOM_VR_CODES,
    NER_INPUT_VRS,
    is_pure_numeric_string_value,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    DEFAULT_NER_COMPILE_OPTIONS,
    NerCompileCell,
    NerCompileOptions,
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
    CLINICAL_KEEP_TERMS,
    MetadataNerItem,
    collect_anonymized_values,
    date_time_pattern_entities,
    descriptor_phi_pattern_entities,
    drop_measurement_digit_id_entities,
    is_anon_identity_tag,
)
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import PhiMatchMode, thresholds_for
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_modality_phi_match_mode,
    load_modality_whitelist,
)
from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match
from anonymizer.controller.script.compile import project_script_operations
from anonymizer.controller.script.operands import is_safe_operation

logger = logging.getLogger(__name__)

_TAG_HEX = re.compile(r"[^0-9A-Fa-f]")


@dataclass(frozen=True, slots=True)
class NerDetectOptions:
    """Compile layout and OpenMed chunking for Clean Descriptors detect.

    Args:
        compile: How tags are joined into the NER string.
        chunk_chars: Max characters per OpenMed call (hard window).
        chunk_overlap: Characters of overlap between consecutive chunks
            (0 = abutting windows). Overlap reduces boundary misses.
    """

    compile: NerCompileOptions = DEFAULT_NER_COMPILE_OPTIONS
    chunk_chars: int = 1600
    chunk_overlap: int = 200


# Default: comma terminator + space separator (prose-like) with overlap.
# Chosen to reduce ID/site under-remove vs newline+period packing; pure-numeric
# whole-cell drop addresses the dominant text_retained over-empty mode.
DEFAULT_NER_DETECT_OPTIONS = NerDetectOptions(
    compile=NerCompileOptions(line_sep=" ", value_terminator=","),
    chunk_chars=1600,
    chunk_overlap=200,
)


def detect_phi_in_texts(
    texts: Iterable[str] | None = None,
    ds: Dataset | None = None,
    *,
    items: Iterable[MetadataNerItem] | None = None,
    locale: str = "en_US",
    whitelist: Sequence[str] | None = None,
    match_mode: PhiMatchMode | None = None,
    project_dir: Path | None = None,
    modality: str | None = None,
    script_operations: Mapping[str, str] | None = None,
    detect_options: NerDetectOptions | None = None,
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
        match_mode: PhiMatchMode for whitelist similarity; None loads the
            per-modality sidecar for project_dir.
        project_dir: Project storage dir holding per-modality whitelists
            and the compiled *-anonymizer.script (@safe skip).
        modality: DICOM Modality code selecting the whitelist (e.g. US).
        script_operations: Optional tag→operand map; else loaded from
            project_dir when present.
        detect_options: Compile + chunking; None uses DEFAULT_NER_DETECT_OPTIONS.

    Returns:
        Mapping of original Content text to its detected entities (NER plus
        post-NER whitelist/date/expand processing).
    """
    if ds is None:
        raise TypeError("detect_phi_in_texts requires ds")

    opts = detect_options or DEFAULT_NER_DETECT_OPTIONS

    effective_whitelist = _with_dicom_vr_allow_terms(
        list(whitelist) if whitelist is not None else load_modality_whitelist(project_dir, modality)
    )
    effective_match = match_mode or load_modality_phi_match_mode(project_dir, modality)
    thresholds = thresholds_for(effective_match)
    similarity = thresholds.whitelist_similarity
    min_length_ratio = 0.70

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

    # --- 2. Compile NER input -----------------------------------------------
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
    compiled = compile_ner_input(compile_cells, options=opts.compile)
    logger.info(
        "Clean Descriptors step 2/7 compile NER input chars=%d cells=%d sep=%r term=%r\n<<<\n%s\n>>>",
        len(compiled.ner_text),
        len(compiled.cells),
        opts.compile.line_sep,
        opts.compile.value_terminator,
        compiled.ner_text,
    )
    if not compiled.ner_text:
        return {}

    # --- 3. OpenMed (chunk + overlap when needed) ---------------------------
    raw_ents = _detect_on_compiled(
        compiled.ner_text,
        locale=locale,
        chunk_chars=opts.chunk_chars,
        chunk_overlap=opts.chunk_overlap,
    )
    logger.info(
        "Clean Descriptors step 3/7 OpenMed entities=%d locale=%s chunk_chars=%d overlap=%d\n<<< raw\n%s\n>>>",
        len(raw_ents),
        locale,
        opts.chunk_chars,
        opts.chunk_overlap,
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
    numeric_dropped = 0
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
        kept, n_drop = _drop_pure_numeric_whole_cell(text, kept)
        numeric_dropped += n_drop
        before_expand = [(e.start, e.end) for e in kept]
        kept = expand_entities_for_remove(text, kept)
        expanded += sum(1 for (a0, a1), e in zip(before_expand, kept, strict=True) if a0 != e.start or a1 != e.end)
        pattern = _post_ner_pattern_entities(text)
        merged = _merge_ner_then_patterns(kept, pattern)
        if len(merged) > len(kept):
            pattern_added += len(merged) - len(kept)
        # Pattern ID fills on a pure-numeric whole cell must not wipe retain.
        merged, n_drop2 = _drop_pure_numeric_whole_cell(text, merged)
        numeric_dropped += n_drop2
        # Float fragments / letter-free measurement cells tagged as ID.
        before_meas = len(merged)
        merged = drop_measurement_digit_id_entities(text, merged)
        numeric_dropped += before_meas - len(merged)
        if merged:
            out[text] = tuple(merged)

    # Cells with no NER hit may still get pattern DATE / descriptor PHI fills.
    for cell in compiled.cells:
        text = cell.text
        if text in out:
            continue
        pattern = _post_ner_pattern_entities(text)
        if not pattern:
            continue
        pattern, n_drop2 = _drop_pure_numeric_whole_cell(text, pattern)
        numeric_dropped += n_drop2
        before_meas = len(pattern)
        pattern = drop_measurement_digit_id_entities(text, pattern)
        numeric_dropped += before_meas - len(pattern)
        if not pattern:
            continue
        pattern_added += len(pattern)
        out[text] = tuple(pattern)

    logger.info(
        "Clean Descriptors step 5/7 post-NER whitelist_drop=%d anon_drop=%d "
        "pure_numeric_whole_cell_drop=%d expand=%d pattern_fills=%d "
        "with_phi=%d whitelist_terms=%d similarity=%.2f",
        whitelist_dropped,
        anon_dropped,
        numeric_dropped,
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


def _detect_on_compiled(
    ner_text: str,
    *,
    locale: str,
    chunk_chars: int,
    chunk_overlap: int,
) -> list[Entity]:
    """OpenMed on compiled text; sliding windows when over the char cap.

    Args:
        ner_text: Compiled NER input.
        locale: NER locale pack.
        chunk_chars: Window size (characters).
        chunk_overlap: Overlap between consecutive windows (clamped below
            chunk_chars). Entities from overlapping windows are merged by
            (label, start, end), keeping the highest score.

    Returns:
        Entity list with offsets into ner_text.
    """
    cap = max(1, int(chunk_chars))
    if len(ner_text) <= cap:
        logger.info("Clean Descriptors step 3/7 OpenMed chunks=1")
        return detect_entities(ner_text, locale=locale)

    overlap = max(0, min(int(chunk_overlap), cap - 1))
    step = max(1, cap - overlap)
    best: dict[tuple[str, int, int], Entity] = {}
    chunks = 0
    start = 0
    while start < len(ner_text):
        end = min(len(ner_text), start + cap)
        chunk = ner_text[start:end]
        chunks += 1
        for ent in detect_entities(chunk, locale=locale):
            abs_start = ent.start + start
            abs_end = ent.end + start
            key = (str(ent.label), abs_start, abs_end)
            prev = best.get(key)
            if prev is None or float(ent.score) > float(prev.score):
                best[key] = Entity(
                    label=ent.label,
                    start=abs_start,
                    end=abs_end,
                    score=ent.score,
                    raw_label=ent.raw_label,
                    replacement=ent.replacement,
                )
        if end >= len(ner_text):
            break
        start += step
    out = sorted(best.values(), key=lambda e: (e.start, e.end))
    logger.info(
        "Clean Descriptors step 3/7 OpenMed chunks=%d overlap=%d unique_spans=%d",
        chunks,
        overlap,
        len(out),
    )
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
    """Append DICOM VR codes and clinical keep terms for post-NER allow.

    Args:
        whitelist: Modality / caller whitelist terms (may already include some VRs).

    Returns:
        Whitelist plus missing VR codes and clinical trial / anatomy keep terms.
    """
    seen = {str(t).strip().upper() for t in whitelist if str(t).strip()}
    out = [str(t).strip() for t in whitelist if str(t).strip()]
    for vr in sorted(DICOM_VR_CODES):
        if vr not in seen:
            out.append(vr)
            seen.add(vr)
    for term in CLINICAL_KEEP_TERMS:
        key = term.upper()
        if key not in seen:
            out.append(term)
            seen.add(key)
    return out


# Labels that must not wipe an entire pure-numeric cell (frame counts, GEMS
# parms). DATE on a YYYYMMDD Series Number is intentional text_removed PHI.
_PURE_NUMERIC_WHOLE_CELL_DROP_LABELS = frozenset({"ID", "PHONE"})


def _drop_pure_numeric_whole_cell(
    text: str,
    ents: Sequence[Entity],
) -> tuple[list[Entity], int]:
    """Drop ID/PHONE spans that blank an entire pure-numeric cell.

    MIDI-B text_retained is dominated by whole-cell empties of pure numbers
    (GEMS PET ``0``, frame counts, etc.). Those are not free-text PHI; scrubbing
    the whole cell fails retain. Substring IDs inside prose are kept. DATE fills
    on a whole-cell YYYYMMDD (e.g. Series Number) are kept for text_removed.

    Args:
        text: Original Content cell.
        ents: Post-whitelist entities on that cell.

    Returns:
        (kept entities, drop count).
    """
    body = str(text or "")
    stripped = body.strip()
    if not stripped or not is_pure_numeric_string_value(stripped):
        return list(ents), 0
    # Map strip window into body offsets.
    lead = len(body) - len(body.lstrip())
    trail_start = lead + len(stripped)
    kept: list[Entity] = []
    dropped = 0
    for ent in ents:
        label = str(ent.label or "")
        if label in _PURE_NUMERIC_WHOLE_CELL_DROP_LABELS and ent.start <= lead and ent.end >= trail_start:
            dropped += 1
            logger.info(
                "Clean Descriptors step 5/7 drop pure_numeric_whole_cell span=%r",
                body[ent.start : ent.end][:60],
            )
            continue
        kept.append(ent)
    return kept, dropped


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


def _post_ner_pattern_entities(text: str) -> list[Entity]:
    """DATE fills first, then descriptor PHI gap-fill (no overlapping spans)."""
    return _merge_ner_then_patterns(
        date_time_pattern_entities(text),
        descriptor_phi_pattern_entities(text),
    )


def _merge_ner_then_patterns(
    ner_ents: Sequence[Entity],
    pattern_ents: Sequence[Entity],
) -> list[Entity]:
    """NER first; add pattern fills that do not conflict.

    When a pattern span fully covers one or more existing spans (e.g. NER
    tagged only ``Harris`` but the pattern claims ``Harris Community Clinic``),
    replace those shorter spans with the longer pattern claim so scrub removes
    the full facility phrase.
    """
    merged = list(ner_ents)
    occupied = [(e.start, e.end) for e in merged]
    for ent in pattern_ents:
        overlap_idxs = [i for i, (a, b) in enumerate(occupied) if ent.start < b and ent.end > a]
        if overlap_idxs:
            # Replace only when the pattern strictly expands every overlapped
            # span (e.g. "Harris" → "Harris Community Clinic"). Equal-length
            # overlaps keep the earlier claim so DATE / NER win over a same-span
            # long_digit_id fill.
            if not all(ent.start <= occupied[i][0] and ent.end >= occupied[i][1] for i in overlap_idxs):
                continue
            if not any(ent.start < occupied[i][0] or ent.end > occupied[i][1] for i in overlap_idxs):
                continue
            for i in sorted(overlap_idxs, reverse=True):
                del merged[i]
                del occupied[i]
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
    return [MetadataNerItem(text=text) for raw in texts or () if (text := str(raw or "").strip())]


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
    parts = [f"{e.label}[{e.start}:{e.end}]={ner_text[e.start : e.end]!r}" for e in ents]
    return "\n".join(parts)
