"""Expected AI batch removal results matching real UX workflow logs.

Batch removal loads the default modality whitelist (``whitelist=None`` in
``remove_pixel_phi``). Unit tests must NOT pass ``whitelist=[]``, which bypasses
that whitelist and inflates removed-text / pixel counts.

Workflow log lines never include OCR/PHI strings — only Series View wording and counts.
"""

from dataclasses import dataclass

from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.support.us_rgb_fixtures import (
    US_RGB_BATCH_PIXELS_CHANGED,
    US_RGB_BATCH_REMOVED_TEXTS,
    US_RGB_DCM,
)

US_MULTI_FRAME_DCM = (
    CONTROLLER_TEST_DCM_FILES_DIR
    / "us_multi_frame_grayscale"
    / "us_multi_frame_grayscale_JPG2000.dcm"
)
DAVIDSON_CXR_DCM = (
    CONTROLLER_TEST_DCM_FILES_DIR
    / "davidson_cxr"
    / "davidson_cxr_monochrome1_uncompressed.dcm"
)


@dataclass(frozen=True)
class BatchUxExpectation:
    """One DICOM instance processed by AI batch Remove Burnt-in Annotation."""

    label: str
    dcm_path: str
    modality: str
    removed_texts: tuple[str, ...]
    pixels_changed: int
    instance_log_tokens: tuple[str, ...]
    series_log_tokens: tuple[str, ...]


def _safe_log_tokens(*, region_count: int, pixels_changed: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    del pixels_changed
    phi = f"{region_count} PHI removed"
    instance = ("Remove Text", "Black out text", phi)
    series = ("PHI removed", "Remove Text", "Black out text", phi)
    return instance, series


_US_MULTI_REMOVED = (
    "LOGIQ",
    "E9",
    "23/Aug/ 1949",
    "16.60.27",
    "TRANS",
    "AXILLA",
    "Christopher",
    "Robinson",
    "16:37:16",
    "Daniel",
    "Smith",
    "14:05:5",
    "Carrie",
    "Ellis",
    "10:48.20",
    "11:02:10",
    "Bailey",
    "Jose",
    "Kelly",
    "Matthews",
    "02.59.58",
    "Navarrosarah",
    "Evan",
    "Perez",
    "08844818",
    "07 / Jan/ 1952",
    "01:15828",
    "Olivia",
    "Diaz",
    "18:1 8:ZEfT",
    "CHBec/1999",
    "14:47:16",
    "01819814",
    "07/Jan",
    "/2098 /Mar / 1958",
    "Stephen",
    "Griffith",
    "07:29.37",
    "Debrd",
    "16:10.51",
    "26/Oct / 1944",
    "12/ Oct / 1964",
)
_US_MULTI_INSTANCE, _US_MULTI_SERIES = _safe_log_tokens(
    region_count=len(_US_MULTI_REMOVED),
    pixels_changed=489_805,
)
_US_RGB_INSTANCE, _US_RGB_SERIES = _safe_log_tokens(
    region_count=len(US_RGB_BATCH_REMOVED_TEXTS),
    pixels_changed=US_RGB_BATCH_PIXELS_CHANGED,
)
_DAVIDSON_REMOVED = (
    "DAVIDSON",
    "DOUGLAS [M]",
    "01.09.2012",
    "Semi-Upright",
    "DOB: 06.16.1976",
)
_DAVIDSON_INSTANCE, _DAVIDSON_SERIES = _safe_log_tokens(
    region_count=len(_DAVIDSON_REMOVED),
    pixels_changed=72_756,
)


BATCH_UX_EXPECTATIONS: tuple[BatchUxExpectation, ...] = (
    BatchUxExpectation(
        label="US multi-frame axilla (Study 1/3)",
        dcm_path=str(US_MULTI_FRAME_DCM),
        modality="US",
        removed_texts=_US_MULTI_REMOVED,
        pixels_changed=489_805,
        instance_log_tokens=_US_MULTI_INSTANCE,
        series_log_tokens=_US_MULTI_SERIES,
    ),
    BatchUxExpectation(
        label="US RGB single-frame (Study 2/3 · USS ABDOMEN)",
        dcm_path=str(US_RGB_DCM),
        modality="US",
        removed_texts=tuple(US_RGB_BATCH_REMOVED_TEXTS),
        pixels_changed=US_RGB_BATCH_PIXELS_CHANGED,
        instance_log_tokens=_US_RGB_INSTANCE,
        series_log_tokens=_US_RGB_SERIES,
    ),
    BatchUxExpectation(
        label="Davidson CXR (Study 3/3)",
        dcm_path=str(DAVIDSON_CXR_DCM),
        modality="CR",
        removed_texts=_DAVIDSON_REMOVED,
        pixels_changed=72_756,
        instance_log_tokens=_DAVIDSON_INSTANCE,
        series_log_tokens=_DAVIDSON_SERIES,
    ),
)
