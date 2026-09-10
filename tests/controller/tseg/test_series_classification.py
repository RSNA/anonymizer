"""Unit tests for structured TS eligibility classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.ai.tseg.dicom_geometry import analyze_series_geometry
from anonymizer.controller.ai.tseg.series_classification import (
    description_suggests_angio_sequence,
    description_suggests_monitoring,
    description_suggests_parametric_map,
    evaluate_ts_suitability,
    metadata_diagnostic_fallback_allowed,
)
from tests.controller.tseg.support.synthetic_ct import (
    build_synthetic_breast_adc_mr_series,
    build_synthetic_breast_mr_anatomical_series,
    build_synthetic_chest_ct_series,
    build_synthetic_ct_perfusion_map_series,
    build_synthetic_survey_mr_series,
)


def test_parametric_keywords_include_ct_perfusion(tmp_path: Path) -> None:
    series_dir = build_synthetic_ct_perfusion_map_series(tmp_path / "perf")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.ts_suitable is False
    assert geometry.ts_skip_category == "parametric_map"


def test_survey_thick_slices_classified_as_localizer(tmp_path: Path) -> None:
    series_dir = build_synthetic_survey_mr_series(tmp_path / "survey")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.dimensionality == "localizer_2d"
    assert geometry.ts_suitable is False
    assert geometry.ts_skip_category == "localizer"


def test_breast_anatomical_mr_skips_ts_for_body_part(tmp_path: Path) -> None:
    series_dir = build_synthetic_breast_mr_anatomical_series(tmp_path / "breast_t2")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.dimensionality == "volume_3d"
    assert geometry.ts_suitable is False
    assert geometry.ts_skip_category == "body_part_no_roi"


def test_angio_sequence_detection() -> None:
    assert description_suggests_angio_sequence("BRAIN TOF MRA WO")
    assert not description_suggests_angio_sequence("CHEST T2 AXIAL")
    assert description_suggests_angio_sequence("CTA CHEST AXIAL")
    assert not description_suggests_angio_sequence("PE CHEST 2.5MM")


def test_cta_study_description_does_not_skip_diagnostic_chest_series(tmp_path: Path) -> None:
    """A CTA-labeled study must not block TS on a non-angio chest series."""
    from pydicom import dcmread

    series_dir = build_synthetic_chest_ct_series(tmp_path / "pe_chest")
    for path in series_dir.glob("*.dcm"):
        ds = dcmread(path)
        ds.StudyDescription = "CTA CHEST W/O & W IV CON"
        ds.SeriesDescription = "PE CHEST 2.5mm"
        ds.save_as(path)

    geometry = analyze_series_geometry(series_dir)
    assert geometry.ts_suitable is True
    assert geometry.ts_skip_category is None


def test_adc_still_parametric_when_derived(tmp_path: Path) -> None:
    from anonymizer.controller.ai.tseg.dicom_geometry import read_series_headers

    series_dir = build_synthetic_breast_adc_mr_series(tmp_path / "adc")
    headers = read_series_headers(series_dir)
    assert description_suggests_parametric_map(headers)


def test_diagnostic_chest_ct_remains_ts_eligible(tmp_path: Path) -> None:
    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    geometry = analyze_series_geometry(series_dir)
    assert geometry.ts_suitable is True
    assert geometry.ts_skip_category is None


@pytest.mark.parametrize(
    ("description", "category"),
    [
        ("BRAIN MRS SVS", "spectroscopy"),
        ("LIVER CSI SPECTROSCOPY", "spectroscopy"),
    ],
)
def test_spectroscopy_skip_category(description: str, category: str) -> None:
    from anonymizer.controller.ai.tseg.dicom_geometry import StackMetrics

    suitability = evaluate_ts_suitability(
        dimensionality="volume_3d",
        provenance="original",
        headers=[],
        stack=StackMetrics(40, 3.0, 120.0, 1.0),
    )
    assert suitability.suitable is True

    from pydicom import Dataset

    header = Dataset()
    header.SeriesDescription = description
    suitability = evaluate_ts_suitability(
        dimensionality="volume_3d",
        provenance="original",
        headers=[header],
        stack=StackMetrics(40, 3.0, 120.0, 1.0),
    )
    assert suitability.suitable is False
    assert suitability.skip_category == category


def test_metadata_fallback_allows_single_slice() -> None:
    assert metadata_diagnostic_fallback_allowed("single_slice")
    assert metadata_diagnostic_fallback_allowed("body_part_no_roi")
    assert not metadata_diagnostic_fallback_allowed("localizer")
    assert not metadata_diagnostic_fallback_allowed("parametric_map")


def test_smart_prep_is_monitoring() -> None:
    assert description_suggests_monitoring("PE SMART PREP LEFT ATRIUM")
    assert description_suggests_monitoring("SMARTPREP")
    assert not description_suggests_monitoring("CT CHEST PULMONARY EMBOLISM (CTPE)")
