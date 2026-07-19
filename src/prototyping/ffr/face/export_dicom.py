from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.uid import generate_uid


def hu_slice_to_stored_pixels(
    hu_slice: np.ndarray,
    *,
    rescale_slope: float,
    rescale_intercept: float,
    dtype: np.dtype,
) -> np.ndarray:
    """Convert HU back to stored DICOM pixels using the source slice rescale tags."""
    slope = rescale_slope if rescale_slope not in (0, 0.0) else 1.0
    stored = (hu_slice - rescale_intercept) / slope
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        return np.clip(np.rint(stored), info.min, info.max).astype(dtype)
    return stored.astype(dtype)


def _prepare_output_directory(output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for path in output_directory.iterdir():
        if path.is_file() and path.suffix.lower() in {".dcm", ".dicom"}:
            path.unlink()


def write_blurred_dicom_series(
    hu: np.ndarray,
    slice_paths: tuple[Path, ...],
    output_directory: Path,
    *,
    series_description_suffix: str = " — face blurred",
) -> tuple[Path, ...]:
    """
    Write ``hu`` as an axial DICOM series in the same patient space as ``slice_paths``.

    Each output slice copies geometry and pixel encoding from the matching source slice,
    assigns new Series/SOP Instance UIDs, and updates ``SeriesDescription``.
    """
    if hu.shape[0] != len(slice_paths):
        raise ValueError(f"HU stack depth {hu.shape[0]} != slice count {len(slice_paths)}")

    output_directory = Path(output_directory).resolve()
    _prepare_output_directory(output_directory)

    series_uid = generate_uid()
    written: list[Path] = []
    for z, source_path in enumerate(slice_paths):
        ds = pydicom.dcmread(str(source_path))
        source_dtype = ds.pixel_array.dtype
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        stored = hu_slice_to_stored_pixels(
            hu[z],
            rescale_slope=slope,
            rescale_intercept=intercept,
            dtype=source_dtype,
        )

        ds.SeriesInstanceUID = series_uid
        ds.SOPInstanceUID = generate_uid()
        if hasattr(ds, "SeriesDescription"):
            base = str(ds.SeriesDescription).rstrip()
            ds.SeriesDescription = f"{base}{series_description_suffix}"
        else:
            ds.SeriesDescription = "Face blurred"
        if hasattr(ds, "ImageType"):
            image_type = list(getattr(ds, "ImageType", []))
            if image_type:
                image_type[0] = "DERIVED"
                if len(image_type) > 1:
                    image_type[1] = "SECONDARY"
                ds.ImageType = image_type

        ds.PixelData = stored.tobytes()
        out_path = output_directory / f"{ds.SOPInstanceUID}.dcm"
        ds.save_as(str(out_path))
        written.append(out_path)

    if not written:
        raise RuntimeError(f"No DICOM slices written to {output_directory}")
    return tuple(written)
