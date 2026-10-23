"""Score predicted ReportHits against gold entity specs."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from prototyping.report_phi.pipeline import PredHit


@dataclass
class EntityScore:
    gold_id: str
    matched: bool
    detail: str
    hit: PredHit | None = None
    prefix_ok: bool | None = None


@dataclass
class ScoreReport:
    gold_path: Path
    n_gold: int
    n_matched: int
    entities: list[EntityScore] = field(default_factory=list)
    extras: list[PredHit] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.n_matched == self.n_gold and self.n_gold > 0

    @property
    def ratio(self) -> float:
        return self.n_matched / self.n_gold if self.n_gold else 0.0


def load_gold(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def _hit_matches_spec(hit: PredHit, spec: dict[str, Any]) -> bool:
    if spec.get("source") and hit.source != spec["source"]:
        return False
    labels = {str(x).upper() for x in spec.get("labels") or []}
    if labels and hit.label.upper() not in labels:
        return False
    text = _norm(hit.text)
    text_cf = text.casefold()

    for needle in spec.get("text_any") or []:
        if _norm(needle).casefold() == text_cf:
            return _excludes_ok(text, spec)

    contains = spec.get("text_contains") or []
    if contains:
        if all(_norm(n) in text for n in contains) or all(
            _norm(n).casefold() in text_cf for n in contains
        ):
            return _excludes_ok(text, spec)
        return False

    contains_any = spec.get("text_contains_any") or []
    if contains_any:
        if any(_norm(n) in text or _norm(n).casefold() in text_cf for n in contains_any):
            return _excludes_ok(text, spec)
        return False

    return False


def _excludes_ok(text: str, spec: dict[str, Any]) -> bool:
    for ex in spec.get("text_excludes") or []:
        if ex in text:
            return False
    return True


def _prefix_ok(hit: PredHit, spec: dict[str, Any]) -> bool | None:
    prefs = spec.get("prefer_prefix") or []
    if not prefs:
        return None
    t = hit.text or ""
    return any(p.casefold() in t.casefold() for p in prefs)


def score_hits(hits: list[PredHit], gold: dict[str, Any]) -> ScoreReport:
    specs: list[dict[str, Any]] = list(gold.get("entities") or [])
    used: set[int] = set()
    entities: list[EntityScore] = []

    for spec in specs:
        gid = str(spec.get("id") or "?")
        best: PredHit | None = None
        best_i: int | None = None
        for i, hit in enumerate(hits):
            if i in used:
                continue
            if _hit_matches_spec(hit, spec):
                best = hit
                best_i = i
                break
        if best is not None and best_i is not None:
            used.add(best_i)
            pref = _prefix_ok(best, spec)
            detail = f"{best.label} {best.text!r} source={best.source}"
            if pref is False:
                detail += " (missing preferred prefix — still matched)"
            entities.append(
                EntityScore(gold_id=gid, matched=True, detail=detail, hit=best, prefix_ok=pref)
            )
        else:
            entities.append(
                EntityScore(gold_id=gid, matched=False, detail="no matching hit", hit=None)
            )

    extras = [h for i, h in enumerate(hits) if i not in used]
    n_matched = sum(1 for e in entities if e.matched)
    return ScoreReport(
        gold_path=Path(),
        n_gold=len(specs),
        n_matched=n_matched,
        entities=entities,
        extras=extras,
    )


def format_score_markdown(report: ScoreReport, *, params_key: str) -> str:
    lines = [
        f"### `{params_key}`",
        "",
        f"- matched **{report.n_matched}/{report.n_gold}** ({100 * report.ratio:.0f}%)",
        f"- passed: **{report.passed}**",
        "",
        "| gold_id | ok | detail |",
        "| --- | --- | --- |",
    ]
    for e in report.entities:
        mark = "yes" if e.matched else "NO"
        lines.append(f"| {e.gold_id} | {mark} | {e.detail.replace('|', '/')} |")
    if report.extras:
        lines.append("")
        lines.append(f"Extras ({len(report.extras)}):")
        for h in report.extras[:20]:
            lines.append(f"- {h.label} {h.text!r} ({h.source})")
    lines.append("")
    return "\n".join(lines)
