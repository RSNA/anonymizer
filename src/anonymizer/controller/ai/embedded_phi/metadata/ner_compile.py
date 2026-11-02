"""Clean Descriptors NER input compile (metadata).

Builds one NER string from eligible text/IS/DS cells so OpenMed sees
clinical-report-style context, with a per-character offset map back to
original Content.

Compile layout is configurable (line separator, value terminator) so
format experiments can compare without forking the remap path. Defaults
match the historical layout: one ``Tag Name: value.`` line per tag,
joined by newlines.

Public API
----------
NerCompileCell
    One text cell eligible for the NER concat.

NerOffset
    One NER-input character → owning tag Content offset (-1 if not value).

NerCompileOptions
    Line separator, value terminator, and whether to keep field-name wraps.

CompiledNerInput
    ner_text, offset_map, and cells used to build them.

DEFAULT_NER_COMPILE_OPTIONS
    Historical default: newline between tags, trailing full stop.

compile_ner_input(cells, *, options=DEFAULT_NER_COMPILE_OPTIONS) -> CompiledNerInput
    Wrap each cell; join; build offset map.

remap_entities_via_offset_map(entities, compiled) -> dict[str, list[Entity]]
    Map OpenMed spans on ner_text onto original Content per cell text.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from anonymizer.controller.ai.embedded_phi.ner.engine import Entity

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NerCompileCell:
    """One text cell eligible for the NER concat."""

    text: str
    field_name: str
    tag: str
    vr: str
    tag_path: str


@dataclass(frozen=True, slots=True)
class NerOffset:
    """One NER-input character → owning tag Content offset.

    original_offset is -1 for Field Name prefix, value terminator, and
    between-tag separators.
    """

    tag_path: str
    original_offset: int
    original_text: str
    field_name: str


@dataclass(frozen=True, slots=True)
class NerCompileOptions:
    """How eligible cells are joined into one OpenMed string.

    Args:
        line_sep: Inserted between tags (newline, space, comma+space, …).
        value_terminator: Appended after each value (``.``, ``,``, or empty).
        include_field_name: When True, emit ``Tag Name: value``; else value only.
    """

    line_sep: str = "\n"
    value_terminator: str = "."
    include_field_name: bool = True


DEFAULT_NER_COMPILE_OPTIONS = NerCompileOptions()


@dataclass(frozen=True, slots=True)
class CompiledNerInput:
    """Result of the compile step."""

    ner_text: str
    offset_map: tuple[NerOffset, ...]
    cells: tuple[NerCompileCell, ...]
    options: NerCompileOptions = DEFAULT_NER_COMPILE_OPTIONS


def compile_ner_input(
    cells: Sequence[NerCompileCell],
    *,
    options: NerCompileOptions = DEFAULT_NER_COMPILE_OPTIONS,
) -> CompiledNerInput:
    """
    Wrap each cell; join with options.line_sep; build offset map.

    Value prep drops only non-printable / control characters (stdlib
    str.isprintable / str.isspace); whitespace becomes ASCII space.
    No whitelist mask, no caret rewrite, no anon blanking before the model.

    Args:
        cells: Text cells in extract order (already filtered for @safe / stamps).
        options: Layout for separators and terminators.

    Returns:
        Compiled NER string plus per-character offset map.
    """
    opts = options
    ner_chars: list[str] = []
    offsets: list[NerOffset] = []
    kept_cells: list[NerCompileCell] = []

    def _emit(
        ch: str,
        *,
        tag_path: str,
        original_offset: int,
        original_text: str,
        field_name: str,
    ) -> None:
        ner_chars.append(ch)
        offsets.append(
            NerOffset(
                tag_path=tag_path,
                original_offset=original_offset,
                original_text=original_text,
                field_name=field_name,
            )
        )

    for cell in cells:
        original = str(cell.text or "")
        if not any(ch.isalnum() for ch in original):
            continue
        kept_cells.append(cell)
        name = str(cell.field_name or "").strip()
        if not name or name in {"item", "value", "-"}:
            name = "field"
        value_chars: list[str] = []
        value_offs: list[int] = []
        for i, ch in enumerate(original):
            kept = _ner_safe_char(ch)
            if kept is None:
                continue
            value_chars.append(kept)
            value_offs.append(i)
        if not value_chars or not any(ch.isalnum() for ch in value_chars):
            continue
        if ner_chars and opts.line_sep:
            for ch in opts.line_sep:
                _emit(
                    ch,
                    tag_path="",
                    original_offset=-1,
                    original_text="",
                    field_name="",
                )
        if opts.include_field_name:
            prefix = f"{name}: "
            for ch in prefix:
                _emit(
                    ch,
                    tag_path=cell.tag_path,
                    original_offset=-1,
                    original_text=original,
                    field_name=cell.field_name,
                )
        for orig_i, ch in zip(value_offs, value_chars, strict=True):
            _emit(
                ch,
                tag_path=cell.tag_path,
                original_offset=orig_i,
                original_text=original,
                field_name=cell.field_name,
            )
        for ch in opts.value_terminator:
            _emit(
                ch,
                tag_path=cell.tag_path,
                original_offset=-1,
                original_text=original,
                field_name=cell.field_name,
            )

    ner_text = "".join(ner_chars)
    if len(offsets) != len(ner_text):
        raise RuntimeError("NER compile offset map length mismatch")

    return CompiledNerInput(
        ner_text=ner_text,
        offset_map=tuple(offsets),
        cells=tuple(kept_cells),
        options=opts,
    )


def remap_entities_via_offset_map(
    entities: Sequence[Entity],
    compiled: CompiledNerInput,
) -> dict[str, list[Entity]]:
    """
    Map OpenMed spans on ner_text onto original Content per cell text.

    Characters in Field Name prefixes, value terminators, and between-tag
    separators are skipped. Spans that cover more than one tag's value are
    split at tag boundaries.

    Args:
        entities: Spans with offsets into compiled.ner_text.
        compiled: Output of compile_ner_input.

    Returns:
        Mapping of original Content string → entity list (may merge later).
    """
    out: dict[str, list[Entity]] = {}
    n = len(compiled.offset_map)
    for ent in entities:
        start = max(0, int(ent.start))
        end = min(n, int(ent.end))
        if start >= end:
            continue
        i = start
        while i < end:
            while i < end and compiled.offset_map[i].original_offset < 0:
                i += 1
            if i >= end:
                break
            path = compiled.offset_map[i].tag_path
            original = compiled.offset_map[i].original_text
            run_end = i + 1
            while run_end < end:
                off = compiled.offset_map[run_end]
                if off.original_offset < 0:
                    # Same-tag terminator stays in the run; separators end it.
                    if off.tag_path == path and off.original_text == original:
                        run_end += 1
                        continue
                    break
                if off.tag_path != path or off.original_text != original:
                    break
                run_end += 1
            value_offs = [
                compiled.offset_map[j] for j in range(i, run_end) if compiled.offset_map[j].original_offset >= 0
            ]
            i = run_end
            if not value_offs:
                continue
            first = value_offs[0]
            last = value_offs[-1]
            orig = first.original_text
            orig_start = first.original_offset
            orig_end = last.original_offset + 1
            if orig_start < 0 or orig_end > len(orig) or orig_start >= orig_end:
                continue
            mapped = Entity(
                label=ent.label,
                start=orig_start,
                end=orig_end,
                score=ent.score,
                raw_label=ent.raw_label,
                replacement=ent.replacement,
            )
            out.setdefault(orig, []).append(mapped)

    for text, ents in out.items():
        ents.sort(key=lambda e: (e.start, e.end))
        out[text] = _dedupe_entities(ents)
    return out


def _ner_safe_char(ch: str) -> str | None:
    """Keep Content chars the NER model accepts; drop illegal controls.

    Uses stdlib only: printable text and whitespace. Whitespace becomes
    ASCII space so each value stays one line. Letters, digits,
    punctuation, hyphens, and carets are kept.

    Args:
        ch: One unicode character from original Content.

    Returns:
        Character to emit into NER input, or None to drop.
    """
    if ch.isspace():
        return " "
    if ch.isprintable():
        return ch
    return None


def _dedupe_entities(ents: Sequence[Entity]) -> list[Entity]:
    """Drop exact duplicate spans; keep first."""
    seen: set[tuple[str, int, int]] = set()
    out: list[Entity] = []
    for ent in ents:
        key = (ent.label, ent.start, ent.end)
        if key in seen:
            continue
        seen.add(key)
        out.append(ent)
    return out
