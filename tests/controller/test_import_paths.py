"""Unit tests for DICOMDIR-aware import path expansion."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from anonymizer.utils.storage.dicom_tree import ImportPathsError, expand_import_directory


class _ReferencedFileId:
    """Stand-in for a DICOM ReferencedFileID data element."""

    def __init__(self, parts: list[str]) -> None:
        self.value = parts
        self.VM = len(parts)


class _ImageRecord:
    """Stand-in for a DICOMDIR IMAGE directory record."""

    DirectoryRecordType = "IMAGE"

    def __init__(self, referenced: _ReferencedFileId) -> None:
        self._referenced = referenced

    def __getitem__(self, key: str) -> _ReferencedFileId:
        assert key == "ReferencedFileID"
        return self._referenced


def _dicomdir_dataset(dicomdir_path: Path, referenced_parts: list[str]) -> SimpleNamespace:
    """Minimal pydicom-like DICOMDIR tree for expand_import_directory."""
    image = _ImageRecord(_ReferencedFileId(referenced_parts))
    series = SimpleNamespace(
        DirectoryRecordType="SERIES",
        children=[image],
        SeriesNumber=1,
        Modality="CT",
        SeriesDescription="series",
    )
    study = SimpleNamespace(
        DirectoryRecordType="STUDY",
        children=[series],
        StudyID="1",
        StudyDate="20200101",
        StudyDescription="study",
    )
    patient = SimpleNamespace(
        children=[study],
        PatientID="P1",
        PatientName="Anon",
    )
    return SimpleNamespace(filename=str(dicomdir_path), patient_records=[patient])


def test_expand_without_dicomdir_uses_tree_walk(tmp_path: Path) -> None:
    """Plain directories use list_import_directory_files."""
    (tmp_path / "a.dcm").write_bytes(b"x")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "b.dcm").write_bytes(b"y")
    paths = expand_import_directory(tmp_path)
    assert sorted(Path(p).name for p in paths) == ["a.dcm", "b.dcm"]


def test_expand_dicomdir_collects_referenced_images(tmp_path: Path) -> None:
    """DICOMDIR path expands ReferencedFileID entries under the DICOMDIR root."""
    dicomdir = tmp_path / "DICOMDIR"
    dicomdir.write_text("placeholder", encoding="utf-8")
    (tmp_path / "IMAGES").mkdir()
    (tmp_path / "IMAGES" / "IMG001").write_bytes(b"dcm")

    ds = _dicomdir_dataset(dicomdir, ["IMAGES", "IMG001"])
    with patch("anonymizer.utils.storage.dicom_tree.dcmread", return_value=ds):
        paths = expand_import_directory(tmp_path)

    assert len(paths) == 1
    assert Path(paths[0]).resolve() == (tmp_path / "IMAGES" / "IMG001").resolve()


def test_expand_dicomdir_read_failure_raises(tmp_path: Path) -> None:
    """Unreadable DICOMDIR raises ImportPathsError."""
    (tmp_path / "DICOMDIR").write_text("bad", encoding="utf-8")
    with patch(
        "anonymizer.utils.storage.dicom_tree.dcmread",
        side_effect=RuntimeError("corrupt"),
    ):
        with pytest.raises(ImportPathsError, match="corrupt"):
            expand_import_directory(tmp_path)
