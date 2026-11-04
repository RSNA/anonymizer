"""Evaluate one EasyOCR override dict across all pixel_phi cases."""

from __future__ import annotations

import gc
import logging
from typing import Any, Mapping, Sequence

from easyocr import Reader

from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _clear_torch_caches
from prototyping.ocr.pixel_phi_easyocr.corpus import PixelPhiCase
from prototyping.ocr.pixel_phi_easyocr.cost import relative_cost
from prototyping.ocr.pixel_phi_easyocr.pipeline import load_ocr_pixels, params_key, run_easyocr
from prototyping.ocr.pixel_phi_easyocr.score import CorpusReport, score_case

logger = logging.getLogger(__name__)


def eval_overrides_on_corpus(
    cases: Sequence[PixelPhiCase],
    overrides: Mapping[str, Any] | None,
    *,
    reader: Reader,
    target_accuracy: float = 0.95,
) -> CorpusReport:
    """
    Run EasyOCR with overrides on every case; score gold-box text recall.

    Loads one frame at a time (no corpus preload) and clears torch caches after
    each image so MPS/CUDA memory does not grow across the sweep.

    Args:
        cases: pixel_phi cases.
        overrides: Extra readtext kwargs (merged after product defaults).
        reader: Shared EasyOCR reader (loaded once for the process).
        target_accuracy: Case-pass fraction goal (default 95%).

    Returns:
        CorpusReport with per-case detail.
    """
    ov = dict(overrides or {})
    reports = []
    # Cost vs a large CR frame (worst-case product canvas path).
    cost = relative_cost(ov, modality="CR", image_max_side=3027)
    for case in cases:
        ds, pixels = load_ocr_pixels(case.dcm_path)
        modality = str(ds.get("Modality", "") or case.modality or "CR")
        # Drop dataset ASAP; only the uint8 frame is needed for OCR.
        del ds
        result = run_easyocr(
            pixels,
            modality=modality,
            overrides=ov,
            reader=reader,
        )
        reports.append(score_case(case, result.raw))
        logger.info(
            "%s %s hit=%d/%d raw=%s",
            case.case_id,
            "OK" if reports[-1].passed else "MISS",
            reports[-1].boxes_hit,
            reports[-1].boxes_total,
            reports[-1].raw_texts[:6],
        )
        del pixels, result
        _clear_torch_caches()
        gc.collect()
    return CorpusReport(
        params_key=params_key(ov),
        overrides=ov,
        relative_cost=cost,
        cases=reports,
        target_accuracy=target_accuracy,
    )


def rank_key(report: CorpusReport) -> tuple:
    """
    Prefer target met, then higher accuracy, then lower compute cost.

    Sort descending with this key.
    """
    return (
        report.met_target,
        report.case_accuracy,
        report.box_recall,
        -report.relative_cost,
    )
