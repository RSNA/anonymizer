"""Remove burnt-in PHI from DICOM pixel data."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import torch
from cv2 import (
    INPAINT_TELEA,
    dilate,
    inpaint,
)
from easyocr import Reader
from numpy import ndarray
from numpy.typing import NDArray
from openjpeg.utils import encode_array
from pydicom import Dataset, dcmread
from pydicom.encaps import encapsulate
from pydicom.pixels.processing import (
    apply_color_lut,
    convert_color_space,
)
from pydicom.uid import JPEG2000Lossless

if TYPE_CHECKING:
    from anonymizer.model.anonymizer import AnonymizerModel

from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    OcrWhitelistMatchSettings,
    PixelPhiRemovalMode,
    _dedupe_texts,
    _draw_text_contours_on_mask,
    _ocr_bgr_from_stored_monochrome,
    detect_text,
    load_modality_whitelist,
    load_modality_whitelist_match_settings,
    ocr_image_for_frame,
)
from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import modality_exclude_rects_for_series
from anonymizer.controller.create_projections import invalidate_projection_cache
from anonymizer.controller.series_io import (
    series_buffer_monochrome_to_stored,
    stored_monochrome_to_series_buffer,
)
from anonymizer.controller.series_overlay import OCRText, UserRectangle
from anonymizer.utils.dicom import SUPPORTED_PHOTOMETRIC_INTERPRETATIONS

logging.getLogger("openjpeg").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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
    if not grayscale:
        if encoded.ndim != 3 or encoded.shape[-1] not in (3, 4):
            raise ValueError(
                f"Expected color frame (rows, cols, 3|4), got shape {encoded.shape}"
            )
        if pi != "RGB":
            encoded = convert_color_space(arr=encoded, current=pi, desired="RGB", per_frame=True)
    return encode_array(
        arr=encoded,
        photometric_interpretation=2 if grayscale else 1,
        use_mct=False,
    )


def _validate_color_frames_match_dicom(
    frames: Sequence[ndarray],
    *,
    rows: int,
    cols: int,
    samples_per_pixel: int,
) -> None:
    expected = (rows, cols, samples_per_pixel)
    for index, frame in enumerate(frames):
        if frame.shape != expected:
            raise ValueError(
                f"Frame {index} shape {frame.shape} does not match DICOM "
                f"Rows={rows}, Columns={cols}, SamplesPerPixel={samples_per_pixel}"
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


def remove_ocr_text_from_frame(
    raw_pixels: ndarray,
    windowed_frame: NDArray[np.uint8],
    ocr_texts: list[OCRText],
    *,
    removal_mode: PixelPhiRemovalMode,
) -> ndarray:
    """Remove OCR text from one frame using blackout or inpaint (Series View)."""
    if removal_mode is PixelPhiRemovalMode.BLACKOUT:
        result = raw_pixels.copy()
        blackout_ocr_text_areas(result, ocr_texts)
        return result
    return remove_text(raw_pixels, windowed_frame, ocr_texts)


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
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    apply_phi_ner_filter: bool = False,
    exclude_rects: Sequence[UserRectangle] | None = None,
    use_exclude_areas: bool = False,
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
    _ = (downscale_dimension_threshold, border_size)  # legacy API; OCR uses Series View frame prep

    # Read the DICOM image file using pydicom which will perform any decompression required
    ds = dcmread(dcm_path)

    series_modality = modality or str(ds.get("Modality", "") or "")
    effective_whitelist = (
        list(whitelist) if whitelist is not None else load_modality_whitelist(project_dir, series_modality or None)
    )
    if whitelist_match_settings is None and project_dir is not None:
        whitelist_match_settings = load_modality_whitelist_match_settings(project_dir, series_modality or None)

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

    if pi not in SUPPORTED_PHOTOMETRIC_INTERPRETATIONS:
        raise ValueError(
            f"Invalid Photometric Interpretation: {pi}. Supported: {SUPPORTED_PHOTOMETRIC_INTERPRETATIONS}"
        )

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

    source_pixels_deid_stack: list | None = None
    source_pixels_changed = False
    detected_texts: list[str] = []
    total_pixels_changed = 0
    is_compressed = ds.file_meta.TransferSyntaxUID.is_compressed

    for frame in range(no_of_frames):
        if no_of_frames > 1:
            logging.debug(f"Processing Frame {frame}...")

        stored_frame = pixels_stack[frame]

        if grayscale:
            pixels = _ocr_bgr_from_stored_monochrome(stored_frame, ds)
        else:
            pixels = ocr_image_for_frame(ds, stored_frame)
        logger.debug(
            "OCR frame prepared with Series View settings (no border/downscale); shape=%s",
            pixels.shape,
        )

        img_h, img_w = pixels.shape[:2]
        saved_exclude = (
            modality_exclude_rects_for_series(
                project_dir,
                series_modality or None,
                width=img_w,
                height=img_h,
            )
            if use_exclude_areas
            else []
        )
        frame_exclude = list(exclude_rects or []) + saved_exclude
        if use_exclude_areas and frame == 0:
            logger.info(
                "OCR exclude areas enabled modality=%s saved=%d session=%d frame_size=%dx%d bboxes=%s",
                series_modality or "?",
                len(saved_exclude),
                len(exclude_rects or []),
                img_w,
                img_h,
                [rect.get_bounding_box() for rect in frame_exclude],
            )

        ocr_texts = detect_text(
            pixels,
            ocr_reader,
            modality=series_modality,
            whitelist=effective_whitelist,
            apply_noise_filter=True,
            whitelist_match_settings=whitelist_match_settings,
            apply_phi_ner_filter=apply_phi_ner_filter,
            exclude_rects=frame_exclude or None,
        ) or []

        if not ocr_texts:
            logger.debug("No qualifying text found in frame after OCR filter")
            continue

        logger.debug("Text boxes retained after filter in frame: %d", len(ocr_texts))

        source_ocr_texts = ocr_texts

        for ocr_text in source_ocr_texts:
            detected_texts.append(ocr_text.text)

        frame_pixels_changed = 0
        source_pixels_deid: ndarray | None = None

        if removal_mode is PixelPhiRemovalMode.BLACKOUT:
            logger.debug("Applying OCR bbox blackout to source pixels (Series View routine)")
            source_frame = source_pixels_decompressed_stack[frame]
            if grayscale:
                viewer_pixels, mono1_invert_max = stored_monochrome_to_series_buffer(source_frame, ds)
                viewer_pixels = viewer_pixels.copy()
                blackout_ocr_text_areas(viewer_pixels, source_ocr_texts)
                source_pixels_deid = series_buffer_monochrome_to_stored(
                    viewer_pixels,
                    ds,
                    mono1_invert_max=mono1_invert_max,
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
                    is_bgr=True,
                )

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

    if not grayscale:
        samples = int(ds.get("SamplesPerPixel", 3) or 3)
        ds.SamplesPerPixel = samples
        ds.PlanarConfiguration = 0
        _validate_color_frames_match_dicom(
            source_pixels_deid_stack,
            rows=int(rows),
            cols=int(cols),
            samples_per_pixel=samples,
        )

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

    invalidate_projection_cache(dcm_path.parent)

    return True, deduped_texts, total_pixels_changed


def apply_instance_embedded_phi(
    anon_model: AnonymizerModel,
    anon_sop_instance_uid: str,
    texts: Sequence[str],
) -> bool:
    return anon_model.set_instance_embedded_phi(anon_sop_instance_uid, texts)


def apply_instance_embedded_phi_for_dcm(
    anon_model: AnonymizerModel,
    dcm_path: Path,
    texts: Sequence[str],
) -> bool:
    ds = dcmread(dcm_path, stop_before_pixels=True)
    return apply_instance_embedded_phi(anon_model, str(ds.SOPInstanceUID), texts)


def collect_series_view_embedded_phi_texts(image_viewer) -> dict[int, list[str]]:
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


def apply_series_view_embedded_phi(
    anon_model: AnonymizerModel,
    slice_paths: Sequence[Path],
    texts_by_frame: Mapping[int, Sequence[str]],
    *,
    projection_frame_count: int = 0,
    anon_series_uid: str | None = None,
) -> int:
    """Persist pixel PHI metadata for series slices that have overlay OCR text.

    Multi-frame files reuse the same path once per frame in ``slice_paths``. Texts from
    those frames are merged (deduped, first-seen order) before writing so one Instance row
    keeps the full comma-delimited digest instead of being overwritten by the last frame.
    """
    texts_by_path: dict[Path, list[str]] = {}
    for frame_index, texts in texts_by_frame.items():
        slice_index = frame_index - projection_frame_count
        if slice_index < 0 or slice_index >= len(slice_paths):
            continue
        bucket = texts_by_path.setdefault(slice_paths[slice_index], [])
        bucket.extend(texts)

    updated = 0
    for dcm_path, texts in texts_by_path.items():
        if apply_instance_embedded_phi_for_dcm(anon_model, dcm_path, _dedupe_texts(texts)):
            updated += 1
    if anon_series_uid:
        anon_model.set_series_embedded_phi_scanned(anon_series_uid, scanned=True)
    return updated


def _ocr_use_gpu() -> bool:
    """True when EasyOCR can use an accelerator (CUDA or Apple MPS)."""
    if torch.cuda.is_available():
        return True
    return bool(torch.backends.mps.is_available())


def _clear_torch_caches() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
