"""One-case EasyOCR sweep: MIDI-B 7590034066 name line.

Gold line 1 is ``JOHNSON MICHELLE [F] 02.10.2012``. Product detection
(canvas ≤ 1200) returns JOHNSON and misses the rest of that line. This
sweep changes one readtext knob at a time, then a short combo, and records
the smallest change that also returns MICHELLE and the study date.

Usage:
  uv run python -m prototyping.ocr.pixel_phi_easyocr.banner_line_sweep
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prototyping.ocr.pixel_phi_easyocr.corpus import load_pixel_phi_cases
from prototyping.ocr.pixel_phi_easyocr.cost import relative_cost
from prototyping.ocr.pixel_phi_easyocr.pipeline import load_ocr_pixels, run_easyocr

logger = logging.getLogger(__name__)

_PATIENT_ID = "7590034066"
_NEEDLE_NAME = "MICHELLE"
_DATE_FORMS = ("02.10.2012", "02/10/2012", "02-10-2012", "02102012")
_OUT = Path(__file__).resolve().parent / "out" / "banner_line_7590034066.json"

# Controlled baseline matches product word boxes, without 90/270 TTA.
# Horizontal banner text is found on the upright pass; TTA only re-reads
# boxes that were already detected.
_BASE: dict[str, Any] = {"rotation_info": [], "width_ths": 0.1}


def _line_hit(texts: list[str]) -> dict[str, bool]:
    blob = " ".join(texts).upper().replace(" ", "")
    michelle = _NEEDLE_NAME in blob
    date = any(form.replace(" ", "") in blob for form in _DATE_FORMS)
    return {"michelle": michelle, "study_date": date, "full_line": michelle and date}


def _points() -> list[tuple[str, dict[str, Any]]]:
    points: list[tuple[str, dict[str, Any]]] = [("product_defaults", {})]
    controlled = dict(_BASE)
    points.append(("controlled_baseline", controlled))
    for value in (0.55, 0.4, 0.3):
        points.append((f"text_threshold_{value}", {**controlled, "text_threshold": value}))
    for value in (0.3, 0.2):
        points.append((f"low_text_{value}", {**controlled, "low_text": value}))
    for value in (1600, 2000, 2560, 3200):
        points.append((f"canvas_{value}", {**controlled, "canvas_size": value}))
    for value in (1.5, 2.0):
        points.append((f"mag_ratio_{value}", {**controlled, "mag_ratio": value}))
    points.append(
        (
            "contrast_mild",
            {**controlled, "contrast_ths": 0.05, "adjust_contrast": 0.7},
        )
    )
    points.append((f"width_ths_0.5", {**controlled, "width_ths": 0.5}))
    points.append((f"add_margin_0.25", {**controlled, "add_margin": 0.25}))
    points.append(
        (
            "canvas_2000_text_0.4",
            {**controlled, "canvas_size": 2000, "text_threshold": 0.4, "low_text": 0.2},
        )
    )
    return points


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cases = [c for c in load_pixel_phi_cases() if c.patient_id == _PATIENT_ID]
    if not cases:
        raise SystemExit(f"Patient {_PATIENT_ID} not in pixel_phi manifest")
    case = cases[0]
    _ds, pixels = load_ocr_pixels(case.dcm_path)
    max_side = max(pixels.shape[0], pixels.shape[1])
    rows: list[dict[str, Any]] = []
    for name, overrides in _points():
        result = run_easyocr(pixels, modality=case.modality, overrides=overrides)
        texts = [hit.text for hit in result.raw]
        hit = _line_hit(texts)
        cost = relative_cost(overrides, modality=case.modality, image_max_side=max_side)
        row = {
            "name": name,
            "overrides": overrides,
            "relative_cost": round(cost, 2),
            "texts": texts,
            **hit,
        }
        rows.append(row)
        logger.info(
            "%s cost=%.2f full_line=%s texts=%s",
            name,
            cost,
            hit["full_line"],
            texts,
        )
    winners = [row for row in rows if row["full_line"]]
    payload = {
        "patient_id": _PATIENT_ID,
        "dcm": str(case.dcm_path),
        "gold_line": case.boxes[0].text.splitlines()[0],
        "image_shape": list(pixels.shape),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "winners": [row["name"] for row in winners],
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("wrote %s winners=%s", _OUT, payload["winners"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
