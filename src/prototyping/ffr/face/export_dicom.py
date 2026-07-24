"""Shim → ``anonymizer.controller.blur_face``."""

from anonymizer.controller.blur_face import (
    hu_slice_to_stored_pixels,
    write_blurred_dicom_series,
)

__all__ = ["hu_slice_to_stored_pixels", "write_blurred_dicom_series"]
