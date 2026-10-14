"""Series metadata PHI index: unique texts, interning, load wiring."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from pydicom import dcmread
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from anonymizer.controller import series_io
from anonymizer.controller.ai.embedded_phi.metadata.extract import MetadataPhiRow
from anonymizer.controller.ai.embedded_phi.metadata.series_index import (
    extract_sop_metadata_rows,
    metadata_text_occurrence_count,
    unique_metadata_texts,
)

_REPO = Path(__file__).resolve().parents[5]
_TEST_DCM = _REPO / "tests/controller/assets/test_dcm_files"


def _series_dirs() -> list[Path]:
    """Immediate child dirs of test_dcm_files that contain at least one .dcm."""
    if not _TEST_DCM.is_dir():
        return []
    return sorted(
        p for p in _TEST_DCM.iterdir() if p.is_dir() and any(p.glob("*.dcm"))
    )


def _row_fingerprint(row: MetadataPhiRow) -> tuple[str, str, str, bool, bool]:
    return (row.tag_path, row.vr, row.text, row.is_private, row.iod_unexpected)


def _assert_loaded_matches_independent_pydicom_read(loaded: series_io.LoadedSeries) -> None:
    """
    Re-read each loaded slice with ``stop_before_pixels=True`` and compare
    extract+IOD rows to ``loaded.metadata_by_sop`` (value equality, not identity).

    Header re-reads follow ``slice_paths`` order (same first-seen SOP order as load)
    so ``metadata_unique_texts`` first-seen order matches.
    """
    assert loaded.metadata_by_sop
    assert loaded.slice_paths

    independent: dict[str, tuple[MetadataPhiRow, ...]] = {}
    for path in loaded.slice_paths:
        # Multi-frame: same path may repeat per frame — extract once per SOP.
        ds = dcmread(str(path), stop_before_pixels=True, force=True)
        sop = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
        assert sop, f"missing SOPInstanceUID in {path}"
        if sop in independent:
            continue
        # Fresh extract — no shared string pool with LoadedSeries.
        independent[sop] = extract_sop_metadata_rows(ds, mark_iod=True)

    assert list(loaded.metadata_by_sop) == list(independent)

    for sop, expected_rows in independent.items():
        got_rows = loaded.metadata_by_sop[sop]
        assert [_row_fingerprint(r) for r in got_rows] == [
            _row_fingerprint(r) for r in expected_rows
        ], f"metadata mismatch for SOP {sop}"

    assert loaded.metadata_unique_texts == unique_metadata_texts(independent)
    occurrences = metadata_text_occurrence_count(loaded.metadata_by_sop)
    assert len(loaded.metadata_unique_texts) <= occurrences


def _tiny_sc(
    *,
    study_description: str,
    image_comments: str,
    study_date: str = "20140315",
) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 8
    ds.Columns = 8
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(8 * 8)
    ds.StudyDescription = study_description
    ds.ImageComments = image_comments
    ds.StudyDate = study_date
    return ds


def _write_series(tmp: Path, count: int, *, shared_study: str = "SHARED STUDY") -> Path:
    series = tmp / "series"
    series.mkdir()
    for i in range(count):
        ds = _tiny_sc(
            study_description=shared_study,
            image_comments=f"slice-{i}-comment",
        )
        ds.InstanceNumber = i + 1
        ds.save_as(series / f"slice_{i:03d}.dcm", write_like_original=False)
    return series


def test_unique_metadata_texts_dedupes_and_skips_dates_and_blanks() -> None:
    pool: dict[str, str] = {}
    by_sop: dict[str, tuple[MetadataPhiRow, ...]] = {}
    for i in range(5):
        ds = _tiny_sc(
            study_description="  SAME  ",
            image_comments=f"c{i}",
            study_date="20200101",
        )
        # Plant blank LO so extract skips empty; whitespace-only via unique strip.
        ds.SeriesDescription = "SAME"  # second copy of same stripped text from Study
        by_sop[str(ds.SOPInstanceUID)] = extract_sop_metadata_rows(
            ds, string_pool=pool, mark_iod=False
        )

    unique = unique_metadata_texts(by_sop)
    assert "SAME" in unique
    assert all(not t.isspace() for t in unique)
    # Shared study text once; per-slice comments distinct.
    assert unique.count("SAME") == 1
    assert sum(1 for t in unique if t.startswith("c")) == 5
    # Dates excluded from unique text index.
    assert "20200101" not in unique
    occurrences = metadata_text_occurrence_count(by_sop)
    assert occurrences > len(unique)


def test_interned_strings_share_identity_across_sops() -> None:
    pool: dict[str, str] = {}
    rows_a = extract_sop_metadata_rows(
        _tiny_sc(study_description="SHARED", image_comments="a"),
        string_pool=pool,
        mark_iod=False,
    )
    rows_b = extract_sop_metadata_rows(
        _tiny_sc(study_description="SHARED", image_comments="b"),
        string_pool=pool,
        mark_iod=False,
    )
    text_a = next(r.text for r in rows_a if r.tag_path == "StudyDescription")
    text_b = next(r.text for r in rows_b if r.tag_path == "StudyDescription")
    assert text_a == "SHARED"
    assert text_a is text_b  # single pooled object


def test_unique_index_memory_cheaper_than_raw_occurrence_list() -> None:
    """Unique tuple holds far fewer string refs than the pre-dedupe occurrence list."""
    pool: dict[str, str] = {}
    by_sop: dict[str, tuple[MetadataPhiRow, ...]] = {}
    n = 40
    for i in range(n):
        ds = _tiny_sc(study_description="SHARED STUDY", image_comments=f"u{i}")
        by_sop[str(ds.SOPInstanceUID)] = extract_sop_metadata_rows(
            ds, string_pool=pool, mark_iod=False
        )

    unique = unique_metadata_texts(by_sop)
    # Naive list: every non-date cell text (duplicates included).
    naive = [
        r.text
        for rows in by_sop.values()
        for r in rows
        if not r.is_date and str(r.text).strip()
    ]
    assert len(naive) == metadata_text_occurrence_count(by_sop)
    assert len(unique) < len(naive)
    # Shared study alone appears n times in naive, once in unique.
    assert naive.count("SHARED STUDY") == n
    assert unique.count("SHARED STUDY") == 1
    # Referent size of the unique index is O(unique), not O(occurrences).
    assert sys.getsizeof(unique) < sys.getsizeof(naive)


def test_load_series_frames_fills_metadata_index(tmp_path: Path) -> None:
    series = _write_series(tmp_path, 4, shared_study="LOAD STUDY")
    loaded = series_io.load_series_frames(series)
    assert len(loaded.metadata_by_sop) == 4
    assert loaded.frames.shape[0] == 4
    assert "LOAD STUDY" in loaded.metadata_unique_texts
    assert loaded.metadata_unique_texts.count("LOAD STUDY") == 1
    # Four distinct slice comments + shared study (+ maybe more tags).
    assert len(loaded.metadata_unique_texts) >= 5
    # Interning survives load path.
    study_texts = [
        next(r.text for r in rows if r.tag_path == "StudyDescription")
        for rows in loaded.metadata_by_sop.values()
    ]
    assert all(t is study_texts[0] for t in study_texts)
    _assert_loaded_matches_independent_pydicom_read(loaded)


@pytest.mark.parametrize(
    "series_dir",
    _series_dirs(),
    ids=lambda p: p.name,
)
def test_each_test_dcm_series_matches_independent_pydicom_read(series_dir: Path) -> None:
    """
    Load every fixture series via ``load_series_frames``, then verify the attached
    metadata index against a separate ``dcmread(..., stop_before_pixels=True)``
    extract for each slice path (no PixelData in the verification pass).
    """
    loaded = series_io.load_series_frames(series_dir)
    assert loaded.frames.shape[0] >= 1
    # One SOP per single-frame file, or one SOP for multi-frame.
    assert len(loaded.metadata_by_sop) >= 1
    assert len(loaded.metadata_by_sop) <= loaded.frames.shape[0]
    _assert_loaded_matches_independent_pydicom_read(loaded)


def test_loose_test_dcm_file_matches_independent_pydicom_read(tmp_path: Path) -> None:
    """Root-level ``*.dcm`` under test_dcm_files (e.g. JPEG-LS_Lossy) as a 1-file series."""
    loose = sorted(_TEST_DCM.glob("*.dcm"))
    if not loose:
        pytest.skip("no loose .dcm files in test_dcm_files")
    for src in loose:
        series = tmp_path / src.stem
        series.mkdir()
        shutil.copy2(src, series / src.name)
        loaded = series_io.load_series_frames(series)
        assert loaded.frames.shape[0] >= 1
        _assert_loaded_matches_independent_pydicom_read(loaded)
