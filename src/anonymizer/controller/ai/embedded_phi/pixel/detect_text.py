# For Burnt-IN Pixel PHI Removal:
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from cv2 import (
    CHAIN_APPROX_SIMPLE,
    COLOR_BGR2GRAY,
    COLOR_RGB2BGR,
    COLOR_RGB2GRAY,
    FONT_HERSHEY_SIMPLEX,
    RETR_TREE,
    THRESH_OTSU,
    cvtColor,
    drawContours,
    findContours,
    putText,
    rectangle,
    threshold,
)
from easyocr import Reader
from numpy import ndarray
from numpy.typing import NDArray
from pydicom import Dataset

if TYPE_CHECKING:
    pass

from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready
from anonymizer.controller.ai.embedded_phi.ner.engine import detect_entities, detect_locale_supported
from anonymizer.controller.series_io import (
    stored_monochrome_to_series_buffer,
)
from anonymizer.controller.series_overlay import OCRText, UserRectangle
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.storage import (
    load_default_whitelist,
    load_project_whitelist,
    project_whitelist_options_path,
    project_whitelist_path,
)
from anonymizer.utils.translate import _
from anonymizer.utils.windowing import apply_windowing

logging.getLogger("openjpeg").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class OcrWhitelistMatchMode(StrEnum):
    EXACT = "exact"
    STRICT = "strict"
    STANDARD = "standard"
    LENIENT = "lenient"
    CUSTOM = "custom"


@dataclass(frozen=True)
class OcrWhitelistMatchSettings:
    match_mode: OcrWhitelistMatchMode = OcrWhitelistMatchMode.STANDARD
    similarity: float = 0.75
    min_length_ratio: float = 0.7

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_mode": self.match_mode.value,
            "similarity": self.similarity,
            "min_length_ratio": self.min_length_ratio,
        }

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> OcrWhitelistMatchSettings:
        if not data:
            return default_whitelist_match_settings()
        mode_raw = str(data.get("match_mode", OcrWhitelistMatchMode.STANDARD.value))
        try:
            match_mode = OcrWhitelistMatchMode(mode_raw)
        except ValueError:
            match_mode = OcrWhitelistMatchMode.STANDARD
        return OcrWhitelistMatchSettings(
            match_mode=match_mode,
            similarity=float(data.get("similarity", 0.75)),
            min_length_ratio=float(data.get("min_length_ratio", 0.7)),
        )


@dataclass(frozen=True)
class WhitelistMatchResult:
    matched: bool
    whitelist_term: str | None = None
    similarity: float = 0.0


_PRESET_VALUES: dict[OcrWhitelistMatchMode, tuple[float, float]] = {
    OcrWhitelistMatchMode.EXACT: (1.0, 1.0),
    OcrWhitelistMatchMode.STRICT: (0.90, 0.85),
    OcrWhitelistMatchMode.STANDARD: (0.75, 0.70),
    OcrWhitelistMatchMode.LENIENT: (0.65, 0.60),
}


def default_whitelist_match_settings() -> OcrWhitelistMatchSettings:
    return OcrWhitelistMatchSettings()


def load_modality_whitelist_match_settings(
    project_dir: Path | None,
    modality_code: str | None,
) -> OcrWhitelistMatchSettings:
    """Load per-modality OCR whitelist match settings from sidecar JSON."""
    if not modality_code or project_dir is None:
        return default_whitelist_match_settings()
    options_path = project_whitelist_options_path(project_dir, modality_code)
    if options_path.is_file():
        try:
            data = json.loads(options_path.read_text(encoding="utf-8"))
            return OcrWhitelistMatchSettings.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Could not load whitelist match settings from %s: %s", options_path, exc)
    return default_whitelist_match_settings()


def save_modality_whitelist_match_settings(
    project_dir: Path,
    modality_code: str,
    settings: OcrWhitelistMatchSettings,
) -> Path:
    """Persist per-modality OCR whitelist match settings to sidecar JSON."""
    if not project_dir.is_dir():
        raise ValueError(f"{project_dir} is not a valid directory")
    filepath = project_whitelist_options_path(project_dir, modality_code)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
    return filepath


def resolve_whitelist_match(
    settings: OcrWhitelistMatchSettings | None,
) -> tuple[float, float]:
    """Return (similarity_threshold, min_length_ratio) for filtering."""
    if settings is None:
        settings = default_whitelist_match_settings()
    if settings.match_mode == OcrWhitelistMatchMode.CUSTOM:
        return settings.similarity, settings.min_length_ratio
    similarity, length_ratio = _PRESET_VALUES[settings.match_mode]
    return similarity, length_ratio


def describe_match_settings(settings: OcrWhitelistMatchSettings | None) -> str:
    """User-facing label for logs and batch preview."""
    if settings is None:
        settings = default_whitelist_match_settings()
    labels = {
        OcrWhitelistMatchMode.EXACT: _("Exact match only"),
        OcrWhitelistMatchMode.STRICT: _("Strict"),
        OcrWhitelistMatchMode.STANDARD: _("Standard"),
        OcrWhitelistMatchMode.LENIENT: _("Lenient"),
        OcrWhitelistMatchMode.CUSTOM: _("Custom"),
    }
    label = labels.get(settings.match_mode, _("Standard"))
    if settings.match_mode == OcrWhitelistMatchMode.CUSTOM:
        return f"{label} ({int(round(settings.similarity * 100))}%)"
    return label


def match_mode_menu_labels() -> dict[str, OcrWhitelistMatchMode]:
    """Map translated menu label -> mode (for Series View OptionMenu)."""
    return {
        _("Exact"): OcrWhitelistMatchMode.EXACT,
        _("Strict"): OcrWhitelistMatchMode.STRICT,
        _("Standard"): OcrWhitelistMatchMode.STANDARD,
        _("Lenient"): OcrWhitelistMatchMode.LENIENT,
    }


def match_mode_menu_label(mode: OcrWhitelistMatchMode) -> str:
    reverse = {
        OcrWhitelistMatchMode.EXACT: _("Exact"),
        OcrWhitelistMatchMode.STRICT: _("Strict"),
        OcrWhitelistMatchMode.STANDARD: _("Standard"),
        OcrWhitelistMatchMode.LENIENT: _("Lenient"),
    }
    return reverse.get(mode, reverse[OcrWhitelistMatchMode.STANDARD])


def match_mode_description(mode: OcrWhitelistMatchMode) -> str:
    descriptions = {
        OcrWhitelistMatchMode.EXACT: _("Only hide text identical to a whitelist entry."),
        OcrWhitelistMatchMode.STRICT: _("Allow only very small OCR differences."),
        OcrWhitelistMatchMode.STANDARD: _("Tolerates minor OCR errors (e.g. AXIL matches AXIAL)."),
        OcrWhitelistMatchMode.LENIENT: _("More tolerance for noisy OCR and short markers."),
        OcrWhitelistMatchMode.CUSTOM: _("Set match closeness manually."),
    }
    return descriptions.get(mode, "")


def _ocr_bgr_from_stored_monochrome(stored: np.ndarray, ds: Dataset) -> NDArray[np.uint8]:
    """EasyOCR input for one stored mono slice — matches Series View Detect Text."""
    viewer_pixels, _ = stored_monochrome_to_series_buffer(stored, ds)
    return ocr_image_for_frame(ds, viewer_pixels)


def ocr_image_for_frame(ds: Dataset, frame: np.ndarray) -> NDArray[np.uint8]:
    """Apply DICOM WL/WW to a processed frame for EasyOCR (Series View and batch)."""
    pi = str(ds.get("PhotometricInterpretation", "") or "").upper()
    if frame.ndim == 3 and frame.shape[-1] == 3 and frame.dtype == np.uint8 and pi == "RGB":
        logger.debug("ocr_image_for_frame RGB uint8 -> BGR for EasyOCR frame_shape=%s", frame.shape)
        return cvtColor(np.ascontiguousarray(frame), COLOR_RGB2BGR)

    wl, ww = get_wl_ww(ds)
    logger.debug("ocr_image_for_frame wl=%.1f ww=%.1f frame_shape=%s", wl, ww, frame.shape)
    return apply_windowing(wl, ww, frame)


def build_series_view_ocr_pixels(images: np.ndarray, ds: Dataset) -> NDArray[np.uint8]:
    """Snapshot per-frame EasyOCR inputs for Series View (DICOM WL only; no viewer WL)."""
    return np.stack([ocr_image_for_frame(ds, frame) for frame in images])


def ocr_text_from_easyocr_result(result, img_width: int, img_height: int) -> OCRText:
    """Create an OCRText from an EasyOCR result tuple (box, text, prob)."""
    box, text, prob = result
    if not (len(box) == 4 and all(len(point) == 2 for point in box)):
        raise ValueError(f"Invalid box format: {box}")

    x1 = int(box[0][0])
    y1 = int(box[0][1])
    x2 = int(box[2][0])
    y2 = int(box[2][1])

    x1_clipped = max(0, x1)
    y1_clipped = max(0, y1)
    x2_clipped = min(img_width, x2)
    y2_clipped = min(img_height, y2)

    if x1_clipped >= x2_clipped or y1_clipped >= y2_clipped:
        raise ValueError(
            f"Bounding box became invalid after clipping. Original: [{x1},{y1},{x2},{y2}], "
            f"Clipped: [{x1_clipped},{y1_clipped},{x2_clipped},{y2_clipped}]"
        )

    return OCRText(
        text=text,
        top_left=(x1_clipped, y1_clipped),
        bottom_right=(x2_clipped, y2_clipped),
        prob=prob,
    )


def _dedupe_texts(texts: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in texts:
        stripped = item.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            deduped.append(stripped)
    return deduped


def _draw_text_contours_on_mask(
    image: ndarray,
    top_left: tuple,
    bottom_right: tuple,
    mask: NDArray[np.uint8],
    *,
    is_bgr: bool = False,
) -> None:
    """
    Draws text contours onto the provided mask (mutates the input mask).

    Args:
        image: The source image to process.
        top_left: The top-left coordinates of the region to extract.
        bottom_right: The bottom-right coordinates of the region to extract.
        mask: The mask that will be modified by drawing contours. [*Mutable*]
        is_bgr: When True, ``image`` is BGR (EasyOCR path); otherwise RGB.
    """
    # Sub-image contour masking:
    # Extracting coordinates
    x1, y1 = top_left
    x2, y2 = bottom_right
    # Skip small rectangles:
    if x2 - x1 < 10 or y2 - y1 < 10:
        return
    # Constructing sub-image
    sub_image = image[y1:y2, x1:x2]
    # If RGB image, then convert sub_image to grayscale for contour detection
    if sub_image.shape[-1] == 3:
        gray_code = COLOR_BGR2GRAY if is_bgr else COLOR_RGB2GRAY
        sub_image = cvtColor(sub_image, gray_code)
    # Threshold the grayscale sub-image:
    _, thresh = threshold(sub_image, 0, 255, THRESH_OTSU)
    # Find contours within the sub-image
    contours, _ = findContours(thresh, RETR_TREE, CHAIN_APPROX_SIMPLE)
    # Shift the contours to match the original image coordinates
    for cnt in contours:
        cnt += np.array([x1, y1])
    # Draw the contours on the mask
    drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)


OCR_MIN_PROB = 0.49
OCR_MIN_TEXT_LEN = 2
OCR_MIN_BOX_PX = 10
OCR_MIN_BOX_AREA = 200
OCR_MIN_BOX_AREA_PER_CHAR = 80
OCR_SHORT_NUMERIC_MAX_LEN = 4
OCR_SHORT_NUMERIC_MIN_AREA = 600
OCR_WHITELIST_SIMILARITY = 0.75
OCR_WHITELIST_MIN_LENGTH_RATIO = 0.7
OCR_CANVAS_SIZE_THRESHOLD = 1200

# Series View / remove_pixel_phi defaults (word-level overlay chips).
_DEFAULT_WIDTH_THS = 0.1
_DEFAULT_YCENTER_THS = 0.7
_DEFAULT_LINK_THRESHOLD = 0.4
_DEFAULT_TEXT_THRESHOLD = 0.65

# Report View pixel-sourced text (PDF embeds, pixel-report frames).
# Tuned via prototyping/report_phi (FL Health letterhead): link_threshold=0.6
# recovers second address LOCATION; width_ths=0.3 balances phone merge vs label glue.
REPORT_PIXEL_EASYOCR_OVERRIDES: dict[str, Any] = {
    "width_ths": 0.3,
    "ycenter_ths": 0.5,
    "link_threshold": 0.6,
    "rotation_info": [0],
}


class PixelPhiRemovalMode(StrEnum):
    INPAINT = "inpaint"
    BLACKOUT = "blackout"


def pixel_phi_removal_mode_menu_values() -> tuple[PixelPhiRemovalMode, ...]:
    """Language-agnostic internal codes for removal-mode picker state."""
    return (PixelPhiRemovalMode.BLACKOUT, PixelPhiRemovalMode.INPAINT)


def pixel_phi_removal_mode_option_label(mode: PixelPhiRemovalMode) -> str:
    """Translated combobox label for a removal mode (not used for menu state)."""
    if mode is PixelPhiRemovalMode.BLACKOUT:
        return _("Black out text")
    return _("Blend into background")


def pixel_phi_removal_mode_menu_labels() -> tuple[str, ...]:
    """Translated combobox labels in canonical order."""
    return tuple(pixel_phi_removal_mode_option_label(mode) for mode in pixel_phi_removal_mode_menu_values())


def normalize_pixel_phi_removal_mode(
    value: object | None,
    *,
    default: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
) -> PixelPhiRemovalMode:
    """Resolve combobox text or internal code to ``PixelPhiRemovalMode``."""
    text = str(value or "").strip()
    if not text:
        return default
    lowered = text.lower().replace(" ", "")
    if lowered in (PixelPhiRemovalMode.BLACKOUT, "blackout"):
        return PixelPhiRemovalMode.BLACKOUT
    if lowered in (PixelPhiRemovalMode.INPAINT, "inpaint"):
        return PixelPhiRemovalMode.INPAINT
    for mode in pixel_phi_removal_mode_menu_values():
        if text == pixel_phi_removal_mode_option_label(mode):
            return mode
    return default


def pixel_phi_removal_mode_from_menu_label(label: str) -> PixelPhiRemovalMode:
    return normalize_pixel_phi_removal_mode(label)


def _ocr_rotation_angles(modality: str | None) -> list[int]:
    """US overlays are horizontal; other modalities may include vertical burnt-in text."""
    if str(modality or "").upper() == "US":
        return [0]
    return [0, 90]


def _easyocr_readtext(
    ocr_reader: Reader,
    pixels: NDArray[np.uint8],
    *,
    modality: str | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> list:
    """
    Run EasyOCR with Series View defaults; optional ``overrides`` for report pixels.

    Same entry used by ``remove_pixel_phi`` / Series View and Report View rasters.
    """
    canvas_size = min(max(pixels.shape[0], pixels.shape[1]), OCR_CANVAS_SIZE_THRESHOLD)
    kwargs: dict[str, Any] = {
        "canvas_size": canvas_size,
        "paragraph": False,
        "add_margin": 0.0,
        "rotation_info": _ocr_rotation_angles(modality),
        "min_size": 1,
        "ycenter_ths": _DEFAULT_YCENTER_THS,
        "link_threshold": _DEFAULT_LINK_THRESHOLD,
        "width_ths": _DEFAULT_WIDTH_THS,
        "text_threshold": _DEFAULT_TEXT_THRESHOLD,
    }
    if overrides:
        kwargs.update(overrides)
    logger.debug(
        "EasyOCR readtext rotation_info=%s modality=%r width_ths=%s",
        kwargs.get("rotation_info"),
        modality,
        kwargs.get("width_ths"),
    )
    return ocr_reader.readtext(pixels, **kwargs)


def _parse_easyocr_results(
    results: list,
    img_width: int,
    img_height: int,
) -> list[OCRText]:
    ocr_texts: list[OCRText] = []
    for result in results:
        try:
            ocr_texts.append(ocr_text_from_easyocr_result(result, img_width, img_height))
        except ValueError as exc:
            logger.warning("Skipping invalid OCR result. Error: %s", exc)
            logger.debug("Invalid OCR result payload: %s", result)
    return ocr_texts


def find_whitelist_match(
    text: str,
    whitelist: Sequence[str],
    similarity_threshold: float,
    min_length_ratio: float = OCR_WHITELIST_MIN_LENGTH_RATIO,
) -> WhitelistMatchResult:
    from anonymizer.controller.ai.embedded_phi.term_similarity import similarity_term_match

    hit = similarity_term_match(
        text,
        whitelist,
        threshold=similarity_threshold,
        min_length_ratio=min_length_ratio,
    )
    return WhitelistMatchResult(
        matched=hit.matched,
        whitelist_term=hit.term,
        similarity=hit.similarity,
    )


def _ocr_text_matches_whitelist(
    text: str,
    whitelist: Sequence[str],
    similarity_threshold: float,
    min_length_ratio: float = OCR_WHITELIST_MIN_LENGTH_RATIO,
) -> bool:
    return find_whitelist_match(text, whitelist, similarity_threshold, min_length_ratio).matched


def _log_whitelist_hits(
    hits: list[tuple[str, WhitelistMatchResult]],
    *,
    settings: OcrWhitelistMatchSettings | None,
    similarity_threshold: float,
) -> None:
    if not hits:
        return
    mode_label = describe_match_settings(settings)
    logger.info(
        "OCR whitelist hid %d detection(s) (mode=%s, threshold=%.2f)",
        len(hits),
        mode_label,
        similarity_threshold,
    )
    for _text, match in hits:
        logger.debug(
            "OCR whitelist hid detection (matched whitelist term %r, similarity=%.3f)",
            match.whitelist_term,
            match.similarity,
        )


def _is_short_numeric(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.isdigit() and len(stripped) <= OCR_SHORT_NUMERIC_MAX_LEN


def _is_ct_spurious_text(text: str) -> bool:
    """True for CT OCR hits that are anatomy/noise, not plausible burned-in PHI."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) == 1:
        return True
    # Slice markers / HU crumbs: pure short digit runs ("64", "04", "229").
    if _is_short_numeric(stripped):
        return True
    # Digit/symbol soup with no letters ("9 <", ">>", "12/") — keep longer digit IDs/dates.
    if not any(ch.isalpha() for ch in stripped):
        digit_count = sum(ch.isdigit() for ch in stripped)
        if digit_count == 0:
            return True
        if digit_count <= OCR_SHORT_NUMERIC_MAX_LEN and len(stripped) <= OCR_SHORT_NUMERIC_MAX_LEN + 2:
            return True
    return False


def _filter_ct_spurious_detections(
    detections: Sequence[OCRText],
    modality: str | None,
) -> list[OCRText]:
    """Drop CT OCR false positives: single chars, short numbers, digit/symbol noise."""
    if (modality or "").upper() != "CT":
        return list(detections)
    kept: list[OCRText] = []
    dropped = 0
    for ocr_text in detections:
        if _is_ct_spurious_text(ocr_text.text or ""):
            dropped += 1
            continue
        kept.append(ocr_text)
    if dropped:
        logger.debug("CT OCR veracity: dropped %d spurious detection(s)", dropped)
    return kept


def filter_ocr_detections(
    detections: Sequence[OCRText],
    *,
    whitelist: Sequence[str] | None = None,
    min_prob: float = OCR_MIN_PROB,
    min_text_len: int = OCR_MIN_TEXT_LEN,
    min_box_px: int = OCR_MIN_BOX_PX,
    min_box_area: int = OCR_MIN_BOX_AREA,
    min_box_area_per_char: float = OCR_MIN_BOX_AREA_PER_CHAR,
    short_numeric_min_area: int = OCR_SHORT_NUMERIC_MIN_AREA,
    whitelist_similarity: float = OCR_WHITELIST_SIMILARITY,
    whitelist_min_length_ratio: float = OCR_WHITELIST_MIN_LENGTH_RATIO,
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
) -> list[OCRText]:
    """Drop OCR noise and optional whitelist-matched overlay terms."""
    if whitelist_match_settings is not None:
        whitelist_similarity, whitelist_min_length_ratio = resolve_whitelist_match(whitelist_match_settings)
    filtered: list[OCRText] = []
    whitelist_items = [item.upper().strip() for item in (whitelist or []) if str(item).strip()]
    whitelisted_hits: list[tuple[str, WhitelistMatchResult]] = []
    for ocr_text in detections:
        text = (ocr_text.text or "").strip()
        if ocr_text.prob < min_prob:
            continue
        if len(text) < min_text_len:
            continue
        if not any(ch.isalnum() for ch in text):
            continue
        x1, y1, x2, y2 = ocr_text.get_bounding_box()
        box_w = x2 - x1
        box_h = y2 - y1
        if box_w < min_box_px or box_h < min_box_px:
            continue
        box_area = ocr_text.box_area()
        if box_area < min_box_area:
            continue
        if len(text) <= OCR_SHORT_NUMERIC_MAX_LEN and box_area / max(len(text), 1) < min_box_area_per_char:
            continue
        if _is_short_numeric(text) and box_area < short_numeric_min_area:
            continue
        if whitelist_items:
            match = find_whitelist_match(
                text, whitelist_items, whitelist_similarity, whitelist_min_length_ratio
            )
            if match.matched:
                whitelisted_hits.append((text, match))
                continue
        filtered.append(ocr_text)
    _log_whitelist_hits(
        whitelisted_hits,
        settings=whitelist_match_settings,
        similarity_threshold=whitelist_similarity,
    )
    return filtered


def _ocr_copy(item: OCRText, *, phi_label: str | None) -> OCRText:
    return OCRText(
        text=item.text,
        top_left=item.top_left,
        bottom_right=item.bottom_right,
        prob=item.prob,
        phi_label=phi_label,
    )


def _best_phi_label(ents: Sequence) -> str | None:
    if not ents:
        return None
    return max(ents, key=lambda e: e.score).label


def _ocr_box_height(item: OCRText) -> int:
    _x1, y1, _x2, y2 = item.get_bounding_box()
    return max(1, y2 - y1)


def _same_ocr_line(a: OCRText, b: OCRText) -> bool:
    _ax1, ay1, _ax2, ay2 = a.get_bounding_box()
    _bx1, by1, _bx2, by2 = b.get_bounding_box()
    overlap = min(ay2, by2) - max(ay1, by1)
    return overlap >= 0.5 * min(_ocr_box_height(a), _ocr_box_height(b))


def _horizontally_adjacent(left: OCRText, right: OCRText) -> bool:
    gap = right.top_left[0] - left.bottom_right[0]
    max_h = max(_ocr_box_height(left), _ocr_box_height(right))
    return -int(0.25 * max_h) <= gap <= max(8, int(1.25 * max_h))


def _name_token_candidate(text: str) -> bool:
    token = (text or "").strip()
    if len(token) < 2 or len(token) > 24:
        return False
    if any(ch.isdigit() for ch in token):
        return False
    letters = [ch for ch in token if ch.isalpha()]
    return len(letters) >= 2


def _joined_token_spans(texts: Sequence[str]) -> tuple[str, list[tuple[int, int]]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    parts: list[str] = []
    for i, raw in enumerate(texts):
        token = raw.strip()
        if i:
            pos += 1
        spans.append((pos, pos + len(token)))
        pos += len(token)
        parts.append(token)
    return " ".join(parts), spans


def _span_covers_token(span_start: int, span_end: int, token_start: int, token_end: int) -> bool:
    overlap = min(span_end, token_end) - max(span_start, token_start)
    length = max(1, token_end - token_start)
    return overlap / length >= 0.5


def _ocr_line_groups(items: Sequence[OCRText]) -> list[list[int]]:
    unused = set(range(len(items)))
    groups: list[list[int]] = []
    while unused:
        seed = min(unused, key=lambda i: (items[i].top_left[1], items[i].top_left[0]))
        line = [i for i in unused if i == seed or _same_ocr_line(items[seed], items[i])]
        unused.difference_update(line)
        line.sort(key=lambda i: items[i].top_left[0])
        groups.append(line)
    return groups


def _propagate_adjacent_name_labels(
    detections: Sequence[OCRText],
    *,
    detect_fn,
    locale: str,
) -> list[OCRText]:
    """Re-run NER on a NAME box plus an adjacent unlabeled neighbor (split OCR names)."""
    out = [
        _ocr_copy(item, phi_label=item.phi_label) for item in detections
    ]
    for _round in range(3):
        changed = False
        for line in _ocr_line_groups(out):
            for pos, idx in enumerate(line):
                item = out[idx]
                if (item.phi_label or "").strip() != "NAME":
                    continue
                for neighbor_pos in (pos - 1, pos + 1):
                    if neighbor_pos < 0 or neighbor_pos >= len(line):
                        continue
                    nidx = line[neighbor_pos]
                    neighbor = out[nidx]
                    if (neighbor.phi_label or "").strip():
                        continue
                    if not _name_token_candidate(neighbor.text):
                        continue
                    left, right = (item, neighbor) if item.top_left[0] <= neighbor.top_left[0] else (neighbor, item)
                    if not _horizontally_adjacent(left, right):
                        continue
                    joined, spans = _joined_token_spans([left.text, right.text])
                    ents = detect_fn(joined, locale=locale)
                    name_ents = [e for e in ents if e.label == "NAME"]
                    if not name_ents:
                        continue
                    neighbor_is_right = neighbor is right
                    token_start, token_end = spans[1 if neighbor_is_right else 0]
                    if not any(_span_covers_token(e.start, e.end, token_start, token_end) for e in name_ents):
                        continue
                    logger.debug(
                        "OCR→NER adjacent NAME propagated to unlabeled neighbor (no PHI text logged)"
                    )
                    out[nidx] = _ocr_copy(neighbor, phi_label="NAME")
                    changed = True
        if not changed:
            break
    return out


def filter_ocr_phi_ner(
    detections: Sequence[OCRText],
    *,
    locale: str = "en_US",
) -> list[OCRText]:
    """
    NER-primary keep/remove: retain detections that contain PHI for blackout.

    Used by batch ``remove_pixel_phi``. Series View detect does **not** use this —
    it keeps OCR hits and annotates labels via ``annotate_ocr_phi_labels``.
    """
    ready = ner_ready()
    if not ready or not detect_locale_supported(locale):
        logger.info(
            "OCR→NER filter skipped (ner_ready=%s locale=%s); dropping all %d text(s) for batch PHI path",
            ready,
            locale,
            len(detections),
        )
        return []
    labeled = annotate_ocr_phi_labels(detections, locale=locale)
    out = [item for item in labeled if (item.phi_label or "").strip()]
    logger.info("OCR→NER filter: %d kept / %d input", len(out), len(detections))
    return out


def annotate_ocr_phi_labels(
    detections: Sequence[OCRText],
    *,
    locale: str = "en_US",
) -> list[OCRText]:
    """Attach ``phi_label`` from NER without dropping non-PHI detections (Series View)."""
    ready = ner_ready()
    if not ready or not detect_locale_supported(locale):
        logger.info(
            "OCR→NER classify skipped (ner_ready=%s locale=%s); %d text(s) unlabeled",
            ready,
            locale,
            len(detections),
        )
        return list(detections)
    out: list[OCRText] = []
    for ocr_text in detections:
        text = (ocr_text.text or "").strip()
        label: str | None = None
        if text:
            ents = detect_entities(text, locale=locale)
            if ents:
                label = _best_phi_label(ents)
                logger.debug("OCR→NER classify → %s", label)
            else:
                logger.debug("OCR→NER classify → overlay / not PHI")
        out.append(_ocr_copy(ocr_text, phi_label=label))
    out = _propagate_adjacent_name_labels(out, detect_fn=detect_entities, locale=locale)
    labeled = sum(1 for item in out if (item.phi_label or "").strip())
    logger.info(
        "OCR→NER classify: %d labeled / %d text(s)",
        labeled,
        len(detections),
    )
    return out

def filter_ocr_whitelist_only(
    detections: Sequence[OCRText],
    whitelist: Sequence[str] | None,
    *,
    whitelist_similarity: float = OCR_WHITELIST_SIMILARITY,
    whitelist_min_length_ratio: float = OCR_WHITELIST_MIN_LENGTH_RATIO,
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    log_steps: bool = True,
) -> list[OCRText]:
    """Drop whitelist-matched overlay terms only (Series View detect; no noise filter).

    Empty / missing whitelist keeps every detection (does not load modality defaults).
    """
    if whitelist_match_settings is not None:
        whitelist_similarity, whitelist_min_length_ratio = resolve_whitelist_match(whitelist_match_settings)
    whitelist_items = [item.upper().strip() for item in (whitelist or []) if str(item).strip()]
    if not whitelist_items:
        if log_steps:
            logger.info(
                "OCR whitelist: empty — keeping all %d text(s)",
                len(detections),
            )
        return list(detections)
    filtered: list[OCRText] = []
    whitelisted_hits: list[tuple[str, WhitelistMatchResult]] = []
    for ocr_text in detections:
        text = (ocr_text.text or "").strip()
        match = find_whitelist_match(text, whitelist_items, whitelist_similarity, whitelist_min_length_ratio)
        if match.matched:
            whitelisted_hits.append((text, match))
            continue
        filtered.append(ocr_text)
    if log_steps:
        _log_whitelist_hits(
            whitelisted_hits,
            settings=whitelist_match_settings,
            similarity_threshold=whitelist_similarity,
        )
        logger.info(
            "OCR whitelist: %d → %d text(s) (%d term(s), hid %d)",
            len(detections),
            len(filtered),
            len(whitelist_items),
            len(whitelisted_hits),
        )
    return filtered


def rects_intersect(
    a: tuple[int, int, int, int] | OCRText | UserRectangle,
    b: tuple[int, int, int, int] | OCRText | UserRectangle,
) -> bool:
    """Return True when two axis-aligned boxes overlap (inclusive edges count as overlap)."""

    def _xyxy(box: tuple[int, int, int, int] | OCRText | UserRectangle) -> tuple[int, int, int, int]:
        if isinstance(box, tuple):
            return box
        return box.get_bounding_box()

    ax1, ay1, ax2, ay2 = _xyxy(a)
    bx1, by1, bx2, by2 = _xyxy(b)
    if ax1 > ax2:
        ax1, ax2 = ax2, ax1
    if ay1 > ay2:
        ay1, ay2 = ay2, ay1
    if bx1 > bx2:
        bx1, bx2 = bx2, bx1
    if by1 > by2:
        by1, by2 = by2, by1
    return ax1 <= bx2 and ax2 >= bx1 and ay1 <= by2 and ay2 >= by1


def filter_ocr_outside_exclude_rects(
    detections: Sequence[OCRText],
    exclude_rects: Sequence[UserRectangle] | None,
) -> list[OCRText]:
    """Drop OCR boxes that intersect any exclude rectangle (spatial keepers)."""
    if not exclude_rects:
        return list(detections)
    kept: list[OCRText] = []
    for ocr_text in detections:
        if any(rects_intersect(ocr_text, rect) for rect in exclude_rects):
            continue
        kept.append(ocr_text)
    return kept


def load_modality_whitelist(project_dir: Path | None, modality: str | None) -> list[str]:
    """Load the effective modality whitelist for batch OCR filtering.

    When a project whitelist file exists, it replaces packaged defaults (same as
    Series View). Otherwise defaults are used.
    """
    if not modality:
        return []

    if project_dir is not None:
        project_path = project_whitelist_path(project_dir, modality)
        if project_path.is_file():
            try:
                return load_project_whitelist(project_dir, modality)
            except (FileNotFoundError, OSError, ValueError) as exc:
                logger.debug("Project whitelist not loaded for %s: %s", modality, exc)

    try:
        return load_default_whitelist(modality)
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.debug("Default whitelist not loaded for %s: %s", modality, exc)
    return []


def _has_voi_lut(ds: Dataset) -> bool:
    # Check for VOILUTSequence
    if "VOILUTSequence" in ds:
        return True
    # Check for WindowCenter and WindowWidth
    return bool("WindowCenter" in ds and "WindowWidth" in ds)


def detect_text(
    pixels: NDArray[np.uint8],
    ocr_reader: Reader,
    draw_boxes_and_text: bool = False,
    *,
    whitelist: Sequence[str] | None = None,
    modality: str | None = None,
    apply_noise_filter: bool = True,
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    phi_ner_locale: str = "en_US",
    apply_phi_ner_filter: bool = False,
    annotate_phi_labels: bool = False,
    exclude_rects: Sequence[UserRectangle] | None = None,
    log_steps: bool = True,
    easyocr_overrides: Mapping[str, Any] | None = None,
) -> list[OCRText] | None:
    """
    Detect text in a 2D uint8 frame.

    Batch removal uses noise + optional whitelist (remove survivors). Opt-in
    ``apply_phi_ner_filter=True`` further keeps only NER-confirmed PHI.
    Series View detect passes ``apply_noise_filter=False``, ``apply_phi_ner_filter=False``,
    and ``annotate_phi_labels=True`` (whitelist applied later in the view; boxes colored by class).

    Report pixel paths pass ``easyocr_overrides=REPORT_PIXEL_EASYOCR_OVERRIDES`` (wider
    box merge). Series View / ``remove_pixel_phi`` omit overrides (word-level defaults).

    Pass ``log_steps=False`` when a caller (e.g. Report PDF OCR arm) owns the workflow log
    so this helper does not emit misleading ``OCR→NER: skipped`` lines.
    """
    if pixels.ndim == 3:
        img_height, img_width = pixels.shape[:2]
    elif pixels.ndim == 2:
        img_height, img_width = pixels.shape
    else:
        logger.error(f"Unsupported image dimensions: {pixels.ndim}")
        return None

    results = _easyocr_readtext(
        ocr_reader, pixels, modality=modality, overrides=easyocr_overrides
    )
    parsed = _parse_easyocr_results(results, img_width, img_height)
    parsed = filter_ocr_outside_exclude_rects(parsed, exclude_rects)
    raw_n = len(parsed)
    if log_steps:
        logger.info("OCR detect: %d raw text(s) modality=%s", raw_n, modality or "?")
    if apply_noise_filter:
        ocr_texts = filter_ocr_detections(
            parsed, whitelist=whitelist, whitelist_match_settings=whitelist_match_settings
        )
        if log_steps:
            logger.info(
                "OCR whitelist+noise: %d → %d text(s) (whitelist=%d term(s))",
                raw_n,
                len(ocr_texts),
                len([w for w in (whitelist or []) if str(w).strip()]),
            )
    else:
        # Series View: whitelist only (or empty keep-all); view may re-apply list for display.
        ocr_texts = filter_ocr_whitelist_only(
            parsed,
            whitelist,
            whitelist_match_settings=whitelist_match_settings,
            log_steps=log_steps,
        )
    before_ct = len(ocr_texts)
    ocr_texts = _filter_ct_spurious_detections(ocr_texts, modality)
    if log_steps and len(ocr_texts) != before_ct:
        logger.info("OCR CT spurious filter: %d → %d text(s)", before_ct, len(ocr_texts))
    # Mutually exclusive: batch PHI removal filters; Series View annotate-only.
    if apply_phi_ner_filter and annotate_phi_labels:
        logger.warning(
            "OCR→NER: apply_phi_ner_filter and annotate_phi_labels both set; using filter (batch) mode"
        )
    if apply_phi_ner_filter:
        ocr_texts = filter_ocr_phi_ner(ocr_texts, locale=phi_ner_locale)
    elif annotate_phi_labels:
        ocr_texts = annotate_ocr_phi_labels(ocr_texts, locale=phi_ner_locale)
    elif log_steps:
        logger.info("OCR→NER: skipped (no filter, no classify)")
    if log_steps:
        logger.info(
            "OCR done: %d text(s) (noise_filter=%s ner_filter=%s annotate=%s)",
            len(ocr_texts),
            apply_noise_filter,
            apply_phi_ner_filter,
            annotate_phi_labels,
        )

    if draw_boxes_and_text:
        for ocr_text in ocr_texts:
            x1, y1, x2, y2 = ocr_text.get_bounding_box()
            box_color = (0, 255, 0)
            rectangle(img=pixels, pt1=(x1, y1), pt2=(x2, y2), color=box_color, thickness=2)
            putText(
                img=pixels,
                text=ocr_text.text,
                org=(x1, y2 + 20),
                fontFace=FONT_HERSHEY_SIMPLEX,
                fontScale=0.75,
                color=box_color,
                thickness=2,
            )

    return ocr_texts


