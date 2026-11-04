"""Try PaddleOCR on the MIDI-B chest image for FTA and R.

One full-image pass with text-line orientation (no answer-key crops).
Compares a few settings and reports whether FTA and R appear.

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.paddle_fta_r
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
import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)
_ANONYMIZER_INSTALL = Path(__file__).resolve().parents[3] / "anonymizer"

# Skip slow model-host connectivity checks during experiments.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _load_ocr_bgr(dcm_path: Path) -> tuple[str, NDArray[np.uint8]]:
    """Same windowed BGR frame the product feeds EasyOCR."""
    from pydicom import dcmread

    from anonymizer.controller.ai.embedded_phi.pixel.detect_text import ocr_image_for_frame

    if Path.cwd().resolve() != _ANONYMIZER_INSTALL.resolve():
        os.chdir(_ANONYMIZER_INSTALL)
    ds = dcmread(str(dcm_path))
    frame = np.asarray(ds.pixel_array)
    pixels = ocr_image_for_frame(ds, frame)
    modality = str(ds.get("Modality") or "CR")
    return modality, pixels


def _has_fta(texts: list[str]) -> bool:
    return any("FTA" in t.upper() for t in texts)


def _has_r(texts: list[str]) -> bool:
    return any(t.strip().upper() == "R" for t in texts)


def _box_to_list(box: Any) -> list | None:
    if box is None:
        return None
    try:
        return np.asarray(box).reshape(-1, 2).astype(float).tolist()
    except Exception:
        return None


def _parse_paddle_result(result: Any) -> list[dict[str, Any]]:
    """Normalize classic and newer PaddleOCR result shapes."""
    hits: list[dict[str, Any]] = []
    if result is None:
        return hits

    if isinstance(result, list) and result and isinstance(result[0], dict):
        for page in result:
            texts = list(page.get("rec_texts") or page.get("texts") or [])
            scores = list(page.get("rec_scores") or page.get("scores") or [])
            boxes = list(page.get("dt_polys") or page.get("rec_polys") or page.get("boxes") or [])
            if not texts and "res" in page:
                return _parse_paddle_result(page["res"])
            for i, text in enumerate(texts):
                conf = float(scores[i]) if i < len(scores) else None
                box = boxes[i] if i < len(boxes) else None
                hits.append({"text": str(text), "confidence": conf, "box": _box_to_list(box)})
        return hits

    lines = result[0] if isinstance(result, list) and result else result
    if not lines:
        return hits
    for line in lines:
        if line is None:
            continue
        try:
            box, rec = line
            text, conf = rec
            hits.append({"text": str(text), "confidence": float(conf), "box": _box_to_list(box)})
        except (TypeError, ValueError, IndexError):
            hits.append({"text": str(line), "confidence": None, "box": None})
    return hits


def _run_ocr(ocr: Any, image: Any) -> list[dict[str, Any]]:
    if hasattr(ocr, "predict"):
        try:
            return _parse_paddle_result(ocr.predict(image))
        except Exception as exc:
            logger.warning("predict() failed (%s); trying ocr()", exc)
    if hasattr(ocr, "ocr"):
        # Newer builds may ignore cls=; still try classic call.
        try:
            return _parse_paddle_result(ocr.ocr(image))
        except TypeError:
            return _parse_paddle_result(ocr.ocr(image, cls=True))
    raise RuntimeError("PaddleOCR object has neither predict nor ocr")


def _make_ocr(
    *,
    use_textline_orientation: bool,
    use_doc_orientation_classify: bool = False,
    use_doc_unwarping: bool = False,
    lang: str = "en",
) -> Any:
    from paddleocr import PaddleOCR

    # Current PaddleOCR: use_angle_cls is deprecated → use_textline_orientation.
    return PaddleOCR(
        lang=lang,
        use_textline_orientation=use_textline_orientation,
        use_doc_orientation_classify=use_doc_orientation_classify,
        use_doc_unwarping=use_doc_unwarping,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="PaddleOCR full-image trial for FTA and R (no answer-key crops)."
    )
    parser.add_argument("--dcm", type=str, default=str(_DEFAULT_DCM))
    parser.add_argument("--out", type=str, default=str(_PKG / "out" / "paddle_fta_r"))
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

    modality, pixels = _load_ocr_bgr(dcm)
    png_path = out_dir / "ocr_frame.png"
    cv2.imwrite(str(png_path), pixels)
    logger.info("Loaded %s frame shape=%s", modality, pixels.shape)

    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe_bgr = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)

    configs: list[dict[str, Any]] = [
        {
            "name": "textline_orientation_on",
            "orient": True,
            "image": pixels,
        },
        {
            "name": "textline_orientation_off",
            "orient": False,
            "image": pixels,
        },
        {
            "name": "textline_orientation_on_clahe",
            "orient": True,
            "image": clahe_bgr,
        },
        {
            "name": "textline_orientation_on_png_path",
            "orient": True,
            "image": str(png_path),
        },
    ]

    trials: list[dict[str, Any]] = []
    shared: dict[bool, Any] = {}

    for cfg in configs:
        name = cfg["name"]
        orient = bool(cfg["orient"])
        try:
            if orient not in shared:
                t0 = time.perf_counter()
                shared[orient] = _make_ocr(use_textline_orientation=orient)
                init_s = time.perf_counter() - t0
                logger.info("Created PaddleOCR orient=%s in %.1fs", orient, init_s)
            else:
                init_s = 0.0
            ocr = shared[orient]
            t1 = time.perf_counter()
            hits = _run_ocr(ocr, cfg["image"])
            infer_s = time.perf_counter() - t1
            texts = [h["text"] for h in hits]
            row = {
                "name": name,
                "ok": True,
                "init_seconds": round(init_s, 3),
                "infer_seconds": round(infer_s, 3),
                "found_fta": _has_fta(texts),
                "found_r": _has_r(texts),
                "texts": texts,
                "hits": hits,
            }
        except Exception as exc:
            row = {"name": name, "ok": False, "error": repr(exc)}
        trials.append(row)
        logger.info(
            "%s → ok=%s FTA=%s R=%s infer=%.2fs texts=%s",
            row.get("name"),
            row.get("ok"),
            row.get("found_fta"),
            row.get("found_r"),
            row.get("infer_seconds") or 0,
            row.get("texts") or row.get("error"),
        )

    both = [t for t in trials if t.get("found_fta") and t.get("found_r")]
    scored = []
    for t in trials:
        if not t.get("ok"):
            continue
        score = int(bool(t.get("found_fta"))) + int(bool(t.get("found_r")))
        scored.append((score, -(t.get("infer_seconds") or 99), t))
    scored.sort(reverse=True)
    best = scored[0][2] if scored else None

    summary = {
        "dcm": str(dcm),
        "library": "paddleocr",
        "goal": "Detect both FTA and R in one full-image pass",
        "note": (
            "use_angle_cls is deprecated in current PaddleOCR; "
            "use_textline_orientation is the replacement."
        ),
        "trials": trials,
        "trials_with_both": [t["name"] for t in both],
        "best": {
            "name": best.get("name"),
            "found_fta": best.get("found_fta"),
            "found_r": best.get("found_r"),
            "infer_seconds": best.get("infer_seconds"),
            "texts": best.get("texts"),
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
            f"PaddleOCR found both FTA and R in one full-image pass "
            f"({t['name']}, {t.get('infer_seconds')}s): {t.get('texts')}."
        )
    ok = [t for t in trials if t.get("ok")]
    if not ok:
        errs = [t.get("error") for t in trials if t.get("error")]
        return f"PaddleOCR trials failed to run. Errors: {errs[:2]}"
    fta = [t["name"] for t in ok if t.get("found_fta")]
    r = [t["name"] for t in ok if t.get("found_r")]
    return (
        "PaddleOCR did not find both FTA and R together in a single full-image pass. "
        f"FTA in: {fta or 'none'}. R in: {r or 'none'}. "
        f"Example texts: {ok[0].get('texts')}."
    )


if __name__ == "__main__":
    sys.exit(main())
