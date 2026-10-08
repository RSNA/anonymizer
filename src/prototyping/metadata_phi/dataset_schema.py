"""Definitive PHI text eval dataset schema and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from prototyping.metadata_phi.types import Span

# Canonical scored labels for the definitive dataset and eval-dataset.
SCORED_LABELS = (
    "NAME",
    "LOCATION",
    "ID",
    "PHONE",
    "DATE",
    "EMAIL",
)

LENGTH_SHORT_MAX = 64
LENGTH_MEDIUM_MAX = 400


def length_class_for(text: str) -> str:
    n = len(text)
    if n <= LENGTH_SHORT_MAX:
        return "short"
    if n <= LENGTH_MEDIUM_MAX:
        return "medium"
    return "long"


@dataclass
class PhiTextExample:
    id: str
    text: str
    spans: list[Span] = field(default_factory=list)
    length_class: str = ""

    def __post_init__(self) -> None:
        if not self.length_class:
            self.length_class = length_class_for(self.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "length_class": self.length_class,
            "text": self.text,
            "spans": [
                {"label": s.label, "start": s.start, "end": s.end} for s in self.spans
            ],
        }


def validate_spans(text: str, spans: Iterable[dict[str, Any] | Span]) -> list[str]:
    """Return a list of error messages (empty if valid)."""
    errors: list[str] = []
    n = len(text)
    seen: set[tuple[str, int, int]] = set()
    for i, s in enumerate(spans):
        if isinstance(s, Span):
            label, start, end = s.label, s.start, s.end
        else:
            label = str(s.get("label", ""))
            start = int(s["start"])
            end = int(s["end"])
        if label not in SCORED_LABELS:
            errors.append(f"span[{i}]: unknown label {label!r}")
            continue
        if start < 0 or end > n or start >= end:
            errors.append(f"span[{i}]: out of bounds start={start} end={end} n={n}")
            continue
        key = (label, start, end)
        if key in seen:
            errors.append(f"span[{i}]: duplicate {key}")
            continue
        seen.add(key)
    return errors


def example_from_dict(obj: dict[str, Any]) -> PhiTextExample:
    spans = [
        Span(
            label=str(s["label"]),
            start=int(s["start"]),
            end=int(s["end"]),
            score=float(s.get("score", 1.0)),
        )
        for s in obj.get("spans", [])
    ]
    text = obj["text"]
    errs = validate_spans(text, spans)
    if errs:
        raise ValueError(f"id={obj.get('id')!r}: " + "; ".join(errs))
    return PhiTextExample(
        id=str(obj["id"]),
        text=text,
        spans=spans,
        length_class=str(obj.get("length_class") or length_class_for(text)),
    )


def load_dataset(path: str | Path) -> list[PhiTextExample]:
    rows: list[PhiTextExample] = []
    for line_no, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            rows.append(example_from_dict(json.loads(line)))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{path}:{line_no}: {exc}") from exc
    return rows


def write_dataset(path: Path, examples: list[PhiTextExample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for ex in examples:
        errs = validate_spans(ex.text, ex.spans)
        if errs:
            raise ValueError(f"{ex.id}: " + "; ".join(errs))
        if ex.length_class != length_class_for(ex.text):
            raise ValueError(
                f"{ex.id}: length_class {ex.length_class!r} != "
                f"{length_class_for(ex.text)!r} for len={len(ex.text)}"
            )
    path.write_text(
        "\n".join(json.dumps(ex.to_dict(), ensure_ascii=False) for ex in examples)
        + ("\n" if examples else ""),
        encoding="utf-8",
    )


def build_manifest(examples: list[PhiTextExample]) -> dict[str, Any]:
    by_len: dict[str, int] = {"short": 0, "medium": 0, "long": 0}
    with_phi = 0
    label_counts: dict[str, int] = {lab: 0 for lab in SCORED_LABELS}
    for ex in examples:
        by_len[ex.length_class] = by_len.get(ex.length_class, 0) + 1
        if ex.spans:
            with_phi += 1
        for s in ex.spans:
            label_counts[s.label] = label_counts.get(s.label, 0) + 1
    return {
        "n": len(examples),
        "with_phi": with_phi,
        "without_phi": len(examples) - with_phi,
        "by_length_class": by_len,
        "span_counts_by_label": label_counts,
    }
