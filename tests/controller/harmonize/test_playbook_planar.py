"""Unit tests for planar Harmonize (XR/US/MG) using checked-in test_dcm fixtures.

Isolation: CT/MR TotalSegmentator path must not run for these series.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset, dcmread
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller.ai.harmonize.pipeline import (
    _load_planar_series_dataset,
    _load_tseg_series_dataset,
    harmonize_series,
)
from anonymizer.controller.ai.harmonize.playbook_planar import (
    build_planar_harmonized_series_description,
    format_planar_series_description,
)
from anonymizer.controller.ai.harmonize.planar_profile import planar_profile_for_modality
from anonymizer.utils.modalities import (
    is_harmonize_modality,
    is_planar_harmonize_modality,
    is_tseg_modality,
)
from anonymizer.view.series.series import harmonize_button_visible
from tests.paths import REPO_ROOT

TEST_DCM = REPO_ROOT / "tests" / "controller" / "assets" / "test_dcm_files"
DAVIDSON_CXR = TEST_DCM / "davidson_cxr" / "davidson_cxr_monochrome1_uncompressed.dcm"
US_RGB = TEST_DCM / "us_rgb_single_frame" / "US_RGB_SingleFrame.dcm"
US_MULTI_FRAME = TEST_DCM / "us_multi_frame_grayscale" / "us_multi_frame_grayscale_JPG2000.dcm"


@pytest.fixture
def davidson_cxr_path() -> Path:
    assert DAVIDSON_CXR.is_file(), f"Missing fixture: {DAVIDSON_CXR}"
    return DAVIDSON_CXR


@pytest.fixture
def us_rgb_path() -> Path:
    assert US_RGB.is_file(), f"Missing fixture: {US_RGB}"
    return US_RGB


@pytest.fixture
def davidson_cxr_series_dir(tmp_path: Path, davidson_cxr_path: Path) -> Path:
    """Copy CXR into a series directory layout expected by harmonize_series."""
    series = tmp_path / "davidson_series"
    series.mkdir()
    dest = series / davidson_cxr_path.name
    dest.write_bytes(davidson_cxr_path.read_bytes())
    return series


@pytest.fixture
def us_rgb_series_dir(tmp_path: Path, us_rgb_path: Path) -> Path:
    series = tmp_path / "us_series"
    series.mkdir()
    dest = series / us_rgb_path.name
    dest.write_bytes(us_rgb_path.read_bytes())
    return series


def test_modality_gates_planar_vs_tseg() -> None:
    assert is_planar_harmonize_modality("CR")
    assert is_planar_harmonize_modality("DX")
    assert is_planar_harmonize_modality("US")
    assert is_planar_harmonize_modality("MG")
    assert not is_planar_harmonize_modality("CT")
    assert not is_planar_harmonize_modality("MR")
    assert not is_planar_harmonize_modality("SC")
    assert not is_planar_harmonize_modality("OT")
    assert not is_planar_harmonize_modality("DOC")

    assert is_tseg_modality("CT") and is_tseg_modality("MR")
    assert not is_tseg_modality("CR")
    assert is_harmonize_modality("CR") and is_harmonize_modality("US") and is_harmonize_modality("CT")
    assert not is_harmonize_modality("SC")

    assert planar_profile_for_modality("CR") is not None
    assert planar_profile_for_modality("CR").cohort == "XR"
    assert planar_profile_for_modality("US").loinc_prefix == "US "
    assert planar_profile_for_modality("CT") is None
    assert planar_profile_for_modality("SC") is None


def test_harmonize_button_visible_for_us_and_cxr() -> None:
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="US",
        already_harmonized=False,
    )
    assert harmonize_button_visible(
        harmonize_models_ready=True,
        modality="CR",
        already_harmonized=False,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="US",
        already_harmonized=True,
    )
    assert not harmonize_button_visible(
        harmonize_models_ready=True,
        modality="SC",
        already_harmonized=False,
    )


def test_davidson_cxr_playbook_from_dicom(davidson_cxr_path: Path) -> None:
    ds = dcmread(davidson_cxr_path, stop_before_pixels=True)
    assert ds.Modality == "CR"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert attrs.cohort == "XR"
    assert attrs.body_part_label == "Chest"
    assert attrs.view_code == "AP"
    assert description == "Chest AP"
    assert "Chest" in format_planar_series_description(attrs)


def test_us_rgb_playbook_from_dicom(us_rgb_path: Path) -> None:
    ds = dcmread(us_rgb_path, stop_before_pixels=True)
    assert ds.Modality == "US"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert attrs.cohort == "US"
    assert attrs.body_part_label == "Abdomen"
    assert description == "Abdomen"
    assert attrs.mode_code == ""


def test_us_multi_frame_axilla_from_study_description() -> None:
    assert US_MULTI_FRAME.is_file(), f"Missing fixture: {US_MULTI_FRAME}"
    ds = dcmread(US_MULTI_FRAME, stop_before_pixels=True)
    assert ds.Modality == "US"
    assert str(ds.get("StudyDescription") or "") == "US Biopsy Axilla"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert attrs.cohort == "US"
    assert attrs.body_part_label == "Axilla"
    assert description == "Axilla"
    assert "catalog:Axilla" in attrs.body_part_evidence or "AXILLA" in attrs.body_part_evidence.upper()


def test_us_axilla_study_description_beats_unspecified_series() -> None:
    ds = Dataset()
    ds.Modality = "US"
    ds.StudyDescription = "US Biopsy Axilla"
    ds.SeriesDescription = "US biopsy unspecified"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert description == "Axilla"
    assert attrs.body_part_label == "Axilla"


def test_xr_axillary_view_is_not_axilla_body_part() -> None:
    ds = Dataset()
    ds.Modality = "CR"
    ds.StudyDescription = "XR Shoulder"
    ds.SeriesDescription = "AP and Axillary"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert attrs.body_part_label == "Shoulder"
    assert description != "Axilla"


def test_load_planar_dataset_accepts_cxr_and_us(
    davidson_cxr_series_dir: Path,
    us_rgb_series_dir: Path,
) -> None:
    cxr = _load_planar_series_dataset(davidson_cxr_series_dir)
    us = _load_planar_series_dataset(us_rgb_series_dir)
    assert cxr is not None and cxr.Modality == "CR"
    assert us is not None and us.Modality == "US"
    assert _load_tseg_series_dataset(davidson_cxr_series_dir) is None
    assert _load_tseg_series_dataset(us_rgb_series_dir) is None


@patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_ct_single_pass")
def test_harmonize_series_davidson_cxr_never_calls_tseg(
    mock_single: MagicMock,
    mock_contrast: MagicMock,
    mock_regions: MagicMock,
    mock_geometry: MagicMock,
    davidson_cxr_series_dir: Path,
) -> None:
    results = harmonize_series([davidson_cxr_series_dir])
    assert len(results) == 1
    merged = results[0]
    assert merged.error is None
    assert merged.radlex_series_description == "Chest AP"
    assert merged.planar is not None
    assert merged.tseg is None
    assert merged.playbook is None
    mock_geometry.assert_not_called()
    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    mock_single.assert_not_called()


@patch("anonymizer.controller.ai.harmonize.pipeline.resolve_series_geometry")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_regions")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_contrast")
@patch("anonymizer.controller.ai.harmonize.pipeline.analyze_tseg_ct_single_pass")
def test_harmonize_series_us_rgb_never_calls_tseg(
    mock_single: MagicMock,
    mock_contrast: MagicMock,
    mock_regions: MagicMock,
    mock_geometry: MagicMock,
    us_rgb_series_dir: Path,
) -> None:
    results = harmonize_series([us_rgb_series_dir])
    assert len(results) == 1
    merged = results[0]
    assert merged.error is None
    assert merged.radlex_series_description == "Abdomen"
    assert merged.planar is not None
    assert merged.tseg is None
    mock_geometry.assert_not_called()
    mock_regions.assert_not_called()
    mock_contrast.assert_not_called()
    mock_single.assert_not_called()


def test_harmonize_series_sc_ignored(tmp_path: Path) -> None:
    series = tmp_path / "sc_series"
    series.mkdir()
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(series / "sc.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.Modality = "SC"
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.PatientID = "SC1"
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(series / "sc.dcm", write_like_original=False)

    results = harmonize_series([series])
    assert len(results) == 1
    assert results[0].error
    assert "CT/MR/XR/US/MG" in (results[0].error or "")


def test_mg_synthetic_headers() -> None:
    ds = Dataset()
    ds.Modality = "MG"
    ds.BodyPartExamined = "BREAST"
    ds.ImageLaterality = "L"
    ds.ViewPosition = "MLO"
    ds.SeriesDescription = "L MLO"
    description, attrs = build_planar_harmonized_series_description(ds)
    assert attrs.cohort == "MG"
    assert attrs.body_part_label == "Breast"
    assert attrs.laterality_code == "L"
    assert attrs.view_code == "MLO"
    assert description == "Breast L MLO"


def test_planar_loinc_ranks_chest_for_cxr_description() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(
        ["Chest AP"],
        loinc_prefix="XR ",
        top_n=5,
        image_count=1,
    )
    assert matches
    assert matches[0].long_common_name == "XR Chest AP"


def test_planar_loinc_ranks_two_views_from_image_count() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(
        ["Chest AP"],
        loinc_prefix="XR ",
        top_n=5,
        image_count=2,
    )
    assert matches
    assert matches[0].long_common_name == "XR Chest 2 Views"


def test_planar_loinc_ranks_three_views_from_image_count() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(
        ["Chest"],
        loinc_prefix="XR ",
        top_n=5,
        image_count=3,
    )
    assert matches
    assert matches[0].long_common_name == "XR Chest 3 Views"


def test_planar_loinc_ranks_abdomen_for_us_description() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(["Abdomen"], loinc_prefix="US ", top_n=5)
    assert matches
    assert matches[0].long_common_name == "US Abdomen"


def test_planar_loinc_ranks_axilla_for_us_description() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(["Axilla"], loinc_prefix="US ", top_n=5)
    assert matches
    assert matches[0].long_common_name == "US Axilla"


def test_planar_loinc_ranks_lower_extremity_from_playbook_string() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import (
        _planar_anatomy_from_descriptions,
        load_loinc_study_descriptions_for_prefix,
        rank_planar_loinc_study_descriptions,
    )

    series = ["Lower extremity AP"]
    assert _planar_anatomy_from_descriptions(series) == ["Lower extremity"]
    matches = rank_planar_loinc_study_descriptions(
        series,
        loinc_prefix="XR ",
        top_n=5,
        image_count=1,
    )
    assert matches
    assert any("lower extremity" in m.long_common_name.lower() for m in matches)
    catalog = {name for _code, name in load_loinc_study_descriptions_for_prefix("XR ")}
    assert all(m.long_common_name in catalog for m in matches)


def test_planar_loinc_ranks_right_lower_extremity_laterality() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import (
        _planar_laterality_from_descriptions,
        load_loinc_study_descriptions_for_prefix,
        rank_planar_loinc_study_descriptions,
    )

    series = ["Lower extremity R"]
    assert _planar_laterality_from_descriptions(series) == "R"
    matches = rank_planar_loinc_study_descriptions(
        series,
        loinc_prefix="XR ",
        top_n=5,
        image_count=1,
    )
    assert matches
    assert matches[0].long_common_name == "XR Lower extremity - right Single view"
    assert "left" not in matches[0].long_common_name.lower()
    catalog = {name for _code, name in load_loinc_study_descriptions_for_prefix("XR ")}
    assert all(m.long_common_name in catalog for m in matches)
    # Conflicting laterality must rank below matching side.
    right_scores = [m.score for m in matches if "right" in m.long_common_name.lower()]
    left_scores = [m.score for m in matches if "left" in m.long_common_name.lower()]
    assert right_scores
    if left_scores:
        assert min(right_scores) > max(left_scores)


def test_planar_loinc_ranks_bilat_wrist_laterality() -> None:
    from anonymizer.controller.ai.harmonize.loinc_study import rank_planar_loinc_study_descriptions

    matches = rank_planar_loinc_study_descriptions(
        ["Wrist Bilat"],
        loinc_prefix="XR ",
        top_n=5,
        image_count=2,
    )
    assert matches
    assert "bilateral" in matches[0].long_common_name.lower()
    assert "wrist" in matches[0].long_common_name.lower()
