"""EasyOCR + OpenMed pixel PHI removal via product remove_pixel_phi."""

from __future__ import annotations

import logging
from pathlib import Path

from easyocr import Reader

from anonymizer.controller.ai.embedded_phi.pixel.cache import (
    OCR_LANGS,
    OCR_MODEL_DIR,
    ocr_models_ready,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import PixelPhiRemovalMode
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import remove_pixel_phi

logger = logging.getLogger(__name__)

_reader: Reader | None = None


def get_ocr_reader() -> Reader:
    global _reader
    if _reader is None:
        if not ocr_models_ready():
            raise RuntimeError("EasyOCR models not ready — download via product AI features")
        _reader = Reader(
            lang_list=list(OCR_LANGS),
            model_storage_directory=str(OCR_MODEL_DIR),
            verbose=False,
        )
    return _reader


def scrub_pixels(
    dcm_path: Path,
    *,
    apply_phi_ner_filter: bool = True,
    removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
    only_if_needed: bool = False,
    burnin_sops: set[str] | None = None,
    sop_uid: str | None = None,
) -> tuple[bool, list[str], int]:
    """
    Run product pixel PHI removal on ``dcm_path`` (mutates file).

    If ``only_if_needed`` and ``burnin_sops`` provided, skip when sop not in set
    (generalizable use: pass Phase-0 discovered set, not hardcoded IDs in callers).
    """
    if only_if_needed and burnin_sops is not None and sop_uid is not None:
        if sop_uid not in burnin_sops:
            return False, [], 0
    reader = get_ocr_reader()
    return remove_pixel_phi(
        dcm_path,
        reader,
        removal_mode=removal_mode,
        apply_phi_ner_filter=apply_phi_ner_filter,
        whitelist=[] if apply_phi_ner_filter else None,
    )
