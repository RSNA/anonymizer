import logging
import pickle
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from pprint import pformat

import numpy as np
from cv2 import (
    COLOR_RGB2GRAY,
    CV_8U,
    INTER_AREA,
    MORPH_RECT,
    NORM_MINMAX,
    Canny,
    GaussianBlur,
    createCLAHE,
    cvtColor,
    dilate,
    getStructuringElement,
    normalize,
    resize,
)
from PIL import Image
from pydicom import Dataset, dcmread
from pydicom.pixel_data_handlers.util import apply_modality_lut

from anonymizer.controller.remove_pixel_phi import OCRText
from anonymizer.utils.storage import get_dcm_files

logger = logging.getLogger(__name__)

PROJECTION_FILENAME = "Projection.pkl"


@dataclass
class Projection:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    proj_images: (
        list[Image.Image] | None
    )  # [min,mean,max] projections multi-frame or [mean,clahe,edge] for single-frame
    ocr: list[OCRText] | None

    def __repr__(self) -> str:
        return f"{pformat(asdict(self), sort_dicts=False)}"


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
    LARGE = (600, 600)

    def width(self):
        return int(self.value[0] * ProjectionImageSizeConfig.get_scaling_factor())

    def height(self):
        return int(self.value[1] * ProjectionImageSizeConfig.get_scaling_factor())


def normalize_uint8(image: np.ndarray) -> np.ndarray:
    """Normalize and convert an image to uint8."""
    return normalize(
        src=image,
        dst=np.empty_like(image),
        alpha=0,
        beta=255,
        norm_type=NORM_MINMAX,
        dtype=CV_8U,
    ).astype(np.uint8)


def cache_projection(projection: Projection, projection_file_path: Path) -> None:
    # Pickle Project object to series path for faster loading next time:
    try:
        with open(projection_file_path, "wb") as pkl_file:
            pickle.dump(projection, pkl_file)
    except Exception as e:
        logger.warning(f"Error saving Projection cache file, error: {e}")
    return


def create_projection_from_single_frame(ds: Dataset) -> Projection:
    # [mean,clahe,edge] for single-frame
    pi = ds.get("PhotometricInterpretation", None)
    if pi is None:
        raise ValueError("No PhotometricInterpretation ")

    pixels = ds.pixel_array
    logger.debug(f"pixels.value.range:[{pixels.min(), pixels.max()}]")

    if pi in ["MONOCHROME1", "MONOCHROME2"]:
        pixels = apply_modality_lut(pixels, ds)
        logger.debug(f"modality_lut: pixels.value.range:[{pixels.min(), pixels.max()}]")
        if pi == "MONOCHROME1":
            logger.info("Convert from MONOCHROME1 to MONOCHROME2")
            pixels = np.max(pixels) - pixels
            logger.debug(f"after inversion pixels.value.range:[{pixels.min(), pixels.max()}]")
    elif pi == "RGB":
        # Convert to Grayscale
        pixels = cvtColor(pixels, COLOR_RGB2GRAY)

    medium_contrast = np.zeros_like(pixels)
    normalize(src=pixels, dst=medium_contrast, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=-1, mask=None)
    medium_contrast = medium_contrast.astype(np.uint8)

    logger.debug(f"After normalization: pixels.value.range:[{medium_contrast.min(), medium_contrast.max()}]")

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

    # Load and process the series: [min,mean,max] projections multi-frame
    dcm_paths: list[Path] = sorted(get_dcm_files(series_path))

    if len(dcm_paths) == 0:
        raise ValueError(f"No DICOM files found in {series_path}")

    logger.debug(f"Create Projection from {series_path.name} from {len(dcm_paths)} DICOM file(s)")

    ds1 = dcmread(dcm_paths[0])
    pi = ds1.get("PhotometricInterpretation", None)
    if pi is None:
        raise ValueError("No PhotometricInterpretation")

    grayscale = pi in ["MONOCHROME1", "MONOCHROME2"]
    no_of_frames = ds1.get("NumberOfFrames", 1)

    if len(dcm_paths) == 1 and no_of_frames == 1:
        projection = create_projection_from_single_frame(ds1)
        cache_projection(projection, projection_file_path)
        del ds1
        return projection

    target_size = (ds1.get("Rows", None), ds1.get("Columns", None))
    all_series_frames = []

    for dcm_path in dcm_paths:
        ds = dcmread(dcm_path) if all_series_frames else ds1

        pixels = ds.pixel_array

        if grayscale:
            pixels = apply_modality_lut(pixels, ds)
            if pi == "MONOCHROME1":
                pixels = np.invert(pixels.astype(np.uint16))
            pixels = np.stack([pixels] * 3, axis=-1)

        if pixels.ndim == 4:
            all_series_frames.append(pixels)
        elif pixels.ndim == 3:
            if pixels.shape[:2] != target_size:
                pixels = resize(pixels, (target_size[1], target_size[0]), interpolation=INTER_AREA)
                # pixels = resize_or_pad_image(pixels, target_size)
            all_series_frames.append(np.expand_dims(pixels, axis=0))
        else:
            logger.error(f"Unexpected pixel array shape, skip: {dcm_path}")

        del ds

    logger.info(f"all_series_frames read, frames= {len(all_series_frames)}")

    all_series_frames = np.concatenate(all_series_frames, axis=0)

    # Compute min, mean, and max projections
    min_projection = normalize_uint8(np.min(all_series_frames, axis=0))
    mean_projection = normalize_uint8(np.mean(all_series_frames, axis=0))
    max_projection = normalize_uint8(np.max(all_series_frames, axis=0))

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
