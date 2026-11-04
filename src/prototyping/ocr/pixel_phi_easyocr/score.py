"""Score EasyOCR hits against MIDI-B pixel_phi gold (single case + corpus)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from prototyping.ocr.pixel_phi_easyocr.corpus import GoldBox, PixelPhiCase

_ALNUM = re.compile(r"[^A-Z0-9]+")


@dataclass
class HitSummary:
    """One EasyOCR / filtered detection for scoring."""

    text: str
    prob: float
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]

    @property
    def norm(self) -> str:
        """Uppercased stripped text."""
        return (self.text or "").strip().upper()


@dataclass
class BoxMatch:
    """Whether one gold box was recovered in raw OCR."""

    gold_text: str
    matched: bool
    matched_ocr: str | None = None
    overlap: bool = False


@dataclass
class CaseReport:
    """Per-case gold recall."""

    case_id: str
    modality: str
    box_matches: list[BoxMatch] = field(default_factory=list)
    raw_texts: list[str] = field(default_factory=list)

    @property
    def boxes_total(self) -> int:
        return len(self.box_matches)

    @property
    def boxes_hit(self) -> int:
        return sum(1 for m in self.box_matches if m.matched)

    @property
    def passed(self) -> bool:
        """Case passes when every gold box text is detected."""
        return self.boxes_total > 0 and self.boxes_hit == self.boxes_total


@dataclass
class CorpusReport:
    """Aggregate accuracy across pixel_phi cases."""

    params_key: str
    overrides: dict[str, Any]
    relative_cost: float
    cases: list[CaseReport]
    target_accuracy: float = 0.95

    @property
    def case_total(self) -> int:
        return len(self.cases)

    @property
    def case_pass(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def case_accuracy(self) -> float:
        return self.case_pass / self.case_total if self.case_total else 0.0

    @property
    def box_total(self) -> int:
        return sum(c.boxes_total for c in self.cases)

    @property
    def box_hit(self) -> int:
        return sum(c.boxes_hit for c in self.cases)

    @property
    def box_recall(self) -> float:
        return self.box_hit / self.box_total if self.box_total else 0.0

    @property
    def met_target(self) -> bool:
        return self.case_accuracy >= self.target_accuracy


def _norm_token(text: str) -> str:
    return _ALNUM.sub("", (text or "").strip().upper())


def _texts_match(ocr: str, gold: str) -> bool:
    """Exact, containment, or alnum-compact match (names / short markers)."""
    a = (ocr or "").strip().upper()
    b = (gold or "").strip().upper()
    if not a or not b:
        return False
    if a == b or b in a or a in b:
        return True
    ca, cb = _norm_token(a), _norm_token(b)
    if not ca or not cb:
        return False
    return ca == cb or cb in ca or ca in cb


def _aabb_overlap(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def match_gold_box(gold: GoldBox, hits: Sequence[HitSummary]) -> BoxMatch:
    """Match one gold box to the best overlapping / text-similar OCR hit."""
    g_box = (*gold.top_left, *gold.bottom_right)
    best: BoxMatch | None = None
    for hit in hits:
        text_ok = _texts_match(hit.norm, gold.norm_text)
        overlap = _aabb_overlap((*hit.top_left, *hit.bottom_right), g_box)
        if text_ok:
            cand = BoxMatch(
                gold_text=gold.norm_text,
                matched=True,
                matched_ocr=hit.norm,
                overlap=overlap,
            )
            if best is None or (overlap and not best.overlap):
                best = cand
    if best is not None:
        return best
    return BoxMatch(gold_text=gold.norm_text, matched=False)


def score_case(case: PixelPhiCase, raw_hits: Sequence[HitSummary]) -> CaseReport:
    """Score one pixel_phi case against its gold boxes using raw EasyOCR hits."""
    return CaseReport(
        case_id=case.case_id,
        modality=case.modality,
        box_matches=[match_gold_box(b, raw_hits) for b in case.boxes],
        raw_texts=[h.norm for h in raw_hits if h.norm],
    )


def format_corpus_markdown(report: CorpusReport, *, failures_limit: int = 12) -> str:
    """Summary markdown for experiment log."""
    status = "PASS" if report.met_target else "FAIL"
    lines = [
        f"### `{report.params_key}` → **{status}** "
        f"(case_acc={report.case_accuracy:.1%} "
        f"{report.case_pass}/{report.case_total}; "
        f"box_recall={report.box_recall:.1%} "
        f"{report.box_hit}/{report.box_total}; "
        f"rel_cost={report.relative_cost:.2f})\n",
        f"overrides={report.overrides or '{}'}\n",
    ]
    fails = [c for c in report.cases if not c.passed]
    if fails:
        lines.append(f"failures (showing {min(failures_limit, len(fails))} of {len(fails)}):\n")
        for case in fails[:failures_limit]:
            miss = [m.gold_text for m in case.box_matches if not m.matched]
            lines.append(f"- {case.case_id} {case.modality}: miss={miss} raw={case.raw_texts[:8]}\n")
    return "".join(lines)


# --- legacy single-fixture helpers (chest marker prototype) ---


@dataclass
class GoldSpec:
    """Expected burned-in texts for the single-case CLI."""

    patient_id: str
    must_detect: list[str]
    want_detect: list[str]
    must_drop_after_noise: list[str]
    boxes: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> GoldSpec:
        return cls(
            patient_id=str(data.get("patient_id") or ""),
            must_detect=[str(t).strip().upper() for t in (data.get("must_detect") or []) if str(t).strip()],
            want_detect=[str(t).strip().upper() for t in (data.get("want_detect") or []) if str(t).strip()],
            must_drop_after_noise=[
                str(t).strip().upper() for t in (data.get("must_drop_after_noise") or []) if str(t).strip()
            ],
            boxes=list(data.get("boxes") or []),
        )


@dataclass
class ScoreReport:
    """Single-fixture report kept for `run` subcommand."""

    params_key: str
    raw_texts: list[str]
    filtered_texts: list[str]
    must_ok: bool
    want_hits: list[str]
    noise_ok: bool
    missing_must: list[str]
    leftover_noise: list[str]
    box_overlap_fta: bool
    score: float

    @property
    def passed(self) -> bool:
        return self.must_ok and self.noise_ok


def score_run(
    *,
    params_key: str,
    raw_hits: Sequence[HitSummary],
    filtered_hits: Sequence[HitSummary],
    gold: GoldSpec,
) -> ScoreReport:
    raw_texts = [h.norm for h in raw_hits if h.norm]
    filtered_texts = [h.norm for h in filtered_hits if h.norm]
    missing_must = [t for t in gold.must_detect if not any(_texts_match(x, t) for x in raw_texts)]
    want_hits = [t for t in gold.want_detect if any(_texts_match(x, t) for x in raw_texts)]
    leftover_noise = [
        t for t in gold.must_drop_after_noise if any(_texts_match(x, t) for x in filtered_texts)
    ]
    box_ok = False
    for b in gold.boxes:
        if str(b.get("text") or "").strip().upper() != "FTA":
            continue
        gb = GoldBox(
            text="FTA",
            top_left=(int(b["top_left"][0]), int(b["top_left"][1])),
            bottom_right=(int(b["bottom_right"][0]), int(b["bottom_right"][1])),
        )
        box_ok = match_gold_box(gb, raw_hits).matched
    must_ok = not missing_must
    noise_ok = not leftover_noise
    score = (10.0 if must_ok else 0.0) + (3.0 if box_ok else 0.0) + 2.0 * len(want_hits)
    score += 1.0 if noise_ok else -0.5 * len(leftover_noise)
    return ScoreReport(
        params_key=params_key,
        raw_texts=raw_texts,
        filtered_texts=filtered_texts,
        must_ok=must_ok,
        want_hits=want_hits,
        noise_ok=noise_ok,
        missing_must=missing_must,
        leftover_noise=leftover_noise,
        box_overlap_fta=box_ok,
        score=score,
    )


def format_score_markdown(report: ScoreReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    return (
        f"### `{report.params_key}` → **{status}** (score={report.score:.2f})\n\n"
        f"- raw: {report.raw_texts}\n"
        f"- after noise: {report.filtered_texts}\n"
        f"- must_ok={report.must_ok} missing={report.missing_must} "
        f"fta_box_overlap={report.box_overlap_fta}\n"
        f"- want_hits={report.want_hits} noise_ok={report.noise_ok} "
        f"leftover_noise={report.leftover_noise}\n"
    )
