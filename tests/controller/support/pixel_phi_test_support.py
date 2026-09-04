"""Shared helpers for synthetic burnt-in PHI controller tests."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pydicom

from anonymizer.model.anonymizer import AnonymizerModel
from tests.controller.tseg.support.synthetic_ct import DEFAULT_BURNED_IN_PHI_LINES, list_dcm_files


def easyocr_results_for_lines(
    lines: Sequence[str],
    *,
    origin: tuple[int, int] = (24, 40),
    line_spacing_px: int = 32,
    char_width_px: int = 12,
    box_height_px: int = 24,
    confidence: float = 0.95,
) -> list:
    """Build EasyOCR-style tuples aligned with synthetic overlay placement."""
    results = []
    x0, y0 = origin
    for index, line in enumerate(lines):
        y1 = y0 + index * line_spacing_px
        x1 = x0 + max(len(line) * char_width_px, box_height_px)
        y2 = y1 + box_height_px
        results.append(
            [
                [(x0, y1), (x1, y1), (x1, y2), (x0, y2)],
                line,
                confidence,
            ]
        )
    return results


def easyocr_results_for_default_phi() -> list:
    return easyocr_results_for_lines(DEFAULT_BURNED_IN_PHI_LINES)


def register_series_with_anonymizer(series_dir: Path, model: AnonymizerModel) -> tuple[str, str]:
    """
    Capture all slices in the model and rewrite DICOM files with anonymized UIDs.

    Returns ``(anon_series_uid, phi_patient_id)`` for the registered series.
    """
    paths = list_dcm_files(series_dir)
    if not paths:
        raise ValueError(f"No DICOM files under {series_dir}")

    phi_patient_id = str(pydicom.dcmread(paths[0]).PatientID)
    for path in paths:
        model.capture_phi(source="pytest", ds=pydicom.dcmread(path), date_offset_from_hash=0)

    phi = model.get_phi_by_phi_patient_id(phi_patient_id)
    if phi is None:
        raise RuntimeError(f"PHI patient {phi_patient_id} was not captured")

    first = pydicom.dcmread(paths[0])
    study = next(item for item in phi.studies if item.study_uid == str(first.StudyInstanceUID))
    series = next(item for item in study.series if item.series_uid == str(first.SeriesInstanceUID))

    for path in paths:
        ds = pydicom.dcmread(path)
        instance = next(item for item in series.instances if item.sop_instance_uid == str(ds.SOPInstanceUID))
        ds.PatientID = phi.anon_patient_id
        ds.StudyInstanceUID = study.anon_study_uid
        ds.SeriesInstanceUID = series.anon_series_uid
        ds.SOPInstanceUID = instance.anon_sop_instance_uid
        ds.save_as(path)

    return series.anon_series_uid, phi_patient_id


def build_synthetic_chest_ct_series_with_two_phi_slices(output_dir: Path) -> Path:
    from tests.controller.tseg.support.synthetic_ct import apply_burned_in_phi_to_dicom, build_synthetic_chest_ct_series

    series_dir = build_synthetic_chest_ct_series(output_dir)
    paths = list_dcm_files(series_dir)
    apply_burned_in_phi_to_dicom(paths[0], ("SMITH^JOHN", "01-Jan-2024"))
    apply_burned_in_phi_to_dicom(paths[1], ("SMITH^JOHN", "ACC12345"))
    return series_dir
