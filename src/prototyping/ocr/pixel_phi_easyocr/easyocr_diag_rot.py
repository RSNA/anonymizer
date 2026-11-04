"""EasyOCR full-image trial: diagonal rotation_info + CLAHE/threshold.

Tests the advice to use rotation_info=[-45, 0, 45] with contrast prep —
one full-image pass, no answer-key crops, no second-pass box crops.

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.easyocr_diag_rot
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.find_fta_r import (
    PREP_FUNCS,
    _has_fta,
    _has_r,
    _texts,
)
from prototyping.ocr.pixel_phi_easyocr.pipeline import (
    ensure_anonymizer_cwd,
    get_ocr_reader,
    load_ocr_pixels,
    run_easyocr,
    write_overlay_png,
)

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)

# Advice under test: try ±45° (and 0°) recognition rotations on detected boxes.
_DIAG_ROT = [-45, 0, 45]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="EasyOCR full-image diagonal rotation + CLAHE/threshold for FTA/R."
    )
    parser.add_argument("--dcm", type=str, default=str(_DEFAULT_DCM))
    parser.add_argument("--out", type=str, default=str(_PKG / "out" / "easyocr_diag_rot"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    dcm = Path(args.dcm)
    if not dcm.is_file():
        raise SystemExit(f"DICOM not found: {dcm}")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ensure_anonymizer_cwd()
    reader = get_ocr_reader()
    ds, base_pixels = load_ocr_pixels(dcm)
    modality = str(ds.get("Modality") or "CR")
    del ds
    logger.info("Loaded frame shape=%s modality=%s", base_pixels.shape, modality)

    # Full-image only: prep × rotation_info combinations from the advice.
    configs: list[tuple[str, str, dict[str, Any]]] = [
        ("raw_product_rot_90_270", "none", {"rotation_info": [90, 270]}),
        ("raw_diag_rot_m45_0_45", "none", {"rotation_info": list(_DIAG_ROT)}),
        ("clahe_diag_rot_m45_0_45", "clahe", {"rotation_info": list(_DIAG_ROT)}),
        ("clahe_strong_diag_rot_m45_0_45", "clahe_strong", {"rotation_info": list(_DIAG_ROT)}),
        ("thresh_otsu_diag_rot_m45_0_45", "otsu", {"rotation_info": list(_DIAG_ROT)}),
        ("clahe_thresh_80_diag_rot_m45_0_45", "clahe_thresh_80", {"rotation_info": list(_DIAG_ROT)}),
        ("clahe_thresh_100_diag_rot_m45_0_45", "clahe_thresh_100", {"rotation_info": list(_DIAG_ROT)}),
        # Same prep with no rotation TTA — isolates prep vs rotation.
        ("clahe_no_rot", "clahe", {"rotation_info": []}),
        ("otsu_no_rot", "otsu", {"rotation_info": []}),
    ]

    trials: list[dict[str, Any]] = []
    for name, prep_name, overrides in configs:
        prepared = PREP_FUNCS[prep_name](base_pixels)
        t0 = time.perf_counter()
        result = run_easyocr(
            prepared,
            modality=modality,
            overrides=overrides,
            reader=reader,
        )
        infer_s = time.perf_counter() - t0
        texts = _texts(result.raw)
        row = {
            "name": name,
            "prep": prep_name,
            "overrides": overrides,
            "ok": True,
            "infer_seconds": round(infer_s, 3),
            "found_fta": _has_fta(texts),
            "found_r": _has_r(texts),
            "texts": texts,
            "hits": [
                {
                    "text": h.text,
                    "prob": round(h.prob, 4),
                    "top_left": list(h.top_left),
                    "bottom_right": list(h.bottom_right),
                }
                for h in result.raw
            ],
            "easyocr_raw": result.easyocr_raw,
        }
        trials.append(row)
        logger.info(
            "%s → FTA=%s R=%s infer=%.2fs texts=%s",
            name,
            row["found_fta"],
            row["found_r"],
            infer_s,
            texts,
        )
        write_overlay_png(
            prepared,
            result.raw,
            out_dir / f"{name}.png",
            title=name,
        )
        del prepared
        _clear_torch_caches()

    both = [t for t in trials if t["found_fta"] and t["found_r"]]
    scored = sorted(
        trials,
        key=lambda t: (
            int(t["found_fta"]) + int(t["found_r"]),
            -(t.get("infer_seconds") or 99),
        ),
        reverse=True,
    )
    best = scored[0] if scored else None
    summary = {
        "dcm": str(dcm),
        "library": "easyocr",
        "goal": "Detect both FTA and R in one full-image pass",
        "advice": {
            "rotation_info": list(_DIAG_ROT),
            "prep": ["clahe", "global threshold / otsu"],
        },
        "note": (
            "rotation_info rotates each detected box for recognition "
            "(ndimage.rotate accepts ±45 even though EasyOCR docs list 90/180/270). "
            "It does not re-run detection on a rotated full frame."
        ),
        "trials": trials,
        "trials_with_both": [t["name"] for t in both],
        "best": {
            "name": best["name"],
            "found_fta": best["found_fta"],
            "found_r": best["found_r"],
            "infer_seconds": best["infer_seconds"],
            "texts": best["texts"],
        }
        if best
        else None,
        "plain_english": _explain(trials, both),
    }
    out_json = out_dir / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary["plain_english"])
    if best:
        print("Best:", json.dumps(summary["best"], indent=2))
    print("wrote", out_json)
    return 0 if both else 1


def _explain(trials: list[dict[str, Any]], both: list[dict[str, Any]]) -> str:
    if both:
        t = both[0]
        return (
            f"EasyOCR found both FTA and R in one full-image pass "
            f"({t['name']}, {t.get('infer_seconds')}s): {t.get('texts')}."
        )
    fta = [t["name"] for t in trials if t.get("found_fta")]
    r = [t["name"] for t in trials if t.get("found_r")]
    return (
        "EasyOCR did not find both FTA and R together in a single full-image pass "
        "with rotation_info=[-45,0,45] plus CLAHE/threshold prep. "
        f"FTA in: {fta or 'none'}. R in: {r or 'none'}. "
        f"Example texts: {trials[0].get('texts') if trials else []}."
    )


if __name__ == "__main__":
    sys.exit(main())
