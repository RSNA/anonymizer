import logging
import pickle
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from pprint import pformat
from typing import List, Optional

import numpy as np
from cv2 import (
    INTER_AREA,
    INTER_LINEAR,
    MORPH_RECT,
    NORM_MINMAX,
    Canny,
    GaussianBlur,
    createCLAHE,
    dilate,
    getStructuringElement,
    normalize,
    resize,
)
from PIL import Image
from pydicom import Dataset, dcmread
from pydicom.errors import InvalidDicomError
from pydicom.pixel_data_handlers.util import apply_color_lut, apply_modality_lut, apply_voi_lut, convert_color_space

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


def normalize_uint8(image: np.ndarray):
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


def cache_projection(projection: Projection, projection_file_path: Path) -> None:
    # Pickle Project object to series path for faster loading next time:
    try:
        with open(projection_file_path, "wb") as pkl_file:
            pickle.dump(projection, pkl_file)
    except Exception as e:
        logger.warning(f"Error saving Projection cache file, error: {e}")
    return


# def load_single_frame(ds: Dataset) -> np.ndarray:
#     pi = ds.get("PhotometricInterpretation", None)
#     if pi is None:
#         raise ValueError("No PhotometricInterpretation ")

#     pixels = ds.pixel_array
#     logger.debug(f"pixels.value.range:[{pixels.min(), pixels.max()}]")

#     if pi in ["MONOCHROME1", "MONOCHROME2"]:
#         pixels = apply_modality_lut(pixels, ds)
#         logger.debug(f"after modality_lut: pixels.value.range:[{pixels.min(), pixels.max()}]")
#         pixels = apply_voi_lut(pixels, ds)
#         logger.debug(f"after voi_lut: pixels.value.range:[{pixels.min(), pixels.max()}]")
#         if pi == "MONOCHROME1":
#             logger.info("Convert from MONOCHROME1 to MONOCHROME2")
#             pixels = np.max(pixels) - pixels
#             logger.debug(f"after inversion pixels.value.range:[{pixels.min(), pixels.max()}]")

#     # elif pi == "RGB":
#     #     # Convert Single Frame RGB to Grayscale
#     #     pixels = cvtColor(pixels, COLOR_RGB2GRAY)
#     #     logger.debug(f"after RGB2GRAY: pixels.value.range:[{pixels.min(), pixels.max()}]")

#     if ds.BitsAllocated != 8:
#         pixels = normalize_uint8(pixels)
#         logger.debug(f"After normalization: pixels.value.range:[{pixels.min(), pixels.max()}]")

#     return pixels


def create_projection_from_single_frame(ds: Dataset, frame: np.ndarray) -> Projection:
    # [mean,clahe,edge] for single-frame
    medium_contrast = frame

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


def validate_dicom_pixel_array(ds: Dataset) -> tuple[np.ndarray, int, int, str]:
    """
    Validate DICOM pixel array related fields exist and are consistent
    Return the pixel data as a decompressed numpy array
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


def load_series_frames(series_path: Path) -> tuple[Dataset, np.ndarray]:
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
              stacked along the first axis. Dtype will be consistent for the series
              (e.g., int16 for grayscale, uint8 for color).
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

    processed_frames: list[np.ndarray] = []
    ds1: Dataset | None = None  # To store the first dataset
    target_size: tuple[int, int] | None = None  # (height, width)
    series_pi: str = ""
    # --- Process the first file to set the standard ---
    try:
        ds1 = dcmread(str(dcm_paths[0]), force=True)
        # Validate first file AND get initial parameters
        __, rows1, cols1, pi1 = validate_dicom_pixel_array(ds1)
        target_size = (rows1, cols1)
        series_pi = pi1.upper()  # Use upper for matching
        logger.info(f"Series detected as {series_pi} with target size {target_size}")
    except (InvalidDicomError, ValueError, AttributeError, KeyError) as e:
        # Catch errors from reading or validating the *first* file
        raise ValueError(f"Error validating or reading essential tags from first file {dcm_paths[0]}: {e}") from e
    except Exception as e:
        raise ValueError(f"Unexpected error reading first file {dcm_paths[0]}: {e}") from e

    # --- Loop through series files ---
    for dcm_path in dcm_paths:
        try:
            ds = dcmread(str(dcm_path), force=True) if processed_frames != [] else ds1

            # Validate and get data for the current file
            raw_pixels, current_rows, current_cols, current_pi = validate_dicom_pixel_array(ds)

            # --- Series PI Consistency Check ---
            if current_pi != series_pi:
                logger.warning(
                    f"Inconsistent PI in {dcm_path} ({current_pi}) vs first file ({series_pi}). Skipping file."
                )
                continue

            # Check dimensions against target_size even before processing
            if (current_rows, current_cols) != target_size:
                logger.warning(
                    f"Inconsistent dimensions in {dcm_path} "
                    f"({current_rows},{current_cols}) vs target ({target_size[0]},{target_size[1]}). "
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
                processed_frame: np.ndarray | None = None

                # Process based on the *series* interpretation determined from the first file
                match series_pi:
                    case "MONOCHROME1" | "MONOCHROME2":
                        modality_pixels = apply_modality_lut(current_frame_pixels, ds)
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
                        if processed_frame.dtype != np.uint8:
                            processed_frame = normalize_uint8(processed_frame)

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
                    logger.error(f"CRITICAL Error: Frame {frame_idx} from {dcm_path} failed to process.")

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


# def load_series_frames_ex(series_path) -> tuple[Dataset, np.ndarray]:
#     """
#     Load and process the series
#     Return numpy array with 4 dimensions: [frame, height, width, 3]
#     Normalised uint8 values
#     Raises ValueError:
#             If no DICOM files found
#             If DICOM header fields are inconsistent for pixel array in any DICOM file in series
#     """
#     # TODO: test a series (ultrasound) comprising multiple dcm files each with multiple frames

#     dcm_paths: list[Path] = sorted(get_dcm_files(series_path))

#     if len(dcm_paths) == 0:
#         raise ValueError(f"No DICOM files found in {series_path}")

#     ds1 = dcmread(dcm_paths[0])
#     pi = ds1.get("PhotometricInterpretation", None)
#     if pi is None:
#         raise ValueError("No PhotometricInterpretation")

#     grayscale = pi in ["MONOCHROME1", "MONOCHROME2"]
#     target_size = (ds1.get("Rows", None), ds1.get("Columns", None))
#     all_series_frames = []

#     # Iterate through all files in the series:
#     for dcm_path in dcm_paths:
#         ds = dcmread(dcm_path) if all_series_frames else ds1

#         pixels = validate_dicom_pixel_array(ds)  # Could be 2D, 3D, or 4D

#         if grayscale:
#             # Apply modality LUT and then VOI LUT:
#             pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)
#             # TODO: handle saturation, eg. see James^Michael CXR RescaleIntercept, RescaleSlope

#             # Convert from Monochrome1 to MonoChrome2:
#             # TODO: check POOLE^OLIVIA
#             if pi == "MONOCHROME1":
#                 logger.debug("Convert from MONOCHROME1 to MONOCHROME, inverting pixel values")
#                 pixels = np.invert(pixels)  # .astype(np.uint16))

#             # Convert Grayscale to 3 channel/RGB
#             pixels = np.stack([pixels] * 3, axis=-1)

#         elif pi == "PALETTE COLOR" and "PaletteColorLookupTableData" in ds:
#             # Apply Color LUT if photometric interpretation is PALETTE COLOR
#             logger.debug("Applying Palette Color Lookup Table")
#             pixels = apply_color_lut(pixels, ds)  # will return RGB or RGBA

#         elif pi in ["YBR_FULL", "YBR_FULL_422"]:
#             # Convert color space if needed (e.g., from YBR to RGB)
#             logger.debug(f"Convert color space from {pi} to RGB")
#             pixels = convert_color_space(arr=pixels, current=pi, desired="RGB", per_frame=True)

#         if pixels.ndim == 4:  # Multi-frame DICOM (already a stack of frames)
#             all_series_frames.append(pixels)

#         elif pixels.ndim == 3:  # Single Frame
#             if pixels.shape[:2] != target_size:  # Ensure EACH pixel frame has size as defined by rows/cols in header
#                 pixels = resize(pixels, (target_size[1], target_size[0]), interpolation=INTER_AREA)

#             # Add Frame dimension as first axis.  This makes it a (1, H, W, C) array.
#             all_series_frames.append(np.expand_dims(pixels, axis=0))

#         else:
#             logger.error(f"Unexpected pixel array shape: {pixels.shape}, skip: {dcm_path}")

#         del ds

#     # Convert all frames into one list, concatenate along the frame dimension (axis=0)
#     # TODO: move normalisation to ImageViewer, maintain full dynamic range in all_series_frames
#     # Normalize and convert to uint8:
#     all_series_frames = normalize_uint8(np.concatenate(all_series_frames, axis=0))

#     return ds1, all_series_frames


def create_projection_from_series(series_path: Path) -> Projection:
    """
    Check series_path for "Projection.pkl" file.
    If present, load and return the corresponding Projection object
    otherwise create Projection object by loading and processing full series
    """
    projection_file_path = series_path / PROJECTION_FILENAME
    if projection_file_path.exists() and projection_file_path.is_file():
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
    mean_projection = np.mean(all_series_frames, axis=0).astype(np.uint8)
    max_projection = np.max(all_series_frames, axis=0)

    projection_images = [
        Image.fromarray(img).resize(
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
