# test_series_io.py

from pathlib import Path

import numpy as np
import pytest
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from anonymizer.controller.series_io import (
    _rows_cols_from_pixel_array,
    apply_series_description,
    clip_and_cast_to_int,
)


def create_basic_dataset() -> Dataset:
    ds = Dataset()
    ds.PatientID = "TestPatientID"
    ds.StudyInstanceUID = "1.2.3"
    ds.SeriesInstanceUID = "1.2.3.4"
    ds.SeriesDescription = "Test Series"
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    return ds


class TestClipAndCastToInt:
    def test_clip_cast_uint16_no_clipping(self, caplog):
        float_arr = np.array([0.0, 100.5, 65535.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        expected = np.array([0, 100, 65535], dtype=np.uint16)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert not any("Values were clipped" in record.message for record in caplog.records)

    def test_clip_cast_uint16_with_clipping(self, caplog):
        float_arr = np.array([-10.0, 300.7, 70000.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        expected = np.array([0, 300, 65535], dtype=np.uint16)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert any(
            record.levelname == "WARNING"
            and "Values were clipped during conversion to <class 'numpy.uint16'>" in record.message
            and "Original range [-10.0..70000.0], Target range [0..65535]" in record.message
            for record in caplog.records
        )

    def test_non_float_input(self, caplog: pytest.LogCaptureFixture):
        int_arr = np.array([0, 100, 200], dtype=np.int32)
        result = clip_and_cast_to_int(int_arr, np.uint8)
        expected = np.array([0, 100, 200], dtype=np.uint8)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert (f"Input array dtype is not float ({int_arr.dtype}), attempting conversion anyway.") in caplog.text

    def test_non_integer_target(self, caplog: pytest.LogCaptureFixture):
        float_arr = np.array([0.0, 1.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.float32)  # type: ignore[arg-type]
        assert result is None
        assert f"Target dtype {np.float32} is not an integer type." in caplog.text
        assert any(record.levelname == "ERROR" for record in caplog.records)

    def test_exception_handling(self, monkeypatch, caplog: pytest.LogCaptureFixture):
        def _raise_iinfo_error(*_args, **_kwargs):
            raise Exception("Test iinfo error")

        monkeypatch.setattr("anonymizer.controller.series_io.np.iinfo", _raise_iinfo_error)
        float_arr = np.array([0.0, 1.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        assert result is None
        assert "Test iinfo error" in caplog.text
        assert any(record.levelname == "ERROR" for record in caplog.records)


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ((600, 800), (600, 800)),
        ((852, 1136, 3), (852, 1136)),
        ((1, 600, 800, 3), (600, 800)),
        ((5, 600, 800, 3), (600, 800)),
        ((5, 600, 800), (600, 800)),
    ],
)
def test_rows_cols_from_pixel_array(shape: tuple[int, ...], expected: tuple[int, int]) -> None:
    pixels = np.zeros(shape, dtype=np.uint8)
    assert _rows_cols_from_pixel_array(pixels) == expected


def test_rows_cols_from_pixel_array_rejects_old_rgb_bug_assignment() -> None:
    """Regression: shape[-2], shape[-1] on (H, W, 3) wrote Columns=3."""
    pixels = np.zeros((852, 1136, 3), dtype=np.uint8)
    buggy_rows, buggy_cols = pixels.shape[-2], pixels.shape[-1]
    assert (buggy_rows, buggy_cols) == (1136, 3)
    assert _rows_cols_from_pixel_array(pixels) == (852, 1136)


def test_apply_series_description_preserves_pixel_data(tmp_path: Path) -> None:
    from pydicom import dcmread

    from tests.controller.tseg.support.synthetic_ct import build_synthetic_chest_ct_series

    series_dir = build_synthetic_chest_ct_series(tmp_path / "chest")
    sample_path = sorted(series_dir.glob("*.dcm"))[0]
    before_pixels = dcmread(sample_path).pixel_array.copy()

    assert apply_series_description(series_dir, "Brain Ax EarlyArt") is True

    after = dcmread(sample_path)
    assert after.SeriesDescription == "Brain Ax EarlyArt"
    assert after.pixel_array.shape == before_pixels.shape
    assert np.array_equal(after.pixel_array, before_pixels)
