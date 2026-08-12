"""DICOM series load/save and series_buffer I/O."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from cv2 import INTER_AREA, INTER_LINEAR, resize
from numpy import ndarray
from pydicom import Dataset, dcmread
from pydicom.dataelem import DataElement
from pydicom.dataset import FileMetaDataset
from pydicom.errors import InvalidDicomError
from pydicom.pixel_data_handlers.util import (
    apply_color_lut,
    apply_modality_lut,
    convert_color_space,
)
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian

from anonymizer.controller.tseg.dicom_geometry import (
    list_dicom_paths,
    stackable_dicom_paths,
)
from anonymizer.utils.dicom import SUPPORTED_PHOTOMETRIC_INTERPRETATIONS, get_wl_ww
from anonymizer.utils.memory import log_process_memory
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)

SERIES_VIEW_PROJECTION_COUNT = 3


@dataclass(frozen=True)
class LoadedSeries:
    """In-memory anatomical frame stack from load_series_frames (one row per slice file)."""

    metadata: Dataset
    frames: np.ndarray
    slice_paths: tuple[Path, ...]
    default_window: tuple[float, float]

    @property
    def is_single_frame(self) -> bool:
        return self.frames.shape[0] == 1

    def series_view_stack(self) -> np.ndarray:
        if self.is_single_frame:
            return self.frames
        slice_count = self.frames.shape[0]
        prefix = SERIES_VIEW_PROJECTION_COUNT
        frames = np.empty(
            (slice_count + prefix,) + self.frames.shape[1:], dtype=self.frames.dtype
        )
        np.copyto(frames[prefix:], self.frames)
        proj_min = np.copy(frames[prefix])
        proj_max = np.copy(frames[prefix])
        proj_sum = frames[prefix].astype(np.float32, copy=True)
        for slice_index in range(prefix + 1, frames.shape[0]):
            slice_frame = frames[slice_index]
            np.minimum(proj_min, slice_frame, out=proj_min)
            np.maximum(proj_max, slice_frame, out=proj_max)
            proj_sum += slice_frame
        frames[0] = proj_min
        frames[2] = proj_max
        frames[1] = (proj_sum / slice_count).astype(frames.dtype, copy=False)
        return frames

    def series_view_slices_from_stack(self, viewer_stack: np.ndarray) -> np.ndarray:
        if self.is_single_frame:
            return viewer_stack
        return viewer_stack[SERIES_VIEW_PROJECTION_COUNT:]


def load_series_frames(series_path: Path) -> LoadedSeries:
    """Load a DICOM series directory (anatomical frames only, no projections)."""
    logger.info("load_series_frames: %s", series_path)
    metadata, frames, slice_paths = _load_series_frames(series_path)
    default_window = get_wl_ww(metadata)
    return LoadedSeries(
        metadata=metadata,
        frames=frames,
        slice_paths=slice_paths,
        default_window=default_window,
    )


__all__ = [
    "LoadedSeries",
    "SERIES_VIEW_PROJECTION_COUNT",
    "apply_series_description",
    "load_series_frames",
    "ordered_series_dcm_paths",
    "save_series_frames",
    "series_buffer_monochrome_to_stored",
    "stored_monochrome_to_series_buffer",
]


def clip_and_cast_to_int(
    float_array: np.ndarray, target_dtype: type[np.integer]
) -> np.ndarray | None:
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
        logger.warning(
            f"Input array dtype is not float ({float_array.dtype}), attempting conversion anyway."
        )
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
        logger.exception(
            f"Error clipping and casting float array to {target_dtype}: {e}"
        )
        return None


def ordered_series_dcm_paths(series_path: Path) -> list[Path]:
    """
    Return DICOM paths in the same order as ``load_series_frames`` / face blur.

    Uses ``stackable_dicom_paths`` (IPP stack order). Falls back to direct children
    of ``series_path`` sorted by ``InstanceNumber`` — never recursive subdirectories.
    """
    series_path = Path(series_path).resolve()
    try:
        return stackable_dicom_paths(series_path)
    except ValueError as exc:
        logger.warning(
            "Falling back to legacy DICOM listing for save in %s: %s", series_path, exc
        )
        try:
            dcm_paths = list(list_dicom_paths(series_path))
        except ValueError:
            dcm_paths = sorted(
                path
                for path in series_path.iterdir()
                if path.is_file() and path.suffix.lower() in {".dcm", ".dicom"}
            )
        if not dcm_paths:
            raise ValueError(f"No DICOM files found in {series_path}") from exc

        def get_instance_number(path: Path) -> int:
            try:
                ds_header = dcmread(str(path), stop_before_pixels=True, force=True)
                return int(ds_header.get("InstanceNumber", 999999))
            except (ValueError, TypeError, InvalidDicomError):
                return 999999

        dcm_paths.sort(key=get_instance_number)
        return dcm_paths


def _stored_integer_dtype(ds: Dataset) -> type[np.integer]:
    bits_allocated = int(getattr(ds, "BitsAllocated", 16) or 16)
    pixel_rep = int(getattr(ds, "PixelRepresentation", 0) or 0)
    if bits_allocated == 16:
        return np.int16 if pixel_rep == 1 else np.uint16
    if bits_allocated == 8:
        return np.uint8
    raise ValueError(f"Unsupported BitsAllocated: {bits_allocated}")


def _prepare_monochrome_stored_pixels(
    frame_data: np.ndarray, ds_orig: Dataset
) -> np.ndarray:
    """
    Convert processed frames to stored pixels using ``ds_orig`` rescale and integer encoding.

    Float input is treated as post-modality-LUT values (same as ``load_series_frames`` output).
    Integer input is clipped/cast to the source slice dtype without changing rescale semantics.
    """
    target_dtype = _stored_integer_dtype(ds_orig)
    slope = float(getattr(ds_orig, "RescaleSlope", 1) or 1)
    intercept = float(getattr(ds_orig, "RescaleIntercept", 0) or 0)
    if slope in (0, 0.0):
        slope = 1.0
    dtype_info = np.iinfo(target_dtype)

    def _one_frame(frame: np.ndarray) -> np.ndarray:
        if np.issubdtype(frame.dtype, np.floating):
            stored = (frame - intercept) / slope
            return np.clip(np.rint(stored), dtype_info.min, dtype_info.max).astype(
                target_dtype
            )
        if frame.dtype != target_dtype:
            return np.clip(frame, dtype_info.min, dtype_info.max).astype(target_dtype)
        return frame

    if frame_data.ndim == 2:
        return _one_frame(frame_data)
    return np.stack(
        [_one_frame(frame_data[index]) for index in range(frame_data.shape[0])], axis=0
    )


def _viewer_chunk_to_stored_pixels(
    viewer_chunk: np.ndarray,
    ds_orig: Dataset,
    *,
    original_stored_pixels: np.ndarray,
) -> np.ndarray:
    """Map Series View float frames back to stored DICOM pixels (incl. MONOCHROME1 invert)."""
    num_frames = int(viewer_chunk.shape[0]) if viewer_chunk.ndim == 3 else 1
    multi_source = original_stored_pixels.ndim > 2 and num_frames > 1

    stored_frames: list[np.ndarray] = []
    for frame_idx in range(num_frames):
        viewer = viewer_chunk[frame_idx] if num_frames > 1 else viewer_chunk
        orig_stored = (
            original_stored_pixels[frame_idx]
            if multi_source
            else original_stored_pixels
        )
        mono1_invert_max: float | None = None
        pi = str(getattr(ds_orig, "PhotometricInterpretation", "") or "").upper()
        if pi == "MONOCHROME1":
            _, mono1_invert_max = stored_monochrome_to_series_buffer(orig_stored, ds_orig)
        stored_frames.append(
            series_buffer_monochrome_to_stored(
                viewer,
                ds_orig,
                mono1_invert_max=mono1_invert_max,
            )
        )

    if num_frames == 1:
        return stored_frames[0]
    return np.stack(stored_frames, axis=0)


def stored_monochrome_to_series_buffer(
    stored_frame: np.ndarray,
    ds: Dataset,
) -> tuple[np.ndarray, float | None]:
    """
    Convert one stored grayscale frame to Series View pixel space (float32).

    Matches ``load_series_frames`` monochrome handling (modality LUT, MONOCHROME1 invert).
    Returns ``(viewer_pixels, mono1_invert_max)``; ``mono1_invert_max`` is required to map back
    for MONOCHROME1 and is ``None`` for MONOCHROME2.
    """
    pi = str(getattr(ds, "PhotometricInterpretation", "") or "").upper()
    modality = np.asarray(apply_modality_lut(stored_frame, ds), dtype=np.float32)
    if pi == "MONOCHROME1":
        mono1_invert_max = float(np.max(modality))
        return mono1_invert_max - modality, mono1_invert_max
    return modality, None


def series_buffer_monochrome_to_stored(
    viewer_frame: np.ndarray,
    ds: Dataset,
    *,
    mono1_invert_max: float | None = None,
) -> np.ndarray:
    """Convert Series View grayscale pixels back to stored DICOM pixels."""
    pi = str(getattr(ds, "PhotometricInterpretation", "") or "").upper()
    viewer = viewer_frame.astype(np.float32, copy=False)
    if pi == "MONOCHROME1":
        if mono1_invert_max is None:
            raise ValueError("mono1_invert_max is required for MONOCHROME1")
        modality = mono1_invert_max - viewer
    else:
        modality = viewer
    return _prepare_monochrome_stored_pixels(modality, ds)


def _pixel_data_vr(ds: Dataset) -> str:
    bits_allocated = int(getattr(ds, "BitsAllocated", 16) or 16)
    return "OW" if bits_allocated == 16 else "OB"


def _rows_cols_from_pixel_array(pixels: np.ndarray) -> tuple[int, int]:
    """Return DICOM (Rows, Columns) for a frame or stacked pixel array."""
    if pixels.ndim == 2:
        return int(pixels.shape[0]), int(pixels.shape[1])
    if pixels.ndim >= 3 and pixels.shape[-1] in (3, 4):
        height_axis = -3 if pixels.ndim > 3 else 0
        return int(pixels.shape[height_axis]), int(pixels.shape[-2])
    if pixels.ndim >= 3:
        return int(pixels.shape[-2]), int(pixels.shape[-1])
    raise ValueError(f"Cannot determine Rows/Columns from pixel array shape {pixels.shape}")


def _validate_dicom_pixel_array(ds: Dataset) -> tuple[ndarray, int, int, str]:
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
    no_of_frames = ds.get(
        "NumberOfFrames", 1
    )  # safe to assume 1 frame if attribute not present?

    if not pi:
        raise ValueError("PhotometricInterpretation attribute missing.")

    if pi not in SUPPORTED_PHOTOMETRIC_INTERPRETATIONS:
        raise ValueError(
            f"Invalid Photometric Interpretation: {pi}. Supported: {SUPPORTED_PHOTOMETRIC_INTERPRETATIONS}"
        )

    if pi in ["MONOCHROME1", "MONOCHROME2"]:
        if samples_per_pixel != 1:
            raise ValueError(
                f"Samples per pixel = {samples_per_pixel} which should be 1 for grayscale images."
            )
    elif samples_per_pixel > 4:
        raise ValueError(
            f"Samples per pixel = {samples_per_pixel} which should be < 4 for multichannel images."
        )

    if not rows or not cols:
        raise ValueError("Missing image dimensions: Rows & Columns")

    if (
        bits_allocated is None
        or bits_stored is None
        or high_bit is None
        or pixel_representation is None
    ):
        raise ValueError(
            "Missing essential pixel attributes (BitsAllocated, BitsStored, HighBit, PixelRepresentation)."
        )

    # Validate if bits stored is less than or equal to bits allocated
    if bits_stored > bits_allocated:
        raise ValueError(
            f"BitsStored ({bits_stored}) cannot be greater than BitsAllocated ({bits_allocated})."
        )

    # Validate the HighBit value
    if high_bit != bits_stored - 1:
        raise ValueError(
            f"HighBit ({high_bit}) should be equal to BitsStored - 1 ({bits_stored - 1})."
        )

    # Validate pixel representation: 0 = unsigned, 1 = signed
    if pixel_representation not in [0, 1]:
        raise ValueError(
            f"Invalid Pixel Representation: {pixel_representation}. Expected 0 (unsigned) or 1 (signed)."
        )

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
        raise ValueError(
            f"Pixel array shape {pixels.shape} does not match Rows and Columns ({rows}, {cols})."
        )
    # TODO: check EVERY frame in the pixel array? Will pydicom have done this when decompressing?

    # Validate the number of frames
    if no_of_frames > 1 and no_of_frames != pixels.shape[0]:  # 3D or 4D array
        raise ValueError(
            f"Number of frames {no_of_frames} does not match pixel array shape {pixels.shape[0]}."
        )

    # Validate the number of dimensions
    if pixels.ndim not in [2, 3, 4]:
        raise ValueError(
            f"Pixel array has unexpected number of dimensions: {pixels.ndim}. Expected 2, 3, or 4."
        )

    # Validate the number of channels
    if samples_per_pixel > 1 and samples_per_pixel != pixels.shape[-1]:
        raise ValueError(
            f"Samples per pixel {samples_per_pixel} does not match pixel array shape {pixels.shape[-1]}."
        )

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
        raise ValueError(
            "Unsupported BitsAllocated value. Only 8 and 16 bits are supported."
        )

    if pixels.dtype != expected_dtype:
        raise ValueError(
            f"Pixel data type {pixels.dtype} does not match expected type {expected_dtype}."
        )

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


def _load_series_frames(series_path: Path) -> tuple[Dataset, ndarray, tuple[Path, ...]]:
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
              Dtype will be consistent for modality.
              Grayscale CT/MR stored-pixel stacks use float32 after modality LUT.
              Shape: (num_frames, height, width) or (num_frames, height, width, 3).
            - Source DICOM paths in the same order as stacked frames (one entry per frame).

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
        dcm_paths = stackable_dicom_paths(series_path)
    except ValueError as exc:
        logger.warning(
            "Falling back to legacy DICOM listing for %s: %s", series_path, exc
        )
        try:
            dcm_paths = sorted(get_dcm_files(series_path))
        except PermissionError as e:
            logger.error(f"Permission denied accessing {series_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error listing files in {series_path}: {e}")
            raise ValueError(f"Could not list files in directory: {series_path}") from e

        def get_instance_number(path: Path) -> int:
            try:
                ds_header = dcmread(str(path), stop_before_pixels=True, force=True)
                return int(ds_header.get("InstanceNumber", 999999))
            except (ValueError, TypeError, InvalidDicomError):
                return 999999

        dcm_paths.sort(key=get_instance_number)

    if not dcm_paths:
        raise ValueError(f"No DICOM files found in {series_path}")

    log_process_memory("load_series_frames_start", extra=str(series_path.name))

    processed_frames: list[ndarray] = []
    processed_paths: list[Path] = []
    ds1: Dataset | None = None
    target_size: tuple[int, int] | None = None
    series_pi: str = ""

    # --- Loop through series files (skip non-image instances without PixelData) ---
    for dcm_path in dcm_paths:
        try:
            ds = dcmread(str(dcm_path), force=True)
            raw_pixels, rows, cols, pi = _validate_dicom_pixel_array(ds)

            if ds1 is None:
                ds1 = ds
                target_size = (rows, cols)
                series_pi = pi.upper()
                logger.info(
                    f"Series detected as {series_pi} with target size {target_size} "
                    f"from {dcm_path.name} and pixels data type {raw_pixels.dtype}"
                )
            elif pi != series_pi:
                logger.warning(
                    f"Inconsistent PI in {dcm_path} ({pi}) vs first file ({series_pi}). Skipping file."
                )
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
                current_frame_pixels = (
                    raw_pixels[frame_idx] if is_multi_frame_source else raw_pixels
                )
                frame: ndarray | None = None

                # Process based on the *series* interpretation determined from the first file
                match series_pi:
                    case "MONOCHROME1" | "MONOCHROME2":
                        modality_pixels = np.asarray(
                            apply_modality_lut(current_frame_pixels, ds),
                            dtype=np.float32,
                        )
                        if modality_pixels.dtype != current_frame_pixels.dtype:
                            logger.debug(
                                "Modality LUT changed pixel data type to %s (stored as float32)",
                                modality_pixels.dtype,
                            )
                        if series_pi == "MONOCHROME1":
                            try:
                                max_val = np.max(modality_pixels)
                                frame = max_val - modality_pixels
                            except Exception:
                                frame = modality_pixels
                                logger.warning(
                                    f"Could not invert MONOCHROME1 frame {frame_idx} in {dcm_path}",
                                    exc_info=True,
                                )
                        else:
                            frame = modality_pixels
                        if (
                            frame is not None
                            and frame.ndim == 3
                            and frame.shape[-1] == 1
                        ):
                            frame = frame.squeeze(axis=-1)

                    case "PALETTE COLOR":
                        frame = apply_color_lut(current_frame_pixels, ds)
                        if frame.shape[-1] == 4:
                            frame = frame[..., :3]
                        # if frame.dtype != np.uint8:
                        #     frame = normalize_uint8(frame)

                    case "YBR_FULL" | "YBR_FULL_422":
                        frame = convert_color_space(
                            current_frame_pixels, series_pi, "RGB"
                        )
                        if (
                            frame.dtype != np.uint8
                            or frame.ndim != 3
                            or frame.shape[-1] != 3
                        ):
                            raise ValueError(
                                f"Color space conversion failed for {dcm_path} frame {frame_idx}."
                            )

                    case "RGB":
                        frame = current_frame_pixels

                # --- Resize frame AFTER processing if necessary ---
                if frame is not None:
                    # Resize to target size if necessary
                    current_h, current_w = frame.shape[:2]
                    target_h, target_w = target_size
                    if current_h != target_h or current_w != target_w:
                        logger.warning(
                            f"Resizing frame {len(processed_frames)} from ({current_h},{current_w}) "
                            f"to target ({target_h},{target_w}) in {dcm_path}"
                        )
                        interpolation = (
                            INTER_AREA
                            if (current_h > target_h or current_w > target_w)
                            else INTER_LINEAR
                        )
                        frame = resize(
                            frame,
                            (target_w, target_h),
                            interpolation=interpolation,
                        )

                    processed_frames.append(frame)
                    processed_paths.append(dcm_path)
                else:
                    raise RuntimeError(
                        f"CRITICAL Error: Frame {frame_idx} from {dcm_path} failed to process."
                    )

        except (InvalidDicomError, ValueError) as e:
            logger.error(f"Invalid DICOM or processing error skipped: {dcm_path} - {e}")
            continue  # Skip this file
        except Exception as e:
            logger.error(f"Unexpected error processing file {dcm_path}: {e}")
            raise ValueError(f"Error processing file in series: {dcm_path}") from e

    if ds1 is None or not processed_frames:
        raise ValueError(f"No image slices with PixelData found in {series_path}")

    # --- Stack frames into one array without np.stack's extra full-volume copy ---
    slice_count = len(processed_frames)
    frame_shape = processed_frames[0].shape
    stack_dtype = (
        np.float32
        if series_pi in ("MONOCHROME1", "MONOCHROME2")
        else processed_frames[0].dtype
    )
    all_series_frames_stacked = np.empty(
        (slice_count,) + frame_shape, dtype=stack_dtype
    )
    for index, frame in enumerate(processed_frames):
        all_series_frames_stacked[index] = frame
        processed_frames[index] = None  # type: ignore[call-overload]
    processed_frames.clear()
    del processed_frames

    log_process_memory(
        "load_series_stacked",
        array=all_series_frames_stacked,
        extra=f"slices={all_series_frames_stacked.shape[0]}",
    )

    logger.info(
        f"Final stacked array - Shape: {all_series_frames_stacked.shape}, Dtype: {all_series_frames_stacked.dtype}"
    )

    return ds1, all_series_frames_stacked, tuple(processed_paths)


def apply_series_description(series_path: Path, description: str) -> bool:
    """
    Set SeriesDescription on every DICOM file in a series directory.

    Args:
        series_path: Directory containing series instance .dcm files.
        description: Value to write to (0008,103E) SeriesDescription.

    Returns:
        True if all files were updated successfully, otherwise False.
    """
    if not series_path.is_dir():
        logger.error(f"Series path is not a directory {series_path}")
        return False

    try:
        dcm_paths = sorted(get_dcm_files(series_path))
    except Exception as ex:
        logger.error(f"Could not list DICOM files in {series_path}: {ex}")
        return False

    if not dcm_paths:
        logger.error(f"No DICOM files found in {series_path}")
        return False

    success = True
    logger.info("Updated SeriesDescription on %s", series_path)
    for dcm_path in dcm_paths:
        try:
            # Full read required: saving after stop_before_pixels=True drops PixelData.
            ds = dcmread(str(dcm_path), force=True)
            if not hasattr(ds, "PixelData"):
                logger.warning(
                    "Skipping SeriesDescription update for %s: no PixelData present",
                    dcm_path.name,
                )
                continue
            ds.SeriesDescription = description
            ds.save_as(dcm_path, write_like_original=True)

        except Exception as ex:
            logger.exception(f"Failed to update SeriesDescription on {dcm_path}: {ex}")
            success = False

    return success


def save_series_frames(
    original_series_path: Path, processed_frames: np.ndarray, reference_ds: Dataset
) -> bool:
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
    logger.info(
        f"Starting to save processed frames, OVERWRITING files in: {original_series_path}"
    )
    if processed_frames is None or processed_frames.size == 0:
        logger.error("No processed frames provided to save.")
        return False
    if not original_series_path.is_dir():
        logger.error(f"Original series path is not a directory: {original_series_path}")
        return False

    # --- 1. Determine Original File Structure (stack order, same as load_series_frames) ---
    try:
        original_dcm_paths = ordered_series_dcm_paths(original_series_path)
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
                logger.warning(
                    f"Could not read frame count from {p}, skipping file: {e}"
                )
                continue

        if total_frames_in_files == 0:
            logger.error(
                "Could not determine frame counts from any original DICOM file."
            )
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

    # --- 2. Determine Series Photometric Interpretation ---
    try:
        series_pi = reference_ds.PhotometricInterpretation.upper()
        logger.info(f"Saving series based on original PI: {series_pi}")
    except Exception as e:
        logger.error(f"Could not determine series type: {e}")
        return False

    # --- 3. Iterate, Process, and Save (Overwrite) ---
    frame_ndx = 0
    success = True
    for original_path, num_frames_in_file in file_frame_counts:
        logger.debug(
            f"Processing {num_frames_in_file} frame(s) to overwrite -> {original_path.name}"
        )
        try:
            ds_orig = dcmread(str(original_path), stop_before_pixels=True, force=True)
            ds_save = ds_orig.copy()
            ds_pixels = dcmread(str(original_path), force=True)
            original_stored_pixels = ds_pixels.pixel_array

            frame_chunk = processed_frames[frame_ndx : frame_ndx + num_frames_in_file]
            if frame_chunk.shape[0] != num_frames_in_file:
                logger.error(f"Frame count mismatch for {original_path}. Skipping.")
                success = False
                frame_ndx += num_frames_in_file
                continue

            if series_pi in ("MONOCHROME1", "MONOCHROME2"):
                try:
                    final_pixel_data = _viewer_chunk_to_stored_pixels(
                        frame_chunk,
                        ds_orig,
                        original_stored_pixels=original_stored_pixels,
                    )
                except ValueError as exc:
                    logger.error(
                        f"Failed monochrome pixel preparation for {original_path.name}: {exc}"
                    )
                    success = False
                    frame_ndx += num_frames_in_file
                    continue

                # Preserve per-slice pixel encoding and presentation metadata from source.
                ds_save.PhotometricInterpretation = ds_orig.PhotometricInterpretation
                ds_save.SamplesPerPixel = int(
                    getattr(ds_orig, "SamplesPerPixel", 1) or 1
                )
                for tag_name in (
                    "PlanarConfiguration",
                    "RescaleSlope",
                    "RescaleIntercept",
                    "BitsAllocated",
                    "BitsStored",
                    "HighBit",
                    "PixelRepresentation",
                ):
                    if tag_name in ds_orig:
                        ds_save[tag_name] = ds_orig[tag_name]
                    elif tag_name in ds_save:
                        del ds_save[tag_name]

                # Keep presentation window from the source DICOM (never viewer-adjusted WL/WW).
                for tag in ("WindowCenter", "WindowWidth"):
                    if tag in ds_orig:
                        ds_save[tag] = ds_orig[tag]
                    elif tag in ds_save:
                        del ds_save[tag]

            elif series_pi in ("RGB", "YBR_FULL", "YBR_FULL_422", "PALETTE COLOR"):
                final_pixel_data = frame_chunk
                if (
                    final_pixel_data.dtype != np.uint8
                    or final_pixel_data.ndim != 4
                    or final_pixel_data.shape[-1] != 3
                ):
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
                for tag in [
                    "RescaleSlope",
                    "RescaleIntercept",
                    "VOILUTSequence",
                    "WindowCenter",
                    "WindowWidth",
                ]:
                    if tag in ds_save:
                        del ds_save[tag]
            else:
                logger.error(
                    f"Cannot save unsupported PI: {series_pi} for {original_path.name}"
                )
                success = False
                frame_ndx += num_frames_in_file
                continue

            # Update Pixel Data and Frame Count
            final_pixel_data_to_save = (
                final_pixel_data.squeeze(axis=0)
                if num_frames_in_file == 1
                else final_pixel_data
            )
            if final_pixel_data_to_save.dtype.byteorder not in ("=", "<"):
                final_pixel_data_to_save = (
                    final_pixel_data_to_save.byteswap().newbyteorder("<")
                )

            # EXPLICITLY SET VR for PixelData because of using ExplicitVRLittleEndian TS
            pixel_data_tag = Tag(0x7FE0, 0x0010)
            pixel_vr = _pixel_data_vr(ds_orig)
            # Create/Update the DataElement with the correct VR and Value
            ds_save[pixel_data_tag] = DataElement(
                tag=pixel_data_tag,
                VR=pixel_vr,
                value=final_pixel_data_to_save.tobytes(),
            )

            try:
                ds_save.Rows, ds_save.Columns = _rows_cols_from_pixel_array(
                    final_pixel_data_to_save
                )
            except ValueError as exc:
                logger.error(
                    "Unexpected shape after squeeze for %s: %s",
                    original_path.name,
                    exc,
                )
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
            logger.debug(f"Successfully overwrote {original_path.name}")

            frame_ndx += num_frames_in_file

        except Exception as e:
            logger.exception(
                f"Failed to process or save file {original_path.name}: {e}"
            )
            success = False
            frame_ndx += num_frames_in_file  # Ensure index advances

    if frame_ndx != processed_frames.shape[0]:
        logger.error(
            f"Frame processing index mismatch, frames: {frame_ndx} expected: {processed_frames.shape[0]}."
        )
        success = False

    # --- 4. Remove Projection File if it exists for series ---
    logger.info(
        f"Finished saving series to {original_series_path}. Overall success: {success}"
    )
    return success
