"""Tests for utils.dicom tag helpers and constants."""

from __future__ import annotations

import logging

import pytest
from pydicom import Dataset, multival
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

from anonymizer.utils.dicom import get_wl_ww


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


class TestGetWlWw:
    def test_get_wl_ww_present_single_value(self):
        ds = create_basic_dataset()
        ds.WindowCenter = 100
        ds.WindowWidth = 200
        wl, ww = get_wl_ww(ds)
        assert wl == 100.0
        assert ww == 200.0

    def test_get_wl_ww_present_multivalue(self):
        ds = create_basic_dataset()
        ds.WindowCenter = multival.MultiValue(float, [50.5, 60])
        ds.WindowWidth = multival.MultiValue(float, [150.0, 180])
        wl, ww = get_wl_ww(ds)
        assert wl == 50.5
        assert ww == 150.0

    def test_get_wl_ww_width_less_than_1(self, caplog: pytest.LogCaptureFixture):
        ds = create_basic_dataset()
        ds.WindowCenter = 100
        ds.WindowWidth = 0.5
        with caplog.at_level(logging.WARNING):
            wl, ww = get_wl_ww(ds)
        assert wl == 100.0
        assert ww == 1.0
        assert "DICOM WindowWidth (0.5) is less than 1. Setting to 1." in caplog.text

    @pytest.mark.parametrize(
        "bits_allocated, expected_wl, expected_ww",
        [
            (8, 127.5, 255.0),
            (16, 32768.0, 65535.0),
            (12, 2048.0, 4096.0),
            (10, 512.0, 1024.0),
            (32, 2147483648.0, 4294967295.0),
        ],
    )
    def test_get_wl_ww_missing_defaults(self, bits_allocated, expected_wl, expected_ww):
        ds = create_basic_dataset()
        ds.BitsAllocated = bits_allocated
        if "WindowCenter" in ds:
            del ds.WindowCenter
        if "WindowWidth" in ds:
            del ds.WindowWidth

        wl, ww = get_wl_ww(ds)
        assert wl == expected_wl
        assert ww == expected_ww

    def test_get_wl_ww_missing_unsupported_bits(self):
        ds = create_basic_dataset()
        ds.BitsAllocated = 7
        with pytest.raises(ValueError, match="Unsupported BitsAllocated value: 7"):
            get_wl_ww(ds)

    def test_get_wl_ww_missing_bits_allocated(self):
        ds = create_basic_dataset()
        with pytest.raises(ValueError, match="Unsupported BitsAllocated value: None"):
            get_wl_ww(ds)
