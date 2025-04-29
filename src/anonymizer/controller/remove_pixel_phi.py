# For Burnt-IN Pixel PHI Removal:
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

import numpy as np
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
    apply_modality_lut,
    apply_voi_lut,
    convert_color_space,
)
from pydicom.uid import JPEG2000Lossless

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


def _has_voi_lut(ds: Dataset) -> bool:
    # Check for VOILUTSequence
    if "VOILUTSequence" in ds:
        return True
    # Check for WindowCenter and WindowWidth
    return bool("WindowCenter" in ds and "WindowWidth" in ds)


def detect_text(
    pixels: NDArray[np.uint8], ocr_reader: Reader, draw_boxes_and_text: bool = False
) -> list[OCRText] | None:
    """
    Detect Text in pixels 2D frame, if present and indicated, draw bounding box and text in green
    * NB * pixels must be 2D or 3D array (grayscale or RGB) data type: uint8
    Return list of OCRText: (bounding boxes, text, confidence)
    """
    if pixels.ndim == 3:
        img_height, img_width = pixels.shape[:2]
    elif pixels.ndim == 2:
        img_height, img_width = pixels.shape
    else:
        logger.error(f"Unsupported image dimensions: {pixels.ndim}")
        return None

    SIZE_THRESHOLD = 1200  # pixels #TODO: provide UX option to set this threshold / increase|decrease OCR accuracy
    canvas_size = min(max(pixels.shape[0], pixels.shape[1]), SIZE_THRESHOLD)
    results = ocr_reader.readtext(
        pixels,
        canvas_size=canvas_size,  # easyocr will resize pixels maintaining aspect ratio, less memory, less compute, less accurate for small text
        paragraph=False,  # paragraph=True will detect text in paragraphs
        add_margin=0.0,  # Margin around the text box
        rotation_info=[0, 90],  # Rotation angles to consider
        min_size=1,  # Minimum size of text to detect
        ycenter_ths=0.7,  # Vertical Center Threshold, to control word in column separation
        link_threshold=0.5,  # related to craft algo for linking characters into words
        width_ths=0.1,
        text_threshold=0.85,
    )

    logger.debug(f"Number of text items found: {len(results)}")

    ocr_texts: list[OCRText] = []
    for result in results:
        try:
            ocr_text = OCRText.from_easyocr_result(result, img_width, img_height)  # Use the OCRText class method
            ocr_texts.append(ocr_text)
        except ValueError as e:
            logger.warning(f"Skipping invalid OCR result: {result}. Error: {e}")
            continue  # Skip to the next result if there is an error

        if draw_boxes_and_text:
            # Draw the bounding box and the recognized word at bottom left of bounding box
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
        src=pixels.astype(np.float32) if pixels.dtype == np.float64 or pixels.dtype == np.int16 else pixels,
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
) -> bool:
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
        If text is detected and file modified with text removed, return True
        If no text is detected, file is not modified, return False

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
    logger.info(f"Remove burnt-in PHI from pixel data of: {dcm_path}")

    # Read the DICOM image file using pydicom which will perform any decompression required
    ds = dcmread(dcm_path)

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

    source_pixels_deid_stack = []
    source_pixels_changed = False

    for frame in range(no_of_frames):
        if no_of_frames > 1:
            logging.debug(f"Processing Frame {frame}...")

        pixels = pixels_stack[frame]

        if grayscale:
            # Apply any modality LUT then VOI LUT & Windowing indicated by metadata:
            # do this here, on every frame to avoid potential memory issues for large number of frames:
            pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)

        # Normalize the pixel array to the range 0-255
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

        if pi == "MONOCHROME1":  # 0 = white
            logger.debug("Convert from MONOCHROME1 to MONOCHROME2 (invert pixel values)")
            pixels = np.invert(pixels)

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
        # tuning params: add_margin=0.0, rotation_info=[90])  # , 180, 270]) #TODO: add to global config?
        results = ocr_reader.readtext(pixels)

        if not results:
            logger.debug("No text found in frame")
            continue

        logger.debug(f"Text boxes detected in frame: {len(results)}")

        # Create an 8 bit mask of pixels for in-painting
        mask = np.zeros(pixels.shape[:2], dtype=np.uint8)

        # Draw bounding boxes around each detected word
        for bbox, __, __ in results:
            # Unpack the bounding box
            (top_left, top_right, bottom_right, bottom_left) = bbox

            top_left = tuple(map(int, top_left))
            bottom_right = tuple(map(int, bottom_right))

            # Perform full anonymization, remove all detected text from image:
            _draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)

        # Remove border from mask
        mask = mask[border_size:-border_size, border_size : mask.shape[1] - border_size]
        logger.debug(f"Remove Border from mask, new mask.shape: {mask.shape}")

        # Upscale mask if downscaling was applied to source image:
        if scale_factor < 1:
            mask = resize(src=mask, dsize=(cols, rows), interpolation=INTER_LINEAR)
            logger.debug(f"Upscale mask back to original source image size, new mask.shape: {mask.shape}")

        kernel = np.ones((3, 3), np.uint8)
        dilated_mask = dilate(src=mask, kernel=kernel, iterations=1)

        # CHANGE SOURCE PIXELS:
        source_pixels_changed = True

        # Apply inpainting mask to source pixel array:
        logger.debug(
            "Change source pixels array using mask from OCR and cv2.inpaint with radius = 5 & INPAINT_TELEA (Poisson PDE) algorithm"
        )

        if bits_allocated == 16 and pixel_representation == 1:
            frame_pixels = source_pixels_decompressed_stack[frame]
            # Inpaint function only supports 8-bit, 16-bit UNSIGNED or 32-bit float 1-channel and 8-bit 3-channel input/output images
            # Mask must be 8-bit, 1 channel
            # Up Shift and Convert to UNSIGNED 16 bit:
            frame_pixels = (frame_pixels + 32768).astype(np.uint16)
            source_pixels_deid = inpaint(
                src=frame_pixels,
                inpaintMask=dilated_mask,
                inpaintRadius=5,
                flags=INPAINT_TELEA,
            )
            # Downshift and convert back to SIGNED 16 bit:
            source_pixels_deid = (source_pixels_deid - 32768).astype(np.int16)
        else:
            source_pixels_deid = inpaint(
                src=source_pixels_decompressed_stack[frame],
                inpaintMask=dilated_mask,
                inpaintRadius=5,
                flags=INPAINT_TELEA,
            )

        # if source pixels were compressed then re-compress using JPEG2000Lossless:
        if ds.file_meta.TransferSyntaxUID.is_compressed:
            logger.debug("Re-compress deidentified source frame")
            if not grayscale and pi != "RGB":
                logger.debug("Convert source frame to RGB")
                source_pixels_deid = convert_color_space(
                    arr=source_pixels_deid, current=pi, desired="RGB", per_frame=True
                )
                ds.PhotometricInterpretation = "RGB"

            source_pixels_deid = encode_array(
                arr=source_pixels_deid,
                photometric_interpretation=2 if grayscale else 1,
                use_mct=False,
            )

        source_pixels_deid_stack.append(source_pixels_deid)

    if not source_pixels_changed:
        logging.info("No changes made to pixel data")
        return False

    # Save processed stack to PixelData:
    if ds.file_meta.TransferSyntaxUID.is_compressed:
        logger.debug("Encapsulate source_pixels_deid_stack")
        ds.PixelData = encapsulate(source_pixels_deid_stack)
        ds["PixelData"].is_undefined_length = True
        ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    else:
        ds.PixelData = np.stack(source_pixels_deid_stack, axis=0).tobytes()

    ds.save_as(dcm_path)
    return True
