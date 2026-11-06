"""Pixel Embedded PHI text pipeline: detect, annotate; callers decide.

Stages fill nested OCRText evidence only (no decision flags, no evaluate mutator).
Callers decide with is_whitelisted / phi_accepted + current PhiMatchMode.
A whitelist score above 0.8 always wins. A weaker hit wins only when
ner.score < whitelist.score - 0.1 (a fuzzy resemblance can stay PHI).

Public API
----------
PhiMatchMode
    EXACT | STRICT | STANDARD | LENIENT — whitelist similarity + NER score floors.

PhiMatchThresholds
    whitelist_similarity and ner_score for one mode.

thresholds_for(mode: PhiMatchMode) -> PhiMatchThresholds
    Preset floors for a match mode.

is_whitelisted(t: OCRText, mode: PhiMatchMode) -> bool
    True when whitelist.score is set and meets the mode similarity floor.

phi_accepted(t: OCRText, mode: PhiMatchMode) -> bool
    True when NER meets the mode floor and whitelist does not override.

effective_phi_label(t: OCRText, mode: PhiMatchMode) -> str | None
    Highest-scoring accepted NER label. Rectangle color uses this one label.

accepted_phi_entities(t: OCRText, mode: PhiMatchMode) -> tuple[tuple[str, str], ...]
    NER entities on this box that meet the mode floor. (label, text) in span order.

detect_text(pixels: NDArray[np.uint8], ocr_reader: Reader, *, modality: str | None=None) -> list[OCRText]
    EasyOCR only. One upright read. Sets ocr.prob; whitelist/ner scores stay None.

filter_ocr_noise(texts: list[OCRText], *, modality: str | None=None) -> list[OCRText]
    Geometry + min_prob; may drop boxes. Optional in the pipe.

make_annotate_whitelist(terms: list[str])
    Factory: best similarity vs terms → whitelist.term / whitelist.score. Never drop.

normalize_clock_text_for_ner(text: str) -> str
    Rewrite HH MM SS to HH:MM:SS for NER TIME (XR/US) only when HH/MM/SS are valid.
    Separators may be non-digits, digit 8 (':' misread), or a mix of both.

annotate_ner(texts: list[OCRText], *, locale: str='en_US', modality: str | None=None, detect_fn=None) -> list[OCRText]
    Frame-join NER (include_time). Skip boxes of 2 characters or fewer.
    No comma after a fragment that already ends with a separator. XR/US clock normalize. Never drop.

pipe(*stages)
    Compose annotate stages; each stage logs. No decide/evaluate stage.

format_ocr_texts_for_log(stage_name: str, texts: list[OCRText], *, mode: PhiMatchMode | None=None, dropped: int | None=None) -> str
    Stage-local log body; header box count matches printed lines.

log_ocr_stage(stage_name: str, texts: list[OCRText], *, mode: PhiMatchMode | None=None, dropped: int | None=None) -> list[OCRText]
    Log format_ocr_texts_for_log; return texts unchanged.

log_ocr_decisions(texts: list[OCRText], mode: PhiMatchMode, *, remove_mode: str | None=None) -> None
    Caller-side decisions log (whitelisted / phi_accepted / other); not a pipe stage.
"""
from __future__ import annotations

import difflib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from easyocr import Reader
from numpy.typing import NDArray

from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
from anonymizer.controller.ai.embedded_phi.ner.engine import detect_entities, detect_locale_supported
from anonymizer.controller.series.series_overlay import (
    NerEvidence,
    OcrEvidence,
    OCRText,
    WhitelistEvidence,
)
from anonymizer.utils.modalities import XR_MODALITIES, Modality

logger = logging.getLogger(__name__)

# Noise-filter constants (geometry / confidence only — not PhiMatchMode).
# Low floor: whitelist + NER decide chrome vs PHI; do not cull weak EasyOCR hits early.
_OCR_MIN_PROB = 0.25
# Longer strings (overlay remnants, clocks, dates) skip min_prob — decide as other/PHI.
_OCR_MIN_PROB_EXEMPT_MIN_LEN = 6
_OCR_MIN_TEXT_LEN = 2
_OCR_SINGLE_LETTER_MIN_TEXT_LEN = 1
_OCR_SINGLE_LETTER_MARKER_MODALITIES = frozenset({Modality.CR, Modality.DX, Modality.MG})
_OCR_MIN_BOX_PX = 10
_OCR_MIN_BOX_AREA = 200
_OCR_MIN_BOX_AREA_PER_CHAR = 80.0
_OCR_SHORT_NUMERIC_MAX_LEN = 4
_OCR_SHORT_NUMERIC_MIN_AREA = 600
_OCR_CANVAS_SIZE_THRESHOLD = 1200
_DEFAULT_YCENTER_THS = 0.5
_DEFAULT_LINK_THRESHOLD = 0.4
# Keep EasyOCR boxes at word level so whitelist / NER see one token per box.
_DEFAULT_WIDTH_THS = 0.1
_DEFAULT_TEXT_THRESHOLD = 0.7
_FRAME_CONTEXT_SEPARATOR = ", "
# Boxes of this many characters or fewer are omitted from the NER line.
_NER_JOIN_MAX_SKIP_CHARS = 2
# A fragment that already ends with one of these is joined to the next with a space.
_NER_TRAILING_SEPARATORS = frozenset(":-/\\|;,.")
_PIXEL_NAME_LABELS = frozenset({"FIRST_NAME", "LAST_NAME"})
# A whitelist score above this always wins over NER.
_WHITELIST_CONFIDENT_SCORE = 0.8
# Weaker hits override NER only when ner.score < whitelist.score - this margin.
_WHITELIST_OVER_NER_MARGIN = 0.1
# XR (CR/DX) and US burn-in clocks: any separators → HH:MM:SS for NER.
_CLOCK_NORMALIZE_MODALITIES = frozenset({*XR_MODALITIES, Modality.US})
# Separators: non-digits and/or digit 8 (EasyOCR often reads ':' as '8'), mixed ok.
_CLOCK_SEP = r"[\D8]+"
_CLOCK_LOOSE_RE = re.compile(
    rf"^(\d{{1,2}}){_CLOCK_SEP}(\d{{1,2}}){_CLOCK_SEP}(\d{{1,2}})"
    rf"(?:{_CLOCK_SEP}(\d{{1,6}}))?$"
)
_WHITELIST_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z0-9]+)?")


class PhiMatchMode(StrEnum):
    """Whitelist similarity + NER score floors for pixel Embedded PHI."""

    EXACT = "exact"
    STRICT = "strict"
    STANDARD = "standard"
    LENIENT = "lenient"


@dataclass(frozen=True, slots=True)
class PhiMatchThresholds:
    """Decide floors for one PhiMatchMode."""

    whitelist_similarity: float
    ner_score: float


_MATCH_PRESETS: dict[PhiMatchMode, PhiMatchThresholds] = {
    PhiMatchMode.EXACT: PhiMatchThresholds(1.0, 0.90),
    PhiMatchMode.STRICT: PhiMatchThresholds(0.90, 0.80),
    PhiMatchMode.STANDARD: PhiMatchThresholds(0.85, 0.30),
    PhiMatchMode.LENIENT: PhiMatchThresholds(0.65, 0.20),
}


def thresholds_for(mode: PhiMatchMode) -> PhiMatchThresholds:
    """Preset floors for a match mode."""
    return _MATCH_PRESETS[mode]


def is_whitelisted(t: OCRText, mode: PhiMatchMode) -> bool:
    """True when whitelist.score is set and score >= mode.whitelist_similarity."""
    thr = thresholds_for(mode)
    return t.whitelist.score is not None and t.whitelist.score >= thr.whitelist_similarity


def _whitelist_overrides_ner(t: OCRText, mode: PhiMatchMode) -> bool:
    """
    True when the box meets the whitelist floor and whitelist wins.

    A whitelist score above 0.8 always wins. A weaker hit wins when NER is
    absent or ner.score < whitelist.score - 0.1. Close scores on a fuzzy
    resemblance stay PHI.

    Args:
        t: Annotated OCR box.
        mode: Current PhiMatchMode floors.

    Returns:
        True when callers should treat the box as whitelist chrome, not PHI.
    """
    if not is_whitelisted(t, mode):
        return False
    wl_score = t.whitelist.score
    if wl_score is None:
        return False
    if float(wl_score) > _WHITELIST_CONFIDENT_SCORE:
        return True
    if t.ner.label is None or t.ner.score is None:
        return True
    return float(t.ner.score) < float(wl_score) - _WHITELIST_OVER_NER_MARGIN


def phi_accepted(t: OCRText, mode: PhiMatchMode) -> bool:
    """
    True when ner.label is set, ner.score meets the mode floor, and whitelist
    does not win. Whitelist wins above 0.8, or when NER is below a weaker
    hit by more than 0.1.

    Args:
        t: Annotated OCR box.
        mode: Current PhiMatchMode floors.

    Returns:
        True when callers should treat the box as Embedded PHI.
    """
    thr = thresholds_for(mode)
    if (
        t.ner.label is None
        or t.ner.score is None
        or t.ner.score < thr.ner_score
    ):
        return False
    return not _whitelist_overrides_ner(t, mode)


def accepted_phi_entities(t: OCRText, mode: PhiMatchMode) -> tuple[tuple[str, str], ...]:
    """
    NER entities on this box that meet the mode floor.

    Whitelist override drops every entity. Each entity is judged by its own
    score. The OCR string is not given one class.

    Args:
        t: Annotated OCR box.
        mode: Current PhiMatchMode floors.

    Returns:
        (label, text) in NER span order.
    """
    if _whitelist_overrides_ner(t, mode):
        return ()
    floor = thresholds_for(mode).ner_score
    accepted: list[tuple[str, str]] = []
    for row in t.ner.entities:
        label = str(row[0] or "")
        text = str(row[1] or "")
        score = float(row[2]) if len(row) > 2 and row[2] is not None else None
        if score is None and t.ner.score is not None:
            score = float(t.ner.score)
        if not label or score is None or score < floor:
            continue
        accepted.append((label, text))
    return tuple(accepted)


def effective_phi_label(t: OCRText, mode: PhiMatchMode) -> str | None:
    """
    Highest-scoring NER class on this box that meets the mode floor.

    One rectangle has one color. Hover uses accepted_phi_entities for every class.

    Args:
        t: Annotated OCR box.
        mode: Current PhiMatchMode floors.

    Returns:
        NER product label, or None when unlabeled / below floor / whitelist overrides.
    """
    if not phi_accepted(t, mode):
        return None
    accepted = accepted_phi_entities(t, mode)
    if not accepted:
        return t.ner.label
    best_score = -1.0
    best_label = accepted[0][0]
    for row in t.ner.entities:
        label = str(row[0] or "")
        score = float(row[2]) if len(row) > 2 and row[2] is not None else None
        if score is None or label not in {item[0] for item in accepted}:
            continue
        if score > best_score:
            best_score = score
            best_label = label
    return best_label


def _decision_outcome(t: OCRText, mode: PhiMatchMode) -> str:
    """Caller-side decisions log label: whitelisted | phi_accepted | other."""
    if phi_accepted(t, mode):
        return "phi_accepted"
    if is_whitelisted(t, mode):
        return "whitelisted"
    return "other"


def _ocr_min_text_len(modality: str | None) -> int:
    code = Modality.from_code(str(modality or "").strip().upper())
    if code is not None and code in _OCR_SINGLE_LETTER_MARKER_MODALITIES:
        return _OCR_SINGLE_LETTER_MIN_TEXT_LEN
    return _OCR_MIN_TEXT_LEN


def _easyocr_readtext(
    ocr_reader: Reader,
    pixels: NDArray[np.uint8],
    *,
    canvas_size: int,
):
    """
    One upright EasyOCR readtext call with the product box settings.

    Args:
        ocr_reader: Initialised EasyOCR reader.
        pixels: 2D or 3-channel uint8 frame.
        canvas_size: EasyOCR canvas cap for this frame.

    Returns:
        EasyOCR (box, text, score) rows.
    """
    return ocr_reader.readtext(
        pixels,
        canvas_size=canvas_size,
        paragraph=False,
        add_margin=0.1,
        rotation_info=[],
        min_size=1,
        ycenter_ths=_DEFAULT_YCENTER_THS,
        link_threshold=_DEFAULT_LINK_THRESHOLD,
        width_ths=_DEFAULT_WIDTH_THS,
        text_threshold=_DEFAULT_TEXT_THRESHOLD,
    )


def _boxes_from_readtext(results, img_width: int, img_height: int) -> list[OCRText]:
    """
    Parse one readtext result list into OCR boxes, skipping invalid rows.

    Args:
        results: EasyOCR (box, text, score) rows.
        img_width: Frame width in pixels.
        img_height: Frame height in pixels.

    Returns:
        Parsed boxes. Invalid rows are logged and omitted.
    """
    out: list[OCRText] = []
    for result in results:
        try:
            out.append(_ocr_text_from_easyocr_result(result, img_width, img_height))
        except ValueError as exc:
            logger.warning(f"Skipping invalid OCR result. Error: {exc}")
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


def detect_text(
    pixels: NDArray[np.uint8],
    ocr_reader: Reader,
    *,
    modality: str | None = None,
) -> list[OCRText]:
    """
    EasyOCR only. Sets ocr.prob; whitelist/ner scores stay None.

    One upright read of the full frame. Noise filtering stays in filter_ocr_noise.

    Args:
        pixels: 2D or 3-channel uint8 frame for EasyOCR.
        ocr_reader: Initialised EasyOCR reader.
        modality: Accepted for callers. The read does not vary by modality.

    Returns:
        Parsed OCR boxes (may be empty).
    """
    if pixels.ndim == 3:
        img_height, img_width = pixels.shape[:2]
    elif pixels.ndim == 2:
        img_height, img_width = pixels.shape
    else:
        logger.error(f"Unsupported image dimensions: {pixels.ndim}")
        return []

    canvas_size = min(max(pixels.shape[0], pixels.shape[1]), _OCR_CANVAS_SIZE_THRESHOLD)
    return log_ocr_stage(
        "detect_text",
        _boxes_from_readtext(
            _easyocr_readtext(ocr_reader, pixels, canvas_size=canvas_size),
            img_width,
            img_height,
        ),
    )


def _is_short_numeric(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.isdigit() and len(stripped) <= _OCR_SHORT_NUMERIC_MAX_LEN


def _noise_drop_reason(ocr_text: OCRText, *, min_text_len: int) -> str | None:
    text = (ocr_text.text or "").strip()
    # Short low-confidence hits are noise; longer OCR strings still go to decide.
    if (
        ocr_text.ocr.prob < _OCR_MIN_PROB
        and len(text) < _OCR_MIN_PROB_EXEMPT_MIN_LEN
    ):
        return f"prob={ocr_text.ocr.prob:.1f}<{_OCR_MIN_PROB}"
    if len(text) < min_text_len:
        return f"text_len={len(text)}<{min_text_len}"
    if not any(ch.isalnum() for ch in text):
        return "no_alnum"
    x1, y1, x2, y2 = ocr_text.get_bounding_box()
    box_w, box_h = x2 - x1, y2 - y1
    if box_w < _OCR_MIN_BOX_PX or box_h < _OCR_MIN_BOX_PX:
        return f"box_px={box_w}x{box_h}<{_OCR_MIN_BOX_PX}"
    box_area = ocr_text.box_area()
    if box_area < _OCR_MIN_BOX_AREA:
        return f"box_area={box_area}<{_OCR_MIN_BOX_AREA}"
    if len(text) <= _OCR_SHORT_NUMERIC_MAX_LEN:
        area_per_char = box_area / max(len(text), 1)
        if area_per_char < _OCR_MIN_BOX_AREA_PER_CHAR:
            return f"area_per_char={area_per_char:.1f}<{_OCR_MIN_BOX_AREA_PER_CHAR}"
    if _is_short_numeric(text) and box_area < _OCR_SHORT_NUMERIC_MIN_AREA:
        return f"short_numeric_area={box_area}<{_OCR_SHORT_NUMERIC_MIN_AREA}"
    return None


def filter_ocr_noise(texts: list[OCRText], *, modality: str | None = None) -> list[OCRText]:
    """
    Geometry + min_prob noise filter; may drop boxes.

    Args:
        texts: OCR boxes from detect_text.
        modality: DICOM modality (single-letter marker min length for CR/DX/MG).

    Returns:
        Surviving boxes.
    """
    min_len = _ocr_min_text_len(modality)
    kept: list[OCRText] = []
    for item in texts:
        if _noise_drop_reason(item, min_text_len=min_len) is not None:
            continue
        kept.append(item)
    dropped = len(texts) - len(kept)
    return log_ocr_stage("filter_ocr_noise", kept, dropped=dropped)


def _whitelist_match_units(text: str) -> list[str]:
    """
    Full uppercased phrase plus per-word tokens for whitelist similarity.

    Args:
        text: OCR box text (any case).

    Returns:
        Units to score against whitelist terms (may be empty).
    """
    processed = (text or "").upper().strip()
    if not processed:
        return []
    words = _WHITELIST_WORD_RE.findall(processed)
    units = [processed]
    for word in words:
        if word != processed:
            units.append(word)
    return units


def _best_whitelist_match(text: str, upper_terms: Sequence[str]) -> tuple[float, str | None]:
    """
    Best SequenceMatcher ratio of any word (or full phrase) vs whitelist terms.

    Args:
        text: OCR box text.
        upper_terms: Uppercased whitelist terms.

    Returns:
        (best_score, best_term_or_None).
    """
    best = 0.0
    best_term: str | None = None
    if not upper_terms:
        return best, best_term
    for unit in _whitelist_match_units(text):
        for candidate in upper_terms:
            sim = difflib.SequenceMatcher(None, unit, candidate).ratio()
            if sim > best:
                best = sim
                best_term = candidate
    return best, best_term


def make_annotate_whitelist(terms: list[str]):
    """
    Factory: best word/phrase similarity vs terms → whitelist evidence. Never drop.

    Each OCR box is scored on the full string and on each alphanumeric word so
    merged multi-word boxes still match single-word whitelist terms.

    Args:
        terms: Modality whitelist terms (any case).

    Returns:
        Stage that annotates whitelist evidence on each box.
    """
    upper_terms = [str(t).upper().strip() for t in terms if str(t).strip()]

    def annotate_whitelist(texts: list[OCRText]) -> list[OCRText]:
        """Best word/phrase similarity vs terms; no PhiMatchMode gate."""
        out: list[OCRText] = []
        for item in texts:
            best, best_term = _best_whitelist_match(item.text or "", upper_terms)
            evidence = WhitelistEvidence(
                term=best_term if best > 0.0 else None,
                score=best,
            )
            out.append(
                OCRText(
                    text=item.text,
                    top_left=item.top_left,
                    bottom_right=item.bottom_right,
                    ocr=item.ocr,
                    whitelist=evidence,
                    ner=item.ner,
                )
            )
        return log_ocr_stage("annotate_whitelist", out)

    annotate_whitelist.__name__ = "annotate_whitelist"
    return annotate_whitelist


def _format_clock_groups(
    hour: str, minute: str, second: str, frac: str | None
) -> str | None:
    """
    Build HH:MM:SS[.frac] from digit groups when they form a valid clock.

    Args:
        hour: Hour digits.
        minute: Minute digits.
        second: Second digits.
        frac: Optional fractional-second digits.

    Returns:
        Normalized clock string, or None when hour/minute/second are out of range.
    """
    h, m, s = int(hour), int(minute), int(second)
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        return None
    normalized = f"{h:02d}:{m:02d}:{s:02d}"
    if frac is not None:
        normalized = f"{normalized}.{frac}"
    return normalized


def normalize_clock_text_for_ner(text: str) -> str:
    """
    Rewrite a loose HH MM SS burn-in clock to HH:MM:SS for NER.

    Requires a valid clock (hour 0–23, minute/second 0–59). Separators may be
    non-digit characters, digit 8 (colon misread), or a mix (e.g. ',8').

    Args:
        text: OCR box text.

    Returns:
        Colon-normalized clock, or the original text when not a valid clock.
    """
    stripped = (text or "").strip()
    match = _CLOCK_LOOSE_RE.fullmatch(stripped)
    if match is not None:
        formatted = _format_clock_groups(*match.groups())
        if formatted is not None:
            return formatted
    return text


def _normalize_clocks_for_modality(
    texts: Sequence[OCRText],
    *,
    modality: str | None,
) -> list[OCRText]:
    """
    Copy boxes with clock text normalized when modality is XR or US.

    Args:
        texts: OCR boxes for one frame.
        modality: DICOM modality code.

    Returns:
        Same boxes, with clock strings rewritten for NER when applicable.
    """
    code = Modality.from_code(str(modality or "").strip().upper())
    if code not in _CLOCK_NORMALIZE_MODALITIES:
        return list(texts)
    out: list[OCRText] = []
    for item in texts:
        normalized = normalize_clock_text_for_ner(item.text or "")
        if normalized == item.text:
            out.append(item)
            continue
        out.append(
            OCRText(
                text=normalized,
                top_left=item.top_left,
                bottom_right=item.bottom_right,
                ocr=item.ocr,
                whitelist=item.whitelist,
                ner=item.ner,
            )
        )
    return out


def _frame_reading_order(detections: Sequence[OCRText]) -> list[int]:
    by_top = sorted(
        range(len(detections)),
        key=lambda i: (detections[i].top_left[1], detections[i].top_left[0]),
    )
    lines: list[list[int]] = []
    for idx in by_top:
        item = detections[idx]
        for line in lines:
            first = detections[line[0]]
            overlap = min(item.bottom_right[1], first.bottom_right[1]) - max(
                item.top_left[1], first.top_left[1]
            )
            min_height = max(
                1,
                min(
                    item.bottom_right[1] - item.top_left[1],
                    first.bottom_right[1] - first.top_left[1],
                ),
            )
            if overlap >= 0.5 * min_height:
                line.append(idx)
                break
        else:
            lines.append([idx])
    ordered: list[int] = []
    for line in lines:
        ordered.extend(sorted(line, key=lambda i: detections[i].top_left[0]))
    return ordered


def _ner_join_separator(previous: str) -> str:
    """
    Separator to place before the next NER fragment.

    Args:
        previous: Fragment already appended to the NER line.

    Returns:
        A space when previous ends with a separator, otherwise comma-space.
    """
    stripped = previous.rstrip()
    if stripped and stripped[-1] in _NER_TRAILING_SEPARATORS:
        return " "
    return _FRAME_CONTEXT_SEPARATOR


def _joined_frame_context(
    detections: Sequence[OCRText], ordered: Sequence[int]
) -> tuple[str, dict[int, tuple[int, int]]]:
    """
    Reading-order NER line. Boxes of 2 characters or fewer are omitted.

    Args:
        detections: OCR boxes for one frame.
        ordered: Indices in reading order.

    Returns:
        Joined text and a map of included box index to (start, end) in that text.
    """
    chunks: list[str] = []
    spans: dict[int, tuple[int, int]] = {}
    pos = 0
    for idx in ordered:
        text = detections[idx].text or ""
        if len(text.strip()) <= _NER_JOIN_MAX_SKIP_CHARS:
            continue
        if chunks:
            sep = _ner_join_separator(chunks[-1])
            chunks.append(sep)
            pos += len(sep)
        start = pos
        chunks.append(text)
        pos += len(text)
        spans[idx] = (start, pos)
    return "".join(chunks), spans


def _entities_in_box(entities: Sequence, joined: str, span: tuple[int, int]) -> list[tuple[str, str, float]]:
    box_start, box_end = span
    out: list[tuple[str, str, float]] = []
    for ent in entities:
        if ent.start < box_end and ent.end > box_start:
            clipped = joined[max(ent.start, box_start) : min(ent.end, box_end)]
            out.append((ent.label, clipped, float(ent.score)))
    return out


def _pixel_phi_label(model_label: str) -> str:
    return "NAME" if model_label in _PIXEL_NAME_LABELS else model_label


def annotate_ner(
    texts: list[OCRText],
    *,
    locale: str = "en_US",
    modality: str | None = None,
    detect_fn=None,
) -> list[OCRText]:
    """
    Frame-join NER. Sets ner.label / ner.entities / ner.score. Never drop.

    Always keeps model TIME as product TIME for pixel PHI. For XR (CR/DX) and
    US, rewrites loose HH MM SS burn-in clocks to HH:MM:SS before the model run.
    Boxes of 2 characters or fewer are left out of the NER line. A fragment
    that already ends with a separator (colon, dash, slash, and similar) is
    followed by a space, not a comma.

    Args:
        texts: OCR boxes of one frame.
        locale: NER locale pack.
        modality: DICOM modality (clock normalize for XR/US).
        detect_fn: Optional text → entities override (tests). Skips the model-ready gate.

    Returns:
        Copies with ner evidence filled (score 0.0 / label None when no entity).
        Clock-normalized text when modality is XR/US.
    """
    texts = _normalize_clocks_for_modality(texts, modality=modality)

    def scan(body: str):
        """Run the test override, or the pixel-PHI NER model."""
        if detect_fn is not None:
            return detect_fn(body)
        return detect_entities(body, locale=locale, include_time=True)

    if detect_fn is None:
        ready = ner_ready()
        if not ready or not detect_locale_supported(locale):
            logger.info(
                f"OCR→NER classify skipped (ner_ready={ready} locale={locale}); "
                f"{len(texts)} text(s) unlabeled"
            )
            out = [
                OCRText(
                    text=t.text,
                    top_left=t.top_left,
                    bottom_right=t.bottom_right,
                    ocr=t.ocr,
                    whitelist=t.whitelist,
                    ner=NerEvidence(label=None, entities=(), score=0.0),
                )
                for t in texts
            ]
            return log_ocr_stage("annotate_ner", out)
    ordered = _frame_reading_order(texts)
    joined, spans = _joined_frame_context(texts, ordered)
    entities = scan(joined) if joined.strip() else []
    out: list[OCRText] = []
    for idx, ocr_text in enumerate(texts):
        span = spans.get(idx)
        in_box = _entities_in_box(entities, joined, span) if span is not None else []
        if in_box:
            best = max(in_box, key=lambda row: row[2])
            label = _pixel_phi_label(best[0])
            score = float(best[2])
            box_entities = tuple(
                (_pixel_phi_label(lab), txt, float(ent_score)) for lab, txt, ent_score in in_box
            )
        else:
            label = None
            score = 0.0
            box_entities = ()
        out.append(
            OCRText(
                text=ocr_text.text,
                top_left=ocr_text.top_left,
                bottom_right=ocr_text.bottom_right,
                ocr=ocr_text.ocr,
                whitelist=ocr_text.whitelist,
                ner=NerEvidence(label=label, entities=box_entities, score=score),
            )
        )
    return log_ocr_stage("annotate_ner", out)


def pipe(*stages: Callable[[list[OCRText]], list[OCRText]]):
    """Compose stages; each stage is responsible for its own stage log."""

    def run(texts: list[OCRText]) -> list[OCRText]:
        for stage in stages:
            texts = stage(texts)
        return texts

    return run


def format_ocr_texts_for_log(
    stage_name: str,
    texts: list[OCRText],
    *,
    mode: PhiMatchMode | None = None,
    dropped: int | None = None,
    remove_mode: str | None = None,
) -> str:
    """
    Stage-local log body; header box count matches printed lines.

    Args:
        stage_name: Stage id (detect_text, annotate_whitelist, …).
        texts: Boxes after the stage.
        mode: Required for decisions stage.
        dropped: Optional drop count for noise filter header.
        remove_mode: Optional Remove Scope value for decisions header.

    Returns:
        Multi-line log string.
    """
    n = len(texts)
    if stage_name == "filter_ocr_noise" and dropped is not None:
        header = f"=== {stage_name}  {n} boxes (dropped {dropped}) ==="
    elif stage_name == "decisions" and mode is not None:
        thr = thresholds_for(mode)
        scope = f"  remove={remove_mode}" if remove_mode else ""
        header = (
            f"=== decisions  mode={mode.value.upper()}{scope}  "
            f"wl>={thr.whitelist_similarity:.2f}  ner>={thr.ner_score:.2f}  {n} boxes ==="
        )
    else:
        header = f"=== {stage_name}  {n} boxes ==="

    lines = [header]
    if stage_name == "detect_text" or stage_name == "filter_ocr_noise":
        for t in texts:
            lines.append(f"  {t.text!r} | {t.ocr.prob:.1f}")
    elif stage_name == "annotate_whitelist":
        for t in texts:
            score = t.whitelist.score if t.whitelist.score is not None else 0.0
            term = t.whitelist.term if t.whitelist.term else "—"
            term_s = repr(term) if term != "—" else "—"
            lines.append(f"  {t.text!r} | {score:.2f} | {term_s}")
    elif stage_name == "annotate_ner":
        for t in texts:
            if t.ner.entities and any(len(row) > 2 for row in t.ner.entities):
                parts = ", ".join(
                    f"{row[0]} {row[1]} {float(row[2]):.2f}" for row in t.ner.entities if len(row) > 2
                )
                lines.append(f"  {t.text!r} | {parts}")
            else:
                score = t.ner.score if t.ner.score is not None else 0.0
                label = t.ner.label if t.ner.label else "—"
                lines.append(f"  {t.text!r} | {score:.2f} | {label}")
    elif stage_name == "decisions" and mode is not None:
        for t in texts:
            outcome = _decision_outcome(t, mode)
            if outcome == "phi_accepted":
                classes = ", ".join(dict.fromkeys(label for label, _text in accepted_phi_entities(t, mode)))
                if classes:
                    lines.append(f"  {t.text!r} | {outcome} {classes}")
                    continue
            lines.append(f"  {t.text!r} | {outcome}")
    else:
        for t in texts:
            lines.append(f"  {t.text!r}")
    return "\n".join(lines)


def log_ocr_stage(
    stage_name: str,
    texts: list[OCRText],
    *,
    mode: PhiMatchMode | None = None,
    dropped: int | None = None,
) -> list[OCRText]:
    """Log format_ocr_texts_for_log; return texts unchanged."""
    logger.info(format_ocr_texts_for_log(stage_name, texts, mode=mode, dropped=dropped))
    return texts


def log_ocr_decisions(
    texts: list[OCRText],
    mode: PhiMatchMode,
    *,
    remove_mode: str | None = None,
) -> None:
    """Caller-side decisions log (whitelist / PHI / other) after annotate."""
    logger.info(
        format_ocr_texts_for_log("decisions", texts, mode=mode, remove_mode=remove_mode)
    )
