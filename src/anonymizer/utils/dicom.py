"""DICOM standard constants and dataset tag helpers (pydicom only)."""

from __future__ import annotations

import logging

from pydicom import Dataset, multival

logger = logging.getLogger(__name__)

# PS3.7 C-FIND/C-STORE/C-MOVE status codes (network layer)
C_SUCCESS = 0x0000
C_STORE_PROCESSING_FAILURE = 0x0110
C_STORE_OUT_OF_RESOURCES = 0xA700
C_MOVE_UNKNOWN_AE = 0xA801
C_STORE_DATASET_ERROR = 0xA900
C_CANCEL = 0xFE00
C_PENDING_A = 0xFF00
C_PENDING_B = 0xFF01
C_SOP_CLASS_INVALID = 0xC313
C_WARNING = 0xB000
C_FAILURE = 0xC000
C_DATA_ELEMENT_DOES_NOT_EXIST = 0x0107
C_STORE_DECODE_ERROR = 0xC210
C_STORE_UNRECOGNIZED_OPERATION = 0xC211

# PS3.3 photometric interpretations supported for series I/O
SUPPORTED_PHOTOMETRIC_INTERPRETATIONS = frozenset(
    {
        "MONOCHROME1",
        "MONOCHROME2",
        "RGB",
        "YBR_FULL",
        "YBR_FULL_422",
        "YBR_ICT",
        "YBR_RCT",
        "PALETTE COLOR",
        "YBR_PARTIAL_420",
    }
)

__all__ = [
    "C_CANCEL",
    "C_DATA_ELEMENT_DOES_NOT_EXIST",
    "C_FAILURE",
    "C_MOVE_UNKNOWN_AE",
    "C_PENDING_A",
    "C_PENDING_B",
    "C_SOP_CLASS_INVALID",
    "C_STORE_DATASET_ERROR",
    "C_STORE_DECODE_ERROR",
    "C_STORE_OUT_OF_RESOURCES",
    "C_STORE_PROCESSING_FAILURE",
    "C_STORE_UNRECOGNIZED_OPERATION",
    "C_SUCCESS",
    "C_WARNING",
    "SUPPORTED_PHOTOMETRIC_INTERPRETATIONS",
    "get_wl_ww",
]


def get_wl_ww(ds: Dataset) -> tuple[float, float]:
    """Read WindowCenter / WindowWidth from ``ds``, with defaults from BitsAllocated."""
    wl_from_ds = ds.get("WindowCenter", None)
    ww_from_ds = ds.get("WindowWidth", None)
    bits_allocated = ds.get("BitsAllocated", None)

    wl_float: float
    ww_float: float

    if wl_from_ds is None or ww_from_ds is None:
        logger.debug(
            "WindowCenter or WindowWidth not found in DICOM dataset. Using default values."
        )
        if bits_allocated == 8:
            wl_float = 127.5
            ww_float = 255.0
        elif bits_allocated == 16:
            wl_float = 32768.0
            ww_float = 65535.0
        elif bits_allocated == 12:
            wl_float = 2048.0
            ww_float = 4096.0
        elif bits_allocated == 10:
            wl_float = 512.0
            ww_float = 1024.0
        elif bits_allocated == 32:
            wl_float = 2147483648.0
            ww_float = 4294967295.0
        else:
            raise ValueError(f"Unsupported BitsAllocated value: {bits_allocated}")
        return wl_float, ww_float

    if isinstance(wl_from_ds, multival.MultiValue):
        wl_float = float(wl_from_ds[0]) if len(wl_from_ds) > 0 else 0.0
    else:
        wl_float = float(wl_from_ds)

    if isinstance(ww_from_ds, multival.MultiValue):
        ww_float = float(ww_from_ds[0]) if len(ww_from_ds) > 0 else 1.0
    else:
        ww_float = float(ww_from_ds)

    if ww_float < 1.0:
        logger.warning(
            "DICOM WindowWidth (%s) is less than 1. Setting to 1.", ww_from_ds
        )
        ww_float = 1.0

    return wl_float, ww_float
