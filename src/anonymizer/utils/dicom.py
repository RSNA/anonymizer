"""DICOM standard constants and dataset tag helpers (pydicom only).

Public API
----------
C_SUCCESS
    C success (0).

C_STORE_PROCESSING_FAILURE
    C store processing failure (272).

C_STORE_OUT_OF_RESOURCES
    C store out of resources (42752).

C_MOVE_UNKNOWN_AE
    C move unknown ae (43009).

C_STORE_DATASET_ERROR
    C store dataset error (43264).

C_CANCEL
    C cancel (65024).

C_PENDING_A
    C pending a (65280).

C_PENDING_B
    C pending b (65281).

C_SOP_CLASS_INVALID
    C sop class invalid (49939).

C_WARNING
    C warning (45056).

C_FAILURE
    C failure (49152).

C_DATA_ELEMENT_DOES_NOT_EXIST
    C data element does not exist (263).

C_STORE_DECODE_ERROR
    C store decode error (49680).

C_STORE_UNRECOGNIZED_OPERATION
    C store unrecognized operation (49681).

SUPPORTED_PHOTOMETRIC_INTERPRETATIONS
    Supported photometric interpretations.

DeidMethodCode
    DCM code value from PS3.16 CID 7050 (De-identification Method).

deid_method_meaning(code: DeidMethodCode) -> str
    English CID 7050 code meaning for code.

record_deid_method_codes(ds: Dataset, codes: Iterable[DeidMethodCode]) -> tuple[int, ...]
    Record executed de-identification options in ds.

get_wl_ww(ds: Dataset) -> tuple[float, float]
    Read WindowCenter / WindowWidth from ds, with defaults from BitsAllocated.
"""
import logging
from collections.abc import Iterable
from enum import IntEnum

from pydicom import Dataset, multival
from pydicom.sequence import Sequence

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

class DeidMethodCode(IntEnum):
    """DCM code value from PS3.16 CID 7050 (De-identification Method)."""

    BASIC = 113100
    CLEAN_PIXEL_DATA = 113101
    CLEAN_VISUAL_FEATURES = 113102
    CLEAN_GRAPHICS = 113103
    CLEAN_STRUCTURED_CONTENT = 113104
    CLEAN_DESCRIPTORS = 113105
    FULL_DATES = 113106
    MODIFIED_DATES = 113107
    PATIENT_CHARACTERISTICS = 113108
    DEVICE_IDENTITY = 113109
    RETAIN_UIDS = 113110
    SAFE_PRIVATE = 113111
    INSTITUTION_IDENTITY = 113112


def _mark_for_translation(text: str) -> str:
    """
    Identity marker so xgettext extracts a UI string (see locales scripts).

    deid_method_meaning must always return the English DICOM text, so the
    meanings cannot be wrapped in _() here; the UI translates them at the
    call site.

    Args:
        text: English string to mark.

    Returns:
        text unchanged.
    """
    return text


_MEANING: dict[DeidMethodCode, str] = {
    DeidMethodCode.BASIC: _mark_for_translation("Basic Application Confidentiality Profile"),
    DeidMethodCode.CLEAN_PIXEL_DATA: _mark_for_translation("Clean Pixel Data Option"),
    DeidMethodCode.CLEAN_VISUAL_FEATURES: _mark_for_translation("Clean Recognizable Visual Features Option"),
    DeidMethodCode.CLEAN_GRAPHICS: _mark_for_translation("Clean Graphics Option"),
    DeidMethodCode.CLEAN_STRUCTURED_CONTENT: _mark_for_translation("Clean Structured Content Option"),
    DeidMethodCode.CLEAN_DESCRIPTORS: _mark_for_translation("Clean Descriptors Option"),
    DeidMethodCode.FULL_DATES: _mark_for_translation("Retain Longitudinal Temporal Information Full Dates Option"),
    DeidMethodCode.MODIFIED_DATES: _mark_for_translation("Retain Longitudinal Temporal Information Modified Dates Option"),
    DeidMethodCode.PATIENT_CHARACTERISTICS: _mark_for_translation("Retain Patient Characteristics Option"),
    DeidMethodCode.DEVICE_IDENTITY: _mark_for_translation("Retain Device Identity Option"),
    DeidMethodCode.RETAIN_UIDS: _mark_for_translation("Retain UIDs Option"),
    DeidMethodCode.SAFE_PRIVATE: _mark_for_translation("Retain Safe Private Option"),
    DeidMethodCode.INSTITUTION_IDENTITY: _mark_for_translation("Retain Institution Identity Option"),
}


def deid_method_meaning(code: DeidMethodCode) -> str:
    """
    English CID 7050 code meaning for code.

    The return value is the gettext msgid: _(deid_method_meaning(code))
    is the UI label. The DICOM Code Meaning uses the return value with no
    gettext call.

    Args:
        code: De-identification method to describe.

    Returns:
        The English CID 7050 code meaning.

    Raises:
        KeyError: If code has no meaning entry.
    """
    return _MEANING[DeidMethodCode(code)]


def record_deid_method_codes(ds: Dataset, codes: Iterable[DeidMethodCode]) -> tuple[int, ...]:
    """
    Record executed de-identification options in ds.

    Appends one DCM item per code to DeidentificationMethodCodeSequence
    (0012,0064), skipping codes already present. Creates the sequence
    when absent.

    Args:
        ds: Dataset to mutate.
        codes: Options that have been executed on ds.

    Returns:
        The code values now present, in sequence order.
    """
    sequence = ds.get("DeidentificationMethodCodeSequence")
    if sequence is None:
        sequence = Sequence()
        ds.DeidentificationMethodCodeSequence = sequence
    present: list[int] = []
    for item in sequence:
        raw = str(getattr(item, "CodeValue", "") or "").strip()
        if raw.isdigit():
            present.append(int(raw))
    for code in codes:
        member = DeidMethodCode(code)
        if int(member) in present:
            continue
        item = Dataset()
        item.CodeValue = str(int(member))
        item.CodingSchemeDesignator = "DCM"
        item.CodeMeaning = deid_method_meaning(member)
        sequence.append(item)
        present.append(int(member))
    return tuple(present)


def get_wl_ww(ds: Dataset) -> tuple[float, float]:
    """Read WindowCenter / WindowWidth from ds, with defaults from BitsAllocated."""
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
