"""Score pattern-only vs context-only engines on the fair eval corpus."""

from __future__ import annotations

import json
import time
from pathlib import Path

from prototyping.metadata_phi.engines.base import get_engine
from prototyping.metadata_phi.eval import (
    aggregate,
    format_report,
    load_gold,
    radiology_fp_count,
    score_example,
)
from prototyping.metadata_phi.pipeline import analyze_text

# Development sets only — MIDI-B held-out is intentionally excluded.
_GOLD_FILES = (
    "gold_embedded_rexerr.jsonl",
    "gold_embedded_openi.jsonl",
    "gold_cued_phi.jsonl",
    "gold_format_ids.jsonl",
    "gold_long_narrative.jsonl",
    "gold_pseudo_phi_tags.jsonl",
    "gold_herolim_sr_tags.jsonl",
    "gold_tcia_dates.jsonl",
)

_FP_FILES = (
    "fp_rexerr.jsonl",
    "fp_openi.jsonl",
    "fp_tcia_sr.jsonl",
    "fp_radiology_desc.jsonl",
    "fp_pseudo_phi_deid.jsonl",
    "fp_herolim_sr_protocol.jsonl",
)

_SUMMARY_LABELS = {
    "gold_embedded_rexerr.jsonl": "hard_rexerr",
    "gold_embedded_openi.jsonl": "hard_openi",
    "gold_cued_phi.jsonl": "easy_cued",
    "gold_format_ids.jsonl": "format_ids",
    "gold_long_narrative.jsonl": "long_narr",
    "gold_pseudo_phi_tags.jsonl": "pseudo_tags",
    "gold_herolim_sr_tags.jsonl": "herolim_tags",
    "gold_tcia_dates.jsonl": "tcia_dates",
}


def _load_fp_texts(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        rows.append((str(obj.get("id", "")), obj["text"]))
    return rows


def run_corpus_eval(
    corpus_dir: Path,
    *,
    engines: list[str],
    locale: str = "en_US",
    apply_guard: bool = True,
    fp_limits: dict[str, int] | None = None,
) -> str:
    """Return a markdown report. ``fp_limits`` caps per-file FP rows for speed."""
    fp_limits = fp_limits or {}
    sections: list[str] = [
        "# Corpus eval — full tables",
        "",
        f"locale={locale} guard={'on' if apply_guard else 'off'}",
        "",
        "See `eval_corpus.md` for the formatted scientific summary.",
        "MIDI-B held-out is not included.",
        "",
        "Detectors scored separately:",
        "- `patterns`: regex/cue pack only",
        "- `spacy_ner`: spaCy NER only",
        "- `presidio_transformers`: Presidio DATE_TIME/phone/email + spaCy + locale "
        "patterns; UID tags/spans excluded",
        "",
    ]
    # Compact F1 pivot for machine use; human summary lives in eval_corpus.md
    summary_rows: list[str] = []

    for engine_name in engines:
        t0 = time.perf_counter()
        sections.append(f"# Engine: `{engine_name}`")
        sections.append("")
        eng = get_engine(engine_name)
        if not eng.is_available():
            err = getattr(eng, "_error", "") or "unavailable"
            sections.append(f"SKIP unavailable: {err}")
            sections.append("")
            summary_rows.append(f"| {engine_name} | — | unavailable | | | | | |")
            continue

        for fname in _GOLD_FILES:
            path = corpus_dir / fname
            if not path.is_file():
                sections.append(f"## {fname}")
                sections.append("")
                sections.append("SKIP missing file")
                sections.append("")
                continue
            gold = load_gold(path)
            per = [
                score_example(
                    ex.spans,
                    analyze_text(
                        ex.text,
                        engine=eng,
                        locale=locale,
                        apply_guard=apply_guard,
                    ),
                )
                for ex in gold
            ]
            scores = aggregate(per)
            sections.append(
                format_report(
                    fname,
                    scores,
                    extra=f"n={len(gold)} engine={engine_name}",
                )
            )
            sections.append("")
            short = _SUMMARY_LABELS.get(fname)
            if short:
                summary_rows.append(
                    "| {eng} | {lab} | {n:.3f} | {d:.3f} | {loc:.3f} | {i:.3f} | {p:.3f} | {e:.3f} |".format(
                        eng=engine_name,
                        lab=short,
                        n=scores["NAME"].f1,
                        d=scores["DATE"].f1,
                        loc=scores["LOCATION"].f1,
                        i=scores["ID"].f1,
                        p=scores["PHONE"].f1,
                        e=scores["EMAIL"].f1,
                    )
                )

        for fname in _FP_FILES:
            path = corpus_dir / fname
            if not path.is_file():
                continue
            texts = _load_fp_texts(path)
            limit = fp_limits.get(fname)
            if limit is not None:
                texts = texts[:limit]
            pred_by_text = [
                (
                    text,
                    analyze_text(
                        text,
                        engine=eng,
                        locale=locale,
                        apply_guard=apply_guard,
                    ),
                )
                for _id, text in texts
            ]
            counts = radiology_fp_count(pred_by_text)
            dirty = sum(1 for _t, preds in pred_by_text if preds)
            sections.append(f"## {fname} (false-alarm)")
            sections.append("")
            sections.append(
                f"n={len(texts)} docs_with_any_hit={dirty} label_counts={counts or {}}"
            )
            sections.append("")

        elapsed = time.perf_counter() - t0
        sections.append(f"_elapsed_seconds={elapsed:.1f}_")
        sections.append("")

    decision = [
        "# Decision summary",
        "",
        "| engine | set | NAME F1 | DATE F1 | LOCATION F1 | ID F1 | PHONE F1 | EMAIL F1 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *summary_rows,
        "",
    ]
    return "\n".join(decision + sections).rstrip() + "\n"
