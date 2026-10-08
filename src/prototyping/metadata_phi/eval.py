"""Evaluate predicted spans against gold JSONL."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from prototyping.metadata_phi import SCORED_LABELS
from prototyping.metadata_phi.types import GoldExample, Span


@dataclass
class ClassScores:
    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def load_gold(path: str | Path) -> list[GoldExample]:
    examples: list[GoldExample] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        spans = [
            Span(
                label=s["label"],
                start=int(s["start"]),
                end=int(s["end"]),
                score=float(s.get("score", 1.0)),
                raw_label=s.get("raw_label", ""),
            )
            for s in obj.get("spans", [])
        ]
        examples.append(
            GoldExample(
                id=str(obj["id"]),
                text=obj["text"],
                spans=spans,
                notes=obj.get("notes", ""),
            )
        )
    return examples


def _overlap(a: Span, b: Span) -> bool:
    return a.label == b.label and a.start < b.end and b.start < a.end


def score_example(gold: list[Span], pred: list[Span]) -> dict[str, ClassScores]:
    by_label: dict[str, ClassScores] = {lab: ClassScores(lab) for lab in SCORED_LABELS}
    gold_used = set()
    pred_used = set()

    for gi, g in enumerate(gold):
        if g.label not in by_label:
            continue
        for pi, p in enumerate(pred):
            if pi in pred_used:
                continue
            if _overlap(g, p):
                by_label[g.label].tp += 1
                gold_used.add(gi)
                pred_used.add(pi)
                break

    for gi, g in enumerate(gold):
        if g.label in by_label and gi not in gold_used:
            by_label[g.label].fn += 1
    for pi, p in enumerate(pred):
        if p.label in by_label and pi not in pred_used:
            by_label[p.label].fp += 1
    return by_label


def aggregate(scores_list: list[dict[str, ClassScores]]) -> dict[str, ClassScores]:
    out: dict[str, ClassScores] = {lab: ClassScores(lab) for lab in SCORED_LABELS}
    for d in scores_list:
        for lab, s in d.items():
            out[lab].tp += s.tp
            out[lab].fp += s.fp
            out[lab].fn += s.fn
    return out


def format_report(title: str, scores: dict[str, ClassScores], *, extra: str = "") -> str:
    lines = [f"## {title}", ""]
    if extra:
        lines.append(extra)
        lines.append("")
    lines.append(f"{'label':22} {'P':>6} {'R':>6} {'F1':>6} {'tp':>4} {'fp':>4} {'fn':>4}")
    lines.append("-" * 58)
    for lab in SCORED_LABELS:
        s = scores[lab]
        lines.append(
            f"{lab:22} {s.precision:6.3f} {s.recall:6.3f} {s.f1:6.3f} {s.tp:4d} {s.fp:4d} {s.fn:4d}"
        )
    return "\n".join(lines)


def radiology_fp_count(pred_by_text: list[tuple[str, list[Span]]]) -> dict[str, int]:
    """Count predicted PHI spans on radiology-description negatives."""
    counts: dict[str, int] = defaultdict(int)
    for _text, preds in pred_by_text:
        for p in preds:
            if p.label in SCORED_LABELS:
                counts[p.label] += 1
    return dict(counts)
