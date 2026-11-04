"""Run product OCR prep + EasyOCR readtext with override kwargs."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from easyocr import Reader
from pydicom import dcmread

from anonymizer.controller.ai.embedded_phi.pixel.cache import (
    OCR_LANGS,
    OCR_MODEL_DIR,
    ocr_models_ready,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import ocr_image_for_frame
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    detect_text,
    filter_ocr_noise,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _ocr_use_gpu
from anonymizer.controller.series.series_overlay import OCRText, OcrEvidence
from prototyping.ocr.pixel_phi_easyocr.score import HitSummary

logger = logging.getLogger(__name__)

_ANONYMIZER_INSTALL_DIR = Path(__file__).resolve().parents[3] / "anonymizer"
_reader: Reader | None = None

# Mirror product defaults from ocr_pipeline.detect_text (for override sweeps).
_OCR_CANVAS_SIZE_THRESHOLD = 1200
_DEFAULT_YCENTER_THS = 0.5
_DEFAULT_LINK_THRESHOLD = 0.4
_DEFAULT_WIDTH_THS = 0.5
_DEFAULT_TEXT_THRESHOLD = 0.7


def ensure_anonymizer_cwd() -> Path:
    """Match product main so relative assets/ai/ocr/model resolves."""
    install = _ANONYMIZER_INSTALL_DIR.resolve()
    if Path.cwd().resolve() != install:
        os.chdir(install)
        logger.info("cwd → %s", install)
    return install


def get_ocr_reader() -> Reader:
    """Lazy EasyOCR Reader using packaged weights (CUDA/MPS when available)."""
    global _reader
    if _reader is None:
        ensure_anonymizer_cwd()
        if not ocr_models_ready():
            raise RuntimeError("EasyOCR models not ready — download via product AI features")
        use_gpu = _ocr_use_gpu()
        _reader = Reader(
            lang_list=list(OCR_LANGS),
            model_storage_directory=str(OCR_MODEL_DIR),
            gpu=use_gpu,
            verbose=False,
        )
        logger.info("EasyOCR Reader ready gpu=%s dir=%s", use_gpu, OCR_MODEL_DIR)
    return _reader


def load_ocr_pixels(dcm_path: Path) -> tuple[Any, np.ndarray]:
    """
    Load a DICOM and build the same BGR uint8 frame Series View / batch use.

    Args:
        dcm_path: Path to a single-frame CR/DX instance.

    Returns:
        (dataset, bgr_uint8_pixels)
    """
    ensure_anonymizer_cwd()
    ds = dcmread(str(dcm_path))
    frame = np.asarray(ds.pixel_array)
    pixels = ocr_image_for_frame(ds, frame)
    return ds, pixels


def params_key(overrides: Mapping[str, Any] | None) -> str:
    """Stable short key for logs / ranking."""
    if not overrides:
        return "product_baseline"
    payload = {k: overrides[k] for k in sorted(overrides)}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


@dataclass
class RunResult:
    """Raw EasyOCR hits plus product noise-filter survivors."""

    params_key: str
    overrides: dict[str, Any]
    modality: str
    raw: list[HitSummary]
    filtered: list[HitSummary]
    easyocr_raw: list[dict[str, Any]]


def _hit_from_ocr_text(item: OCRText) -> HitSummary:
    x1, y1, x2, y2 = item.get_bounding_box()
    return HitSummary(
        text=item.text or "",
        prob=float(item.ocr.prob),
        top_left=(x1, y1),
        bottom_right=(x2, y2),
    )


def _easyocr_summary(results: list) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for result in results:
        try:
            box, text, prob = result
            out.append(
                {
                    "text": text,
                    "prob": round(float(prob), 4),
                    "box": [[round(float(x), 1), round(float(y), 1)] for x, y in box],
                }
            )
        except (TypeError, ValueError, IndexError):
            out.append({"raw": repr(result)[:240]})
    return out


def _ocr_text_from_easyocr_result(result, img_width: int, img_height: int) -> OCRText:
    box, text, prob = result
    if not (len(box) == 4 and all(len(point) == 2 for point in box)):
        raise ValueError(f"Invalid box format: {box}")
    xs = [float(point[0]) for point in box]
    ys = [float(point[1]) for point in box]
    x1, y1, x2, y2 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    x1_c = max(0, x1)
    y1_c = max(0, y1)
    x2_c = min(img_width, x2)
    y2_c = min(img_height, y2)
    if x1_c >= x2_c or y1_c >= y2_c:
        raise ValueError(f"Bounding box invalid after clipping [{x1},{y1},{x2},{y2}]")
    return OCRText(
        text=str(text),
        top_left=(x1_c, y1_c),
        bottom_right=(x2_c, y2_c),
        ocr=OcrEvidence(prob=float(prob)),
    )


def _rotation_angles(modality: str | None) -> list[int]:
    if str(modality or "").upper() == "US":
        return []
    return [90, 270]


def run_easyocr(
    pixels: np.ndarray,
    *,
    modality: str,
    overrides: Mapping[str, Any] | None = None,
    reader: Reader | None = None,
) -> RunResult:
    """
    Run EasyOCR with product defaults plus optional overrides; apply noise filter.

    Args:
        pixels: BGR uint8 frame from ocr_image_for_frame.
        modality: DICOM modality (drives product rotation_info).
        overrides: Extra readtext kwargs merged after product defaults.
        reader: Optional shared Reader.

    Returns:
        Raw and noise-filtered hit summaries.
    """
    ocr = reader or get_ocr_reader()
    ov = dict(overrides or {})
    if not ov:
        raw_texts = detect_text(pixels, ocr, modality=modality)
        filtered = filter_ocr_noise(raw_texts, modality=modality)
        return RunResult(
            params_key=params_key(ov),
            overrides=ov,
            modality=modality,
            raw=[_hit_from_ocr_text(t) for t in raw_texts],
            filtered=[_hit_from_ocr_text(t) for t in filtered],
            easyocr_raw=[],
        )

    canvas_size = min(max(pixels.shape[0], pixels.shape[1]), _OCR_CANVAS_SIZE_THRESHOLD)
    kwargs: dict[str, Any] = {
        "canvas_size": canvas_size,
        "paragraph": False,
        "add_margin": 0.1,
        "rotation_info": _rotation_angles(modality),
        "min_size": 1,
        "ycenter_ths": _DEFAULT_YCENTER_THS,
        "link_threshold": _DEFAULT_LINK_THRESHOLD,
        "width_ths": _DEFAULT_WIDTH_THS,
        "text_threshold": _DEFAULT_TEXT_THRESHOLD,
    }
    kwargs.update(ov)
    results = ocr.readtext(pixels, **kwargs)
    h, w = pixels.shape[:2]
    raw_texts: list[OCRText] = []
    for result in results:
        try:
            raw_texts.append(_ocr_text_from_easyocr_result(result, w, h))
        except ValueError as exc:
            logger.warning("skip invalid OCR result: %s", exc)
    filtered = filter_ocr_noise(raw_texts, modality=modality)
    return RunResult(
        params_key=params_key(ov),
        overrides=ov,
        modality=modality,
        raw=[_hit_from_ocr_text(t) for t in raw_texts],
        filtered=[_hit_from_ocr_text(t) for t in filtered],
        easyocr_raw=_easyocr_summary(results),
    )


def write_overlay_png(
    pixels: np.ndarray,
    hits: list[HitSummary],
    out_path: Path,
    *,
    title: str = "",
) -> Path:
    """Draw AABB boxes + labels on a copy of the OCR frame."""
    import cv2

    canvas = pixels.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    for hit in hits:
        x1, y1 = hit.top_left
        x2, y2 = hit.bottom_right
        color = (0, 255, 0) if hit.prob >= 0.5 else (0, 128, 255)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        label = f"{hit.text} ({hit.prob:.2f})"
        cv2.putText(
            canvas,
            label,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )
    if title:
        cv2.putText(
            canvas,
            title[:120],
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Downscale for archive size while keeping readable markers.
    max_side = 1600
    h, w = canvas.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        canvas = cv2.resize(canvas, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out_path), canvas)
    return out_path
