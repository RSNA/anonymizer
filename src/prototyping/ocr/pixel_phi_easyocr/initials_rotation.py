"""Focused experiment: recover diagonal burned-in initials (FTA / R) via crop + fine angles.

Product EasyOCR only TTA-rotates recognition crops by 90/180/270. Diagonal ~45°
markers are supposed to be deskewed from free-form CRAFT quads; on this CR that
fails (FTA region often decoded as '8'). This harness:

1. Crops the MIDI-B gold FTA box (+ margin) and a wider top-left patch (R+FTA).
2. Rotates each crop through fine angles and runs the shared product Reader.
3. Reports which angle first yields FTA / R — evidence for a cheap deskew path
   to merge (crop-local rotate), not full-image TTA.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.pipeline import (
    ensure_anonymizer_cwd,
    get_ocr_reader,
    load_ocr_pixels,
    run_easyocr,
    write_overlay_png,
)
from prototyping.ocr.pixel_phi_easyocr.score import HitSummary

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent
_DEFAULT_DCM = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/pixel_phi/test/113575183/"
    "11-11-2013-NA-XR CHEST 1 VIEW AP for 486-93-8764-77898/"
    "20131111.000000-AP-54935/1-1.dcm"
)
# MIDI-B gold FTA AABB (native pixel coords).
_FTA_TL = (225, 213)
_FTA_BR = (318, 317)
_DEFAULT_ANGLES = (0, 15, 30, 45, 60, -15, -30, -45, -60, 90, -90)
_TARGETS = ("FTA", "R")


@dataclass(frozen=True)
class AngleHit:
    """One crop×angle EasyOCR outcome."""

    region: str
    angle_deg: float
    texts: tuple[str, ...]
    found_fta: bool
    found_r: bool


def _norm_texts(hits: Sequence[HitSummary]) -> tuple[str, ...]:
    return tuple(h.norm for h in hits if h.norm)


def _has_token(texts: Sequence[str], token: str) -> bool:
    """Match gold token; single-letter markers (R) require exact equality."""
    tok = token.upper()
    if len(tok) == 1:
        return any(t == tok for t in texts)
    return any(t == tok or tok in t for t in texts)


def crop_aabb(
    pixels: NDArray[np.uint8],
    top_left: tuple[int, int],
    bottom_right: tuple[int, int],
    *,
    margin_px: int = 40,
) -> tuple[NDArray[np.uint8], tuple[int, int, int, int]]:
    """
    Axis-aligned crop with margin, clipped to the frame.

    Returns:
        (crop_bgr, (x1, y1, x2, y2) in full-image coords)
    """
    h, w = pixels.shape[:2]
    x1 = max(0, int(top_left[0]) - margin_px)
    y1 = max(0, int(top_left[1]) - margin_px)
    x2 = min(w, int(bottom_right[0]) + margin_px)
    y2 = min(h, int(bottom_right[1]) + margin_px)
    return pixels[y1:y2, x1:x2].copy(), (x1, y1, x2, y2)


def rotate_bound(image: NDArray[np.uint8], angle_deg: float) -> NDArray[np.uint8]:
    """Rotate image about center; expand canvas so corners are not clipped."""
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


def _ocr_crop(
    crop: NDArray[np.uint8],
    *,
    reader,
    modality: str,
    easyocr_overrides: dict[str, Any] | None,
) -> list[HitSummary]:
    # No product rotation_info — we supply the deskew ourselves.
    ov = {"rotation_info": [], **(easyocr_overrides or {})}
    result = run_easyocr(crop, modality=modality, overrides=ov, reader=reader)
    return list(result.raw)


def sweep_region(
    *,
    region: str,
    crop: NDArray[np.uint8],
    angles: Sequence[float],
    reader,
    modality: str,
    out_dir: Path | None,
) -> list[AngleHit]:
    """OCR one crop at each angle; optionally write overlay PNGs."""
    hits: list[AngleHit] = []
    for angle in angles:
        rotated = rotate_bound(crop, float(angle))
        raw = _ocr_crop(rotated, reader=reader, modality=modality, easyocr_overrides=None)
        texts = _norm_texts(raw)
        row = AngleHit(
            region=region,
            angle_deg=float(angle),
            texts=texts,
            found_fta=_has_token(texts, "FTA"),
            found_r=_has_token(texts, "R"),
        )
        hits.append(row)
        logger.info(
            "%s angle=%+.0f° fta=%s r=%s texts=%s",
            region,
            angle,
            row.found_fta,
            row.found_r,
            list(texts),
        )
        if out_dir is not None:
            write_overlay_png(
                rotated,
                raw,
                out_dir / f"{region}_ang{int(angle):+04d}.png",
                title=f"{region} {angle:+.0f}deg",
            )
        del rotated, raw
        _clear_torch_caches()
    return hits


def run_initials_experiment(
    dcm_path: Path,
    *,
    angles: Sequence[float] = _DEFAULT_ANGLES,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Full-frame baseline + gold FTA crop + top-left patch, fine-angle sweep.

    Args:
        dcm_path: MIDI-B / Whitaker-class CR with diagonal FTA.
        angles: Deskew angles in degrees (OpenCV: positive = counter-clockwise).
        out_dir: Optional directory for crop overlays.

    Returns:
        JSON-serializable summary of what recovered FTA / R.
    """
    ensure_anonymizer_cwd()
    reader = get_ocr_reader()
    ds, pixels = load_ocr_pixels(dcm_path)
    modality = str(ds.get("Modality", "") or "CR")
    del ds

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    # --- Full frame product path (no extra angles) ---
    full = run_easyocr(pixels, modality=modality, overrides={"rotation_info": []}, reader=reader)
    full_texts = _norm_texts(full.raw)
    logger.info("full_frame texts=%s", list(full_texts))
    if out_dir is not None:
        write_overlay_png(pixels, full.raw, out_dir / "full_frame.png", title="full no-TTA")

    # --- Gold FTA crop ---
    fta_crop, fta_box = crop_aabb(pixels, _FTA_TL, _FTA_BR, margin_px=48)
    # --- Wider top-left (R above FTA) ---
    tl_crop, tl_box = crop_aabb(pixels, (40, 40), (520, 480), margin_px=0)

    fta_hits = sweep_region(
        region="fta_gold",
        crop=fta_crop,
        angles=angles,
        reader=reader,
        modality=modality,
        out_dir=out_dir,
    )
    tl_hits = sweep_region(
        region="top_left",
        crop=tl_crop,
        angles=angles,
        reader=reader,
        modality=modality,
        out_dir=out_dir,
    )

    def _first(rows: list[AngleHit], attr: str) -> float | None:
        for row in rows:
            if getattr(row, attr):
                return row.angle_deg
        return None

    summary = {
        "dcm": str(dcm_path),
        "modality": modality,
        "gold_fta_box": {"top_left": list(_FTA_TL), "bottom_right": list(_FTA_BR)},
        "crops": {"fta_gold": list(fta_box), "top_left": list(tl_box)},
        "full_frame": {
            "texts": list(full_texts),
            "found_fta": _has_token(full_texts, "FTA"),
            "found_r": _has_token(full_texts, "R"),
        },
        "first_angle_fta_gold": _first(fta_hits, "found_fta"),
        "first_angle_r_top_left": _first(tl_hits, "found_r"),
        "first_angle_fta_top_left": _first(tl_hits, "found_fta"),
        "fta_gold_sweep": [
            {
                "angle": h.angle_deg,
                "texts": list(h.texts),
                "fta": h.found_fta,
                "r": h.found_r,
            }
            for h in fta_hits
        ],
        "top_left_sweep": [
            {
                "angle": h.angle_deg,
                "texts": list(h.texts),
                "fta": h.found_fta,
                "r": h.found_r,
            }
            for h in tl_hits
        ],
        "conclusion": _conclusion(fta_hits, tl_hits, full_texts),
    }
    return summary


def _conclusion(
    fta_hits: list[AngleHit],
    tl_hits: list[AngleHit],
    full_texts: Sequence[str],
) -> str:
    fta_ang = next((h.angle_deg for h in fta_hits if h.found_fta), None)
    r_ang = next((h.angle_deg for h in tl_hits if h.found_r), None)
    fta_tl = next((h.angle_deg for h in tl_hits if h.found_fta), None)
    if _has_token(full_texts, "FTA"):
        return "Full-frame already reads FTA — rotation not the blocker."
    if fta_ang is not None:
        return (
            f"FTA recovered on gold crop at {fta_ang:+.0f}° deskew. "
            "Merge candidate: local fine-angle TTA on free-form / short-marker crops only "
            "(not full-image 90° TTA)."
        )
    if fta_tl is not None:
        return (
            f"FTA recovered on wider top-left crop at {fta_tl:+.0f}° "
            f"(R at {r_ang}). Crop size/context matters as well as angle."
        )
    return (
        "FTA not recovered at any tested fine angle on crops — "
        "not solely a missing 45° product rotation_info issue; "
        "check contrast / CRAFT box / recognizer allowlist next."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fine-angle deskew experiment for FTA/R initials")
    parser.add_argument("--dcm", type=str, default=str(_DEFAULT_DCM))
    parser.add_argument(
        "--angles",
        type=str,
        default=",".join(str(a) for a in _DEFAULT_ANGLES),
        help="Comma-separated deskew angles in degrees",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(_PKG / "out" / "initials_rotation"),
        help="Overlay + summary JSON directory",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    dcm = Path(args.dcm)
    if not dcm.is_file():
        raise SystemExit(f"DICOM not found: {dcm}")
    angles = tuple(float(x.strip()) for x in args.angles.split(",") if x.strip())
    out_dir = Path(args.out)
    summary = run_initials_experiment(dcm, angles=angles, out_dir=out_dir)
    out_json = out_dir / "summary.json"
    out_json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "full_frame",
        "first_angle_fta_gold",
        "first_angle_fta_top_left",
        "first_angle_r_top_left",
        "conclusion",
    )}, indent=2))
    print("wrote", out_json)
    log = _PKG / "PIXEL_PHI_EASYOCR_EXPERIMENT.md"
    with log.open("a", encoding="utf-8") as f:
        f.write(
            f"\n## initials_rotation {datetime.now(timezone.utc).isoformat()}\n\n"
            f"conclusion: {summary['conclusion']}\n\n"
            f"```json\n{json.dumps({k: summary[k] for k in ('full_frame', 'first_angle_fta_gold', 'first_angle_fta_top_left', 'first_angle_r_top_left')}, indent=2)}\n```\n"
        )
    ok = summary["first_angle_fta_gold"] is not None or summary["first_angle_fta_top_left"] is not None
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
