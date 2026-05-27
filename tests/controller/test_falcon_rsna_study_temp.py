"""Temporary FALCON RSNA eligibility scan (preprocessing only, no model inference)."""

from __future__ import annotations

import csv
import gc
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil
import pydicom
import pytest

from anonymizer.controller.falcon.pipeline import preprocess_series_directory

RSNA_TEST_DATA_DIR = Path("/Users/michaelevans/DATA/RSNA_TEST_DATA")
ELIGIBILITY_OUTPUT_DIR = Path(__file__).resolve().parent / "tmp" / "falcon_rsna"
CT_SERIES_PATHS_FILE = ELIGIBILITY_OUTPUT_DIR / "ct_series_paths.txt"
ANONYMIZER_INSTALL_DIR = Path(__file__).resolve().parents[2] / "src" / "anonymizer"

ELIGIBLE_CSV = ELIGIBILITY_OUTPUT_DIR / "eligible.csv"
INELIGIBLE_CSV = ELIGIBILITY_OUTPUT_DIR / "ineligible.csv"
ELIGIBLE_FIRST_10_CSV = ELIGIBILITY_OUTPUT_DIR / "eligible_first_10.csv"
INELIGIBLE_FIRST_10_CSV = ELIGIBILITY_OUTPUT_DIR / "ineligible_first_10.csv"

CSV_FIELDNAMES = (
    "patient_folder",
    "study_instance_uid",
    "series_instance_uid",
    "series_directory",
    "series_description",
    "number_of_slices",
    "error",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CtSeriesRef:
    """Lightweight CT series reference discovered on disk."""

    path: Path
    patient_folder: str
    study_instance_uid: str
    series_instance_uid: str
    series_description: str
    slice_count: int


@dataclass(frozen=True)
class EligibilityScanResult:
    """Summary counts from a linear eligibility scan."""

    total: int
    eligible: int
    ineligible: int
    rss_start_mb: float
    rss_end_mb: float


@pytest.fixture(scope="module")
def falcon_runtime() -> None:
    previous = os.getcwd()
    os.chdir(ANONYMIZER_INSTALL_DIR)
    logging.getLogger("anonymizer.controller.falcon").setLevel(logging.WARNING)
    yield
    os.chdir(previous)


def process_rss_mb() -> float:
    """Return current process RSS in megabytes."""
    return psutil.Process().memory_info().rss / (1024 * 1024)


def iter_ct_series(root: Path) -> Iterator[CtSeriesRef]:
    """Yield CT series directories under ``root`` without loading pixel data."""
    for patient_dir in sorted(root.iterdir()):
        if not patient_dir.is_dir() or patient_dir.name == "out":
            continue
        for study_dir in sorted(patient_dir.iterdir()):
            if not study_dir.is_dir():
                continue
            for series_dir in sorted(study_dir.iterdir()):
                if not series_dir.is_dir():
                    continue
                dcm_files = sorted(series_dir.glob("*.dcm"))
                if not dcm_files:
                    continue
                meta = None
                try:
                    meta = pydicom.dcmread(dcm_files[0], stop_before_pixels=True)
                    if meta.Modality != "CT":
                        continue
                    yield CtSeriesRef(
                        path=series_dir,
                        patient_folder=patient_dir.name,
                        study_instance_uid=study_dir.name,
                        series_instance_uid=series_dir.name,
                        series_description=str(getattr(meta, "SeriesDescription", "")),
                        slice_count=len(dcm_files),
                    )
                except Exception:
                    continue
                finally:
                    del meta, dcm_files


def write_ct_series_paths_file(root: Path, output_path: Path) -> int:
    """Filter CT series under ``root`` and write one path per line to ``output_path``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for series in iter_ct_series(root):
            handle.write(f"{series.path}\n")
            count += 1
    return count


def check_series_eligibility(series_dir: Path) -> str | None:
    """Run preprocessing eligibility for one series; return error text or ``None`` if eligible."""
    mem_before = process_rss_mb()
    logger.info("  preprocessing start | RSS %.1f MB", mem_before)

    image, error = preprocess_series_directory(series_dir)
    del image
    gc.collect()

    mem_after = process_rss_mb()
    delta_mb = mem_after - mem_before
    if error is None:
        logger.info(
            "  result: ELIGIBLE | RSS %.1f MB -> %.1f MB (%+.1f MB)",
            mem_before,
            mem_after,
            delta_mb,
        )
    else:
        logger.info(
            "  result: INELIGIBLE (%s) | RSS %.1f MB -> %.1f MB (%+.1f MB)",
            error,
            mem_before,
            mem_after,
            delta_mb,
        )
    return error


def series_to_csv_row(series: CtSeriesRef, *, error: str | None) -> dict[str, str | int]:
    return {
        "patient_folder": series.patient_folder,
        "study_instance_uid": series.study_instance_uid,
        "series_instance_uid": series.series_instance_uid,
        "series_directory": str(series.path),
        "series_description": series.series_description,
        "number_of_slices": series.slice_count,
        "error": error or "",
    }


def load_ct_series_paths(paths_file: Path) -> list[Path]:
    """Load CT series directory paths from a one-path-per-line file."""
    return [Path(line.strip()) for line in paths_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def ct_series_ref_from_path(series_dir: Path) -> CtSeriesRef:
    """Build a ``CtSeriesRef`` from a series directory path."""
    dcm_files = sorted(series_dir.glob("*.dcm"))
    series_description = ""
    if dcm_files:
        meta = pydicom.dcmread(dcm_files[0], stop_before_pixels=True)
        series_description = str(getattr(meta, "SeriesDescription", ""))
        del meta
    return CtSeriesRef(
        path=series_dir,
        patient_folder=series_dir.parent.parent.name,
        study_instance_uid=series_dir.parent.name,
        series_instance_uid=series_dir.name,
        series_description=series_description,
        slice_count=len(dcm_files),
    )


def scan_eligibility_linear(
    series_paths: list[Path],
    *,
    eligible_csv: Path,
    ineligible_csv: Path,
) -> EligibilityScanResult:
    """Check eligibility one series at a time (linear, no model inference)."""
    eligible_csv.parent.mkdir(parents=True, exist_ok=True)
    ineligible_csv.parent.mkdir(parents=True, exist_ok=True)

    eligible_count = 0
    ineligible_count = 0
    total = len(series_paths)
    rss_start_mb = process_rss_mb()

    logger.info("Eligibility scan starting: %d series (linear, preprocessing only)", total)
    logger.info("Process RSS at scan start: %.1f MB", rss_start_mb)

    with (
        eligible_csv.open("w", newline="", encoding="utf-8") as eligible_handle,
        ineligible_csv.open("w", newline="", encoding="utf-8") as ineligible_handle,
    ):
        eligible_writer = csv.DictWriter(eligible_handle, fieldnames=CSV_FIELDNAMES)
        ineligible_writer = csv.DictWriter(ineligible_handle, fieldnames=CSV_FIELDNAMES)
        eligible_writer.writeheader()
        ineligible_writer.writeheader()

        for index, series_path in enumerate(series_paths, start=1):
            series = ct_series_ref_from_path(series_path)
            logger.info(
                "Series %d/%d | patient=%s | slices=%d | %s",
                index,
                total,
                series.patient_folder,
                series.slice_count,
                series.series_description or series.series_instance_uid,
            )

            error = check_series_eligibility(series.path)
            row = series_to_csv_row(series, error=error)
            if error is None:
                eligible_writer.writerow(row)
                eligible_count += 1
            else:
                ineligible_writer.writerow(row)
                ineligible_count += 1

            eligible_handle.flush()
            ineligible_handle.flush()
            del error, row, series
            gc.collect()

    rss_end_mb = process_rss_mb()
    logger.info(
        "Eligibility scan complete: eligible=%d ineligible=%d | RSS %.1f MB -> %.1f MB (%+.1f MB)",
        eligible_count,
        ineligible_count,
        rss_start_mb,
        rss_end_mb,
        rss_end_mb - rss_start_mb,
    )
    logger.info("Eligible CSV:   %s", eligible_csv)
    logger.info("Ineligible CSV: %s", ineligible_csv)

    return EligibilityScanResult(
        total=total,
        eligible=eligible_count,
        ineligible=ineligible_count,
        rss_start_mb=rss_start_mb,
        rss_end_mb=rss_end_mb,
    )


def write_eligibility_csvs_for_paths(
    series_paths: list[Path],
    output_dir: Path,
) -> tuple[int, int, int]:
    """Check eligibility for each path and write CSV summaries (no model inference)."""
    result = scan_eligibility_linear(
        series_paths,
        eligible_csv=output_dir / "eligible.csv",
        ineligible_csv=output_dir / "ineligible.csv",
    )
    return result.total, result.eligible, result.ineligible


def write_eligibility_csvs(root: Path, output_dir: Path) -> tuple[int, int, int]:
    """Scan CT series, check eligibility one-by-one, and write CSV summaries."""
    series_paths = [series.path for series in iter_ct_series(root)]
    return write_eligibility_csvs_for_paths(series_paths, output_dir)


def configure_scan_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )
    logging.getLogger("anonymizer.controller.falcon").setLevel(logging.WARNING)


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
def test_falcon_filter_rsna_ct_series_paths(capsys) -> None:
    """Filter RSNA dataset for CT series and write directory paths to a temp file."""
    count = write_ct_series_paths_file(RSNA_TEST_DATA_DIR, CT_SERIES_PATHS_FILE)

    print(f"\nFound {count} CT series")
    print(f"Paths written to {CT_SERIES_PATHS_FILE}")

    assert count > 0
    assert CT_SERIES_PATHS_FILE.is_file()
    assert all(line.strip() for line in CT_SERIES_PATHS_FILE.read_text(encoding="utf-8").splitlines())


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
@pytest.mark.skipif(not CT_SERIES_PATHS_FILE.is_file(), reason="CT series paths file not generated yet")
def test_falcon_scan_rsna_ct_eligibility_first_10(capsys) -> None:
    """Linear eligibility scan on the first 10 CT paths (preprocessing only, no models)."""
    configure_scan_logging()
    series_paths = load_ct_series_paths(CT_SERIES_PATHS_FILE)[:10]

    result = scan_eligibility_linear(
        series_paths,
        eligible_csv=ELIGIBLE_FIRST_10_CSV,
        ineligible_csv=INELIGIBLE_FIRST_10_CSV,
    )

    assert result.total == 10
    assert result.eligible + result.ineligible == 10
    assert ELIGIBLE_FIRST_10_CSV.is_file()
    assert INELIGIBLE_FIRST_10_CSV.is_file()


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
@pytest.mark.skipif(not CT_SERIES_PATHS_FILE.is_file(), reason="CT series paths file not generated yet")
def test_falcon_scan_rsna_ct_eligibility_from_paths_file(capsys) -> None:
    """Run eligibility preprocessing on full CT paths list (no model inference)."""
    configure_scan_logging()
    series_paths = load_ct_series_paths(CT_SERIES_PATHS_FILE)

    result = scan_eligibility_linear(
        series_paths,
        eligible_csv=ELIGIBLE_CSV,
        ineligible_csv=INELIGIBLE_CSV,
    )

    assert result.total > 0
    assert result.eligible + result.ineligible == result.total
    assert ELIGIBLE_CSV.is_file()
    assert INELIGIBLE_CSV.is_file()


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
def test_falcon_scan_rsna_ct_eligibility(falcon_runtime, capsys) -> None:
    """Scan RSNA CT series and write eligible/ineligible lists without loading models."""
    configure_scan_logging()
    ct_series_count, eligible_count, ineligible_count = write_eligibility_csvs(
        RSNA_TEST_DATA_DIR,
        ELIGIBILITY_OUTPUT_DIR,
    )

    assert ct_series_count > 0
    assert eligible_count + ineligible_count == ct_series_count
    assert ELIGIBLE_CSV.is_file()
    assert INELIGIBLE_CSV.is_file()


def run_eligibility_scan_first_10() -> EligibilityScanResult:
    """CLI entry point: linear eligibility scan on first 10 CT paths."""
    configure_scan_logging()
    series_paths = load_ct_series_paths(CT_SERIES_PATHS_FILE)[:10]
    return scan_eligibility_linear(
        series_paths,
        eligible_csv=ELIGIBLE_FIRST_10_CSV,
        ineligible_csv=INELIGIBLE_FIRST_10_CSV,
    )


if __name__ == "__main__":
    run_eligibility_scan_first_10()
