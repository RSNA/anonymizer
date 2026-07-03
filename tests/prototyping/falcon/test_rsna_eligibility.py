"""Tests for FALCON RSNA eligibility scan (local RSNA data required)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from prototyping.falcon.rsna_eligibility import (
    CT_SERIES_PATHS_FILE,
    ELIGIBLE_CSV,
    ELIGIBLE_FIRST_10_CSV,
    ELIGIBILITY_OUTPUT_DIR,
    INELIGIBLE_CSV,
    INELIGIBLE_FIRST_10_CSV,
    RSNA_TEST_DATA_DIR,
    configure_scan_logging,
    falcon_runtime_context,
    load_ct_series_paths,
    scan_eligibility_linear,
    write_ct_series_paths_file,
    write_eligibility_csvs,
)


def test_load_ct_series_paths(tmp_path: Path) -> None:
    paths_file = tmp_path / "paths.txt"
    paths_file.write_text("/series/a\n\n/series/b\n", encoding="utf-8")
    assert load_ct_series_paths(paths_file) == [Path("/series/a"), Path("/series/b")]


def test_write_ct_series_paths_file_synthetic_chest(synthetic_chest_series: Path, tmp_path: Path) -> None:
    """Discover CT paths under a synthetic patient/study/series tree."""
    patient_root = tmp_path / "RSNA_like"
    series_dir = patient_root / "patient1" / "study1" / "series001"
    series_dir.parent.mkdir(parents=True)
    shutil.copytree(synthetic_chest_series, series_dir)
    output_path = tmp_path / "ct_paths.txt"
    count = write_ct_series_paths_file(patient_root, output_path)
    assert count == 1
    assert load_ct_series_paths(output_path) == [series_dir.resolve()]


@pytest.fixture(scope="module")
def falcon_runtime():
    with falcon_runtime_context():
        yield


pytestmark = pytest.mark.rsna_local_data


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
def test_filter_rsna_ct_series_paths() -> None:
    """Filter RSNA dataset for CT series and write directory paths to a temp file."""
    count = write_ct_series_paths_file(RSNA_TEST_DATA_DIR, CT_SERIES_PATHS_FILE)

    print(f"\nFound {count} CT series")
    print(f"Paths written to {CT_SERIES_PATHS_FILE}")

    assert count > 0
    assert CT_SERIES_PATHS_FILE.is_file()
    assert all(line.strip() for line in CT_SERIES_PATHS_FILE.read_text(encoding="utf-8").splitlines())


@pytest.mark.skipif(not RSNA_TEST_DATA_DIR.is_dir(), reason="RSNA test data directory not available locally")
@pytest.mark.skipif(not CT_SERIES_PATHS_FILE.is_file(), reason="CT series paths file not generated yet")
def test_scan_rsna_ct_eligibility_first_10() -> None:
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
def test_scan_rsna_ct_eligibility_from_paths_file() -> None:
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
def test_scan_rsna_ct_eligibility(falcon_runtime) -> None:
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
