"""Re-test EasyOCR MIDI-B failures with Surya full-image OCR.

Selects up to N cases: all unique EasyOCR product-baseline failures first,
then short burned-in marker cases (same class as FTA/R) to fill the set.
Scores Surya hits with the same gold-box matcher as the EasyOCR corpus eval.

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.surya_rescue_failures
  uv run python -m prototyping.ocr.pixel_phi_easyocr.surya_rescue_failures --n 30
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2
from PIL import Image

# Surya before torch so MPS fallback env is applied.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.corpus import PixelPhiCase, load_pixel_phi_cases
from prototyping.ocr.pixel_phi_easyocr.pipeline import (
    ensure_anonymizer_cwd,
    get_ocr_reader,
    load_ocr_pixels,
    run_easyocr,
)
from prototyping.ocr.pixel_phi_easyocr.score import CaseReport, HitSummary, score_case
from prototyping.ocr.pixel_phi_easyocr.surya_fta_r import (
    _DEFAULT_GGUF,
    _DEFAULT_MMPROJ,
    _configure_apple_silicon,
    _html_to_text,
    _resolve_gguf,
)

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_EVAL_LATEST = _PKG / "out" / "eval_latest.json"


def _is_short_marker(text: str) -> bool:
    t = (text or "").strip().upper()
    return 1 <= len(t) <= 6 and t.replace(" ", "").isalnum()


def _unique_easyocr_failure_ids(eval_path: Path) -> list[str]:
    if not eval_path.is_file():
        return []
    doc = json.loads(eval_path.read_text(encoding="utf-8"))
    seen: list[str] = []
    for row in doc.get("failures") or []:
        cid = str(row.get("case_id") or "")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


def _select_cases(
    all_cases: list[PixelPhiCase],
    *,
    n: int,
    failure_ids: list[str],
    failures_only: bool = True,
) -> list[tuple[PixelPhiCase, str]]:
    """
    Pick up to n cases.

    Default (failures_only): unique EasyOCR product-baseline failures only.
    Returns (case, reason) where reason is easyocr_failure|short_marker|fill.
    """
    by_id = {c.case_id: c for c in all_cases}
    selected: list[tuple[PixelPhiCase, str]] = []
    used: set[str] = set()

    for cid in failure_ids:
        if len(selected) >= n:
            break
        case = by_id.get(cid)
        if case is None or cid in used:
            continue
        selected.append((case, "easyocr_failure"))
        used.add(cid)

    if failures_only:
        return selected

    short = [
        c
        for c in all_cases
        if c.case_id not in used and any(_is_short_marker(b.norm_text) for b in c.boxes)
    ]
    for case in short:
        if len(selected) >= n:
            break
        selected.append((case, "short_marker"))
        used.add(case.case_id)

    for case in all_cases:
        if len(selected) >= n:
            break
        if case.case_id in used:
            continue
        selected.append((case, "fill"))
        used.add(case.case_id)

    return selected


def _confirm_easyocr(
    case: PixelPhiCase,
    *,
    reader,
) -> CaseReport:
    ds, pixels = load_ocr_pixels(case.dcm_path)
    modality = str(ds.get("Modality") or case.modality or "CR")
    del ds
    result = run_easyocr(pixels, modality=modality, overrides=None, reader=reader)
    report = score_case(case, result.raw)
    del pixels, result
    _clear_torch_caches()
    return report


def _surya_hits(page: Any) -> list[HitSummary]:
    hits: list[HitSummary] = []
    for block in getattr(page, "blocks", None) or []:
        text = _html_to_text(getattr(block, "html", "") or "")
        if not text:
            continue
        polygon = getattr(block, "polygon", None)
        if polygon is None:
            tl, br = (0, 0), (0, 0)
        else:
            xs = [float(p[0]) for p in polygon]
            ys = [float(p[1]) for p in polygon]
            tl = (int(min(xs)), int(min(ys)))
            br = (int(max(xs)), int(max(ys)))
        conf = getattr(block, "confidence", None)
        hits.append(
            HitSummary(
                text=text,
                prob=float(conf) if conf is not None else 0.0,
                top_left=tl,
                bottom_right=br,
            )
        )
    return hits


def _bgr_to_pil(pixels) -> Image.Image:
    rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rescue EasyOCR MIDI-B failures with Surya full-image OCR."
    )
    parser.add_argument(
        "--n",
        type=int,
        default=0,
        help="Max cases (0 = all unique EasyOCR failures, no padding)",
    )
    parser.add_argument("--out", type=str, default=str(_PKG / "out" / "surya_rescue"))
    parser.add_argument("--gguf", type=str, default="")
    parser.add_argument("--mmproj", type=str, default=str(_DEFAULT_MMPROJ))
    parser.add_argument(
        "--pad",
        action="store_true",
        help="If set, pad beyond EasyOCR failures with short-marker cases up to --n",
    )
    parser.add_argument(
        "--skip-easyocr-confirm",
        action="store_true",
        help="Trust eval_latest.json failure list without re-running EasyOCR",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ensure_anonymizer_cwd()
    all_cases = load_pixel_phi_cases()
    failure_ids = _unique_easyocr_failure_ids(_EVAL_LATEST)
    n = args.n if args.n > 0 else len(failure_ids)
    logger.info(
        "Corpus=%d; unique EasyOCR failures in eval_latest=%d; n=%d pad=%s",
        len(all_cases),
        len(failure_ids),
        n,
        args.pad,
    )

    selected = _select_cases(
        all_cases,
        n=n,
        failure_ids=failure_ids,
        failures_only=not args.pad,
    )
    logger.info(
        "Selected %d cases (%s)",
        len(selected),
        {
            reason: sum(1 for _, r in selected if r == reason)
            for reason in ("easyocr_failure", "short_marker", "fill")
        },
    )

    # Confirm EasyOCR status on the selected set (product defaults).
    easyocr_by_id: dict[str, dict[str, Any]] = {}
    if not args.skip_easyocr_confirm:
        reader = get_ocr_reader()
        for case, reason in selected:
            report = _confirm_easyocr(case, reader=reader)
            miss = [m.gold_text for m in report.box_matches if not m.matched]
            easyocr_by_id[case.case_id] = {
                "passed": report.passed,
                "miss": miss,
                "raw": report.raw_texts,
                "selection_reason": reason,
            }
            logger.info(
                "EasyOCR %s %s miss=%s raw=%s",
                case.case_id,
                "OK" if report.passed else "FAIL",
                miss,
                report.raw_texts[:6],
            )
    else:
        for case, reason in selected:
            easyocr_by_id[case.case_id] = {
                "passed": reason != "easyocr_failure",
                "miss": [b.norm_text for b in case.boxes] if reason == "easyocr_failure" else [],
                "raw": [],
                "selection_reason": reason,
            }

    gguf = _resolve_gguf(Path(args.gguf) if args.gguf else None)
    mmproj = Path(args.mmproj)
    if not mmproj.is_file():
        raise SystemExit(f"mmproj not found: {mmproj}")
    device_info = _configure_apple_silicon(gguf=gguf, mmproj=mmproj)
    # Keep server up across the batch (third-party Surya setting).
    from surya.settings import settings

    settings.SURYA_INFERENCE_KEEP_ALIVE = True

    from surya.inference import SuryaInferenceManager
    from surya.recognition import RecognitionPredictor

    t0 = time.perf_counter()
    manager = SuryaInferenceManager(method="llamacpp", lazy=False)
    rec = RecognitionPredictor(manager)
    init_s = time.perf_counter() - t0
    logger.info("Surya ready in %.1fs device=%s", init_s, device_info)

    rows: list[dict[str, Any]] = []
    try:
        for i, (case, reason) in enumerate(selected):
            ds, pixels = load_ocr_pixels(case.dcm_path)
            modality = str(ds.get("Modality") or case.modality or "CR")
            del ds
            image = _bgr_to_pil(pixels)
            t1 = time.perf_counter()
            try:
                pages = rec([image])
                hits = _surya_hits(pages[0]) if pages else []
                err = None
            except Exception as exc:
                hits = []
                err = repr(exc)
            infer_s = time.perf_counter() - t1
            report = score_case(case, hits)
            miss = [m.gold_text for m in report.box_matches if not m.matched]
            eo = easyocr_by_id.get(case.case_id) or {}
            rescued = (not eo.get("passed", True)) and report.passed
            row = {
                "case_id": case.case_id,
                "modality": modality,
                "selection_reason": reason,
                "gold": [b.norm_text for b in case.boxes],
                "easyocr_passed": eo.get("passed"),
                "easyocr_miss": eo.get("miss"),
                "easyocr_raw": eo.get("raw"),
                "surya_passed": report.passed,
                "surya_miss": miss,
                "surya_raw": report.raw_texts,
                "surya_rescued": rescued,
                "infer_seconds": round(infer_s, 3),
                "error": err,
            }
            rows.append(row)
            logger.info(
                "[%d/%d] %s easyocr=%s surya=%s rescued=%s miss=%s texts=%s (%.1fs)",
                i + 1,
                len(selected),
                case.case_id,
                "OK" if eo.get("passed") else "FAIL",
                "OK" if report.passed else "FAIL",
                rescued,
                miss,
                report.raw_texts[:6],
                infer_s,
            )
            del pixels, image, hits
    finally:
        try:
            manager.stop()
        except Exception as exc:
            logger.warning("manager.stop failed: %s", exc)

    easyocr_fail_rows = [r for r in rows if not r.get("easyocr_passed")]
    rescued = [r for r in easyocr_fail_rows if r.get("surya_rescued")]
    still_fail = [r for r in easyocr_fail_rows if not r.get("surya_passed")]
    surya_pass = [r for r in rows if r.get("surya_passed")]
    short_rows = [r for r in rows if r.get("selection_reason") == "short_marker"]

    summary = {
        "library": "surya-ocr",
        "goal": "Rescue EasyOCR MIDI-B pixel_phi failures with one full-image Surya pass",
        "n_requested": n,
        "n_selected": len(rows),
        "failures_only": not args.pad,
        "n_easyocr_failures_in_eval_latest": len(failure_ids),
        "n_easyocr_failures_in_selection": len(easyocr_fail_rows),
        "n_surya_pass": len(surya_pass),
        "n_rescued_easyocr_failures": len(rescued),
        "n_easyocr_failures_still_miss": len(still_fail),
        "selection_counts": {
            "easyocr_failure": sum(1 for r in rows if r["selection_reason"] == "easyocr_failure"),
            "short_marker": sum(1 for r in rows if r["selection_reason"] == "short_marker"),
            "fill": sum(1 for r in rows if r["selection_reason"] == "fill"),
        },
        "device": device_info,
        "init_seconds": round(init_s, 3),
        "cases": rows,
        "rescued_case_ids": [r["case_id"] for r in rescued],
        "still_fail_case_ids": [r["case_id"] for r in still_fail],
        "plain_english": _explain(
            n_fail=len(easyocr_fail_rows),
            n_rescued=len(rescued),
            n_still=len(still_fail),
            n_short=len(short_rows),
            short_pass=sum(1 for r in short_rows if r.get("surya_passed")),
            n_selected=len(rows),
            failure_ids_available=len(failure_ids),
            failures_only=not args.pad,
        ),
    }
    out_json = out_dir / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary["plain_english"])
    print("wrote", out_json)
    return 0 if len(still_fail) == 0 and easyocr_fail_rows else 1


def _explain(
    *,
    n_fail: int,
    n_rescued: int,
    n_still: int,
    n_short: int,
    short_pass: int,
    n_selected: int,
    failure_ids_available: int,
    failures_only: bool,
) -> str:
    if failures_only:
        parts = [
            f"Ran Surya on all {n_selected} unique EasyOCR product-baseline failures "
            f"(eval_latest had {failure_ids_available}; {n_fail} confirmed FAIL on re-check).",
            f"Surya rescued {n_rescued}/{n_fail}; {n_still} still miss gold text.",
        ]
    else:
        parts = [
            f"Selected {n_selected} cases from {failure_ids_available} EasyOCR failures "
            f"plus padding ({n_fail} confirmed failures).",
            f"Surya rescued {n_rescued}/{n_fail}; {n_still} still miss gold text.",
        ]
        if n_short:
            parts.append(
                f"On {n_short} extra short-marker cases, Surya passed {short_pass}/{n_short}."
            )
    return " ".join(parts)


if __name__ == "__main__":
    sys.exit(main())
