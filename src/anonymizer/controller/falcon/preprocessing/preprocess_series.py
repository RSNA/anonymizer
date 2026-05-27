"""Preprocess a CT DICOM series directory for FALCON inference."""

from pathlib import Path

import SimpleITK as sitk

from anonymizer.controller.falcon.preprocessing.dicom_loading import get_sitk_from_dicom
from anonymizer.controller.falcon.preprocessing.image_transformation import crop_image, respacing

CROP_SHAPE = (200, 200, 100)
SCALE_SIZE = (150, 150, 100)
NEW_SPACING = (1.0, 1.0, 3.0)
CLIPPING = -1000


def preprocess_series(series_directory: Path) -> np.ndarray:
    """
    This function orchestrates the complete preprocessing pipeline for a single CT series:

    1. Loads DICOM slices from the specified directory into a SimpleITK image object
    2. Resamples the volume to a standardized spacing to normalize voxel dimensions
    3. Crops and scales the volume to match the expected input dimensions for FALCON model inference
    
    Intermediate image objects are processed sequentially, allowing garbage collection to free memory
    as each preprocessing step completes.

    Args:
        series_directory (Path): Path to a directory containing DICOM slice files for a single CT series.
            The directory should contain only the DICOM files for one volumetric study.

    Returns:
        np.ndarray:     
            A preprocessed NumPy array with standardized spacing and dimensions,
            ready for input into the FALCON torch inference pipeline.

    Raises:
        ValueError: 
            If insufficient DICOM slices are found
            If zero x,y or z spacing is detected in the loaded image volume.
            If the center of mass cannot be calculated for cropping (e.g., empty or invalid volume).
            If interpoloation method is invalid for resampling.
            If scaled image dimensions do not match expected dimensions after cropping and scaling.
    
    Note:
        The preprocessing uses predefined constants (NEW_SPACING, CROP_SHAPE, CLIPPING, SCALE_SIZE)
        that must be configured according to FALCON model requirements.
    """
    sitk_object = get_sitk_from_dicom(series_directory)

    respaced_object = respacing(sitk_object, interp_type="linear", new_spacing=NEW_SPACING)

    cropped_object = crop_image(
        respaced_object,
        crop_shape=CROP_SHAPE,
        clipping=CLIPPING,
        scale_size=SCALE_SIZE,
    )
    # Extract the NumPy array
    image_np = sitk.GetArrayFromImage(cropped_object)
    
    # Explicitly release the SimpleITK C++ memory before returning
    del sitk_object, respaced_object, cropped_object
    
    return image_np
