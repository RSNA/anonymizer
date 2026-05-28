"""Load stacked CT DICOM slices into a SimpleITK image."""

from pathlib import Path

import numpy as np
import SimpleITK as sitk
from pydicom import Dataset, dcmread
from pydicom.misc import is_dicom

MIN_DICOM_SLICES = 11


def get_sitk_from_dicom(dicom_dir: Path) -> sitk.Image:
    dicom_dir = Path(dicom_dir)
    dicom_files = sorted(
        path for path in dicom_dir.iterdir() if path.is_file() and is_dicom(path)
    )
    slice_paths, img_spacing, img_direction, img_origin = load_dicom(dicom_files)
    if 0.0 in img_spacing:
        raise ValueError(f"Zero spacing found for series: {img_spacing}")

    img_cube = get_pixel_array(slice_paths)
    img_sitk = sitk.GetImageFromArray(img_cube)
    del img_cube
    img_sitk.SetSpacing(img_spacing)
    img_sitk.SetDirection(img_direction)
    img_sitk.SetOrigin(img_origin)
    return img_sitk


def load_dicom(slice_list: list[Path]) -> tuple[list[Path], list[float], list[float], list[float]]:
    if len(slice_list) < MIN_DICOM_SLICES:
        raise ValueError(f"Found only {len(slice_list)} slices; need at least {MIN_DICOM_SLICES}")

    img_dirs = [
        img_path
        for img_path in slice_list
        if img_path.stem not in {"RTDOSE", "RTSTRUCT"}
    ]

    accepted_paths: list[Path] = []
    for index, current_path in enumerate(img_dirs):
        slice1 = dcmread(current_path, stop_before_pixels=True)
        next_path = img_dirs[index + 1] if index + 1 < len(img_dirs) else None
        if next_path is not None:
            slice2 = dcmread(next_path, stop_before_pixels=True)

            if slice1.SliceThickness is None:
                slice1.SliceThickness = float(
                    abs(slice1.ImagePositionPatient[2] - slice2.ImagePositionPatient[2])
                )

            if list(slice1.ImageOrientationPatient) == [0, 1, 0, 0, 0, -1]:
                slice1.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
                slice2.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]

            if float(slice1.SliceThickness) == abs(slice1.ImagePositionPatient[2] - slice2.ImagePositionPatient[2]) or list(slice1.ImageOrientationPatient) == [1, 0, 0, 0, 1, 0]:
                accepted_paths.append(current_path)

            if index + 1 == len(img_dirs) - 1:
                accepted_paths.append(next_path)

        elif len(img_dirs) == 1:
            accepted_paths.append(current_path)

    if len(accepted_paths) < MIN_DICOM_SLICES:
        raise ValueError(f"Found only {len(accepted_paths)} slices; need at least {MIN_DICOM_SLICES}")

    accepted_paths.sort(
        key=lambda path: float(dcmread(path, stop_before_pixels=True).ImagePositionPatient[2])
    )
    first_slice = dcmread(accepted_paths[0], stop_before_pixels=True)
    second_slice = dcmread(accepted_paths[1], stop_before_pixels=True)
    slice_thickness = abs(first_slice.ImagePositionPatient[2] - second_slice.ImagePositionPatient[2])
    if slice_thickness > 3 or slice_thickness == 0:
        tenth_slice = dcmread(accepted_paths[9], stop_before_pixels=True)
        eleventh_slice = dcmread(accepted_paths[10], stop_before_pixels=True)
        slice_thickness = abs(tenth_slice.ImagePositionPatient[2] - eleventh_slice.ImagePositionPatient[2])

    img_spacing = [
        float(first_slice.PixelSpacing[0]),
        float(first_slice.PixelSpacing[1]),
        slice_thickness,
    ]
    img_direction = [float(value) for value in first_slice.ImageOrientationPatient] + [0.0, 0.0, 1.0]
    img_origin = [float(value) for value in first_slice.ImagePositionPatient]

    return accepted_paths, img_spacing, img_direction, img_origin


def get_pixel_array(slice_paths: list[Path]) -> np.ndarray:
    """
    Load HU values slice-by-slice without retaining full pydicom datasets.
     - Uses RescaleSlope and RescaleIntercept to convert raw pixel values to Hounsfield Units.
     - Clips values below -1000 HU to -1000, as these are outside the valid range for CT data and can skew model predictions.
     - Returns a 3D numpy array of shape (num_slices, height, width) containing the processed pixel data ready for model input.
    """
    first_dataset = dcmread(slice_paths[0])
    image = np.empty((len(slice_paths), *first_dataset.pixel_array.shape), dtype=np.int16)
    image[0] = _rescale_slice_to_hu(first_dataset)
    del first_dataset

    for slice_number, path in enumerate(slice_paths[1:], start=1):
        dataset = dcmread(path)
        image[slice_number] = _rescale_slice_to_hu(dataset)
        del dataset

    np.clip(image, -1000, None, out=image)
    return image


def _rescale_slice_to_hu(dataset: Dataset) -> np.ndarray:
    slice_pixels = dataset.pixel_array.astype(np.int16, copy=True)
    intercept = dataset.RescaleIntercept
    slope = dataset.RescaleSlope
    if slope != 1:
        slice_pixels = (slope * slice_pixels.astype(np.float64)).astype(np.int16)
    slice_pixels += np.int16(intercept)
    return slice_pixels
