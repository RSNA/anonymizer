"""OpenMed presentation probe: compiled chunk vs isolated tag string.

When MIDI text_removed PHI is missed under the product Clean Descriptors
compile layout, re-test the same tag Content alone. Cases where isolation
recovers the span are presentation-sensitive; misses in both are model gaps.

Public API
----------
ProbeCase
    One unique (field, body, needle) under-remove sample.

ProbeResult
    Chunk vs isolated OpenMed coverage for one ProbeCase.

load_underremove_cases(discrepancy_csv, *, limit=0) -> list[ProbeCase]
    Unique text_removed needles still present in answer_value.

probe_case(case, *, detect_options=None, distractors=None) -> ProbeResult
    Run OpenMed on multi-tag chunk and isolated presentations.

write_probe_report(results, out_dir) -> Path
    Write summary Markdown + JSON case list.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.metadata.detect import (
    DEFAULT_NER_DETECT_OPTIONS,
    NerDetectOptions,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    NerCompileOptions,
    compile_ner_input,
    remap_entities_via_offset_map,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import Entity, detect_entities

logger = logging.getLogger(__name__)

# Clinical distractors so the probe chunk resembles a multi-tag compile.
_DEFAULT_DISTRACTORS: tuple[tuple[str, str, str, str], ...] = (
    ("Series Description", "AXIAL T2 FSE", "(0008,103e)", "LO"),
    ("Slice Thickness", "5.0", "(0018,0050)", "DS"),
    ("Image Comments", "supine", "(0020,4000)", "LT"),
    ("Contrast Bolus Agent", "OMNISCAN", "(0018,0010)", "LO"),
    ("Study Description", "CT ABDOMEN", "(0008,1030)", "LO"),
)


@dataclass(frozen=True, slots=True)
class ProbeCase:
    """One unique under-remove sample to probe."""

    field_name: str
    tag_ds: str
    body: str
    needle: str
    fail_count: int = 1


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """OpenMed coverage for one case under chunk vs isolated presentations."""

    case: ProbeCase
    chunk_hit: bool
    isolated_wrapped_hit: bool
    isolated_raw_hit: bool
    classification: str
    chunk_spans: tuple[str, ...] = ()
    isolated_wrapped_spans: tuple[str, ...] = ()
    isolated_raw_spans: tuple[str, ...] = ()
    chunk_preview: str = ""
    isolated_wrapped_preview: str = ""


def load_underremove_cases(
    discrepancy_csv: Path,
    *,
    limit: int = 0,
    tags: Sequence[str] | None = None,
) -> list[ProbeCase]:
    """
    Load unique text_removed (field, body, needle) rows from a discrepancy CSV.

    Uses answer_value as body (original Content) when the needle appears there.

    Args:
        discrepancy_csv: Official discrepancy_report_participant.csv path.
        limit: Max unique cases (0 = all).
        tags: Optional MIDI tag_ds allow-list (e.g. Protocol Name only).

    Returns:
        Deduped ProbeCase list sorted by fail_count descending.
    """
    tag_names = {
        "<(0018,1030)>": "Protocol Name",
        "<(0008,103e)>": "Series Description",
        "<(0008,1030)>": "Study Description",
        "<(0010,21b0)>": "Additional Patient History",
        "<(0032,1060)>": "Requested Procedure Description",
        "<(0032,4000)>": "Study Comments",
        "<(0020,4000)>": "Image Comments",
        "<(0040,0275)>[<0000>]<(0040,0007)>": "Scheduled Procedure Step Description",
    }
    allow = set(tags) if tags else None
    counts: dict[tuple[str, str, str, str], int] = {}
    with Path(discrepancy_csv).open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("action") != "<text_removed>":
                continue
            tag_ds = str(row.get("tag_ds") or "")
            if allow is not None and tag_ds not in allow:
                continue
            body = _strip_angles(row.get("answer_value"))
            needle = _strip_angles(row.get("action_text"))
            if not body or not needle:
                continue
            if needle.lower() not in body.lower():
                continue
            field_name = tag_names.get(tag_ds) or _strip_angles(row.get("tag_name")) or "field"
            key = (field_name, tag_ds, body, needle)
            counts[key] = counts.get(key, 0) + 1

    cases = [
        ProbeCase(
            field_name=field_name,
            tag_ds=tag_ds,
            body=body,
            needle=needle,
            fail_count=n,
        )
        for (field_name, tag_ds, body, needle), n in counts.items()
    ]
    cases.sort(key=lambda c: (-c.fail_count, c.field_name, c.needle, c.body))
    if limit > 0:
        cases = cases[:limit]
    return cases


def probe_case(
    case: ProbeCase,
    *,
    detect_options: NerDetectOptions | None = None,
    distractors: Sequence[tuple[str, str, str, str]] | None = None,
) -> ProbeResult:
    """
    Run OpenMed on a multi-tag product chunk and on the tag string alone.

    Args:
        case: Under-remove sample.
        detect_options: Compile + chunk settings (product defaults if None).
        distractors: (field_name, text, tag, vr) rows packed around the target.

    Returns:
        ProbeResult with classification:
        - chunk_hit
        - presentation_sensitive (chunk miss, isolated hit)
        - model_gap (chunk miss, isolated miss)
    """
    opts = detect_options or DEFAULT_NER_DETECT_OPTIONS
    compile_opts = opts.compile
    fillers = list(distractors) if distractors is not None else list(_DEFAULT_DISTRACTORS)

    target = NerCompileCell(
        text=case.body,
        field_name=case.field_name,
        tag=case.tag_ds,
        vr="LO",
        tag_path=case.field_name.replace(" ", ""),
    )
    chunk_cells: list[NerCompileCell] = []
    # Put target near the middle of distractors.
    mid = max(1, len(fillers) // 2)
    for i, (fname, text, tag, vr) in enumerate(fillers):
        if i == mid:
            chunk_cells.append(target)
        chunk_cells.append(
            NerCompileCell(
                text=text,
                field_name=fname,
                tag=tag,
                vr=vr,
                tag_path=fname.replace(" ", ""),
            )
        )
    if mid >= len(fillers):
        chunk_cells.append(target)

    chunk_hit, chunk_spans, chunk_preview = _openmed_on_compiled(
        chunk_cells,
        target_text=case.body,
        needle=case.needle,
        compile_opts=compile_opts,
        chunk_chars=opts.chunk_chars,
        chunk_overlap=opts.chunk_overlap,
    )
    wrapped_hit, wrapped_spans, wrapped_preview = _openmed_on_compiled(
        [target],
        target_text=case.body,
        needle=case.needle,
        compile_opts=compile_opts,
        chunk_chars=opts.chunk_chars,
        chunk_overlap=opts.chunk_overlap,
    )
    raw_hit, raw_spans, _raw_preview = _openmed_on_raw(case.body, case.needle)

    if chunk_hit:
        classification = "chunk_hit"
    elif wrapped_hit or raw_hit:
        classification = "presentation_sensitive"
    else:
        classification = "model_gap"

    return ProbeResult(
        case=case,
        chunk_hit=chunk_hit,
        isolated_wrapped_hit=wrapped_hit,
        isolated_raw_hit=raw_hit,
        classification=classification,
        chunk_spans=tuple(chunk_spans),
        isolated_wrapped_spans=tuple(wrapped_spans),
        isolated_raw_spans=tuple(raw_spans),
        chunk_preview=chunk_preview,
        isolated_wrapped_preview=wrapped_preview,
    )


def write_probe_report(
    results: Sequence[ProbeResult],
    out_dir: Path,
    *,
    title: str = "NER presentation probe",
) -> Path:
    """
    Write Markdown summary + JSON case list for strategy follow-up.

    Args:
        results: Probe outcomes.
        out_dir: Destination directory (created if needed).
        title: Report heading.

    Returns:
        Path to the Markdown report.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_class: dict[str, list[ProbeResult]] = {}
    for r in results:
        by_class.setdefault(r.classification, []).append(r)

    md_path = out_dir / "NER_PRESENTATION_PROBE.md"
    json_path = out_dir / "ner_presentation_probe_cases.json"

    lines: list[str] = [
        f"# {title}",
        "",
        "OpenMed on the **product multi-tag compile chunk** vs the **same tag "
        "string in isolation** (field-wrapped and raw).",
        "",
        "## Counts",
        "",
        "| Classification | Cases | Fail rows (sum) |",
        "|---|---:|---:|",
    ]
    for key in ("presentation_sensitive", "model_gap", "chunk_hit"):
        rows = by_class.get(key, [])
        fail_sum = sum(r.case.fail_count for r in rows)
        lines.append(f"| `{key}` | {len(rows)} | {fail_sum} |")
    lines.append("")

    def _section(label: str, heading: str, note: str) -> None:
        rows = by_class.get(label, [])
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(note)
        lines.append("")
        if not rows:
            lines.append("(none)")
            lines.append("")
            return
        lines.append("| Fails | Field | Needle | Body (trim) | Isolated wrapped spans | Isolated raw spans |")
        lines.append("|---:|---|---|---|---|---|")
        for r in sorted(rows, key=lambda x: -x.case.fail_count):
            body = _md_cell(r.case.body, 60)
            needle = _md_cell(r.case.needle, 40)
            w = _md_cell(", ".join(r.isolated_wrapped_spans) or "—", 40)
            raw = _md_cell(", ".join(r.isolated_raw_spans) or "—", 40)
            lines.append(f"| {r.case.fail_count} | `{r.case.field_name}` | `{needle}` | `{body}` | `{w}` | `{raw}` |")
        lines.append("")

    _section(
        "presentation_sensitive",
        "Presentation-sensitive (chunk miss, isolated hit)",
        "Model finds the PHI when the tag string is alone — prefer compile / "
        "chunking / packing experiments before treating as a model gap.",
    )
    _section(
        "model_gap",
        "Model gap (chunk miss, isolated miss)",
        "OpenMed misses the needle even on the isolated tag string — regex "
        "post-NER gap-fill or model fine-tune candidates.",
    )
    _section(
        "chunk_hit",
        "Already found in chunk (control)",
        "Needle covered under product multi-tag compile; not a presentation miss.",
    )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "title": title,
        "counts": {
            k: {
                "cases": len(v),
                "fail_rows": sum(r.case.fail_count for r in v),
            }
            for k, v in by_class.items()
        },
        "cases": [_result_dict(r) for r in results],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("wrote %s and %s", md_path, json_path)
    return md_path


def run_probe_from_discrepancy(
    discrepancy_csv: Path,
    out_dir: Path,
    *,
    limit: int = 200,
    tags: Sequence[str] | None = None,
) -> Path:
    """
    Load under-remove cases, probe each, write the report.

    Args:
        discrepancy_csv: Path to discrepancy_report_participant.csv.
        out_dir: Report output directory.
        limit: Max unique cases to probe (OpenMed cost).
        tags: Optional tag_ds filter.

    Returns:
        Path to the Markdown report.
    """
    cases = load_underremove_cases(discrepancy_csv, limit=limit, tags=tags)
    logger.info("probing %d unique under-remove cases from %s", len(cases), discrepancy_csv)
    results = [probe_case(c) for c in cases]
    return write_probe_report(
        results,
        out_dir,
        title=f"NER presentation probe — {discrepancy_csv.parent.parent.parent.name}",
    )


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------


def _strip_angles(value: object) -> str:
    s = "" if value is None else str(value).strip()
    if s.startswith("<") and s.endswith(">") and len(s) >= 2:
        return s[1:-1]
    return s


def _needle_covered(body: str, needle: str, ents: Sequence[Entity]) -> bool:
    n = needle.lower()
    for ent in ents:
        span = body[ent.start : ent.end].lower()
        if n in span or span in n:
            return True
        toks = [t for t in n.replace(".", " ").split() if len(t) > 1]
        if toks and all(t in span for t in toks):
            return True
    return False


def _span_texts(body: str, ents: Sequence[Entity]) -> list[str]:
    return [f"{e.label}:{body[e.start : e.end]}" for e in ents]


def _detect_chunked(
    ner_text: str,
    *,
    chunk_chars: int,
    chunk_overlap: int,
) -> list[Entity]:
    """Mirror Clean Descriptors sliding windows when over the char cap."""
    cap = max(1, int(chunk_chars))
    if len(ner_text) <= cap:
        return detect_entities(ner_text)
    overlap = max(0, min(int(chunk_overlap), cap - 1))
    step = max(1, cap - overlap)
    best: dict[tuple[str, int, int], Entity] = {}
    start = 0
    while start < len(ner_text):
        end = min(len(ner_text), start + cap)
        for ent in detect_entities(ner_text[start:end]):
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
    return sorted(best.values(), key=lambda e: (e.start, e.end))


def _openmed_on_compiled(
    cells: Sequence[NerCompileCell],
    *,
    target_text: str,
    needle: str,
    compile_opts: NerCompileOptions,
    chunk_chars: int,
    chunk_overlap: int,
) -> tuple[bool, list[str], str]:
    compiled = compile_ner_input(cells, options=compile_opts)
    raw_ents = _detect_chunked(
        compiled.ner_text,
        chunk_chars=chunk_chars,
        chunk_overlap=chunk_overlap,
    )
    by_text = remap_entities_via_offset_map(raw_ents, compiled)
    ents = by_text.get(target_text, [])
    preview = compiled.ner_text if len(compiled.ner_text) <= 240 else compiled.ner_text[:240] + "…"
    return _needle_covered(target_text, needle, ents), _span_texts(target_text, ents), preview


def _openmed_on_raw(body: str, needle: str) -> tuple[bool, list[str], str]:
    ents = detect_entities(body)
    return _needle_covered(body, needle, ents), _span_texts(body, ents), body[:240]


def _md_cell(text: str, max_len: int) -> str:
    t = str(text).replace("|", "/").replace("\n", " ")
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _result_dict(r: ProbeResult) -> dict:
    d = asdict(r)
    # dataclasses.asdict is fine for nested ProbeCase
    return d
