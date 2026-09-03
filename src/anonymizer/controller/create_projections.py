"""View Index projection thumbnails (Projection.pkl).

Builds min/mean/max or CLAHE/edge preview images for the PHI Index.
Series pixel I/O lives in ``series_io``; this module lazy-imports ``load_series_frames``
when building uncached projections.
"""

from __future__ import annotations

import logging
import pickle
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from pprint import pformat
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from anonymizer.controller.series_io import LoadedSeries

import numpy as np
from cv2 import (
    COLOR_RGB2GRAY,
    MORPH_RECT,
    NORM_MINMAX,
    Canny,
    GaussianBlur,
    createCLAHE,
    cvtColor,
    dilate,
    getStructuringElement,
    normalize,
)
from numpy import ndarray
from PIL import Image
from pydicom import Dataset

from anonymizer.controller.series_overlay import OCRText
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.windowing import apply_windowing

logger = logging.getLogger(__name__)

_loaded_series_cache: dict[Path, LoadedSeries] = {}


def cache_loaded_series(series_path: Path, loaded: LoadedSeries) -> None:
    _loaded_series_cache[series_path.resolve()] = loaded


def take_loaded_series_cache(series_path: Path) -> LoadedSeries | None:
    """Pop a LoadedSeries cached while building projection thumbnails (Projection View handoff)."""
    return _loaded_series_cache.pop(series_path.resolve(), None)

PROJECTION_FILENAME = "Projection.pkl"


def invalidate_projection_cache(series_path: Path) -> None:
    """Remove stale PHI Index projection cache after on-disk series changes."""
    cache_file = Path(series_path) / PROJECTION_FILENAME
    if not cache_file.is_file():
        return
    try:
        cache_file.unlink()
        logger.info("Deleted stale projection cache: %s", cache_file)
    except OSError as exc:
        logger.warning("Error deleting projection cache %s: %s", cache_file, exc)


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


def cache_projection(projection: Projection, projection_file_path: Path) -> None:
    # Pickle Project object to series path for faster loading next time:
    try:
        with open(projection_file_path, "wb") as pkl_file:
            pickle.dump(projection, pkl_file)
    except Exception as e:
        logger.warning(f"Error saving Projection cache file, error: {e}")
    return


def _single_frame_to_uint8_gray(frame: ndarray) -> ndarray:
    """Window a single frame to ``uint8`` grayscale for CLAHE / Canny.

    Color ultrasound frames from ``load_series_frames`` are RGB ``(H, W, 3)``;
    OpenCV CLAHE requires ``CV_8UC1`` or ``CV_16UC1``.
    """
    frame_float = frame.astype(np.float32)
    min_val, max_val = float(np.min(frame_float)), float(np.max(frame_float))
    ww_safe = max(1.0, max_val - min_val)
    windowed = np.clip(((frame_float - min_val) / ww_safe) * 255.0, 0, 255).astype(np.uint8)

    if windowed.ndim == 2:
        return windowed
    if windowed.ndim == 3 and windowed.shape[-1] == 3:
        return cvtColor(windowed, COLOR_RGB2GRAY)
    if windowed.ndim == 3 and windowed.shape[-1] == 1:
        return windowed.squeeze(axis=-1)
    raise ValueError(f"Unsupported single-frame shape for projections: {windowed.shape}")


def create_projection_from_single_frame(ds: Dataset, frame: ndarray) -> Projection:
    # [mean,clahe,edge] for single-frame
    gray = _single_frame_to_uint8_gray(frame)
    logger.debug("single-frame gray: shape=%s range=[%s,%s]", gray.shape, gray.min(), gray.max())

    # Apply CLAHE for enhanced contrast
    clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray_clahe = clahe.apply(gray)

    # Apply Gaussian Blur to reduce noise
    blurred = GaussianBlur(gray, (5, 5), 0)

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
        for img in [gray, gray_clahe, edges_dilated]
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

    from anonymizer.controller.series_io import load_series_frames

    loaded = load_series_frames(series_path)
    cache_loaded_series(series_path, loaded)
    ds1 = loaded.metadata
    all_series_frames = loaded.frames

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
