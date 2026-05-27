"""Resample and crop CT volumes for FALCON inference."""

import logging
from typing import cast

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

logger = logging.getLogger(__name__)


def respacing(img: sitk.Image, interp_type: str, new_spacing: tuple[float, float, float]) -> sitk.Image:
    old_size = img.GetSize()
    old_spacing = img.GetSpacing()
    new_size = [
        int(round((old_size[0] * old_spacing[0]) / float(new_spacing[0]))),
        int(round((old_size[1] * old_spacing[1]) / float(new_spacing[1]))),
        int(round((old_size[2] * old_spacing[2]) / float(new_spacing[2]))),
    ]

    if interp_type == "linear":
        sitk_interp = sitk.sitkLinear
    elif interp_type == "bspline":
        sitk_interp = sitk.sitkBSpline
    elif interp_type == "nearest_neighbor":
        sitk_interp = sitk.sitkNearestNeighbor
    else:
        raise ValueError(f"Unsupported interpolation type: {interp_type}")

    resample = sitk.ResampleImageFilter()
    resample.SetOutputSpacing(new_spacing)
    resample.SetSize(new_size)
    resample.SetOutputOrigin(img.GetOrigin())
    resample.SetOutputDirection(img.GetDirection())
    resample.SetInterpolator(sitk_interp)
    resample.SetDefaultPixelValue(img.GetPixelIDValue())
    resample.SetOutputPixelType(sitk.sitkFloat32)
    
    return resample.Execute(img)


def crop_image(
    nrrd_file: sitk.Image,
    crop_shape: tuple[int, int, int],
    clipping: float | None = None,
    scale_size: tuple[int, int, int] | None = None,
    verbose: bool = False,
    mass_centered: bool = False,
) -> sitk.Image:
    spacing = nrrd_file.GetSpacing()
    origin = nrrd_file.GetOrigin()

    img_arr = sitk.GetArrayFromImage(nrrd_file)
    del nrrd_file

    if clipping is not None:
        img_arr[img_arr < clipping] = clipping
        img_arr[img_arr > 700] = 0

    depth, height, width = img_arr.shape
    x_crop, y_crop, c_crop = crop_shape

    ## Get center of mass to center the crop in Y plane
    mask_arr = np.copy(img_arr) 
    mask_arr[mask_arr > -500] = 1
    mask_arr[mask_arr <= -500] = 0
    if not mass_centered: 
        mask_arr[mask_arr >= -500] = 1

    
    center_of_mass = ndimage.center_of_mass(mask_arr)

    if np.any(np.isnan(center_of_mass)):
        raise ValueError("Empty or invalid volume for cropping. Center of mass could not be calculated.")
    
    center_of_mass = tuple(int(x) for x in cast(tuple, center_of_mass))
    
    startc = int(center_of_mass[0] - c_crop//2)
    starty = int(center_of_mass[1] - y_crop//2)      
    startx = int(center_of_mass[2] - x_crop//2)

    pad_c_before = -min(0, startc)
    pad_c_after = max(0, startc + c_crop - depth)
    pad_y_before = -min(0, starty)
    pad_y_after = max(0, starty + y_crop - height)
    pad_x_before = -min(0, startx)
    pad_x_after = max(0, startx + x_crop - width)

    if verbose:
        logger.debug(
            "FALCON crop center=%s start=(%s,%s,%s) padding before=(%s,%s,%s) after=(%s,%s,%s)",
            center_of_mass,
            startx,
            starty,
            startc,
            pad_c_before,
            pad_y_before,
            pad_x_before,
            pad_c_after,
            pad_y_after,
            pad_x_after,
        )

    pad_value = -1000.0
    img_arr_padded = np.pad(
        img_arr,
        ((pad_c_before, pad_c_after), (pad_y_before, pad_y_after), (pad_x_before, pad_x_after)),
        mode="constant",
        constant_values=((pad_value, pad_value), (pad_value, pad_value), (pad_value, pad_value)),
    )
    del img_arr

    startc += pad_c_before
    starty += pad_y_before
    startx += pad_x_before

    img_crop_arr = img_arr_padded[startc : startc + c_crop, starty : starty + y_crop, startx : startx + x_crop]
    del img_arr_padded

    if scale_size is not None:
        scaled = scale_image(img_crop_arr, scale_size)
        del img_crop_arr
        img_crop_arr = scaled

    img_crop_nrrd = sitk.GetImageFromArray(img_crop_arr)
    del img_crop_arr
    img_crop_nrrd.SetSpacing(spacing)
    img_crop_nrrd.SetOrigin(origin)
    return img_crop_nrrd


def scale_image(img_crop_arr: np.ndarray, scale_size: tuple[int, int, int]) -> np.ndarray:
    target_shape = (img_crop_arr.shape[0], scale_size[0], scale_size[1])
    zoom_factors = (
        1.0,
        scale_size[0] / img_crop_arr.shape[1],
        scale_size[1] / img_crop_arr.shape[2],
    )
    scaled: np.ndarray = np.asarray(ndimage.zoom(img_crop_arr, zoom_factors, order=1))
    
    if scaled.shape != target_shape:
        raise ValueError(f"Scaled image shape {scaled.shape} does not match target {target_shape}")
    
    return scaled.astype(img_crop_arr.dtype, copy=False)
