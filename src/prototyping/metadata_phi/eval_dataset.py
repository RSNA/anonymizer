"""Accuracy and confusion-matrix evaluation for phi_text_eval.jsonl."""

from __future__ import annotations

import time
from dataclasses import dataclass

from prototyping.metadata_phi.dataset_schema import SCORED_LABELS, load_dataset
from prototyping.metadata_phi.engines.base import get_engine
from prototyping.metadata_phi.eval import _overlap
from prototyping.metadata_phi.pipeline import analyze_text
from prototyping.metadata_phi.types import Span


@dataclass
class BinaryCM:
    """2×2 confusion matrix for a binary decision."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, expected: bool, predicted: bool) -> None:
        if expected and predicted:
            self.tp += 1
        elif not expected and predicted:
            self.fp += 1
        elif expected and not predicted:
            self.fn += 1
        else:
            self.tn += 1

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.n if self.n else 0.0

    def merge(self, other: BinaryCM) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn
        self.tn += other.tn


@dataclass
class SpanCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0


def _labels_present(spans: list[Span]) -> set[str]:
    return {s.label for s in spans if s.label in SCORED_LABELS}


def _score_spans(expected: list[Span], predicted: list[Span]) -> dict[str, SpanCounts]:
    out = {lab: SpanCounts() for lab in SCORED_LABELS}
    gold = [s for s in expected if s.label in SCORED_LABELS]
    pred = [s for s in predicted if s.label in SCORED_LABELS]
    gold_used: set[int] = set()
    pred_used: set[int] = set()
    for gi, g in enumerate(gold):
        for pi, p in enumerate(pred):
            if pi in pred_used:
                continue
            if _overlap(g, p):
                out[g.label].tp += 1
                gold_used.add(gi)
                pred_used.add(pi)
                break
    for gi, g in enumerate(gold):
        if gi not in gold_used:
            out[g.label].fn += 1
    for pi, p in enumerate(pred):
        if pi not in pred_used:
            out[p.label].fp += 1
    return out


def _format_cm(title: str, cm: BinaryCM) -> str:
    lines = [
        f"### {title}",
        "",
        f"N = {cm.n} accuracy = {cm.accuracy:.4f}",
        "",
        "|  | pred PHI | pred no PHI |",
        "| --- | ---: | ---: |",
        f"| **expected PHI** | TP {cm.tp} | FN {cm.fn} |",
        f"| **expected no PHI** | FP {cm.fp} | TN {cm.tn} |",
        "",
    ]
    return "\n".join(lines)


def run_dataset_eval(
    dataset_path,
    *,
    engines: list[str],
    locale: str = "en_US",
    apply_guard: bool = True,
) -> str:
    examples = load_dataset(dataset_path)
    sections: list[str] = [
        "# PHI text dataset evaluation",
        "",
        f"dataset=`{dataset_path}` N={len(examples)} locale={locale} "
        f"guard={'on' if apply_guard else 'off'}",
        "",
        "Primary metrics: document-level accuracy and 2×2 confusion matrices.",
        "Labels: " + ", ".join(SCORED_LABELS),
        "",
    ]

    for engine_name in engines:
        t0 = time.perf_counter()
        eng = get_engine(engine_name)
        sections.append(f"# Engine: `{engine_name}`")
        sections.append("")
        if not eng.is_available():
            err = getattr(eng, "_error", "") or "unavailable"
            sections.append(f"SKIP: {err}")
            sections.append("")
            continue

        doc_cm = BinaryCM()
        by_len: dict[str, BinaryCM] = {
            "short": BinaryCM(),
            "medium": BinaryCM(),
            "long": BinaryCM(),
        }
        label_cm: dict[str, BinaryCM] = {lab: BinaryCM() for lab in SCORED_LABELS}
        span_tot: dict[str, SpanCounts] = {lab: SpanCounts() for lab in SCORED_LABELS}

        for ex in examples:
            pred = analyze_text(
                ex.text, engine=eng, locale=locale, apply_guard=apply_guard
            )
            # Restrict to scored labels for document decisions
            pred_scored = [s for s in pred if s.label in SCORED_LABELS]
            exp_pos = bool(ex.spans)
            pred_pos = bool(pred_scored)
            doc_cm.add(exp_pos, pred_pos)
            by_len.setdefault(ex.length_class, BinaryCM()).add(exp_pos, pred_pos)

            exp_labs = _labels_present(ex.spans)
            pred_labs = _labels_present(pred_scored)
            for lab in SCORED_LABELS:
                label_cm[lab].add(lab in exp_labs, lab in pred_labs)

            for lab, sc in _score_spans(ex.spans, pred_scored).items():
                span_tot[lab].tp += sc.tp
                span_tot[lab].fp += sc.fp
                span_tot[lab].fn += sc.fn

        sections.append("## Document: any PHI present?")
        sections.append("")
        sections.append(_format_cm("Overall", doc_cm))
        for lc in ("short", "medium", "long"):
            sections.append(_format_cm(f"length_class = {lc}", by_len[lc]))

        sections.append("## Document: per-label presence")
        sections.append("")
        for lab in SCORED_LABELS:
            sections.append(_format_cm(lab, label_cm[lab]))

        sections.append("## Span location counts (overlap, same label)")
        sections.append("")
        sections.append("| label | TP | FP | FN |")
        sections.append("| --- | ---: | ---: | ---: |")
        for lab in SCORED_LABELS:
            sc = span_tot[lab]
            sections.append(f"| {lab} | {sc.tp} | {sc.fp} | {sc.fn} |")
        sections.append("")
        sections.append(f"_elapsed_seconds={time.perf_counter() - t0:.1f}_")
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
