import logging
import pickle
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from pprint import pformat
from typing import List, Optional

import numpy as np
from cv2 import (
    COLOR_GRAY2BGR,
    COLOR_RGBA2BGR,
    INTER_AREA,
    INTER_LINEAR,
    MORPH_RECT,
    NORM_MINMAX,
    Canny,
    GaussianBlur,
    convertScaleAbs,
    createCLAHE,
    cvtColor,
    dilate,
    getStructuringElement,
    normalize,
    resize,
)
from numpy import ndarray
from numpy.typing import NDArray
from PIL import Image
from pydicom import Dataset, dcmread, multival
from pydicom.dataelem import DataElement
from pydicom.dataset import FileMetaDataset
from pydicom.errors import InvalidDicomError
from pydicom.pixel_data_handlers.util import apply_color_lut, apply_modality_lut, convert_color_space
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian

from anonymizer.controller.remove_pixel_phi import OCRText
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)

PROJECTION_FILENAME = "Projection.pkl"

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
    "YBR_PARTIAL_420",
]


@dataclass
class Projection:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    proj_images: Optional[List[Image.Image]] = field(
        default=None,
        metadata={"description": "[min,mean,max] projections multi-frame or [mean,clahe,edge] for single-frame"},
    )
    ocr: Optional[List[OCRText]] = field(default=None)

    def __repr__(self) -> str:
        return f"{pformat(asdict(self), sort_dicts=False)}"

    def __enter__(self):
        """Called when entering the 'with' statement."""
        return self  # Return the object itself

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Called when exiting the 'with' statement (or on object deletion)."""
        self.cleanup()  # Delegate cleanup to a dedicated method

    def __del__(self):
        """Called when the object is about to be garbage collected (fallback)."""
        self.cleanup()

    def cleanup(self):
        """Releases resources (image data) held by the Projection object."""
        if self.proj_images:
            logger.debug(f"Cleaning up Projection for series: {self.series_uid}")
            for img in self.proj_images:
                if img:
                    try:
                        img.close()  # Close the PIL Image, releasing resources
                    except Exception as e:
                        logger.warning(f"Error closing image: {e}")
                    img = None  # avoid errors in __del__
            self.proj_images = None  # Release the list
        # Add cleanup for 'ocr' if it holds any resources that need releasing
        self.ocr = None  # Assuming OCRText doesn't need special cleanup


class ProjectionImageSizeConfig:
    _scaling_factor = 1.0

    @classmethod
    def set_scaling_factor(cls, factor):
        if factor <= 0:
            raise ValueError("Scaling factor must be greater than zero.")
        cls._scaling_factor = factor

    @classmethod
    def get_scaling_factor(cls):
        return cls._scaling_factor

    @classmethod
    def set_scaling_factor_if_needed(cls, screen_width):
        """Sets the scaling factor only if three LARGE images don't fit within screen width."""
        large_image_width = ProjectionImageSize.LARGE.value[0]  # Original width of LARGE image
        total_large_width = large_image_width * 3  # Total original width of three LARGE images

        if total_large_width > screen_width:
            scaling_factor = screen_width / total_large_width
            cls.set_scaling_factor(scaling_factor)
            logging.info(f"Scaling factor set to {scaling_factor}")
        else:
            # If they fit, make sure the scaling factor is 1.0 (reset)
            cls.set_scaling_factor(1.0)
            logging.info("Scaling factor reset to 1.0")


class ProjectionImageSize(Enum):
    SMALL = (200, 200)
    MEDIUM = (400, 400)
    LARGE = (800, 800)

    def width(self):
        return int(self.value[0] * ProjectionImageSizeConfig.get_scaling_factor())

    def height(self):
        return int(self.value[1] * ProjectionImageSizeConfig.get_scaling_factor())


def normalize_uint8(image: ndarray):
    """Normalize and convert an image to uint8."""
    return normalize(
        src=image,
        dst=np.empty_like(image),
        alpha=0,
        beta=255,
        norm_type=NORM_MINMAX,
        dtype=-1,
        mask=None,
    ).astype(np.uint8)


def clip_and_cast_to_int(float_array: np.ndarray, target_dtype: type[np.integer]) -> np.ndarray | None:
    """
    Safely converts a float NumPy array to a target integer dtype by:
    1. Clipping values to the valid range of the target integer dtype.
    2. Casting the clipped float array to the target integer dtype (truncates decimals).

    Args:
        float_array: Input NumPy array (float dtype).
        target_dtype: The target NumPy integer dtype (e.g., np.uint16, np.int16).

    Returns:
        NumPy array with the target integer dtype, or None on error.
    """
    if not np.issubdtype(float_array.dtype, np.floating):
        logger.warning(f"Input array dtype is not float ({float_array.dtype}), attempting conversion anyway.")
    if not np.issubdtype(target_dtype, np.integer):
        logger.error(f"Target dtype {target_dtype} is not an integer type.")
        return None

    try:
        # 1. Get target dtype limits
        dtype_info = np.iinfo(target_dtype)
        min_val, max_val = dtype_info.min, dtype_info.max

        # 2. Clip the float values to the target integer range
        #    This prevents wraparound during the subsequent cast.
        clipped_float = np.clip(float_array, min_val, max_val)

        # 3. Cast the *clipped* float array to the final target integer data type.
        #    Since values are guaranteed to be in range, astype performs safe truncation.
        int_array = clipped_float.astype(target_dtype)

        # Optional: Check if clipping actually occurred (for logging/debugging)
        if np.any(float_array < min_val) or np.any(float_array > max_val):
            logger.warning(
                f"Values were clipped during conversion to {target_dtype}. "
                f"Original range [{np.min(float_array):.1f}..{np.max(float_array):.1f}], "
                f"Target range [{min_val}..{max_val}]"
            )

        return int_array
    except Exception as e:
        logger.exception(f"Error clipping and casting float array to {target_dtype}: {e}")
        return None


def cache_projection(projection: Projection, projection_file_path: Path) -> None:
    # Pickle Project object to series path for faster loading next time:
    try:
        with open(projection_file_path, "wb") as pkl_file:
            pickle.dump(projection, pkl_file)
    except Exception as e:
        logger.warning(f"Error saving Projection cache file, error: {e}")
    return


def create_projection_from_single_frame(ds: Dataset, frame: ndarray) -> Projection:
    # [mean,clahe,edge] for single-frame
    # Window using max & min values and convert to uint8
    frame_float = frame.astype(np.float32)
    min_val, max_val = np.min(frame_float), np.max(frame_float)
    ww = max_val - min_val
    ww_safe = max(1.0, float(ww))  # Avoid division by zero
    output_float = ((frame_float - min_val) / ww_safe) * 255.0
    medium_contrast = np.clip(output_float, 0, 255).astype(np.uint8)
    logger.debug(f"medium_contrast: pixels.value.range:[{medium_contrast.min(), medium_contrast.max()}]")

    # Apply CLAHE for enhanced contrast
    clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_clahe = clahe.apply(medium_contrast)

    # Apply Gaussian Blur to reduce noise
    blurred = GaussianBlur(medium_contrast, (5, 5), 0)

    # Apply Canny edge detection with adjusted thresholds
    edges = Canny(blurred, threshold1=100, threshold2=200)

    # Dilate edges to make them more pronounced
    kernel = getStructuringElement(shape=MORPH_RECT, ksize=(2, 2))
    edges_dilated = dilate(src=edges, kernel=kernel, iterations=2)

    projection_images = [
        Image.fromarray(img)
        .convert("RGB")
        .resize(
            (
                ProjectionImageSize.LARGE.value[0],
                ProjectionImageSize.LARGE.value[1],
            ),
            Image.Resampling.NEAREST,
        )
        for img in [medium_contrast, gray_clahe, edges_dilated]
    ]

    return Projection(
        patient_id=ds.PatientID,
        study_uid=ds.StudyInstanceUID,
        series_uid=ds.SeriesInstanceUID,
        series_description=ds.get("SeriesDescription", "?"),
        proj_images=projection_images,
        ocr=None,
    )


def validate_dicom_pixel_array(ds: Dataset) -> tuple[ndarray, int, int, str]:
    """
    Validate DICOM pixel array related fields exist and are consistent
    Return the tuple: (pixel data as a decompressed numpy array, rows, cols, photometric interpretation)
    Raises ValueError if any validation fails
    """
    # Mandatory fields:
    if not hasattr(ds, "is_implicit_VR"):
        raise ValueError("Invalid DICOM dataset: Missing is_implicit_VR attribute.")
    if not hasattr(ds, "is_little_endian"):
        raise ValueError("Invalid DICOM dataset: Missing is_little_endian attribute.")
    if not hasattr(ds, "file_meta"):
        raise ValueError("Invalid DICOM dataset: Missing file_meta attribute.")
    if not hasattr(ds.file_meta, "TransferSyntaxUID"):
        raise ValueError("Invalid DICOM dataset: Missing TransferSyntaxUID attribute.")
    if not hasattr(ds, "PixelData"):
        raise ValueError("Invalid DICOM dataset: Missing PixelData attribute.")

    pi = ds.get("PhotometricInterpretation", None)
    samples_per_pixel = ds.get("SamplesPerPixel", 1)
    rows = ds.get("Rows", None)
    cols = ds.get("Columns", None)
    bits_allocated = ds.get("BitsAllocated", None)
    bits_stored = ds.get("BitsStored", None)
    high_bit = ds.get("HighBit", None)
    pixel_representation = ds.get("PixelRepresentation", None)
    # Not mandatory fields:
    pixel_spacing = ds.get("PixelSpacing", None)
    no_of_frames = ds.get("NumberOfFrames", 1)  # safe to assume 1 frame if attribute not present?

    if not pi:
        raise ValueError("PhotometricInterpretation attribute missing.")

    if pi not in VALID_COLOR_SPACES:
        raise ValueError(f"Invalid Photometric Interpretation: {pi}. Support Color Spaces: {VALID_COLOR_SPACES}")

    if pi in ["MONOCHROME1", "MONOCHROME2"]:
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
        logger.debug("PixelSpacing missing")

    # DECOMPRESS source pixel array (if compressed):
    pixels = ds.pixel_array

    # Validate Pixel Array:
    # Validate the shape of the Pixel Array
    frame1 = pixels[0] if no_of_frames > 1 else pixels
    if frame1.shape[0] != rows or frame1.shape[1] != cols:
        raise ValueError(f"Pixel array shape {pixels.shape} does not match Rows and Columns ({rows}, {cols}).")
    # TODO: check EVERY frame in the pixel array? Will pydicom have done this when decompressing?

    # Validate the number of frames
    if no_of_frames > 1 and no_of_frames != pixels.shape[0]:  # 3D or 4D array
        raise ValueError(f"Number of frames {no_of_frames} does not match pixel array shape {pixels.shape[0]}.")

    # Validate the number of dimensions
    if pixels.ndim not in [2, 3, 4]:
        raise ValueError(f"Pixel array has unexpected number of dimensions: {pixels.ndim}. Expected 2, 3, or 4.")

    # Validate the number of channels
    if samples_per_pixel > 1 and samples_per_pixel != pixels.shape[-1]:
        raise ValueError(f"Samples per pixel {samples_per_pixel} does not match pixel array shape {pixels.shape[-1]}.")

    # Validate the pixel spacing
    if pixel_spacing and len(pixel_spacing) != 2:
        raise ValueError(f"Pixel spacing {pixel_spacing} is not a 2D value.")
    if pixel_spacing and pixel_spacing[0] != pixel_spacing[1]:
        logger.debug(f"Pixel spacing {pixel_spacing} is not isotropic.")

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

    # Pixel Display related attributes:
    if ds.get("WindowCenter") is not None:
        logger.debug(f"WindowCenter: {ds.WindowCenter}")
    if ds.get("WindowWidth") is not None:
        logger.debug(f"WindowWidth: {ds.WindowWidth}")
    if ds.get("RescaleSlope") is not None:
        logger.debug(f"RescaleSlope: {ds.RescaleSlope}")
    if ds.get("RescaleIntercept") is not None:
        logger.debug(f"RescaleIntercept: {ds.RescaleIntercept}")
    if ds.get("RescaleType") is not None:
        logger.debug(f"RescaleType: {ds.RescaleType}")
    if ds.get("VOILUTSequence") is not None:
        logger.debug(f"VOILUTSequence: {ds.VOILUTSequence}")
    if ds.get("ModalityLUTSequence") is not None:
        logger.debug(f"ModalityLUTSequence: {ds.ModalityLUTSequence}")
    if ds.get("VOILUTFunction") is not None:
        logger.debug(f"VOILUTFunction: {ds.VOILUTFunction}")

    # Trace the pixel relevant attributes:
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
    return pixels, rows, cols, pi.upper()


def apply_windowing(wl: float, ww: float, image_array_raw: ndarray) -> NDArray[np.uint8]:
    """
    Applies the WW (window width) & WL (window level) settings to the raw image data based on its type.
    Handles high bit-depth grayscale with true WW/WL (NumPy/clip) and
    simulates WW/WL on uint8 data using derived alpha/beta with convertScaleAbs.

    Args:
        wl, ww: Window level and width settings.
        image_array_raw: The raw input image frame (copy) as a NumPy array.

    Returns:
        A NumPy array (uint8, BGR) processed and ready for overlay rendering and OCR.
        Returns a black image on error.

    * NOTE * This is a simplification for user interactive windowing, VOI LUT data ignored.
    """
    try:
        current_dtype = image_array_raw.dtype
        current_ndim = image_array_raw.ndim
        num_channels = image_array_raw.shape[-1] if current_ndim == 3 else 1
        image_height, image_width = image_array_raw.shape[:2]
        logger.debug(f"apply_windowing: {image_array_raw.shape} dtype={current_dtype}")

        # Determine if it's high bit depth grayscale FOR THIS FRAME
        is_high_bit_gray = (current_ndim == 2 and current_dtype != np.uint8) or (
            current_ndim == 3 and num_channels == 1 and current_dtype != np.uint8
        )

        if is_high_bit_gray:
            # --- Apply True WW/WL using NumPy/clip ---
            logger.debug(f"Applying true WW/WL: WL={wl:.1f}, WW={ww:.1f}")
            img_to_process = image_array_raw.squeeze() if current_ndim == 3 else image_array_raw

            min_val = float(wl) - float(ww) / 2.0
            # max_val = float(wl) + float(ww) / 2.0
            image_float = img_to_process.astype(np.float32)
            ww_safe = max(1.0, float(ww))  # Avoid division by zero

            output_float = ((image_float - min_val) / ww_safe) * 255.0
            output_clipped = np.clip(output_float, 0, 255)
            # np.clip handles BOTH lower bound (values < min_val become < 0 after mapping -> clip to 0)
            # AND upper bound (values > max_val become > 255 after mapping -> clip to 255)
            output_uint8_gray = output_clipped.astype(np.uint8)
            # Convert final uint8 grayscale to BGR for overlay compatibility
            image_processed_bgr = cvtColor(output_uint8_gray, COLOR_GRAY2BGR)

        else:  # Assume uint8 Grayscale or Color
            # --- Apply Simulated WW/WL using Alpha/Beta for uint8 ---
            logger.debug("Applying simulated WW/WL (alpha/beta) for uint8 input")

            # Ensure input is BGR uint8
            if current_ndim == 2 and current_dtype == np.uint8:
                image_color = cvtColor(image_array_raw, COLOR_GRAY2BGR)
            elif current_ndim == 3 and image_array_raw.shape[-1] == 4 and current_dtype == np.uint8:
                image_color = cvtColor(image_array_raw, COLOR_RGBA2BGR)
            elif current_ndim == 3 and image_array_raw.shape[-1] == 3 and current_dtype == np.uint8:
                image_color = image_array_raw  # Already uint8 BGR/RGB
            else:
                logger.error(
                    f"Cannot apply alpha/beta to unexpected uint8 format: Shape={image_array_raw.shape}, Dtype={current_dtype}"
                )
                return np.zeros((image_height, image_width, 3), dtype=np.uint8)

            # Calculate derived alpha/beta locally
            ww_safe = max(1.0, ww)
            derived_alpha = 255.0 / ww_safe
            derived_beta = int(127.5 - (derived_alpha * wl))

            if derived_alpha != 1.0 or derived_beta != 0:
                image_processed_bgr = convertScaleAbs(image_color, alpha=derived_alpha, beta=derived_beta)
            else:
                image_processed_bgr = image_color

        return image_processed_bgr.astype(np.uint8)  # Ensure uint8

    except Exception as e:
        logger.exception(
            f"Error applying windowing to frame with shape {image_array_raw.shape} dtype {current_dtype}: {e}"
        )
        return np.zeros((image_height, image_width, 3), dtype=np.uint8)


def get_wl_ww(ds: Dataset) -> tuple[float, float]:
    """
    Get the window level and width from the DICOM dataset ds

    If not specified in the dataset, calculates default values based on pixels data type

    Args:
        ds: pydicom Dataset object
    Returns:
        A tuple containing the window level and width (wl, ww).

    """
    wl_from_ds = ds.get("WindowCenter", None)  # Use a different variable name initially
    ww_from_ds = ds.get("WindowWidth", None)  # Use a different variable name initially
    bits_allocated = ds.get("BitsAllocated", None)

    wl_float: float
    ww_float: float

    if wl_from_ds is None or ww_from_ds is None:
        logger.debug("WindowCenter or WindowWidth not found in DICOM dataset. Using default values.")
        if bits_allocated == 8:
            wl_float = 127.5
            ww_float = 255.0
        elif bits_allocated == 16:
            wl_float = 32768.0
            ww_float = 65535.0
        # ... (other default conditions) ...
        elif bits_allocated == 12:  # Added for completeness from original code
            wl_float = 2048.0
            ww_float = 4096.0
        elif bits_allocated == 10:  # Added for completeness from original code
            wl_float = 512.0
            ww_float = 1024.0
        elif bits_allocated == 32:  # Added for completeness from original code
            wl_float = 2147483648.0
            ww_float = 4294967295.0
        else:
            raise ValueError(f"Unsupported BitsAllocated value: {bits_allocated}")
        return wl_float, ww_float  # Return defaults directly

    # Handle single vs. multi-value
    if isinstance(wl_from_ds, multival.MultiValue):
        wl_float = float(wl_from_ds[0]) if len(wl_from_ds) > 0 else 0.0  # Provide a default if empty multivalue
    else:
        wl_float = float(wl_from_ds)

    if isinstance(ww_from_ds, multival.MultiValue):
        ww_float = float(ww_from_ds[0]) if len(ww_from_ds) > 0 else 1.0  # Provide a default if empty multivalue
    else:
        ww_float = float(ww_from_ds)

    # Ensure Window Width is positive
    if ww_float < 1.0:
        logger.warning(
            f"DICOM WindowWidth ({ww_from_ds}) is less than 1. Setting to 1."  # Log original value
        )
        ww_float = 1.0  # Correct ww_float itself

    return wl_float, ww_float


def load_series_frames(series_path: Path, border_px: int | None = 20) -> tuple[Dataset, ndarray]:
    """
    Loads and processes DICOM series frames from a directory, resizing to match
    the first frame's dimensions.

    Preserves original dynamic range and data type for MONOCHROME images after
    applying Modality LUT and MONOCHROME1 inversion.
    Converts standard Color images (RGB, PALETTE_COLOR, YBR*) to uint8 RGB.

    Args:
        series_path: Path object for the directory containing DICOM files.

    Returns:
        A tuple containing:
            - The pydicom Dataset from the first file (for metadata).
            - A single NumPy array containing all processed and resized frames,
              stacked along the first axis.
              Dtype will be consitent for modality.
              For grayscale, if modality LUT applied rescale operation then conversion to float64 will occur
              Shape: (num_frames, height, width) or (num_frames, height, width, 3).

    Raises:
        ValueError: If no DICOM files are found, or if essential DICOM tags
                    are missing or invalid during processing, or if frames
                    cannot be consistently processed or stacked.
        FileNotFoundError: If the series_path does not exist.
        PermissionError: If read permissions are denied.
    """
    if not series_path.is_dir():
        raise FileNotFoundError(f"Provided path is not a directory: {series_path}")

    try:
        dcm_paths: list[Path] = sorted(get_dcm_files(series_path))
    except PermissionError as e:
        logger.error(f"Permission denied accessing {series_path}: {e}")
        raise
    except Exception as e:  # Catch other potential OS errors
        logger.error(f"Error listing files in {series_path}: {e}")
        raise ValueError(f"Could not list files in directory: {series_path}") from e

    if not dcm_paths:
        raise ValueError(f"No DICOM files found in {series_path}")

    processed_frames: list[ndarray] = []
    ds1: Dataset | None = None  # To store the first dataset
    target_size: tuple[int, int] | None = None  # (height, width)
    series_pi: str = ""
    # --- Process the first file to set the standard ---
    try:
        ds1 = dcmread(str(dcm_paths[0]), force=True)
        # Validate first file AND get initial parameters
        raw_pixels, rows, cols, pi = validate_dicom_pixel_array(ds1)
        target_size = (rows, cols)
        series_pi = pi.upper()
        logger.info(
            f"Series detected as {series_pi} with target size {target_size} and pixels data type {raw_pixels.dtype}"
        )
    except (InvalidDicomError, ValueError, AttributeError, KeyError) as e:
        # Catch errors from reading or validating the *first* file
        raise ValueError(f"Error validating or reading essential tags from first file {dcm_paths[0]}: {e}") from e
    except Exception as e:
        raise ValueError(f"Unexpected error reading first file {dcm_paths[0]}: {e}") from e

    # --- Loop through series files ---
    for dcm_path in dcm_paths:
        try:
            # Don't re-read and validate first file:
            if processed_frames != []:
                ds = dcmread(str(dcm_path), force=True)
                raw_pixels, rows, cols, pi = validate_dicom_pixel_array(ds)
            else:
                ds = ds1

            # --- Series PI Consistency Check ---
            if pi != series_pi:
                logger.warning(f"Inconsistent PI in {dcm_path} ({pi}) vs first file ({series_pi}). Skipping file.")
                continue

            # Check dimensions against target_size even before processing
            if (rows, cols) != target_size:
                logger.warning(
                    f"Inconsistent dimensions in {dcm_path} "
                    f"({rows},{cols}) vs target ({target_size[0]},{target_size[1]}). "
                    f"Frame will be resized after processing."
                )

            num_frames = ds.get("NumberOfFrames", 1)
            is_multi_frame_source = raw_pixels.ndim > 2 and num_frames > 1
            if is_multi_frame_source and raw_pixels.shape[0] != num_frames:
                logger.warning(
                    f"NumberOfFrames tag ({num_frames}) mismatch with pixel array "
                    f"shape ({raw_pixels.shape[0]}) in {dcm_path}. Using array shape."
                )
                num_frames = raw_pixels.shape[0]

            # --- Process each frame ---
            for frame_idx in range(num_frames):
                current_frame_pixels = raw_pixels[frame_idx] if is_multi_frame_source else raw_pixels
                processed_frame: ndarray | None = None

                # Process based on the *series* interpretation determined from the first file
                match series_pi:
                    case "MONOCHROME1" | "MONOCHROME2":
                        # Conversion to float64 may occur from rescale operation in applying modality LUT
                        modality_pixels = apply_modality_lut(current_frame_pixels, ds)
                        if modality_pixels.dtype != current_frame_pixels.dtype:
                            logger.debug(f"Modality LUT changed pixel data type to {modality_pixels.dtype}")
                        if series_pi == "MONOCHROME1":
                            try:
                                max_val = np.max(modality_pixels)
                                processed_frame = max_val - modality_pixels
                            except Exception:
                                processed_frame = modality_pixels
                                logger.warning(
                                    f"Could not invert MONOCHROME1 frame {frame_idx} in {dcm_path}", exc_info=True
                                )
                        else:
                            processed_frame = modality_pixels
                        if processed_frame is not None and processed_frame.ndim == 3 and processed_frame.shape[-1] == 1:
                            processed_frame = processed_frame.squeeze(axis=-1)

                    case "PALETTE COLOR":
                        processed_frame = apply_color_lut(current_frame_pixels, ds)
                        if processed_frame.shape[-1] == 4:
                            processed_frame = processed_frame[..., :3]
                        # if processed_frame.dtype != np.uint8:
                        #     processed_frame = normalize_uint8(processed_frame)

                    case "YBR_FULL" | "YBR_FULL_422":
                        processed_frame = convert_color_space(current_frame_pixels, series_pi, "RGB")
                        if (
                            processed_frame.dtype != np.uint8
                            or processed_frame.ndim != 3
                            or processed_frame.shape[-1] != 3
                        ):
                            raise ValueError(f"Color space conversion failed for {dcm_path} frame {frame_idx}.")

                    case "RGB":
                        processed_frame = current_frame_pixels

                # --- Resize frame AFTER processing if necessary ---
                if processed_frame is not None:
                    # Resize to target size if necessary
                    current_h, current_w = processed_frame.shape[:2]
                    target_h, target_w = target_size
                    if current_h != target_h or current_w != target_w:
                        logger.warning(
                            f"Resizing frame {len(processed_frames)} from ({current_h},{current_w}) "
                            f"to target ({target_h},{target_w}) in {dcm_path}"
                        )
                        interpolation = INTER_AREA if (current_h > target_h or current_w > target_w) else INTER_LINEAR
                        processed_frame = resize(processed_frame, (target_w, target_h), interpolation=interpolation)

                    processed_frames.append(processed_frame)
                else:
                    raise RuntimeError(f"CRITICAL Error: Frame {frame_idx} from {dcm_path} failed to process.")

        except (InvalidDicomError, ValueError) as e:
            logger.error(f"Invalid DICOM or processing error skipped: {dcm_path} - {e}")
            continue  # Skip this file
        except Exception as e:
            logger.error(f"Unexpected error processing file {dcm_path}: {e}")
            raise ValueError(f"Error processing file in series: {dcm_path}") from e

    if not processed_frames:
        raise ValueError(f"Could not load any valid frames from series: {series_path}")

    # --- Stack the list of consistently typed and sized frames ---
    try:
        all_series_frames_stacked = np.stack(processed_frames, axis=0)
    except ValueError as e:
        logger.error(f"Error stacking frames: {e}. Check frame dimensions consistency.")
        for i, frame in enumerate(processed_frames):
            logger.error(f"Frame {i} shape: {frame.shape}, dtype: {frame.dtype}")
        raise ValueError("Inconsistent frame dimensions prevent stacking.") from e

    logger.info(
        f"Final stacked array - Shape: {all_series_frames_stacked.shape}, Dtype: {all_series_frames_stacked.dtype}"
    )

    return ds1, all_series_frames_stacked


def save_series_frames(original_series_path: Path, processed_frames: np.ndarray, reference_ds: Dataset) -> bool:
    """
    Saves processed frames back by OVERWRITING original DICOM files.
    Converts processed float grayscale data safely to target integer type.
    Sets metadata based on the actual data type being saved. Uses Explicit VR LE.

    Args:
        original_series_path: Path to the directory containing the original DICOM files.
        processed_frames: The NumPy array containing all frames to be saved.
        reference_ds: The pydicom Dataset from the first file of the original series.

    Returns:
        True if saving was successful for all files, otherwise False.
    """
    logger.info(f"Starting to save processed frames, OVERWRITING files in: {original_series_path}")
    if processed_frames is None or processed_frames.size == 0:
        logger.error("No processed frames provided to save.")
        return False
    if not original_series_path.is_dir():
        logger.error(f"Original series path is not a directory: {original_series_path}")
        return False

    # --- 1. Determine Original File Structure ---
    try:
        original_dcm_paths: list[Path] = sorted(get_dcm_files(original_series_path))
        if not original_dcm_paths:
            logger.error(f"No original DICOM files found in {original_series_path}.")
            return False

        file_frame_counts: list[tuple[Path, int]] = []
        total_frames_in_files = 0
        for p in original_dcm_paths:
            try:
                ds_meta = dcmread(str(p), stop_before_pixels=True, force=True)
                frames_in_file = ds_meta.get("NumberOfFrames", 1)
                file_frame_counts.append((p, frames_in_file))
                total_frames_in_files += frames_in_file
            except Exception as e:
                logger.warning(f"Could not read frame count from {p}, skipping file: {e}")
                continue

        if total_frames_in_files == 0:
            logger.error("Could not determine frame counts from any original DICOM file.")
            return False
        if total_frames_in_files != processed_frames.shape[0]:
            logger.error(
                f"Mismatch: Processed frames ({processed_frames.shape[0]}) != "
                f"Total frames in original files ({total_frames_in_files}). Cannot save."
            )
            return False
    except Exception as e:
        logger.error(f"Error analyzing original series structure: {e}")
        return False

    # --- 2. Determine Series Photometric Interpretation & Target Stored Dtype ---
    try:
        series_pi = reference_ds.PhotometricInterpretation.upper()
        bits_allocated = reference_ds.get("BitsAllocated", 16 if series_pi.startswith("MONO") else 8)
        pixel_rep = reference_ds.get("PixelRepresentation", 0)  # 0=unsigned, 1=signed
        if bits_allocated == 16:
            target_dtype = np.uint16 if pixel_rep == 0 else np.int16
        elif bits_allocated == 8:
            target_dtype = np.uint8
        else:
            raise ValueError(f"Unsupported BitsAllocated: {bits_allocated}")
        logger.info(f"Saving series based on original PI: {series_pi} with target stored dtype {target_dtype}")
    except Exception as e:
        logger.error(f"Could not determine series type/dtype: {e}")
        return False

    # --- 3. Iterate, Process, and Save (Overwrite) ---
    frame_ndx = 0
    success = True
    for original_path, num_frames_in_file in file_frame_counts:
        logger.info(f"Processing {num_frames_in_file} frame(s) to overwrite -> {original_path.name}")
        try:
            ds_orig = dcmread(str(original_path), stop_before_pixels=True, force=True)
            ds_save = ds_orig.copy()

            frame_chunk = processed_frames[frame_ndx : frame_ndx + num_frames_in_file]
            if frame_chunk.shape[0] != num_frames_in_file:
                logger.error(f"Frame count mismatch for {original_path}. Skipping.")
                success = False
                frame_ndx += num_frames_in_file
                continue

            final_pixel_data = frame_chunk

            if series_pi in ("MONOCHROME1", "MONOCHROME2"):
                if np.issubdtype(final_pixel_data.dtype, np.floating):
                    logger.debug(
                        f"Converting float pixel data via clipping to {target_dtype} for {original_path.name}..."
                    )
                    converted_pixels = clip_and_cast_to_int(final_pixel_data, target_dtype)
                    if converted_pixels is None:
                        logger.error(f"Failed conversion to {target_dtype} for {original_path.name}. Skipping.")
                        success = False
                        frame_ndx += num_frames_in_file
                        continue
                    final_pixel_data = converted_pixels
                    ds_save.RescaleSlope = 1
                    ds_save.RescaleIntercept = 0
                elif final_pixel_data.dtype != target_dtype:
                    logger.warning(f"Casting input frame dtype {final_pixel_data.dtype} to target {target_dtype}.")
                    final_pixel_data = final_pixel_data.astype(target_dtype)
                    ds_save.RescaleSlope = 1
                    ds_save.RescaleIntercept = 0

                # --- Update Metadata for Monochrome ---
                ds_save.PhotometricInterpretation = "MONOCHROME2"
                ds_save.SamplesPerPixel = 1

                if "PlanarConfiguration" in ds_save:
                    del ds_save.PlanarConfiguration

                # Set metadata based on the final_pixel_data's dtype
                saved_dtype = final_pixel_data.dtype
                if saved_dtype == np.uint16:
                    ds_save.PixelRepresentation = 0
                    bits = 16
                elif saved_dtype == np.int16:
                    ds_save.PixelRepresentation = 1
                    bits = 16
                elif saved_dtype == np.uint8:
                    ds_save.PixelRepresentation = 0
                    bits = 8
                else:
                    # This should not happen if conversion/casting worked
                    raise ValueError(f"Unsupported final dtype for monochrome save: {saved_dtype}")

                ds_save.BitsAllocated = bits
                ds_save.BitsStored = bits
                ds_save.HighBit = bits - 1

            elif series_pi in ("RGB", "YBR_FULL", "YBR_FULL_422", "PALETTE COLOR"):
                if final_pixel_data.dtype != np.uint8 or final_pixel_data.ndim != 4 or final_pixel_data.shape[-1] != 3:
                    logger.error(
                        f"Expected uint8 RGB data for {original_path.name}, got {final_pixel_data.shape} dtype {final_pixel_data.dtype}. Skipping."
                    )
                    success = False
                    frame_ndx += num_frames_in_file
                    continue
                # Update Metadata for RGB
                ds_save.PhotometricInterpretation = "RGB"
                ds_save.SamplesPerPixel = 3
                ds_save.PlanarConfiguration = 0
                ds_save.BitsAllocated = 8
                ds_save.BitsStored = 8
                ds_save.HighBit = 7
                ds_save.PixelRepresentation = 0
                for tag in ["RescaleSlope", "RescaleIntercept", "VOILUTSequence", "WindowCenter", "WindowWidth"]:
                    if tag in ds_save:
                        del ds_save[tag]
            else:
                logger.error(f"Cannot save unsupported PI: {series_pi} for {original_path.name}")
                success = False
                frame_ndx += num_frames_in_file
                continue

            # Update Pixel Data and Frame Count
            final_pixel_data_to_save = final_pixel_data.squeeze(axis=0) if num_frames_in_file == 1 else final_pixel_data
            if final_pixel_data_to_save.dtype.byteorder not in ("=", "<"):
                final_pixel_data_to_save = final_pixel_data_to_save.byteswap().newbyteorder("<")

            # EXPLICITLY SET VR for PixelData because of using ExplicitVRLittleEndian TS
            pixel_data_tag = Tag(0x7FE0, 0x0010)
            # Determine VR based on BitsAllocated set above
            if ds_save.BitsAllocated == 16:
                pixel_vr = "OW"
            elif ds_save.BitsAllocated == 8:
                pixel_vr = "OB"
            # Create/Update the DataElement with the correct VR and Value
            ds_save[pixel_data_tag] = DataElement(
                tag=pixel_data_tag, VR=pixel_vr, value=final_pixel_data_to_save.tobytes()
            )

            # Use shape of data being saved for Rows/Columns metadata
            if final_pixel_data_to_save.ndim == 2:
                ds_save.Rows, ds_save.Columns = final_pixel_data_to_save.shape
            elif final_pixel_data_to_save.ndim >= 3:
                ds_save.Rows, ds_save.Columns = final_pixel_data_to_save.shape[-2], final_pixel_data_to_save.shape[-1]
            else:
                logger.error(f"Unexpected shape after squeeze: {final_pixel_data_to_save.shape}")
                success = False
                frame_ndx += num_frames_in_file
                continue

            if num_frames_in_file > 1:
                ds_save.NumberOfFrames = num_frames_in_file
            elif "NumberOfFrames" in ds_save:
                del ds_save.NumberOfFrames

            # --- Set File Meta Information ---
            # Copy original meta info first
            ds_save.file_meta = FileMetaDataset(ds_orig.file_meta)

            # Set preferred uncompressed transfer syntax: Explicit VR Little Endian
            ds_save.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds_save.is_little_endian = True
            ds_save.is_implicit_VR = False  # Explicit VR

            # Save the File (Overwrite Original)
            ds_save.save_as(original_path, write_like_original=False)
            logger.info(f"Successfully overwrote {original_path.name}")

            frame_ndx += num_frames_in_file

        except Exception as e:
            logger.exception(f"Failed to process or save file {original_path.name}: {e}")
            success = False
            frame_ndx += num_frames_in_file  # Ensure index advances

    if frame_ndx != processed_frames.shape[0]:
        logger.error(f"Frame processing index mismatch, frames: {frame_ndx} expected: {processed_frames.shape[0]}.")
        success = False

    # --- 4. Remove Projection File if it exists for series ---
    projection_file_path = original_series_path / PROJECTION_FILENAME
    if projection_file_path.exists() and projection_file_path.is_file():
        try:
            projection_file_path.unlink()
            logger.info(f"Deleted existing projection file: {projection_file_path}")
        except Exception as e:  # Catch any errors during deletion
            logger.warning(f"Error deleting projection file {projection_file_path}: {e}")

    logger.info(f"Finished saving series to {original_series_path}. Overall success: {success}")
    return success


def create_projection_from_series(series_path: Path) -> Projection:
    """
    Check series_path for "Projection.pkl" file.
    If present, load and return the corresponding Projection object
    otherwise create Projection object by loading and processing full series
    """
    projection_file_path = series_path / PROJECTION_FILENAME
    if projection_file_path.exists() and projection_file_path.is_file():
        # projection_file_path.unlink()
        try:
            with open(projection_file_path, "rb") as pkl_file:
                projection = pickle.load(pkl_file)
            logger.debug(f"Projection cache: {projection_file_path}")
            return projection
        except Exception as e:
            logger.warning(f"Error loading Projection from {projection_file_path}: {e}")
            projection_file_path.unlink()  # Delete the projection file

    logger.debug(f"Create Projection from {series_path.name}")

    ds1, all_series_frames = load_series_frames(series_path)

    # Handle single frame in series:
    if all_series_frames.shape[0] == 1:
        projection = create_projection_from_single_frame(ds1, all_series_frames[0])
        cache_projection(projection, projection_file_path)
        del ds1
        return projection

    logger.info(f"all_series_frames read, frames.shape= {all_series_frames.shape}")

    # Compute min, mean, and max projections
    min_projection = np.min(all_series_frames, axis=0)
    mean_projection = np.mean(all_series_frames, axis=0).astype(all_series_frames.dtype)
    max_projection = np.max(all_series_frames, axis=0)

    wl, ww = get_wl_ww(ds1)

    projection_images = [
        Image.fromarray(apply_windowing(wl, ww, img)).resize(
            (
                ProjectionImageSize.LARGE.value[0],
                ProjectionImageSize.LARGE.value[1],
            ),
            Image.Resampling.NEAREST,
        )
        for img in [min_projection, mean_projection, max_projection]
    ]

    projection = Projection(
        patient_id=ds1.PatientID,
        study_uid=ds1.StudyInstanceUID,
        series_uid=ds1.SeriesInstanceUID,
        series_description=ds1.get("SeriesDescription", "?"),
        proj_images=projection_images,
        ocr=None,
    )

    cache_projection(projection, projection_file_path)

    return projection
