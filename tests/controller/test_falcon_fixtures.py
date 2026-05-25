"""Tests for synthetic CT DICOM fixtures used by FALCON controller tests."""

from pathlib import Path

import pydicom
import pytest
from pydicom.data import get_testdata_file

from tests.controller.dicom_test_files import CT_STUDY_1_SERIES_4_IMAGES
from tests.controller.falcon_fixtures import (
    CT_SMALL_TEMPLATE,
    DEFAULT_SYNTHETIC_SLICE_COUNT,
    FALCON_MIN_SLICES,
    build_synthetic_ct_series,
    list_dcm_files,
)


class TestBuildSyntheticCtSeries:
    def test_synthetic_series_has_at_least_eleven_dcm_files(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_series(tmp_path / "series")

        dcm_files = list_dcm_files(series_dir)

        assert len(dcm_files) >= FALCON_MIN_SLICES
        assert len(dcm_files) == DEFAULT_SYNTHETIC_SLICE_COUNT

    def test_synthetic_series_files_are_valid_dicom(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_series(tmp_path / "series")

        for dcm_path in list_dcm_files(series_dir):
            ds = pydicom.dcmread(dcm_path)
            assert ds.Modality == "CT"
            assert ds.SOPClassUID is not None
            assert ds.pixel_array.shape == (128, 128)

    def test_synthetic_series_has_distinct_slice_positions(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_series(tmp_path / "series")

        z_positions = []
        for dcm_path in list_dcm_files(series_dir):
            ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
            z_positions.append(float(ds.ImagePositionPatient[2]))

        assert len(z_positions) == DEFAULT_SYNTHETIC_SLICE_COUNT
        assert z_positions == sorted(z_positions)
        assert len(set(z_positions)) == DEFAULT_SYNTHETIC_SLICE_COUNT

    def test_synthetic_series_uses_ct_small_as_template(self, tmp_path: Path) -> None:
        template = pydicom.dcmread(get_testdata_file(CT_SMALL_TEMPLATE))
        series_dir = build_synthetic_ct_series(tmp_path / "series")
        sample = pydicom.dcmread(list_dcm_files(series_dir)[0])

        assert sample.Modality == template.Modality
        assert sample.Rows == template.Rows
        assert sample.Columns == template.Columns
        assert list(sample.PixelSpacing) == list(template.PixelSpacing)
        assert list(sample.ImageOrientationPatient) == list(template.ImageOrientationPatient)
        assert float(sample.RescaleSlope) == float(template.RescaleSlope)
        assert int(sample.RescaleIntercept) == int(template.RescaleIntercept)

    def test_build_rejects_fewer_than_eleven_slices(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="num_slices must be at least 11"):
            build_synthetic_ct_series(tmp_path / "series", num_slices=10)


class TestPydicomStockCtData:
    def test_pydicom_stock_ct_slice_count_below_falcon_minimum(self) -> None:
        stock_slice_count = len(CT_STUDY_1_SERIES_4_IMAGES)

        assert stock_slice_count < FALCON_MIN_SLICES

        for relative_path in CT_STUDY_1_SERIES_4_IMAGES:
            assert get_testdata_file(relative_path.lstrip("./")) is not None
