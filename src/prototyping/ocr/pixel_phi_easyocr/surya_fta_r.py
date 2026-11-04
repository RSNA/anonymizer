"""Try Surya OCR on the MIDI-B chest image for FTA and R.

One full-image pass (no answer-key crops). Uses Surya's Apple Silicon path:
llama.cpp with all layers on Metal (-ngl 99). Reports whether FTA and R appear.

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.surya_fta_r
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

# Surya must import before torch so MPS fallback env is set for layout detector.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)
_ANONYMIZER_INSTALL = Path(__file__).resolve().parents[3] / "anonymizer"
_TAG_RE = re.compile(r"<[^>]+>")
_DEFAULT_GGUF = Path.home() / "Downloads" / "surya-2.5.gguf"
_DEFAULT_MMPROJ = Path.home() / "Downloads" / "surya-2.5-mmproj.gguf"
# Safari in-progress package layout.
_SAFARI_GGUF = Path.home() / "Downloads" / "surya-2.5.gguf.download" / "surya-2.5.gguf"
_EXPECTED_GGUF_BYTES = 1_180_178_976


def _resolve_gguf(path: Path | None) -> Path:
    """Prefer an explicit path, then finished Downloads file, then Safari package."""
    candidates = [p for p in (path, _DEFAULT_GGUF, _SAFARI_GGUF) if p is not None]
    for candidate in candidates:
        if candidate.is_file() and candidate.stat().st_size >= _EXPECTED_GGUF_BYTES:
            return candidate
    for candidate in candidates:
        if candidate.is_file():
            size = candidate.stat().st_size
            raise SystemExit(
                f"GGUF incomplete: {candidate} is {size} bytes "
                f"(need {_EXPECTED_GGUF_BYTES}). Wait for the download to finish."
            )
    raise SystemExit(
        f"GGUF not found. Expected {_DEFAULT_GGUF} (or Safari .download package)."
    )


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
    # Whole-token R only — "R FTA" counts; the R inside PORTABLE does not.
    for text in texts:
        tokens = re.findall(r"[A-Za-z0-9]+", text.upper())
        if "R" in tokens:
            return True
    return False


def _html_to_text(html: str) -> str:
    """Plain text from a Surya block's HTML (API uses html, not text)."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    except Exception:
        return _TAG_RE.sub(" ", html).strip()


def _configure_apple_silicon(
    *,
    gguf: Path,
    mmproj: Path,
) -> dict[str, Any]:
    """Prefer Metal for llama.cpp and MPS for the layout detector; use local GGUFs."""
    import torch
    from surya.settings import settings

    mps_ok = bool(torch.backends.mps.is_available())
    # llamacpp is the supported Apple Silicon path (Metal via -ngl).
    # mlx needs a separate converted checkpoint; not used here.
    settings.SURYA_INFERENCE_BACKEND = "llamacpp"
    settings.LLAMA_CPP_NGL = 99
    settings.SURYA_GGUF_LOCAL_MODEL_PATH = str(gguf)
    settings.SURYA_GGUF_LOCAL_MMPROJ_PATH = str(mmproj)
    if mps_ok:
        settings.TORCH_DEVICE = "mps"
        settings.FAST_DETECTOR_DEVICE = "mps"
    return {
        "backend": settings.SURYA_INFERENCE_BACKEND,
        "llama_cpp_ngl": settings.LLAMA_CPP_NGL,
        "torch_device": settings.TORCH_DEVICE_MODEL,
        "fast_detector_device": settings.FAST_DETECTOR_DEVICE or settings.TORCH_DEVICE_MODEL,
        "mps_available": mps_ok,
        "gguf": str(gguf),
        "mmproj": str(mmproj),
    }


def _parse_page(page: Any) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    blocks = getattr(page, "blocks", None) or []
    for block in blocks:
        html = getattr(block, "html", "") or ""
        text = _html_to_text(html)
        # Also surface label when text is empty (layout saw a region).
        label = getattr(block, "label", "") or ""
        polygon = getattr(block, "polygon", None)
        conf = getattr(block, "confidence", None)
        hits.append(
            {
                "text": text,
                "label": label,
                "confidence": float(conf) if conf is not None else None,
                "box": np.asarray(polygon).reshape(-1, 2).astype(float).tolist()
                if polygon is not None
                else None,
                "skipped": bool(getattr(block, "skipped", False)),
                "error": bool(getattr(block, "error", False)),
                "html": html[:500] if html else "",
            }
        )
    return hits


def _bgr_to_pil(pixels: NDArray[np.uint8]):
    from PIL import Image

    rgb = cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _run_surya(rec_predictor: Any, image) -> list[dict[str, Any]]:
    results = rec_predictor([image])
    if not results:
        return []
    return _parse_page(results[0])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Surya OCR full-image trial for FTA and R (Apple Silicon / Metal)."
    )
    parser.add_argument("--dcm", type=str, default=str(_DEFAULT_DCM))
    parser.add_argument("--out", type=str, default=str(_PKG / "out" / "surya_fta_r"))
    parser.add_argument(
        "--gguf",
        type=str,
        default="",
        help=f"Local surya-2.5.gguf (default: {_DEFAULT_GGUF})",
    )
    parser.add_argument(
        "--mmproj",
        type=str,
        default=str(_DEFAULT_MMPROJ),
        help=f"Local surya-2.5-mmproj.gguf (default: {_DEFAULT_MMPROJ})",
    )
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

    gguf = _resolve_gguf(Path(args.gguf) if args.gguf else None)
    mmproj = Path(args.mmproj)
    if not mmproj.is_file():
        raise SystemExit(
            f"mmproj not found: {mmproj}. Also download surya-2.5-mmproj.gguf "
            f"(~207MB) from datalab-to/surya-ocr-2.5-gguf."
        )

    device_info = _configure_apple_silicon(gguf=gguf, mmproj=mmproj)
    logger.info("Surya device config: %s", device_info)

    modality, pixels = _load_ocr_bgr(dcm)
    png_path = out_dir / "ocr_frame.png"
    cv2.imwrite(str(png_path), pixels)
    logger.info("Loaded %s frame shape=%s", modality, pixels.shape)

    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe_bgr = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)

    from surya.inference import SuryaInferenceManager
    from surya.recognition import RecognitionPredictor

    t0 = time.perf_counter()
    manager = SuryaInferenceManager(method="llamacpp", lazy=False)
    rec_predictor = RecognitionPredictor(manager)
    init_s = time.perf_counter() - t0
    logger.info("Created Surya manager+predictor in %.1fs (backend=%s)", init_s, manager.method)

    configs: list[dict[str, Any]] = [
        {"name": "full_page", "image": _bgr_to_pil(pixels)},
        {"name": "full_page_clahe", "image": _bgr_to_pil(clahe_bgr)},
        {"name": "full_page_png", "image": _bgr_to_pil(cv2.imread(str(png_path)))},
    ]

    trials: list[dict[str, Any]] = []
    try:
        for i, cfg in enumerate(configs):
            name = cfg["name"]
            try:
                t1 = time.perf_counter()
                hits = _run_surya(rec_predictor, cfg["image"])
                infer_s = time.perf_counter() - t1
                texts = [h["text"] for h in hits if h.get("text")]
                row = {
                    "name": name,
                    "ok": True,
                    "init_seconds": round(init_s if i == 0 else 0.0, 3),
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
    finally:
        try:
            manager.stop()
        except Exception as exc:
            logger.warning("manager.stop() failed: %s", exc)

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
        "library": "surya-ocr",
        "goal": "Detect both FTA and R in one full-image pass",
        "device": device_info,
        "note": (
            "User snippet used block.text; Surya 0.23 exposes block.html. "
            "Apple Silicon uses llamacpp + Metal (-ngl 99), not the mlx backend "
            "(mlx needs a separately converted checkpoint)."
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
    print("Device:", json.dumps(device_info, indent=2))
    print("wrote", out_json)
    return 0 if both else 1


def _explain(trials: list[dict[str, Any]], both: list[dict[str, Any]]) -> str:
    if both:
        t = both[0]
        return (
            f"Surya found both FTA and R in one full-image pass "
            f"({t['name']}, {t.get('infer_seconds')}s): {t.get('texts')}."
        )
    ok = [t for t in trials if t.get("ok")]
    if not ok:
        errs = [t.get("error") for t in trials if t.get("error")]
        return f"Surya trials failed to run. Errors: {errs[:2]}"
    fta = [t["name"] for t in ok if t.get("found_fta")]
    r = [t["name"] for t in ok if t.get("found_r")]
    return (
        "Surya did not find both FTA and R together in a single full-image pass. "
        f"FTA in: {fta or 'none'}. R in: {r or 'none'}. "
        f"Example texts: {ok[0].get('texts')}."
    )


if __name__ == "__main__":
    sys.exit(main())
