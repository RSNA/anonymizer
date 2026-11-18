"""Early-failure paths for save_series_frames (no happy-path roundtrip)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from anonymizer.controller.series.series_io import save_series_frames


def _write_minimal_series(series_dir: Path, *, bits_allocated: int = 16) -> tuple[Path, Dataset]:
    series_dir.mkdir(parents=True, exist_ok=True)
    path = series_dir / "1.dcm"
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = file_meta
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.Rows = 8
    ds.Columns = 8
    ds.BitsAllocated = bits_allocated
    ds.BitsStored = min(bits_allocated, 16)
    ds.HighBit = ds.BitsStored - 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    dtype = np.uint16 if bits_allocated == 16 else np.uint8
    ds.PixelData = np.zeros((8, 8), dtype=dtype).tobytes()
    ds.save_as(path, enforce_file_format=True)
    return path, ds


def test_save_series_frames_empty_or_none(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    assert save_series_frames(series, None, ref) is False  # type: ignore[arg-type]
    assert save_series_frames(series, np.array([]), ref) is False


def test_save_series_frames_bad_path(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    frames = np.zeros((1, 8, 8), dtype=np.float32)
    assert save_series_frames(tmp_path / "missing", frames, ref) is False


def test_save_series_frames_no_dcm(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    ref = Dataset()
    ref.PhotometricInterpretation = "MONOCHROME2"
    assert save_series_frames(empty, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_count_mismatch(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    assert save_series_frames(series, np.zeros((2, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_missing_pi(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _write_minimal_series(series)
    ref = Dataset()  # no PhotometricInterpretation
    assert save_series_frames(series, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_unsupported_pi(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    ref.PhotometricInterpretation = "HSV"
    assert save_series_frames(series, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_rgb_bad_dtype(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    ref.PhotometricInterpretation = "RGB"
    # Wrong dtype/shape for RGB path.
    assert save_series_frames(series, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_monochrome_conversion_error(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series, bits_allocated=16)
    with patch(
        "anonymizer.controller.series.series_io._viewer_chunk_to_stored_pixels",
        side_effect=ValueError("Unsupported BitsAllocated: 32"),
    ):
        assert save_series_frames(series, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_save_as_fail(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    with patch.object(Dataset, "save_as", side_effect=OSError("disk")):
        assert save_series_frames(series, np.zeros((1, 8, 8), dtype=np.float32), ref) is False


def test_save_series_frames_end_index_mismatch(tmp_path: Path) -> None:
    series = tmp_path / "ser"
    _, ref = _write_minimal_series(series)
    frames = np.zeros((1, 8, 8), dtype=np.float32)

    # After the early count check, force the loop to leave frame_ndx short.
    real_shape = frames.shape

    class _ShapeShift(np.ndarray):
        @property
        def shape(self):  # type: ignore[override]
            # First reads during structure check see 1; later end check sees 2.
            return real_shape

    # Simpler: patch processed_frames.shape after loop via wrapping save to mutate.
    # Use a list side_effect on the end check by patching logger and forcing
    # frame_ndx advance without matching — call with 1 frame but skip file via exception
    # that still advances, then change expectation via monkeypatch of shape access.
    # Practical approach: patch ordered path to two files with 1 frame each but only
    # provide 2 frames where second file raises before advancing incorrectly —
    # Actually the code always advances frame_ndx. End mismatch needs shape[0]
    # changing after the early check. Use a custom ndarray subclass:

    class MutatingFrames(np.ndarray):
        _reads = 0

        def __new__(cls, arr):
            obj = np.asarray(arr).view(cls)
            return obj

        @property
        def shape(self):  # type: ignore[override]
            MutatingFrames._reads += 1
            base = super().shape
            # After structure check (~few reads), report larger length for end compare.
            if MutatingFrames._reads > 6:
                return (base[0] + 1,) + base[1:]
            return base

    MutatingFrames._reads = 0
    mutating = MutatingFrames(frames)
    # Happy enough monochrome path; end check should trip.
    with patch(
        "anonymizer.controller.series.series_io._viewer_chunk_to_stored_pixels",
        return_value=np.zeros((8, 8), dtype=np.uint16),
    ):
        assert save_series_frames(series, mutating, ref) is False
