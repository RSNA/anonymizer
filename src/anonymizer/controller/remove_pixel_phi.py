# For Burnt-IN Pixel PHI Removal:
from __future__ import annotations

import difflib
import gc
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from cv2 import (
    BORDER_CONSTANT,
    CHAIN_APPROX_SIMPLE,
    COLOR_RGB2GRAY,
    FONT_HERSHEY_SIMPLEX,
    INPAINT_TELEA,
    INTER_LINEAR,
    NORM_MINMAX,
    RETR_TREE,
    THRESH_OTSU,
    copyMakeBorder,
    cvtColor,
    dilate,
    drawContours,
    findContours,
    inpaint,
    normalize,
    putText,
    rectangle,
    resize,
    threshold,
)
from easyocr import Reader
from numpy import ndarray
from numpy.typing import NDArray
from openjpeg.utils import encode_array  # JPEG2000Lossless
from pydicom import Dataset, dcmread
from pydicom.encaps import encapsulate
from pydicom.pixel_data_handlers.util import (
    apply_color_lut,
    convert_color_space,
)
from pydicom.uid import JPEG2000Lossless

if TYPE_CHECKING:
    from anonymizer.model.anonymizer import AnonymizerModel

VALID_COLOR_SPACES = [
    "MONOCHROME1",
    "MONOCHROME2",
    "RGB",
    # "RGBA", TODO: provide support for Alpha channel?
    "YBR_FULL",
    "YBR_FULL_422",
    "YBR_ICT",
    "YBR_RCT",
    "PALETTE COLOR",
]

logging.getLogger("openjpeg").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

OCR_MODEL_DIR = Path("assets/ai/ocr/model")
OCR_LANGS = ("en", "de", "fr", "es")
_MIN_OCR_MODEL_FILES = 2
_ocr_downloading = False


class OcrModelStatus(StrEnum):
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


def probe_ocr_models() -> tuple[OcrModelStatus, str]:
    """Return OCR model cache status under assets/ai/ocr/model."""
    if _ocr_downloading:
        return OcrModelStatus.DOWNLOADING, "Downloading OCR models…"
    if not OCR_MODEL_DIR.is_dir():
        return OcrModelStatus.MISSING, "Not downloaded"
    try:
        models = [name for name in os.listdir(OCR_MODEL_DIR) if not name.startswith(".")]
    except OSError as exc:
        return OcrModelStatus.FAILED, str(exc)
    if len(models) < _MIN_OCR_MODEL_FILES:
        return OcrModelStatus.MISSING, "Not downloaded"
    return OcrModelStatus.READY, "Downloaded"


def download_ocr_models(*, verbose: bool = False) -> tuple[bool, str]:
    """Download EasyOCR weights into assets/ai/ocr/model."""
    from anonymizer.utils.download_progress import begin_download, end_download, update_download

    global _ocr_downloading
    OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    status, _ = probe_ocr_models()
    if status == OcrModelStatus.READY:
        return True, "OCR models already downloaded."
    _ocr_downloading = True
    start_message = f"Downloading OCR models to {OCR_MODEL_DIR}"
    begin_download("remove_pixel_phi", message=start_message)
    try:
        logger.info("Downloading OCR models to %s", OCR_MODEL_DIR)
        update_download("remove_pixel_phi", message=start_message)
        update_download("remove_pixel_phi", message="Downloading OCR language models…")
        Reader(
            lang_list=list(OCR_LANGS),
            model_storage_directory=str(OCR_MODEL_DIR),
            verbose=verbose,
        )
        status, detail = probe_ocr_models()
        if status == OcrModelStatus.READY:
            return True, "OCR models downloaded."
        return False, detail or "OCR model download incomplete."
    except Exception as exc:
        logger.exception("OCR model download failed")
        return False, str(exc)
    finally:
        end_download("remove_pixel_phi")
        _ocr_downloading = False


def ocr_models_ready() -> bool:
    return probe_ocr_models()[0] == OcrModelStatus.READY


def remove_ocr_models() -> None:
    """Delete cached EasyOCR weights under assets/ai/ocr/model."""
    import shutil

    if OCR_MODEL_DIR.is_dir():
        shutil.rmtree(OCR_MODEL_DIR)
    OCR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Removed OCR models from %s", OCR_MODEL_DIR)


@dataclass()  # Mutable, user can edit box in ImageViewer
class OCRText:
    text: str
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]
    prob: float

    @classmethod
    def from_easyocr_result(cls, result, img_width: int, img_height: int) -> "OCRText":
        """Creates an OCRText instance from an EasyOCR result tuple."""
        box, text, prob = result
        # Ensure box has exactly 4 points and they are integers
        if not (len(box) == 4 and all(len(point) == 2 for point in box)):
            raise ValueError(f"Invalid box format: {box}")

        # Extract initial coordinates
        x1 = int(box[0][0])
        y1 = int(box[0][1])
        # Use bottom-right for consistency, assuming rectangular alignment from EasyOCR
        x2 = int(box[2][0])
        y2 = int(box[2][1])

        # --- Clip Bounding Box Coordinates ---
        x1_clipped = max(0, x1)
        y1_clipped = max(0, y1)
        x2_clipped = min(img_width, x2)
        y2_clipped = min(img_height, y2)

        # --- Check if clipped box is still valid (has area) ---
        if x1_clipped >= x2_clipped or y1_clipped >= y2_clipped:
            raise ValueError(
                f"Bounding box became invalid after clipping. Original: [{x1},{y1},{x2},{y2}], Clipped: [{x1_clipped},{y1_clipped},{x2_clipped},{y2_clipped}]"
            )

        # Use clipped coordinates
        return cls(text=text, top_left=(x1_clipped, y1_clipped), bottom_right=(x2_clipped, y2_clipped), prob=prob)

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        """Returns the bounding box as (x1, y1, x2, y2)."""
        return (self.top_left[0], self.top_left[1], self.bottom_right[0], self.bottom_right[1])

    def box_area(self) -> int:
        x1, y1, x2, y2 = self.get_bounding_box()
        return max(0, x2 - x1) * max(0, y2 - y1)


# Overlay layer types:
class LayerType(Enum):
    TEXT = auto()  # OCR text and rectangle coordinates
    USER_RECT = auto()  # User defined rectangle coordinates
    SEGMENTATIONS = auto()  # polygon vertices
    # ... other layer types ...


@dataclass
class UserRectangle:
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]

    def get_bounding_box(self) -> tuple[int, int, int, int]:
        return self.top_left[0], self.top_left[1], self.bottom_right[0], self.bottom_right[1]


@dataclass
class PolygonPoint:
    x: int
    y: int


@dataclass
class Segmentation:
    points: list[PolygonPoint]


@dataclass
class OverlayData:
    ocr_texts: list[OCRText] = field(default_factory=list)
    user_rects: list[UserRectangle] = field(default_factory=list)
    segmentations: list[Segmentation] = field(default_factory=list)


def _dedupe_texts(texts: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in texts:
        stripped = item.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            deduped.append(stripped)
    return deduped


def _draw_text_contours_on_mask(image: ndarray, top_left: tuple, bottom_right: tuple, mask: NDArray[np.uint8]) -> None:
    """
    Draws text contours onto the provided mask (mutates the input mask).

    Args:
        image: The source image to process.
        top_left: The top-left coordinates of the region to extract.
        bottom_right: The bottom-right coordinates of the region to extract.
        mask: The mask that will be modified by drawing contours. [*Mutable*]
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
        sub_image = cvtColor(sub_image, COLOR_RGB2GRAY)
    # Threshold the grayscale sub-image:
    _, thresh = threshold(sub_image, 0, 255, THRESH_OTSU)
    # Find contours within the sub-image
    contours, _ = findContours(thresh, RETR_TREE, CHAIN_APPROX_SIMPLE)
    # Shift the contours to match the original image coordinates
    for cnt in contours:
        cnt += np.array([x1, y1])
    # Draw the contours on the mask
    drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)


OCR_MIN_PROB = 0.55
OCR_MIN_TEXT_LEN = 2
OCR_MIN_BOX_PX = 10
OCR_MIN_BOX_AREA = 200
OCR_MIN_BOX_AREA_PER_CHAR = 80
OCR_SHORT_NUMERIC_MAX_LEN = 4
OCR_SHORT_NUMERIC_MIN_AREA = 600
OCR_WHITELIST_SIMILARITY = 0.75
OCR_CANVAS_SIZE_THRESHOLD = 1200


class PixelPhiRemovalMode(StrEnum):
    INPAINT = "inpaint"
    BLACKOUT = "blackout"


def pixel_phi_removal_mode_display_label(mode: PixelPhiRemovalMode) -> str:
    """Short action label for batch workflow logs."""
    from anonymizer.utils.translate import _

    if mode is PixelPhiRemovalMode.BLACKOUT:
        return _("blacked out")
    return _("blended")


def _easyocr_readtext(ocr_reader: Reader, pixels: NDArray[np.uint8]) -> list:
    """Run EasyOCR with tuned parameters shared by manual and batch paths."""
    canvas_size = min(max(pixels.shape[0], pixels.shape[1]), OCR_CANVAS_SIZE_THRESHOLD)
    return ocr_reader.readtext(
        pixels,
        canvas_size=canvas_size,
        paragraph=False,
        add_margin=0.0,
        rotation_info=[0, 90],
        min_size=10,
        ycenter_ths=0.7,
        link_threshold=0.5,
        width_ths=0.1,
        text_threshold=0.85,
    )


def _parse_easyocr_results(
    results: list,
    img_width: int,
    img_height: int,
) -> list[OCRText]:
    ocr_texts: list[OCRText] = []
    for result in results:
        try:
            ocr_texts.append(OCRText.from_easyocr_result(result, img_width, img_height))
        except ValueError as exc:
            logger.warning("Skipping invalid OCR result: %s. Error: %s", result, exc)
    return ocr_texts


def _ocr_text_matches_whitelist(text: str, whitelist: Sequence[str], similarity_threshold: float) -> bool:
    processed = text.upper().strip()
    if not processed:
        return False
    for whitelist_item in whitelist:
        similarity = difflib.SequenceMatcher(None, processed, whitelist_item).ratio()
        if similarity > similarity_threshold:
            return True
    return False


def _is_short_numeric(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.isdigit() and len(stripped) <= OCR_SHORT_NUMERIC_MAX_LEN


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
) -> list[OCRText]:
    """Drop OCR noise and optional whitelist-matched overlay terms."""
    filtered: list[OCRText] = []
    whitelist_items = [item.upper().strip() for item in (whitelist or []) if str(item).strip()]
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
        if whitelist_items and _ocr_text_matches_whitelist(text, whitelist_items, whitelist_similarity):
            continue
        filtered.append(ocr_text)
    return filtered


def load_modality_whitelist(project_dir: Path | None, modality: str | None) -> list[str]:
    """Load default and project modality whitelists for batch OCR filtering."""
    if not modality:
        return []
    from anonymizer.utils.storage import load_default_whitelist, load_project_whitelist

    seen: set[str] = set()
    items: list[str] = []
    for loader, args in (
        (load_default_whitelist, (modality,)),
        (load_project_whitelist, (project_dir, modality)) if project_dir is not None else (None, ()),
    ):
        if loader is None:
            continue
        try:
            for term in loader(*args):
                key = str(term).upper().strip()
                if key and key not in seen:
                    seen.add(key)
                    items.append(key)
        except (FileNotFoundError, OSError, ValueError) as exc:
            logger.debug("Whitelist not loaded from %s: %s", loader.__name__, exc)
    return items


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
) -> list[OCRText] | None:
    """
    Detect text in a 2D uint8 frame; apply shared noise (and optional whitelist) filtering.
    """
    if pixels.ndim == 3:
        img_height, img_width = pixels.shape[:2]
    elif pixels.ndim == 2:
        img_height, img_width = pixels.shape
    else:
        logger.error(f"Unsupported image dimensions: {pixels.ndim}")
        return None

    results = _easyocr_readtext(ocr_reader, pixels)
    ocr_texts = filter_ocr_detections(
        _parse_easyocr_results(results, img_width, img_height),
        whitelist=whitelist,
    )
    logger.debug("OCR detections after filter: %d", len(ocr_texts))

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


def blackout_ocr_text_areas(pixels: ndarray, ocr_texts: list[OCRText]) -> None:
    """Zero-fill OCR bounding boxes on the source pixel array (in-place)."""
    if not ocr_texts:
        return
    rects = [UserRectangle(top_left=ocr_text.top_left, bottom_right=ocr_text.bottom_right) for ocr_text in ocr_texts]
    blackout_rectangular_areas(pixels, rects)


def _map_ocr_texts_to_source_coordinates(
    ocr_texts: Sequence[OCRText],
    *,
    border_size: int,
    scale_factor: float,
    source_cols: int,
    source_rows: int,
) -> list[OCRText]:
    """Map OCR boxes from bordered/downscaled detection space to source DICOM pixels."""
    if scale_factor <= 0:
        scale_factor = 1.0
    mapped: list[OCRText] = []
    for ocr_text in ocr_texts:
        x1, y1, x2, y2 = ocr_text.get_bounding_box()

        def to_source(value: float, border: int) -> int:
            return int(round((value - border) / scale_factor))

        x1_source = max(0, to_source(x1, border_size))
        y1_source = max(0, to_source(y1, border_size))
        x2_source = min(source_cols, to_source(x2, border_size))
        y2_source = min(source_rows, to_source(y2, border_size))
        if x1_source >= x2_source or y1_source >= y2_source:
            continue
        mapped.append(
            OCRText(
                text=ocr_text.text,
                top_left=(x1_source, y1_source),
                bottom_right=(x2_source, y2_source),
                prob=ocr_text.prob,
            )
        )
    return mapped


def _apply_frame_removal_mask(
    frame_pixels: ndarray,
    dilated_mask: NDArray[np.uint8],
    *,
    bits_allocated: int,
    pixel_representation: int,
    removal_mode: PixelPhiRemovalMode,
) -> ndarray:
    if removal_mode is PixelPhiRemovalMode.BLACKOUT:
        raise ValueError("Use blackout_ocr_text_areas for blackout removal")

    if bits_allocated == 16 and pixel_representation == 1:
        working = (frame_pixels + 32768).astype(np.uint16)
        deid = inpaint(
            src=working,
            inpaintMask=dilated_mask,
            inpaintRadius=5,
            flags=INPAINT_TELEA,
        )
        return (deid - 32768).astype(np.int16)

    return inpaint(
        src=frame_pixels,
        inpaintMask=dilated_mask,
        inpaintRadius=5,
        flags=INPAINT_TELEA,
    )


def _encode_decompressed_frame_for_save(
    frame_pixels: ndarray,
    *,
    ds: Dataset,
    grayscale: bool,
    pi: str,
) -> ndarray:
    if not ds.file_meta.TransferSyntaxUID.is_compressed:
        return frame_pixels
    encoded = frame_pixels
    if not grayscale and pi != "RGB":
        encoded = convert_color_space(arr=encoded, current=pi, desired="RGB", per_frame=True)
    return encode_array(
        arr=encoded,
        photometric_interpretation=2 if grayscale else 1,
        use_mct=False,
    )


def remove_text(pixels: ndarray, windowed_frame: NDArray[np.uint8], ocr_texts: list[OCRText]) -> ndarray:
    """
    Remove the PHI in the pixel data of the supplied pixels 2D frame using the suplied ocr_text rectangles
    Use the windowed frame to determine the text contours on the mask
    Perform inpainting using cv2.inpaint with radius = 5 & INPAINT_TELEA (Poisson PDE) algorithm
    Args:
        pixels: NumPy array representing the image (grayscale or color).
        windowed_frame: Windowed pixels to determine the text contours on the mask
        ocr_texts: A list of OCRText objects specifying the text and rectangles to remove using inpainting
    Returns:
        The inpainted image as a NumPy array.
    Raises:
        General Exception from OpenCV.inpaint
    """

    # Create an 8 bit mask of pixels for in-painting
    mask: NDArray[np.uint8] = np.zeros(pixels.shape[:2], dtype=np.uint8)

    for ocr_text in ocr_texts:
        _draw_text_contours_on_mask(
            image=windowed_frame,
            top_left=ocr_text.top_left,
            bottom_right=ocr_text.bottom_right,
            mask=mask,
        )

    kernel: NDArray[np.uint8] = np.ones((3, 3), np.uint8)
    dilated_mask = dilate(src=mask, kernel=kernel, iterations=1)

    # Inpaint function only supports 8-bit, 16-bit UNSIGNED or 32-bit float 1-channel and 8-bit 3-channel input/output images
    return inpaint(
        src=pixels.astype(np.float32)
        if np.issubdtype(pixels.dtype, np.floating) or pixels.dtype == np.int16
        else pixels,
        inpaintMask=dilated_mask,
        inpaintRadius=5,
        flags=INPAINT_TELEA,
    )


def blackout_rectangular_areas(pixels: ndarray, user_rects: list[UserRectangle]):
    # For user defined rectangles simply blacken out the area defined by the user_rect
    """
    Blacks out rectangular areas defined in user_rects on the input image.

    Args:
        pixels: NumPy array representing the image (grayscale or color).
                This array will be modified IN-PLACE.
        user_rects: A list of UserRectangle objects specifying the areas to black out.
    """
    if not user_rects:  # No rectangles to process
        return

    img_height, img_width = pixels.shape[:2]  # Get image dimensions

    for rect in user_rects:
        try:
            # Get bounding box coordinates, ensuring x1<=x2 and y1<=y2
            x1, y1, x2, y2 = rect.get_bounding_box()

            # Clamp coordinates to image boundaries to prevent errors
            r1 = max(0, y1)  # Row start (y1)
            r2 = min(img_height, y2)  # Row end (y2)
            c1 = max(0, x1)  # Col start (x1)
            c2 = min(img_width, x2)  # Col end (x2)

            # Check if the clamped rectangle has a valid area
            if r1 < r2 and c1 < c2:
                # Efficiently set the slice to black (0)
                # NumPy broadcasting handles grayscale (2D) and color (3D)
                pixels[r1:r2, c1:c2] = 0
        except Exception as e:
            # Log error if a specific rectangle causes issues
            logging.error(f"Error processing rectangle {rect}: {e}")
            continue  # Skip to the next rectangle


# TODO: split this process up into sub-alogirthms for pluggable functional pipeline:
# [pixel attribute validation > apply LUT > normalize > add border > downscaling > OCR > upscaling > inpainting > compression]
# TODO: make source file immutable & keep source file? add backup parameter?
def remove_pixel_phi(
    dcm_path: Path,
    ocr_reader: Reader,
    downscale_dimension_threshold: int = 800,
    border_size: int = 20,
    *,
    removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
    project_dir: Path | None = None,
    modality: str | None = None,
    whitelist: Sequence[str] | None = None,
) -> tuple[bool, list[str], int]:
    """
    Description:
        Removes the PHI in the pixel data of a DICOM file with 1...N frames
        If the incoming pixel array was compressed, burnt-in annotation is detected and pixel_array modified
        then the pixel_array is re-compressed with JPG2000Lossless compression and the ds transfer syntax changed accordingly

    Args:
         dcm_path (Path): path to source DICOM file [*Mutable*]
         ocr_reader (easyOCR.Reader): initialised OCR Reader object from easyocr
         downscale_dimension_threshold:
            if either dimension (rows or cols) of pixel frame is larger than this threshold
            the image will be downscaled to decrease OCR speed
         border_size: size in pixels added to the pixel frame to enable text detection at the edges

    Returns:
        Tuple of (modified, detected_texts, pixels_changed). ``modified`` is True when pixel data was changed.
        ``detected_texts`` is a deduplicated list of OCR strings found across all frames.
        ``pixels_changed`` counts source-image pixels altered by the removal mask.

    Raises:
        InvalidDicomError: if dcm_path not a valid DICOM file
        TypeError: if dcm_path is none or unsupported type
        ValueError:
            If any essential pixel attribute is missing or invalid
            If group 2 elements are in dataset rather than dataset.file_meta, or if a preamble is given but is not 128 bytes long, or if Transfer Syntax is a compressed type and pixel data is not compressed
            If thrown by ds.save_as / dcmwrite
        General Exception from OpenCV.inpaint
        Runtime Exception from OpenJPEG.encode_array
    """
    logger.debug(f"Remove burnt-in PHI from pixel data of: {dcm_path}")

    # Read the DICOM image file using pydicom which will perform any decompression required
    ds = dcmread(dcm_path)

    series_modality = modality or str(ds.get("Modality", "") or "")
    effective_whitelist = (
        list(whitelist) if whitelist is not None else load_modality_whitelist(project_dir, series_modality or None)
    )

    logger.debug(f"Processing Image, SOPClassUID: {ds.SOPClassUID} AnonPatientID: {ds.PatientID}")

    # Extract relevant attributes for pixel data processing:
    # Mandatory:
    pi = ds.get("PhotometricInterpretation", None)
    samples_per_pixel = ds.get("SamplesPerPixel", 1)
    rows = ds.get("Rows", None)
    cols = ds.get("Columns", None)
    bits_allocated = ds.get("BitsAllocated", None)
    bits_stored = ds.get("BitsStored", None)
    high_bit = ds.get("HighBit", None)
    pixel_representation = ds.get("PixelRepresentation", None)
    # Not mandatory:
    pixel_spacing = ds.get("PixelSpacing", None)
    no_of_frames = ds.get("NumberOfFrames", 1)

    # Validate pixel related attributes:
    if not pi:
        raise ValueError("PhotometricInterpretation attribute missing.")

    if pi not in VALID_COLOR_SPACES:
        raise ValueError(f"Invalid Photometric Interpretation: {pi}. Support Color Spaces: {VALID_COLOR_SPACES}")

    grayscale = False
    if pi in ["MONOCHROME1", "MONOCHROME2"]:
        grayscale = True
        if samples_per_pixel != 1:
            raise ValueError(f"Samples per pixel = {samples_per_pixel} which should be 1 for grayscale images.")
    elif samples_per_pixel > 4:
        raise ValueError(f"Samples per pixel = {samples_per_pixel} which should be < 4 for multichannel images.")

    if not rows or not cols:
        raise ValueError("Missing image dimensions: Rows & Columns")

    if bits_allocated is None or bits_stored is None or high_bit is None or pixel_representation is None:
        raise ValueError(
            "Missing essential pixel attributes (BitsAllocated, BitsStored, HighBit, PixelRepresentation)."
        )

    # Validate if bits stored is less than or equal to bits allocated
    if bits_stored > bits_allocated:
        raise ValueError(f"BitsStored ({bits_stored}) cannot be greater than BitsAllocated ({bits_allocated}).")

    # Validate the HighBit value
    if high_bit != bits_stored - 1:
        raise ValueError(f"HighBit ({high_bit}) should be equal to BitsStored - 1 ({bits_stored - 1}).")

    # Validate pixel representation: 0 = unsigned, 1 = signed
    if pixel_representation not in [0, 1]:
        raise ValueError(f"Invalid Pixel Representation: {pixel_representation}. Expected 0 (unsigned) or 1 (signed).")

    # Check that pixel data exists
    if not hasattr(ds, "PixelData"):
        raise ValueError("PixelData element is missing.")

    if not pixel_spacing:
        logger.warning("PixelSpacing missing")

    # Decompress source pixel array:
    source_pixels_decompressed = ds.pixel_array

    # Make a COPY the decompressed source pixel array for processing:
    pixels = source_pixels_decompressed.copy()

    # Validate Pixel Array:
    # Validate the shape of the Pixel Array
    frame1 = pixels[0] if no_of_frames > 1 else pixels
    if frame1.shape[0] != rows or frame1.shape[1] != cols:
        raise ValueError(f"Pixel array shape {pixels.shape} does not match Rows and Columns ({rows}, {cols}).")

    # Validate the data type
    if bits_allocated == 8:
        expected_dtype = np.uint8 if pixel_representation == 0 else np.int8
    elif bits_allocated == 16:
        expected_dtype = np.uint16 if pixel_representation == 0 else np.int16
    else:
        raise ValueError("Unsupported BitsAllocated value. Only 8 and 16 bits are supported.")

    if pixels.dtype != expected_dtype:
        raise ValueError(f"Pixel data type {pixels.dtype} does not match expected type {expected_dtype}.")

    # Validate pixel value range according to BitsStored
    max_valid_value = (1 << bits_stored) - 1
    if pixel_representation == 0:  # unsigned
        if np.any(pixels < 0) or np.any(pixels > max_valid_value):
            raise ValueError(
                f"Pixel values out of range for BitsStored ({bits_stored}): Found range [{pixels.min()}, {pixels.max()}]."
            )
    else:  # signed
        min_valid_value = -(1 << (bits_stored - 1))
        max_valid_value = (1 << (bits_stored - 1)) - 1
        if np.any(pixels < min_valid_value) or np.any(pixels > max_valid_value):
            raise ValueError(
                f"Pixel values out of range for signed BitsStored ({bits_stored}): Found range [{pixels.min()}, {pixels.max()}]."
            )

    # DICOM grayscale image is now validated
    logger.debug("Header and pixel array valid, now processing copy of pixel array...")
    logger.debug(f"Transfer Syntax: {ds.file_meta.TransferSyntaxUID}")
    logger.debug(f"Compressed: {ds.file_meta.TransferSyntaxUID.is_compressed}")
    logger.debug(f"PhotometricInterpretation: {pi}")
    logger.debug(f"SamplePerPixel: {samples_per_pixel}")
    logger.debug(f"Rows={rows} Columns={cols}")
    logger.debug(
        f"BitsAllocated={bits_allocated} BitsStored={bits_stored} HighBit={high_bit} Signed={pixel_representation != 0}"
    )
    logger.debug(f"pixels.shape: {pixels.shape}")
    logger.debug(f"pixels.value.range:[{pixels.min()}..{pixels.max()}]")
    logger.debug(f"Pixel Spacing: {pixel_spacing}")
    logger.debug(f"Number of Frames: {no_of_frames}")

    # *BEGIN PROCESSING*:
    # GET TEXT REDCACTION CONTOURS TO APPLY TO SOURCE PIXELS

    # Apply Color LUT if photometric interpretation is PALETTE COLOR
    if pi == "PALETTE COLOR" and "PaletteColorLookupTableData" in ds:
        logger.debug("Applying Palette Color Lookup Table")
        pixels = apply_color_lut(pixels, ds)  # will return RGB or RGBA

    # # Convert color space if needed (e.g., from YBR to RGB)
    elif pi in ["YBR_FULL", "YBR_FULL_422"]:
        logger.debug(f"Convert color space from {pi} to RGB")
        pixels = convert_color_space(arr=pixels, current=pi, desired="RGB", per_frame=True)

    if no_of_frames == 1:
        pixels_stack = [pixels]
        source_pixels_decompressed_stack = [source_pixels_decompressed]
    else:
        pixels_stack = pixels
        source_pixels_decompressed_stack = source_pixels_decompressed

    # To improve OCR processing speed:
    # TODO: Work out more precisely using "readable" text size, pixel spacing (not always present), mask blur kernel size & inpainting radius
    # Downscale the image if its rows or cols exceeds the downscale_dimension_threshold (for now, empirically determined to 800 pixels)
    scale_factor = 1
    if cols > downscale_dimension_threshold:
        scale_factor = downscale_dimension_threshold / cols
    elif rows > downscale_dimension_threshold:
        scale_factor = downscale_dimension_threshold / rows

    source_pixels_deid_stack: list | None = None
    source_pixels_changed = False
    detected_texts: list[str] = []
    total_pixels_changed = 0
    is_compressed = ds.file_meta.TransferSyntaxUID.is_compressed

    for frame in range(no_of_frames):
        if no_of_frames > 1:
            logging.debug(f"Processing Frame {frame}...")

        stored_frame = pixels_stack[frame]
        frame_border_size = border_size
        frame_scale_factor = scale_factor

        if grayscale:
            from anonymizer.controller.create_projections import prepare_series_view_ocr_frame

            pixels = prepare_series_view_ocr_frame(stored_frame, ds)
            frame_border_size = 0
            frame_scale_factor = 1.0
            logger.debug(
                "OCR frame prepared with Series View settings (DICOM WL/WW, no border/downscale); shape=%s",
                pixels.shape,
            )
        else:
            pixels = stored_frame.copy()
            normalize(
                src=pixels,
                dst=pixels,
                alpha=0,
                beta=255,
                norm_type=NORM_MINMAX,
                dtype=-1,
                mask=None,
            )
            pixels = pixels.astype(np.uint8)

            if frame_scale_factor < 1:
                new_size = (int(cols * frame_scale_factor), int(rows * frame_scale_factor))
                pixels = resize(pixels, new_size, interpolation=INTER_LINEAR)
                logger.debug(
                    "Downscaled OCR image with scaling factor=%.2f, new pixels.shape: %s",
                    frame_scale_factor,
                    pixels.shape,
                )

            pixels = copyMakeBorder(
                pixels,
                frame_border_size,
                frame_border_size,
                frame_border_size,
                frame_border_size,
                BORDER_CONSTANT,
                value=[0, 0, 0],
            )
            logger.debug(f"Black Border of {frame_border_size}px added, new pixels.shape: {pixels.shape}")

        ocr_height, ocr_width = pixels.shape[:2]
        raw_results = _easyocr_readtext(ocr_reader, pixels)
        ocr_texts = filter_ocr_detections(
            _parse_easyocr_results(raw_results, ocr_width, ocr_height),
            whitelist=effective_whitelist,
        )

        if not ocr_texts:
            logger.debug("No qualifying text found in frame after OCR filter")
            continue

        logger.debug("Text boxes retained after filter in frame: %d", len(ocr_texts))

        source_ocr_texts = _map_ocr_texts_to_source_coordinates(
            ocr_texts,
            border_size=frame_border_size,
            scale_factor=frame_scale_factor,
            source_cols=cols,
            source_rows=rows,
        )
        if not source_ocr_texts:
            logger.debug("No OCR boxes mapped to source coordinates")
            continue

        for ocr_text in source_ocr_texts:
            detected_texts.append(ocr_text.text)

        frame_pixels_changed = 0
        source_pixels_deid: ndarray | None = None

        if removal_mode is PixelPhiRemovalMode.BLACKOUT:
            logger.debug("Applying OCR bbox blackout to source pixels (Series View routine)")
            source_frame = source_pixels_decompressed_stack[frame]
            if grayscale:
                from anonymizer.controller.create_projections import (
                    stored_grayscale_frame_to_viewer_pixels,
                    viewer_grayscale_pixels_to_stored_frame,
                )

                viewer_pixels, modality_max = stored_grayscale_frame_to_viewer_pixels(source_frame, ds)
                viewer_pixels = viewer_pixels.copy()
                blackout_ocr_text_areas(viewer_pixels, source_ocr_texts)
                source_pixels_deid = viewer_grayscale_pixels_to_stored_frame(
                    viewer_pixels,
                    ds,
                    modality_max=modality_max,
                )
            else:
                source_pixels_deid = source_frame.copy()
                blackout_ocr_text_areas(source_pixels_deid, source_ocr_texts)
            frame_pixels_changed = sum(text.box_area() for text in source_ocr_texts)
        else:
            mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
            for ocr_text in ocr_texts:
                _draw_text_contours_on_mask(
                    pixels,
                    ocr_text.top_left,
                    ocr_text.bottom_right,
                    mask,
                )

            mask = (
                mask[frame_border_size:-frame_border_size, frame_border_size : mask.shape[1] - frame_border_size]
                if frame_border_size > 0
                else mask
            )
            logger.debug(f"Remove Border from mask, new mask.shape: {mask.shape}")

            if frame_scale_factor < 1:
                mask = resize(src=mask, dsize=(cols, rows), interpolation=INTER_LINEAR)
                logger.debug(f"Upscale mask back to original source image size, new mask.shape: {mask.shape}")

            kernel = np.ones((3, 3), np.uint8)
            dilated_mask = dilate(src=mask, kernel=kernel, iterations=1)
            frame_pixels_changed = int(np.count_nonzero(dilated_mask))
            if frame_pixels_changed <= 0:
                logger.debug("Inpaint mask empty after contour detection; skipping frame")
                continue

            logger.debug("Change source pixels using OCR mask and cv2.inpaint (radius=5, INPAINT_TELEA)")
            source_pixels_deid = _apply_frame_removal_mask(
                source_pixels_decompressed_stack[frame],
                dilated_mask,
                bits_allocated=bits_allocated,
                pixel_representation=pixel_representation,
                removal_mode=removal_mode,
            )

        if frame_pixels_changed <= 0 or source_pixels_deid is None:
            continue

        source_pixels_changed = True
        total_pixels_changed += frame_pixels_changed

        if no_of_frames > 1:
            if source_pixels_deid_stack is None:
                source_pixels_deid_stack = [
                    source_pixels_decompressed_stack[index].copy() for index in range(no_of_frames)
                ]
            source_pixels_deid_stack[frame] = source_pixels_deid
        else:
            if source_pixels_deid_stack is None:
                source_pixels_deid_stack = []
            source_pixels_deid_stack.append(source_pixels_deid)

    deduped_texts = _dedupe_texts(detected_texts)

    if not source_pixels_changed or total_pixels_changed <= 0 or source_pixels_deid_stack is None:
        logger.debug("No changes made to pixel data")
        return False, deduped_texts, 0

    if is_compressed:
        if not grayscale and pi != "RGB":
            ds.PhotometricInterpretation = "RGB"
        source_pixels_deid_stack = [
            _encode_decompressed_frame_for_save(
                frame_pixels,
                ds=ds,
                grayscale=grayscale,
                pi=pi,
            )
            for frame_pixels in source_pixels_deid_stack
        ]

    # Save processed stack to PixelData:
    if is_compressed:
        logger.debug("Encapsulate source_pixels_deid_stack")
        ds.PixelData = encapsulate(source_pixels_deid_stack)
        ds["PixelData"].is_undefined_length = True
        ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    else:
        ds.PixelData = np.stack(source_pixels_deid_stack, axis=0).tobytes()

    ds.save_as(dcm_path)

    from anonymizer.controller.create_projections import delete_series_projection_cache

    delete_series_projection_cache(dcm_path.parent)

    return True, deduped_texts, total_pixels_changed


def apply_instance_pixel_phi(
    anon_model: AnonymizerModel,
    anon_sop_instance_uid: str,
    texts: Sequence[str],
) -> bool:
    return anon_model.set_instance_pixel_phi(anon_sop_instance_uid, texts)


def apply_instance_pixel_phi_for_dcm(
    anon_model: AnonymizerModel,
    dcm_path: Path,
    texts: Sequence[str],
) -> bool:
    ds = dcmread(dcm_path, stop_before_pixels=True)
    return apply_instance_pixel_phi(anon_model, str(ds.SOPInstanceUID), texts)


def collect_series_view_pixel_phi_texts(image_viewer) -> dict[int, list[str]]:
    """Collect OCR text strings from a Series View image viewer overlay, keyed by frame index."""
    texts_by_frame: dict[int, list[str]] = {}
    overlay_data = getattr(image_viewer, "overlay_data", None)
    if not overlay_data:
        return texts_by_frame

    for frame_index, overlay in overlay_data.items():
        frame_texts = [text.text for text in overlay.ocr_texts if text.text.strip()]
        deduped = _dedupe_texts(frame_texts)
        if deduped:
            texts_by_frame[frame_index] = deduped
    return texts_by_frame


def apply_series_view_pixel_phi(
    anon_model: AnonymizerModel,
    slice_paths: Sequence[Path],
    texts_by_frame: Mapping[int, Sequence[str]],
    *,
    projection_frame_count: int = 0,
    anon_series_uid: str | None = None,
) -> int:
    """Persist pixel PHI metadata for series slices that have overlay OCR text."""
    updated = 0
    for frame_index, texts in texts_by_frame.items():
        slice_index = frame_index - projection_frame_count
        if slice_index < 0 or slice_index >= len(slice_paths):
            continue
        if apply_instance_pixel_phi_for_dcm(anon_model, slice_paths[slice_index], texts):
            updated += 1
    if anon_series_uid:
        anon_model.set_series_pixel_phi_scanned(anon_series_uid, scanned=True)
    return updated


_SHUTDOWN = object()
_WORKER_SLEEP_SECS = 0.075


def _ocr_use_gpu() -> bool:
    """Unified GPU policy for EasyOCR (CUDA only; EasyOCR does not use MPS via gpu=True)."""
    return torch.cuda.is_available()


def _clear_torch_caches() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()


@dataclass
class _OcrJob:
    fn: Callable[[Reader], Any] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    preload_only: bool = False
    release_reader: bool = False


class OcrService:
    """Single background thread owns one EasyOCR Reader for the whole process."""

    _instance: OcrService | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._queue: Queue[_OcrJob | object] = Queue()
        self._session_depth = 0
        self._session_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="OcrServiceWorker",
            daemon=True,
        )
        self._worker.start()

    @classmethod
    def instance(cls) -> OcrService:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Shut down and discard the singleton (tests only)."""
        with cls._instance_lock:
            instance = cls._instance
            cls._instance = None
        if instance is not None:
            instance.shutdown()

    def ensure_models(self) -> None:
        """Ensure OCR model weights exist on disk (download if missing)."""
        if not ocr_models_ready():
            logger.warning("OCR models missing; downloading to %s", OCR_MODEL_DIR)
            download_ocr_models()
        elif OCR_MODEL_DIR.is_dir():
            logger.debug("EasyOCR models present: %s", os.listdir(OCR_MODEL_DIR))

    def process_dicom_path(
        self,
        path: Path,
        *,
        removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
        project_dir: Path | None = None,
        modality: str | None = None,
    ) -> tuple[bool, list[str], int]:
        """Run remove_pixel_phi on the worker thread."""
        path = Path(path)
        return self._run(
            lambda reader: remove_pixel_phi(
                path,
                reader,
                removal_mode=removal_mode,
                project_dir=project_dir,
                modality=modality,
            )
        )

    def detect_text(
        self,
        pixels: NDArray,
        *,
        draw_boxes: bool = False,
    ) -> list[OCRText]:
        """Run detect_text on the worker thread."""
        results = self._run(
            lambda reader: detect_text(
                pixels,
                reader,
                draw_boxes_and_text=draw_boxes,
            )
        )
        return results or []

    @contextmanager
    def batch_session(self, *, preload: bool = True, release: bool = False) -> Iterator[None]:
        """Preload the reader at phase start; optionally release it when the outermost session ends."""
        with self._session_lock:
            self._session_depth += 1
            entering = self._session_depth == 1

        try:
            if entering and preload:
                self.ensure_models()
                self._preload_reader()
            yield
        finally:
            with self._session_lock:
                self._session_depth -= 1
                exiting = self._session_depth == 0
            if exiting and release:
                self._release_reader()

    def pending_count(self) -> int:
        return self._queue.qsize()

    @classmethod
    def shutdown_batch(cls) -> None:
        """Stop the OCR worker and release loaded models after a batch OCR phase."""
        with cls._instance_lock:
            instance = cls._instance
            cls._instance = None
        if instance is None:
            return
        if instance._worker.is_alive():
            with suppress(Exception):
                instance._release_reader()
            instance.shutdown()
        _clear_torch_caches()
        gc.collect()
        logger.info("OCR batch worker stopped and models released")

    def shutdown(self) -> None:
        if not self._worker.is_alive():
            return
        self._queue.put(_SHUTDOWN)
        self._worker.join(timeout=120)

    def _run(self, fn: Callable[[Reader], Any]) -> Any:
        job = _OcrJob(fn=fn)
        self._queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error
        return job.result

    def _preload_reader(self) -> None:
        job = _OcrJob(preload_only=True)
        self._queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error

    def _release_reader(self) -> None:
        job = _OcrJob(release_reader=True)
        self._queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error

    def _create_reader(self) -> Reader:
        self.ensure_models()
        logger.info(
            "Initialising EasyOCR Reader (gpu=%s, cuda=%s, mps=%s)",
            _ocr_use_gpu(),
            torch.cuda.is_available(),
            torch.backends.mps.is_available(),
        )
        return Reader(
            lang_list=list(OCR_LANGS),
            gpu=_ocr_use_gpu(),
            model_storage_directory=str(OCR_MODEL_DIR),
            verbose=False,
        )

    def _worker_loop(self) -> None:
        logger.info("thread=%s start", threading.current_thread().name)
        reader: Reader | None = None

        while True:
            time.sleep(_WORKER_SLEEP_SECS)
            item = self._queue.get()
            if item is _SHUTDOWN:
                self._queue.task_done()
                break

            job = item
            assert isinstance(job, _OcrJob)
            try:
                if job.release_reader:
                    if reader is not None:
                        del reader
                        reader = None
                        _clear_torch_caches()
                        logger.info("OCR Reader released")
                elif job.preload_only:
                    if reader is None:
                        reader = self._create_reader()
                        logger.info("OCR Reader preloaded")
                elif job.fn is not None:
                    if reader is None:
                        reader = self._create_reader()
                    job.result = job.fn(reader)
            except BaseException as exc:
                job.error = exc
                logger.exception("OCR job failed")
            finally:
                job.done.set()
                self._queue.task_done()

        if reader is not None:
            del reader
        _clear_torch_caches()
        logger.info("thread=%s end", threading.current_thread().name)
