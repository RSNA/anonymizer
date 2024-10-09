# For Burnt-IN Pixel PHI Removal:
from pathlib import Path
import logging

import numpy as np
from numpy import ndarray
from cv2 import threshold, findContours, drawContours, normalize, copyMakeBorder, resize, dilate, inpaint, cvtColor
from cv2 import (
    THRESH_OTSU,
    COLOR_BGR2GRAY,
    RETR_TREE,
    CHAIN_APPROX_SIMPLE,
    NORM_MINMAX,
    INTER_LINEAR,
    BORDER_CONSTANT,
    INPAINT_TELEA,
)

from easyocr import Reader
from pydicom import Dataset, dcmread
from pydicom.pixel_data_handlers.util import apply_voi_lut, apply_modality_lut
from pydicom.encaps import encapsulate
from pydicom.uid import JPEG2000Lossless
from openjpeg.utils import encode_array  # JPG2000Lossless

grayscale_spaces = ["MONOCHROME1", "MONOCHROME2"]
color_spaces = [
    "RGB",
    "RGBA",
    "YBR_FULL",
    "YBR_FULL_422",
    "YBR_ICT",
    "YBR_RCT",
    "PALETTE COLOR",
]
downscale_dimension_threshold = 800
border_size = 20

logging.getLogger("openjpeg").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def remove_pixel_phi(dcm_path: Path, ocr_reader: Reader) -> None:
    """
    Removes the PHI in the pixel data of a DICOM file with 1...N frames
    If the incoming ds pixel array was compressed, burnt-in annotation is detected and pixel_array modified
    then the pixel_array is re-compressed with JPG2000Lossless compression and the ds transfer syntax changed accordingly

    Args:
        dcm_path (Path): path to source DICOM file [*Mutable*] TODO: immutable & keep source file?

    Raises:
        InvalidDicomError: if dcm_path not a valid DICOM file
        TypeError: if dcm_path is none or unsupported type
        ValueError:
            - If any essential pixel attribute is missing or invalid.
            - If group 2 elements are in dataset rather than dataset.file_meta, or if a preamble is given but is not 128 bytes long,
              or if Transfer Syntax is a compressed type and pixel data is not compressed.
        AttributeError If either ds.is_implicit_VR or ds.is_little_endian have not been set.
    """
    # Read the DICOM image file using pydicom which will perform any decompression required
    ds = dcmread(dcm_path)

    # Process Grayscale and Color Images with different functions:
    pi = ds.get("PhotometricInterpretation", None)
    if not pi:
        raise ValueError("PhotometricInterpretation attribute missing.")
    if pi in grayscale_spaces:
        _process_grayscale_image(ds, ocr_reader)
    else:
        if pi not in color_spaces:
            raise ValueError(f"Invalid Photometric Interpretation: {pi}. Expected one of {color_spaces}.")
        raise NotImplementedError(f"Remove PHI from Color Images not implemented")

    ds.save_as(dcm_path)


def _draw_text_contours_on_mask(image, top_left, bottom_right, mask: ndarray) -> None:
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
    # Convert sub_image to grayscale for contour detection
    # sub_image = cvtColor(sub_image, COLOR_BGR2GRAY)
    # Threshold the grayscale sub-image:
    _, thresh = threshold(sub_image, 0, 255, THRESH_OTSU)
    # Find contours within the sub-image
    contours, _ = findContours(thresh, RETR_TREE, CHAIN_APPROX_SIMPLE)
    # Shift the contours to match the original image coordinates
    for cnt in contours:
        cnt += np.array([x1, y1])
    # Draw the contours on the mask
    drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)


def _has_voi_lut(ds: Dataset) -> bool:
    # Check for VOILUTSequence
    if "VOILUTSequence" in ds:
        return True
    # Check for WindowCenter and WindowWidth
    if "WindowCenter" in ds and "WindowWidth" in ds:
        return True
    return False


# TODO: split this process up into sub-alogirthms for pluggable functional pipeline:
# after pixel attribute validation:  [apply LUT > normalize > add border > downscaling > OCR > upscaling > inpainting > compression]
def _process_grayscale_image(ds: Dataset, ocr: Reader):
    """
    Processes a grayscale image by validating pixel-related attributes, performing necessary checks, and applying OCR processing.

    Args:
        ds (Dataset): pydicom Dataset [*Mutable*]

    Raises:
        ValueError: If any essential pixel attribute in ds is missing or invalid.

    Returns:
        None
        If successful the ds dataset pixel_array will be modified via inpainting to remove all detected text

    """
    logger.info(f"Processing Grayscale Image, SOPClassUID: {ds.SOPClassUID} AnonPatientID: {ds.PatientID}")
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

    if pi not in ["MONOCHROME1", "MONOCHROME2"]:
        raise ValueError(f"Invalid Photometric Interpretation: {pi}. Expected 'MONOCHROME1' or 'MONOCHROME2'.")

    if samples_per_pixel != 1:
        raise ValueError(f"Samples per pixel = {samples_per_pixel} which should be 1 for grayscale images.")

    if not rows or not cols:
        raise ValueError("Missing image dimensions: Rows & Columns")

    if bits_allocated is None or bits_stored is None or high_bit is None or pixel_representation is None:
        raise ValueError(
            f"Missing essential pixel attributes (BitsAllocated, BitsStored, HighBit, PixelRepresentation)."
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
    # Copy the decompressed source pixel array:
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
    logger.debug(f"Header and pixel array valid, now processing...")
    logger.debug(f"Transfer Syntax: {ds.file_meta.TransferSyntaxUID}")
    logger.debug(f"Compressed: {ds.file_meta.TransferSyntaxUID.is_compressed}")
    logger.debug(f"PhotometricInterpretation: {pi}")
    logger.debug(f"SamplePerPixel: {samples_per_pixel}")
    logger.debug(f"Rows={rows} Columns={cols}")
    logger.debug(
        f"BitsAllocated={bits_allocated} BitStored={bits_stored} HighBit={high_bit} Signed={pixel_representation!=0}"
    )
    logger.debug(f"pixels.shape: {pixels.shape}")
    logger.debug(f"pixels.value.range:[{pixels.min()}..{pixels.max()}]")
    logger.debug(f"Pixel Spacing: {pixel_spacing}")
    logger.debug(f"Number of Frames: {no_of_frames}")

    # *BEGIN PROCESSING*:
    # GET REDCACTION CONTOURS TO APPLY TO SOURCE PIXELS

    # Invert pixel values if necessary
    if pi == "MONOCHROME1":  # 0 = white
        logger.info("Convert from MONOCHROME1 to MONOCHROME2")
        pixels = np.max(pixels) - pixels

    if no_of_frames == 1:
        pixels_stack = [pixels]
        source_pixels_decompressed_stack = [source_pixels_decompressed]
    else:
        pixels_stack = pixels
        source_pixels_decompressed_stack = source_pixels_decompressed

    # To improve OCR processing speed:
    # TODO: Work out more precisely using readable text size, pixel spacing (not always present), mask blur kernel size & inpainting radius
    # Downscale the image if its width exceeds the downscale_dimension_threshold
    scale_factor = 1
    if cols > downscale_dimension_threshold:
        scale_factor = downscale_dimension_threshold / cols
    elif rows > downscale_dimension_threshold:
        scale_factor = downscale_dimension_threshold / rows

    source_pixels_deid_stack = []

    for frame in range(no_of_frames):

        if no_of_frames > 1:
            logging.debug(f"Processing Frame {frame}...")

        pixels = pixels_stack[frame]

        # Apply Modality LUT if present
        if "ModalityLUTSequence" in ds:
            pixels = apply_modality_lut(pixels, ds)
            logger.debug(f"Applied Modality LUT: new pixels.value.range:[{int(pixels.min())}..{int(pixels.max())}]")
        elif _has_voi_lut(ds):
            # Apply Value of Interest Lookup (Windowing) if present:
            # TODO: is this necessary?
            pixels = apply_voi_lut(pixels, ds)
            logger.debug(f"Applied VOI LUT: new pixels.value.range:[{int(pixels.min())}..{int(pixels.max())}]")

        # Normalize the pixel array to the range 0-255
        normalize(src=pixels, dst=pixels, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=-1, mask=None)
        pixels = pixels.astype(np.uint8)
        logger.debug(f"After normalization: pixels.value.range:[{pixels.min()}..{pixels.max()}]")

        # DOWNSCALE if necessary:
        if scale_factor < 1:
            new_size = (int(cols * scale_factor), int(rows * scale_factor))
            pixels = resize(pixels, new_size, interpolation=INTER_LINEAR)
            logger.debug(f"Downscaled image with scaling factor={scale_factor:.2f}, new pixels.shape: {pixels.shape}")
        else:
            logger.debug(f"Max Image Dimension < {downscale_dimension_threshold}, no downscaling required.")

        # Add a border to the resized image
        pixels = copyMakeBorder(
            pixels,
            border_size,
            border_size,
            border_size,
            border_size,
            BORDER_CONSTANT,
            value=[0, 0, 0],  # Black border
        )
        logger.debug(f"Black Border of {border_size}px added, new pixels.shape: {pixels.shape}")

        # Perform OCR on the bordered image
        # for word-level detection: width_ths=0.1, paragraph=False
        results = ocr.readtext(
            pixels
        )  #  ,add_margin=0.0, rotation_info=[90])  # , 180, 270]) #TODO: add to global config?

        if not results:
            logger.info("No text found in frame")
            continue

        logger.info(f"Text boxes detected in frame: {len(results)}")

        # Create a mask for in-painting
        mask = np.zeros(pixels.shape[:2], dtype=np.uint8)

        # Draw bounding boxes around each detected word
        for bbox, text, prob in results:

            # Unpack the bounding box
            (top_left, top_right, bottom_right, bottom_left) = bbox

            top_left = tuple(map(int, top_left))
            bottom_right = tuple(map(int, bottom_right))

            # Peform full anonymization, remove all detected text from image:
            _draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)

        # CHANGE SOURCE PIXELS:

        # Remove border from mask
        mask = mask[border_size:-border_size, border_size : mask.shape[1] - border_size]
        logger.debug(f"Remove Border from mask, new mask.shape: {mask.shape}")

        # Upscale mask if downscaling was applied to source image:
        if scale_factor < 1:
            mask = resize(src=mask, dsize=(cols, rows), interpolation=INTER_LINEAR)
            logger.debug(f"Upscale mask back to original source image size, new mask.shape: {mask.shape}")

        kernel = np.ones((3, 3), np.uint8)
        dilated_mask = dilate(src=mask, kernel=kernel, iterations=1)

        # Apply inpainting mask to source pixel array:
        source_pixels_deid = inpaint(
            src=source_pixels_decompressed_stack[frame],
            inpaintMask=dilated_mask,
            inpaintRadius=5,
            flags=INPAINT_TELEA,
        )

        # if source pixels were compressed then re-compress to JPG2000Lossless:
        if ds.file_meta.TransferSyntaxUID.is_compressed:
            logger.debug("Re-compress deidentified source frame")
            source_pixels_deid = encode_array(arr=source_pixels_deid, photometric_interpretation=2, use_mct=False)

        source_pixels_deid_stack.append(source_pixels_deid)

    if not source_pixels_deid_stack:
        logging.info("No changes made to pixel data")
        return

    # Save processed stack to PixelData:
    if ds.file_meta.TransferSyntaxUID.is_compressed:
        logger.debug("Encapsulate source_pixels_deid_stack")
        ds.PixelData = encapsulate(source_pixels_deid_stack)
        ds["PixelData"].is_undefined_length = True
        ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    else:
        ds.PixelData = np.stack(source_pixels_deid_stack, axis=0).tobytes()
