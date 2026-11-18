"""Tests for description apply OAS policy (off by default; helpers retained)."""

from pathlib import Path

import numpy as np
import pytest
from pydicom import Dataset, dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

import anonymizer.controller.series.series_io as series_io
from anonymizer.controller.series.series_io import apply_series_description
from anonymizer.utils.version import get_version


def _write_minimal_series(
    series_dir: Path,
    *,
    series_description: str,
    institution_name: str | None = None,
    department_name: str | None = None,
    source_ae_title: str | None = None,
) -> Path:
    series_dir.mkdir(parents=True, exist_ok=True)
    path = series_dir / "1.dcm"
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    if source_ae_title is not None:
        file_meta.SourceApplicationEntityTitle = source_ae_title
    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.SeriesDescription = series_description
    if institution_name is not None:
        ds.InstitutionName = institution_name
    if department_name is not None:
        ds.InstitutionalDepartmentName = department_name
    ds.Rows = 8
    ds.Columns = 8
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.PixelData = np.zeros((8, 8), dtype=np.uint16).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path


def test_apply_series_description_does_not_write_oas_by_default(tmp_path: Path) -> None:
    """Priors stay in PHI DB / Lookup — exported files must not get OAS description history."""
    series_dir = tmp_path / "series"
    path = _write_minimal_series(series_dir, series_description="SCOUT WITH PATIENT NAME")
    assert apply_series_description(series_dir, "CT Chest Ax PortVen") is True
    ds = dcmread(str(path))
    assert str(ds.SeriesDescription) == "CT Chest Ax PortVen"
    assert not hasattr(ds, "OriginalAttributesSequence") or not ds.OriginalAttributesSequence


def _oas_item_after_series_apply(path: Path, series_dir: Path) -> Dataset:
    assert apply_series_description(series_dir, "CT Chest Ax PortVen") is True
    ds = dcmread(str(path))
    assert str(ds.SeriesDescription) == "CT Chest Ax PortVen"
    oas = getattr(ds, "OriginalAttributesSequence", None)
    assert oas is not None and len(oas) == 1
    return oas[0]


def test_apply_series_description_oas_helpers_still_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retained OAS path stays callable when the opt-in flag is enabled."""
    monkeypatch.setattr(series_io, "_WRITE_DESCRIPTION_ORIGINAL_ATTRIBUTES", True)
    series_dir = tmp_path / "series"
    path = _write_minimal_series(series_dir, series_description="SCOUT")
    item = _oas_item_after_series_apply(path, series_dir)
    assert str(item.ModifyingSystem) == f"RSNA Anonymizer {get_version()}"
    assert str(item.SourceOfPreviousValues) == ""
    assert str(item.ReasonForTheAttributeModification) == "COERCE"
    assert getattr(item, "AttributeModificationDateTime", None)
    modified = item.ModifiedAttributesSequence[0]
    assert str(modified.SeriesDescription) == "SCOUT"
    ds = dcmread(str(path))
    private = [elem for elem in ds if elem.tag.is_private]
    assert private == []


@pytest.mark.parametrize(
    ("kwargs", "expected_source"),
    [
        ({"institution_name": "General Hospital"}, "General Hospital"),
        (
            {
                "institution_name": "General Hospital",
                "department_name": "Radiology",
                "source_ae_title": "PACS_AE",
            },
            "General Hospital",
        ),
        (
            {"department_name": "Radiology", "source_ae_title": "PACS_AE"},
            "Radiology",
        ),
        ({"source_ae_title": "PACS_AE"}, "PACS_AE"),
    ],
)
def test_source_of_previous_values_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str],
    expected_source: str,
) -> None:
    monkeypatch.setattr(series_io, "_WRITE_DESCRIPTION_ORIGINAL_ATTRIBUTES", True)
    series_dir = tmp_path / "series"
    path = _write_minimal_series(series_dir, series_description="SCOUT", **kwargs)
    item = _oas_item_after_series_apply(path, series_dir)
    assert str(item.SourceOfPreviousValues) == expected_source
