"""Three EasyOCR-only improvement rounds on MIDI-B product-baseline failures.

No Surya. Targets the unique EasyOCR failures from eval_latest.json.
Uses full-image deskew and CXR top-left / top-right layout bands (not gold boxes).

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.easyocr_iterate_failures
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from numpy.typing import NDArray

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.corpus import PixelPhiCase, load_pixel_phi_cases
from prototyping.ocr.pixel_phi_easyocr.find_fta_r import (
    PREP_FUNCS,
    cxr_corner_bands,
    rotate_image,
)
from prototyping.ocr.pixel_phi_easyocr.pipeline import (
    ensure_anonymizer_cwd,
    get_ocr_reader,
    load_ocr_pixels,
    run_easyocr,
)
from prototyping.ocr.pixel_phi_easyocr.score import HitSummary, score_case

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_EVAL_LATEST = _PKG / "out" / "eval_latest.json"


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


@dataclass(frozen=True)
class Strategy:
    """One EasyOCR trial recipe."""

    name: str
    prep: str
    angles_deg: tuple[float, ...]
    overrides: dict[str, Any]
    # full = whole frame; cxr_corners = top-left + top-right layout bands.
    region: str = "full"


def _merge_hits(groups: Sequence[Sequence[HitSummary]]) -> list[HitSummary]:
    """Union hits; keep first occurrence of each normalized text."""
    out: list[HitSummary] = []
    seen: set[str] = set()
    for hits in groups:
        for hit in hits:
            key = (hit.text or "").strip().upper()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(hit)
    return out


def _region_views(pixels: NDArray[np.uint8], region: str) -> list[NDArray[np.uint8]]:
    if region == "full":
        return [pixels]
    if region == "cxr_corners":
        return [crop for _, crop in cxr_corner_bands(pixels)]
    if region == "cxr_top_left":
        return [cxr_corner_bands(pixels)[0][1]]
    if region == "cxr_top_right":
        return [cxr_corner_bands(pixels)[1][1]]
    raise ValueError(f"Unknown region: {region}")


def _run_strategy(
    case: PixelPhiCase,
    strategy: Strategy,
    *,
    reader,
    pixels: NDArray[np.uint8],
    modality: str,
) -> tuple[bool, list[str], list[str], float]:
    prep_fn: Callable[[NDArray[np.uint8]], NDArray[np.uint8]] = PREP_FUNCS[strategy.prep]
    prepared = prep_fn(pixels)
    views = _region_views(prepared, strategy.region)
    groups: list[list[HitSummary]] = []
    t0 = time.perf_counter()
    for view in views:
        for angle in strategy.angles_deg:
            frame = rotate_image(view, float(angle)) if abs(angle) > 1e-6 else view
            result = run_easyocr(
                frame,
                modality=modality,
                overrides=strategy.overrides,
                reader=reader,
            )
            groups.append(result.raw)
            _clear_torch_caches()
    elapsed = time.perf_counter() - t0
    merged = _merge_hits(groups)
    report = score_case(case, merged)
    miss = [m.gold_text for m in report.box_matches if not m.matched]
    return report.passed, report.raw_texts, miss, elapsed


def _eval_strategies(
    cases: list[PixelPhiCase],
    strategies: list[Strategy],
    *,
    reader,
    iteration: int,
) -> dict[str, Any]:
    per_strategy: list[dict[str, Any]] = []
    pixels_cache: dict[str, tuple[str, NDArray[np.uint8]]] = {}

    for case in cases:
        if case.case_id not in pixels_cache:
            ds, pixels = load_ocr_pixels(case.dcm_path)
            modality = str(ds.get("Modality") or case.modality or "CR")
            del ds
            pixels_cache[case.case_id] = (modality, pixels)

    best_name = ""
    best_pass = -1
    best_rows: list[dict[str, Any]] = []

    for strategy in strategies:
        rows: list[dict[str, Any]] = []
        n_pass = 0
        for case in cases:
            modality, pixels = pixels_cache[case.case_id]
            passed, texts, miss, elapsed = _run_strategy(
                case,
                strategy,
                reader=reader,
                pixels=pixels,
                modality=modality,
            )
            n_pass += int(passed)
            rows.append(
                {
                    "case_id": case.case_id,
                    "gold": [b.norm_text for b in case.boxes],
                    "passed": passed,
                    "miss": miss,
                    "texts": texts,
                    "seconds": round(elapsed, 3),
                }
            )
            logger.info(
                "iter%d %s %s → %s miss=%s texts=%s (%.1fs)",
                iteration,
                strategy.name,
                case.case_id,
                "OK" if passed else "FAIL",
                miss,
                texts[:6],
                elapsed,
            )
        per_strategy.append(
            {
                "name": strategy.name,
                "prep": strategy.prep,
                "region": strategy.region,
                "angles_deg": list(strategy.angles_deg),
                "overrides": strategy.overrides,
                "n_pass": n_pass,
                "n_total": len(cases),
                "pass_rate": n_pass / len(cases) if cases else 0.0,
                "rescued_ids": [r["case_id"] for r in rows if r["passed"]],
                "still_fail_ids": [r["case_id"] for r in rows if not r["passed"]],
                "cases": rows,
            }
        )
        if n_pass > best_pass:
            best_pass = n_pass
            best_name = strategy.name
            best_rows = rows

    pixels_cache.clear()
    return {
        "iteration": iteration,
        "strategies": per_strategy,
        "best_strategy": best_name,
        "best_n_pass": best_pass,
        "best_still_fail_ids": [r["case_id"] for r in best_rows if not r["passed"]],
        "best_rescued_ids": [r["case_id"] for r in best_rows if r["passed"]],
    }


def _iter1_strategies() -> list[Strategy]:
    """Full-image geometric deskew (detection-time)."""
    base_ov = {"rotation_info": []}
    return [
        Strategy("i1_full_angles_0_pm30_pm45", "none", (0, 30, -30, 45, -45), dict(base_ov), "full"),
        Strategy(
            "i1_full_clahe_angles_0_pm30_pm45",
            "clahe",
            (0, 30, -30, 45, -45),
            dict(base_ov),
            "full",
        ),
    ]


def _iter2_strategies() -> list[Strategy]:
    """CXR top-left + top-right marker bands with deskew."""
    base_ov = {"rotation_info": []}
    tight = (0, 30, 45, -45)
    sensitive = {
        "rotation_info": [],
        "text_threshold": 0.5,
        "low_text": 0.3,
        "contrast_ths": 0.05,
        "adjust_contrast": 0.7,
        "width_ths": 0.05,
        "add_margin": 0.15,
    }
    return [
        Strategy("i2_corners_angles", "none", tight, dict(base_ov), "cxr_corners"),
        Strategy("i2_corners_clahe_angles", "clahe", tight, dict(base_ov), "cxr_corners"),
        Strategy("i2_corners_clahe_sensitive", "clahe", tight, sensitive, "cxr_corners"),
        Strategy("i2_corners_clahe_strong", "clahe_strong", tight, dict(base_ov), "cxr_corners"),
    ]


def _iter3_strategies(iter1: dict[str, Any], iter2: dict[str, Any]) -> list[Strategy]:
    """Corners + allowlist / wider angles / merge with best full-image idea."""
    rescued: set[str] = set(iter1.get("best_rescued_ids") or [])
    rescued.update(iter2.get("best_rescued_ids") or [])
    still = (set(iter1.get("best_still_fail_ids") or []) | set(iter2.get("best_still_fail_ids") or [])) - rescued
    logger.info("Entering iter3; still-hard after iter1/2 union: %s", sorted(still))

    allow = {
        "rotation_info": [],
        "allowlist": "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- ",
        "text_threshold": 0.45,
        "low_text": 0.25,
        "contrast_ths": 0.05,
        "adjust_contrast": 0.7,
        "width_ths": 0.05,
        "add_margin": 0.2,
    }
    wide = (0, 15, 30, 45, 60, -30, -45)
    # Full + corners union done by scoring merged texts in one strategy via corners
    # on CLAHE and also a full deskew pass combined externally — here one strategy
    # runs corners with wide angles; another runs full with winning angles.
    return [
        Strategy("i3_corners_clahe_allow_wide", "clahe", wide, allow, "cxr_corners"),
        Strategy("i3_corners_clahe_allow_hires", "clahe", (0, 30, 45, -45, 60), {
            **allow,
            "canvas_size": 1600,
            "mag_ratio": 1.8,
        }, "cxr_corners"),
        Strategy("i3_full_clahe_allow_angles", "clahe", (0, 30, 45, -45), allow, "full"),
        Strategy("i3_tl_only_clahe_wide", "clahe", wide, allow, "cxr_top_left"),
        Strategy("i3_tr_only_clahe_wide", "clahe", wide, allow, "cxr_top_right"),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Iterate EasyOCR on MIDI-B failures (3 rounds).")
    parser.add_argument("--out", type=str, default=str(_PKG / "out" / "easyocr_iterate"))
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
    fail_ids = _unique_easyocr_failure_ids(_EVAL_LATEST)
    by_id = {c.case_id: c for c in all_cases}
    cases = [by_id[cid] for cid in fail_ids if cid in by_id]
    if not cases:
        raise SystemExit("No EasyOCR failure cases found")
    logger.info("Loaded %d EasyOCR failure cases", len(cases))

    reader = get_ocr_reader()
    iterations: list[dict[str, Any]] = []

    logger.info("=== Iteration 1: full-image deskew ===")
    i1 = _eval_strategies(cases, _iter1_strategies(), reader=reader, iteration=1)
    iterations.append(i1)
    logger.info(
        "Iter1 best=%s pass=%d/%d still=%s",
        i1["best_strategy"],
        i1["best_n_pass"],
        len(cases),
        i1["best_still_fail_ids"],
    )

    logger.info("=== Iteration 2: CXR top-left + top-right bands ===")
    i2 = _eval_strategies(cases, _iter2_strategies(), reader=reader, iteration=2)
    iterations.append(i2)
    logger.info(
        "Iter2 best=%s pass=%d/%d still=%s",
        i2["best_strategy"],
        i2["best_n_pass"],
        len(cases),
        i2["best_still_fail_ids"],
    )

    logger.info("=== Iteration 3: corners + allowlist / wider angles ===")
    i3 = _eval_strategies(cases, _iter3_strategies(i1, i2), reader=reader, iteration=3)
    iterations.append(i3)
    logger.info(
        "Iter3 best=%s pass=%d/%d still=%s",
        i3["best_strategy"],
        i3["best_n_pass"],
        len(cases),
        i3["best_still_fail_ids"],
    )

    ever: set[str] = set()
    for it in iterations:
        for st in it["strategies"]:
            ever.update(st["rescued_ids"])
    still_all = [c.case_id for c in cases if c.case_id not in ever]
    best_overall = max(iterations, key=lambda x: x["best_n_pass"])

    summary = {
        "library": "easyocr",
        "goal": (
            "Improve EasyOCR on product-baseline MIDI-B failures "
            "(3 iterations; CXR corner bands allowed; no Surya / no gold boxes)"
        ),
        "n_failures": len(cases),
        "failure_ids": [c.case_id for c in cases],
        "iterations": iterations,
        "best_single_strategy": {
            "iteration": best_overall["iteration"],
            "name": best_overall["best_strategy"],
            "n_pass": best_overall["best_n_pass"],
            "still_fail_ids": best_overall["best_still_fail_ids"],
        },
        "union_any_strategy_pass": sorted(ever),
        "union_n_pass": len(ever),
        "union_still_fail": still_all,
        "plain_english": (
            f"Over 3 EasyOCR-only iterations on {len(cases)} failures "
            f"(full-image deskew + CXR top-left/top-right bands), "
            f"best single strategy `{best_overall['best_strategy']}` "
            f"rescued {best_overall['best_n_pass']}/{len(cases)}. "
            f"Union across all tried strategies: {len(ever)}/{len(cases)}. "
            f"Still miss: {still_all or 'none'}."
        ),
    }
    out_json = out_dir / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary["plain_english"])
    print("wrote", out_json)
    return 0 if len(ever) == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
