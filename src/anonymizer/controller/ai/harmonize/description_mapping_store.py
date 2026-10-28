"""Per-project description mapping CSVs under storage_dir/mappings (no PHI).

Sticky intake SeriesDescription → RadLex Playbook string, and StudyDescription →
LOINC number (resolve name via LOINC CSV). Used by GUI, CLI batch, and harmonize.

Public API
----------
SERIES_CSV_NAME, STUDY_CSV_NAME
    Mapping CSV filenames under the project mappings directory.

SeriesDescriptionOverride, StudyDescriptionOverride
    Frozen row types for series and study mappings.

ensure_mappings_dir(mappings_dir) -> Path
    Create mappings_dir if missing.

series_csv_path(mappings_dir) -> Path
study_csv_path(mappings_dir) -> Path
    Paths to the series and study mapping CSVs.

load_series_overrides(mappings_dir) -> dict[str, str]
load_study_loinc_overrides(mappings_dir) -> dict[str, str]
    Load original→value maps for batch and CLI.

list_series_overrides(mappings_dir) -> list[SeriesDescriptionOverride]
list_study_overrides(mappings_dir) -> list[StudyDescriptionOverride]
    Sorted row lists for the mappings inspector UI.

lookup_series_override(mappings_dir, original) -> SeriesDescriptionOverride | None
lookup_study_override(mappings_dir, original) -> StudyDescriptionOverride | None
    Exact lookup by sticky original description.

upsert_series_override / upsert_study_override / delete_* / remember_*
    Persist or remove mapping rows.
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SERIES_CSV_NAME = "series.csv"
STUDY_CSV_NAME = "study.csv"
_SERIES_FIELDS = ("original", "harmonized")
_STUDY_FIELDS = ("original", "loinc_number")


@dataclass(frozen=True)
class SeriesDescriptionOverride:
    """One series original→harmonized row."""

    original: str
    harmonized: str


@dataclass(frozen=True)
class StudyDescriptionOverride:
    """One study original→LOINC number row."""

    original: str
    loinc_number: str


def ensure_mappings_dir(mappings_dir: Path) -> Path:
    """
    Create mappings_dir if missing.

    Args:
        mappings_dir: Project storage_dir/mappings path.

    Returns:
        The same path.
    """
    mappings_dir.mkdir(parents=True, exist_ok=True)
    return mappings_dir


def series_csv_path(mappings_dir: Path) -> Path:
    """Path to the series description mapping CSV."""
    return Path(mappings_dir) / SERIES_CSV_NAME


def study_csv_path(mappings_dir: Path) -> Path:
    """Path to the study description mapping CSV."""
    return Path(mappings_dir) / STUDY_CSV_NAME


def load_series_overrides(mappings_dir: Path) -> dict[str, str]:
    """
    Load series original→harmonized map.

    Args:
        mappings_dir: Project mappings directory.

    Returns:
        Dict keyed by stripped original description.
    """
    path = series_csv_path(mappings_dir)
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                original = (row.get("original") or "").strip()
                harmonized = (row.get("harmonized") or "").strip()
                if original and harmonized:
                    result[original] = harmonized
    except OSError as exc:
        logger.error("Failed to read series description mappings %s: %s", path, exc)
    return result


def load_study_loinc_overrides(mappings_dir: Path) -> dict[str, str]:
    """
    Load study original→loinc_number map.

    Args:
        mappings_dir: Project mappings directory.

    Returns:
        Dict keyed by stripped original study description.
    """
    path = study_csv_path(mappings_dir)
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                original = (row.get("original") or "").strip()
                loinc_number = (row.get("loinc_number") or "").strip()
                if original and loinc_number:
                    result[original] = loinc_number
    except OSError as exc:
        logger.error("Failed to read study description mappings %s: %s", path, exc)
    return result


def list_series_overrides(mappings_dir: Path) -> list[SeriesDescriptionOverride]:
    """Return series mapping rows sorted by original."""
    return [
        SeriesDescriptionOverride(original=key, harmonized=value)
        for key, value in sorted(load_series_overrides(mappings_dir).items())
    ]


def list_study_overrides(mappings_dir: Path) -> list[StudyDescriptionOverride]:
    """Return study mapping rows sorted by original."""
    return [
        StudyDescriptionOverride(original=key, loinc_number=value)
        for key, value in sorted(load_study_loinc_overrides(mappings_dir).items())
    ]


def lookup_series_override(mappings_dir: Path, original: str) -> SeriesDescriptionOverride | None:
    """
    Exact lookup of a series mapping by sticky original description.

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake SeriesDescription.

    Returns:
        Matching row or None.
    """
    key = (original or "").strip()
    if not key:
        return None
    harmonized = load_series_overrides(mappings_dir).get(key)
    if not harmonized:
        return None
    return SeriesDescriptionOverride(original=key, harmonized=harmonized)


def lookup_study_override(mappings_dir: Path, original: str) -> StudyDescriptionOverride | None:
    """
    Exact lookup of a study mapping by sticky original description.

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake StudyDescription.

    Returns:
        Matching row or None.
    """
    key = (original or "").strip()
    if not key:
        return None
    loinc_number = load_study_loinc_overrides(mappings_dir).get(key)
    if not loinc_number:
        return None
    return StudyDescriptionOverride(original=key, loinc_number=loinc_number)


def upsert_series_override(mappings_dir: Path, *, original: str, harmonized: str) -> bool:
    """
    Upsert a series original→harmonized mapping.

    Skips empty keys and identity mappings (same text after strip).

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake SeriesDescription.
        harmonized: Chosen RadLex Playbook description.

    Returns:
        True when the file was updated.
    """
    key = (original or "").strip()
    value = (harmonized or "").strip()
    if not key or not value or key == value:
        return False
    rows = load_series_overrides(mappings_dir)
    if rows.get(key) == value:
        return False
    rows[key] = value
    _write_series(mappings_dir, rows)
    return True


def upsert_study_override(mappings_dir: Path, *, original: str, loinc_number: str) -> bool:
    """
    Upsert a study original→loinc_number mapping.

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake StudyDescription.
        loinc_number: LOINC catalog code (e.g. 41806-1).

    Returns:
        True when the file was updated.
    """
    key = (original or "").strip()
    code = (loinc_number or "").strip()
    if not key or not code:
        return False
    rows = load_study_loinc_overrides(mappings_dir)
    if rows.get(key) == code:
        return False
    rows[key] = code
    _write_study(mappings_dir, rows)
    return True


def delete_series_override(mappings_dir: Path, original: str) -> bool:
    """
    Delete a series mapping by original key.

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake SeriesDescription key.

    Returns:
        True when a row was removed.
    """
    key = (original or "").strip()
    if not key:
        return False
    rows = load_series_overrides(mappings_dir)
    if key not in rows:
        return False
    del rows[key]
    _write_series(mappings_dir, rows)
    return True


def delete_study_override(mappings_dir: Path, original: str) -> bool:
    """
    Delete a study mapping by original key.

    Args:
        mappings_dir: Project mappings directory.
        original: Sticky intake StudyDescription key.

    Returns:
        True when a row was removed.
    """
    key = (original or "").strip()
    if not key:
        return False
    rows = load_study_loinc_overrides(mappings_dir)
    if key not in rows:
        return False
    del rows[key]
    _write_study(mappings_dir, rows)
    return True


def remember_series_override(
    mappings_dir: Path,
    *,
    original: str,
    harmonized: str,
) -> bool:
    """Persist a series override from sticky intake description (UX write path)."""
    return upsert_series_override(mappings_dir, original=original, harmonized=harmonized)


def remember_study_override(
    mappings_dir: Path,
    *,
    original: str,
    loinc_number: str,
) -> bool:
    """Persist a study override from sticky intake description (UX write path)."""
    return upsert_study_override(mappings_dir, original=original, loinc_number=loinc_number)


def _write_series(mappings_dir: Path, rows: dict[str, str]) -> None:
    ensure_mappings_dir(mappings_dir)
    path = series_csv_path(mappings_dir)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_SERIES_FIELDS))
        writer.writeheader()
        for original in sorted(rows):
            writer.writerow({"original": original, "harmonized": rows[original]})


def _write_study(mappings_dir: Path, rows: dict[str, str]) -> None:
    ensure_mappings_dir(mappings_dir)
    path = study_csv_path(mappings_dir)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_STUDY_FIELDS))
        writer.writeheader()
        for original in sorted(rows):
            writer.writerow({"original": original, "loinc_number": rows[original]})
