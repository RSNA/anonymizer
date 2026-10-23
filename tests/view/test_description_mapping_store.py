"""Tests for view-owned description mapping CSVs."""

from pathlib import Path

from anonymizer.view.project.description_mapping_store import (
    delete_series_override,
    delete_study_override,
    list_series_overrides,
    list_study_overrides,
    load_series_overrides,
    load_study_loinc_overrides,
    lookup_series_override,
    lookup_study_override,
    upsert_series_override,
    upsert_study_override,
)


def test_series_override_upsert_lookup_delete(tmp_path: Path) -> None:
    mappings_dir = tmp_path / "mappings"
    assert upsert_series_override(
        mappings_dir,
        original="chest ax porto venous",
        harmonized="CT Chest Ax PortVen",
    )
    hit = lookup_series_override(mappings_dir, "chest ax porto venous")
    assert hit is not None
    assert hit.harmonized == "CT Chest Ax PortVen"
    assert load_series_overrides(mappings_dir) == {
        "chest ax porto venous": "CT Chest Ax PortVen",
    }
    rows = list_series_overrides(mappings_dir)
    assert len(rows) == 1
    assert delete_series_override(mappings_dir, "chest ax porto venous") is True
    assert list_series_overrides(mappings_dir) == []


def test_series_skips_identity(tmp_path: Path) -> None:
    mappings_dir = tmp_path / "mappings"
    assert (
        upsert_series_override(
            mappings_dir,
            original="CT Chest Ax",
            harmonized="CT Chest Ax",
        )
        is False
    )
    assert load_series_overrides(mappings_dir) == {}


def test_study_override_requires_loinc(tmp_path: Path) -> None:
    mappings_dir = tmp_path / "mappings"
    assert (
        upsert_study_override(
            mappings_dir,
            original="CT CHEST",
            loinc_number="",
        )
        is False
    )
    assert upsert_study_override(
        mappings_dir,
        original="CHEST CT W/O",
        loinc_number="24627-2",
    )
    hit = lookup_study_override(mappings_dir, "CHEST CT W/O")
    assert hit is not None
    assert hit.loinc_number == "24627-2"
    assert load_study_loinc_overrides(mappings_dir) == {"CHEST CT W/O": "24627-2"}
    assert delete_study_override(mappings_dir, "CHEST CT W/O") is True
    assert list_study_overrides(mappings_dir) == []
