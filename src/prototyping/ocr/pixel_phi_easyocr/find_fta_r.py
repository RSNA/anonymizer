"""Find EasyOCR settings that read both FTA and R on the MIDI-B chest CR.

No answer-key boxes. Crops come only from EasyOCR's own detections, or from
simple full-image image prep (CLAHE / threshold).

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.find_fta_r
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.pipeline import (
    ensure_anonymizer_cwd,
    get_ocr_reader,
    load_ocr_pixels,
    run_easyocr,
)

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)


def _texts(hits) -> list[str]:
    return [(h.text or "").strip() for h in hits if (h.text or "").strip()]


def _has_fta(texts: Sequence[str]) -> bool:
    return any("FTA" in t.upper() for t in texts)


def _has_r(texts: Sequence[str]) -> bool:
    # Exact token only — do not match the letter R inside PORTABLE.
    return any(t.strip().upper() == "R" for t in texts)


def _to_bgr_gray_stack(gray: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


def prep_none(pixels: NDArray[np.uint8]) -> NDArray[np.uint8]:
    return pixels


def prep_clahe(pixels: NDArray[np.uint8]) -> NDArray[np.uint8]:
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return _to_bgr_gray_stack(clahe.apply(gray))


def prep_clahe_strong(pixels: NDArray[np.uint8]) -> NDArray[np.uint8]:
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    return _to_bgr_gray_stack(clahe.apply(gray))


def prep_clahe_thresh(pixels: NDArray[np.uint8], thresh: int = 80) -> NDArray[np.uint8]:
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    _, binary = cv2.threshold(eq, thresh, 255, cv2.THRESH_BINARY)
    return _to_bgr_gray_stack(binary)


def prep_otsu(pixels: NDArray[np.uint8]) -> NDArray[np.uint8]:
    gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return _to_bgr_gray_stack(binary)


PREP_FUNCS: dict[str, Callable[[NDArray[np.uint8]], NDArray[np.uint8]]] = {
    "none": prep_none,
    "clahe": prep_clahe,
    "clahe_strong": prep_clahe_strong,
    "clahe_thresh_80": lambda p: prep_clahe_thresh(p, 80),
    "clahe_thresh_100": lambda p: prep_clahe_thresh(p, 100),
    "otsu": prep_otsu,
}


def rotate_image(image: NDArray[np.uint8], angle_deg: float) -> NDArray[np.uint8]:
    if abs(angle_deg) < 1e-6:
        return image
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    matrix[0, 2] += (new_w / 2.0) - center[0]
    matrix[1, 2] += (new_h / 2.0) - center[1]
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def crop_from_hit(pixels: NDArray[np.uint8], hit, *, pad: int = 24) -> NDArray[np.uint8]:
    """Crop using EasyOCR's own box only (not any answer file)."""
    h, w = pixels.shape[:2]
    x1, y1 = hit.top_left
    x2, y2 = hit.bottom_right
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    return pixels[y1:y2, x1:x2].copy()


@dataclass
class TrialResult:
    name: str
    texts: list[str]
    found_fta: bool
    found_r: bool

    @property
    def score(self) -> int:
        return int(self.found_fta) + int(self.found_r)


def run_trial(
    name: str,
    pixels: NDArray[np.uint8],
    *,
    reader,
    modality: str,
    overrides: dict[str, Any] | None,
) -> TrialResult:
    result = run_easyocr(pixels, modality=modality, overrides=overrides, reader=reader)
    texts = _texts(result.raw)
    trial = TrialResult(
        name=name,
        texts=texts,
        found_fta=_has_fta(texts),
        found_r=_has_r(texts),
    )
    logger.info(
        "%s → FTA=%s R=%s texts=%s",
        name,
        trial.found_fta,
        trial.found_r,
        texts,
    )
    _clear_torch_caches()
    return trial


def pick_retry_hits(hits) -> list:
    """
    Choose EasyOCR boxes worth a second look.

    Prefer large boxes whose text is short, digit-like, or not a clear
    horizontal label (skip PORTABLE / SEMI-ERECT style hits).
    """
    skip = {"PORTABLE", "SEMI-ERECT", "SEMI", "ERECT", "UPRIGHT"}
    ranked = []
    for hit in hits:
        text = (hit.text or "").strip()
        upper = text.upper()
        if upper in skip or any(s in upper for s in ("PORTABLE", "SEMI-ERECT", "UPRIGHT")):
            continue
        x1, y1 = hit.top_left
        x2, y2 = hit.bottom_right
        area = max(0, x2 - x1) * max(0, y2 - y1)
        short = len(text) <= 4
        digitish = any(ch.isdigit() for ch in text) and not any(ch.isalpha() for ch in text)
        if area < 2000:
            continue
        if short or digitish or area >= 20000:
            ranked.append((area, hit))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [hit for _, hit in ranked[:5]]


def top_left_band(
    pixels: NDArray[np.uint8],
    *,
    frac_w: float = 0.30,
    frac_h: float = 0.35,
) -> NDArray[np.uint8]:
    """
    Fixed top-left band of the image.

    General chest X-ray layout habit for side markers — not coordinates
    from any answer file.
    """
    h, w = pixels.shape[:2]
    return pixels[0 : int(h * frac_h), 0 : int(w * frac_w)].copy()


def top_right_band(
    pixels: NDArray[np.uint8],
    *,
    frac_w: float = 0.30,
    frac_h: float = 0.35,
) -> NDArray[np.uint8]:
    """
    Fixed top-right band of the image.

    General chest X-ray layout habit for side markers — not coordinates
    from any answer file.
    """
    h, w = pixels.shape[:2]
    x0 = w - int(w * frac_w)
    return pixels[0 : int(h * frac_h), x0:w].copy()


def cxr_corner_bands(
    pixels: NDArray[np.uint8],
    *,
    frac_w: float = 0.32,
    frac_h: float = 0.38,
) -> list[tuple[str, NDArray[np.uint8]]]:
    """Top-left and top-right CXR marker bands (layout heuristic only)."""
    return [
        ("top_left", top_left_band(pixels, frac_w=frac_w, frac_h=frac_h)),
        ("top_right", top_right_band(pixels, frac_w=frac_w, frac_h=frac_h)),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find EasyOCR setup that reads both FTA and R (no answer-key crops)."
    )
    parser.add_argument("--dcm", type=str, default=str(_DEFAULT_DCM))
    parser.add_argument(
        "--out",
        type=str,
        default=str(_PKG / "out" / "find_fta_r"),
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

    ensure_anonymizer_cwd()
    reader = get_ocr_reader()
    ds, base_pixels = load_ocr_pixels(dcm)
    modality = str(ds.get("Modality") or "CR")
    del ds

    trials: list[TrialResult] = []

    # --- A. Full image: EasyOCR settings only ---
    full_settings: list[tuple[str, dict[str, Any]]] = [
        ("full_product_rot_90_270", {"rotation_info": [90, 270]}),
        ("full_no_rot", {"rotation_info": []}),
        ("full_rot_45", {"rotation_info": [45]}),
        ("full_rot_15_30_45", {"rotation_info": [15, 30, 45]}),
        ("full_rot_45_90_270", {"rotation_info": [45, 90, 270]}),
        (
            "full_contrast_boost",
            {
                "rotation_info": [],
                "contrast_ths": 0.05,
                "adjust_contrast": 0.7,
            },
        ),
        (
            "full_low_text_thresh",
            {
                "rotation_info": [],
                "text_threshold": 0.5,
                "low_text": 0.3,
            },
        ),
    ]
    for name, overrides in full_settings:
        trials.append(
            run_trial(name, base_pixels, reader=reader, modality=modality, overrides=overrides)
        )

    # --- B. Full image after simple image prep (YouTube-style) ---
    for prep_name, prep_fn in PREP_FUNCS.items():
        if prep_name == "none":
            continue
        prepared = prep_fn(base_pixels)
        for rot_name, rot in (
            ("no_rot", []),
            ("rot_45", [45]),
            ("rot_15_30_45", [15, 30, 45]),
        ):
            trials.append(
                run_trial(
                    f"full_{prep_name}_{rot_name}",
                    prepared,
                    reader=reader,
                    modality=modality,
                    overrides={"rotation_info": rot},
                )
            )
        del prepared

    # --- C. Second pass on EasyOCR's own boxes (from the product-like pass) ---
    seed = run_easyocr(
        base_pixels,
        modality=modality,
        overrides={"rotation_info": [90, 270]},
        reader=reader,
    )
    retry_hits = pick_retry_hits(seed.raw)
    logger.info(
        "Second-pass candidates from EasyOCR boxes: %s",
        [(h.text, h.top_left, h.bottom_right) for h in retry_hits],
    )
    deskew_angles = (0, 15, 30, 45, 60, -15, -30)
    for i, hit in enumerate(retry_hits):
        crop = crop_from_hit(base_pixels, hit, pad=32)
        for prep_name in ("none", "clahe", "clahe_strong"):
            prepared = PREP_FUNCS[prep_name](crop)
            for angle in deskew_angles:
                rotated = rotate_image(prepared, float(angle))
                name = f"retry_box{i}_{prep_name}_ang{int(angle):+d}"
                trials.append(
                    run_trial(
                        name,
                        rotated,
                        reader=reader,
                        modality=modality,
                        overrides={"rotation_info": []},
                    )
                )
                del rotated
            del prepared
        del crop

    # --- D. Fixed top-left band of the image (layout habit, not answer coords) ---
    band = top_left_band(base_pixels)
    for prep_name in ("none", "clahe", "clahe_strong"):
        prepared = PREP_FUNCS[prep_name](band)
        for angle in deskew_angles:
            rotated = rotate_image(prepared, float(angle))
            trials.append(
                run_trial(
                    f"topleft_band_{prep_name}_ang{int(angle):+d}",
                    rotated,
                    reader=reader,
                    modality=modality,
                    overrides={"rotation_info": []},
                )
            )
            del rotated
        # Also try EasyOCR built-in fine rotations on the band
        trials.append(
            run_trial(
                f"topleft_band_{prep_name}_easyocr_rot_15_30_45",
                prepared,
                reader=reader,
                modality=modality,
                overrides={"rotation_info": [15, 30, 45]},
            )
        )
        del prepared
    del band

    # Rank: both FTA and R first, then either, then by name.
    trials.sort(key=lambda t: (t.score, t.found_fta, t.found_r), reverse=True)
    best = trials[0]
    both = [t for t in trials if t.score == 2]

    summary = {
        "dcm": str(dcm),
        "n_trials": len(trials),
        "best": {
            "name": best.name,
            "score": best.score,
            "found_fta": best.found_fta,
            "found_r": best.found_r,
            "texts": best.texts,
        },
        "trials_with_both_fta_and_r": [
            {"name": t.name, "texts": t.texts} for t in both
        ],
        "all_trials": [
            {
                "name": t.name,
                "score": t.score,
                "found_fta": t.found_fta,
                "found_r": t.found_r,
                "texts": t.texts,
            }
            for t in trials
        ],
        "plain_english": _explain(both, best, retry_hits),
    }
    out_json = out_dir / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary["plain_english"])
    print("\nBest trial:", json.dumps(summary["best"], indent=2))
    print(f"Trials with both FTA and R: {len(both)}")
    print("wrote", out_json)
    return 0 if both else 1


def _explain(both: list[TrialResult], best: TrialResult, retry_hits) -> str:
    lines = []
    if both:
        lines.append(
            f"SUCCESS: {len(both)} setup(s) found both FTA and R. "
            f"Best example: {both[0].name} → {both[0].texts}."
        )
        # Prefer full-image wins over second-pass if any.
        full_both = [t for t in both if t.name.startswith("full_")]
        retry_both = [t for t in both if t.name.startswith("retry_")]
        if full_both:
            lines.append(
                "A full-image setup worked (image prep and/or EasyOCR rotation). "
                f"Example: {full_both[0].name}."
            )
        if retry_both:
            lines.append(
                "A second pass also worked: take EasyOCR's own large short/digit "
                f"box(es) {[(h.text, h.top_left, h.bottom_right) for h in retry_hits]}, "
                "crop that box, optionally CLAHE, rotate the crop, run EasyOCR again. "
                f"Example: {retry_both[0].name}."
            )
    else:
        lines.append(
            f"Neither FTA and R together in one trial. Best was {best.name} "
            f"(FTA={best.found_fta}, R={best.found_r}, texts={best.texts})."
        )
    return " ".join(lines)


if __name__ == "__main__":
    sys.exit(main())
