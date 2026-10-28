"""Clean* option stamp coupling and Clean Graphics not-executed guards."""

from __future__ import annotations

from pathlib import Path

from pydicom import dcmread
from pydicom.data import get_testdata_file
from pydicom.dataset import Dataset

import pytest

from anonymizer.controller.ai.feature_availability import deid_option_ready
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import AT_INGEST, BASIC_OPTIONS, NOT_EXECUTED
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU


def _codes_on(ds: Dataset) -> set[str]:
    seq = getattr(ds, "DeidentificationMethodCodeSequence", None)
    if not seq:
        return set()
    return {str(item.CodeValue) for item in seq}


def test_clean_graphics_never_ready_and_not_executed() -> None:
    """Clean Graphics is intentionally unimplemented."""
    assert DeidMethodCode.CLEAN_GRAPHICS in NOT_EXECUTED
    assert DeidMethodCode.CLEAN_GRAPHICS not in AT_INGEST
    assert not deid_option_ready(DeidMethodCode.CLEAN_GRAPHICS)


def test_clean_graphics_absent_from_method_sequence_after_ingest(
    controller: ProjectController,
) -> None:
    """Selecting Clean Graphics with Basic still does not stamp 113103 at ingest."""
    controller.apply_confidentiality_options(
        BASIC_OPTIONS | {DeidMethodCode.CLEAN_GRAPHICS}
    )
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "GRAPHICS-NEVER"
    ds.StudyDate = "20200115"
    ds.SOPInstanceUID = "1.2.840.10008.graphics.never.1"
    assert controller.anonymizer.anonymize(LocalSCU, ds) is None
    assert str(int(DeidMethodCode.CLEAN_GRAPHICS)) not in _codes_on(ds)
    assert _codes_on(ds) == {str(int(DeidMethodCode.BASIC))}


@pytest.mark.parametrize(
    "code",
    [
        DeidMethodCode.CLEAN_PIXEL_DATA,
        DeidMethodCode.CLEAN_VISUAL_FEATURES,
    ],
)
def test_clean_pixel_and_visual_stamp_codes(code: DeidMethodCode) -> None:
    """
    AI success paths record the matching CID 7050 cleaning code.

    Mirrors record_deid_method_codes call sites in remove_pixel_phi and
    face-blur export (controller-level contract without running OCR/TS).
    """
    ds = Dataset()
    present = record_deid_method_codes(ds, {code})
    assert int(code) in present
    codes = {str(item.CodeValue) for item in ds.DeidentificationMethodCodeSequence}
    assert str(int(code)) in codes


def test_clean_pixel_and_visual_stamp_sites_use_expected_enums() -> None:
    """Source coupling: pixel/face modules stamp the Clean Pixel / Visual codes."""
    import anonymizer.controller.ai.blur_face.pipeline as face_mod
    import anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi as pixel_mod

    pixel_src = Path(pixel_mod.__file__).read_text(encoding="utf-8")
    face_src = Path(face_mod.__file__).read_text(encoding="utf-8")
    assert "CLEAN_PIXEL_DATA" in pixel_src
    assert "record_deid_method_codes" in pixel_src
    assert "CLEAN_VISUAL_FEATURES" in face_src
    assert "record_deid_method_codes" in face_src
