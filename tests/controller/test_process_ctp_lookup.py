"""Tests for controller/process_ctp_lookup.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from anonymizer.controller.process_ctp_lookup import (
    LookupPropertiesError,
    commit_ctp_lookup,
    preview_ctp_lookup,
    private_anonymizer_script_path,
    private_lookup_properties_path,
)
from anonymizer.model.anonymizer import AnonymizerModel, LookupPatient
from tests.controller.dicom.support.test_nodes import TEST_SITEID, TEST_UIDROOT
from tests.paths import DEFAULT_ANONYMIZER_SCRIPT


def _write_properties(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthetic_trial_properties(path: Path, *, with_dateoffset: bool) -> dict[str, tuple[str, int | None]]:
    """
    Write a multi-patient synthetic properties file.

    Returns expected patient_id -> (anon_patient_id, date_offset) mapping.
    """
    patients = {
        "MRN-1001": ("527408-000101", 42 if with_dateoffset else None),
        "MRN-1002": ("527408-000102", 84 if with_dateoffset else None),
        "MRN-1003": ("527408-000103", 127 if with_dateoffset else None),
    }
    lines = [
        "# Synthetic CTP trial lookup table",
        "",
        "ptid/MRN-1001=527408-000101",
        "ptid/MRN-1002=527408-000102",
        "ptid/MRN-1003=527408-000103",
    ]
    if with_dateoffset:
        lines.extend(
            [
                "dateoffset/MRN-1001=42",
                "dateoffset/MRN-1002=84",
                "dateoffset/MRN-1003=127",
            ]
        )
    _write_properties(path, lines)
    return patients


def _lookup_rows_from_db(db_path: Path) -> list[tuple[str, str, int | None]]:
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT patient_id, anon_patient_id, date_offset FROM lookup_patient ORDER BY patient_id")
        ).fetchall()
    engine.dispose()
    return [(row[0], row[1], row[2]) for row in rows]


def _assert_model_matches_expected(
    model: AnonymizerModel,
    expected: dict[str, tuple[str, int | None]],
) -> None:
    for patient_id, (anon_id, offset) in expected.items():
        row = model.get_lookup_patient(patient_id)
        assert row is not None, f"missing lookup row for {patient_id!r}"
        assert row.anon_patient_id == anon_id
        assert row.date_offset == offset


# --- preview / parse ---


def test_preview_parses_ptid_and_dateoffset(tmp_path: Path) -> None:
    props = tmp_path / "trial.properties"
    _write_properties(
        props,
        [
            "ptid/12345=527408-000042",
            "dateoffset/12345=127",
        ],
    )
    preview = preview_ctp_lookup(props)
    assert len(preview.rows) == 1
    assert preview.rows[0].patient_id == "12345"
    assert preview.rows[0].anon_patient_id == "527408-000042"
    assert preview.rows[0].date_offset == 127
    assert preview.has_dateoffset is True
    assert any(change.after == "@lookup(this,ptid)" for change in preview.script_patch.changes)
    assert any(change.after == "@lookup(this,dateoffset)" for change in preview.script_patch.changes)


def test_preview_parses_synthetic_multi_patient_file(tmp_path: Path) -> None:
    props = tmp_path / "synthetic.properties"
    expected = _synthetic_trial_properties(props, with_dateoffset=True)

    preview = preview_ctp_lookup(props)

    assert preview.has_dateoffset is True
    assert len(preview.rows) == len(expected)
    preview_by_id = {row.patient_id: row for row in preview.rows}
    for patient_id, (anon_id, offset) in expected.items():
        row = preview_by_id[patient_id]
        assert row.anon_patient_id == anon_id
        assert row.date_offset == offset


def test_preview_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    props = tmp_path / "trial.properties"
    _write_properties(
        props,
        [
            "# header comment",
            "",
            "! bang comment",
            "ptid/ALPHA=527408-000001",
            "  ptid/BETA=527408-000002  ",
        ],
    )
    preview = preview_ctp_lookup(props)
    assert {row.patient_id for row in preview.rows} == {"ALPHA", "BETA"}


def test_preview_ptid_only_does_not_patch_hashdate(tmp_path: Path) -> None:
    props = tmp_path / "trial.properties"
    _write_properties(props, ["ptid/12345=527408-000042"])
    preview = preview_ctp_lookup(props)
    assert preview.has_dateoffset is False
    assert not any("@lookup(this,dateoffset)" in change.after for change in preview.script_patch.changes)
    assert any(change.after == "@lookup(this,ptid)" for change in preview.script_patch.changes)


def test_preview_requires_dateoffset_for_all_ptid(tmp_path: Path) -> None:
    props = tmp_path / "trial.properties"
    _write_properties(
        props,
        [
            "ptid/111=AAA-001",
            "ptid/222=AAA-002",
            "dateoffset/111=10",
        ],
    )
    with pytest.raises(LookupPropertiesError, match="Missing"):
        preview_ctp_lookup(props)


# --- full load: preview -> commit -> model + files ---


def test_full_load_ptid_only_into_model(controller, tmp_path: Path) -> None:
    props = tmp_path / "synthetic_ptid_only.properties"
    expected = _synthetic_trial_properties(props, with_dateoffset=False)

    preview = preview_ctp_lookup(props)
    script_path = commit_ctp_lookup(controller, preview)

    properties_dest = private_lookup_properties_path(controller.model)
    assert properties_dest.read_text(encoding="utf-8") == props.read_text(encoding="utf-8")
    assert script_path == private_anonymizer_script_path(controller.model)
    assert script_path.read_text(encoding="utf-8").count("@lookup(this,dateoffset)") == 0

    _assert_model_matches_expected(controller.anonymizer.model, expected)

    db_rows = _lookup_rows_from_db(Path(controller.model.get_db_url().replace("sqlite:///", "")))
    assert len(db_rows) == len(expected)
    for patient_id, (anon_id, offset) in expected.items():
        assert (patient_id, anon_id, offset) in db_rows

    tag_keep = controller.anonymizer.model._tag_keep
    assert tag_keep.get("00100010") == "@lookup(this,ptid)"
    assert tag_keep.get("00100020") == "@lookup(this,ptid)"
    assert tag_keep.get("00080020") == "@hashdate"


def test_full_load_with_dateoffsets_into_model(controller, tmp_path: Path) -> None:
    props = tmp_path / "synthetic_full.properties"
    expected = _synthetic_trial_properties(props, with_dateoffset=True)

    preview = preview_ctp_lookup(props)
    assert preview.has_dateoffset is True
    patient_changes = [c for c in preview.script_patch.changes if c.after == "@lookup(this,ptid)"]
    date_changes = [c for c in preview.script_patch.changes if c.after == "@lookup(this,dateoffset)"]
    assert len(patient_changes) == 2
    assert len(date_changes) >= 1

    script_path = commit_ctp_lookup(controller, preview)

    assert (private_lookup_properties_path(controller.model)).is_file()
    assert script_path.is_file()
    assert controller.model.anonymizer_script_path == script_path
    assert controller.anonymizer.project_model.anonymizer_script_path == script_path

    _assert_model_matches_expected(controller.anonymizer.model, expected)

    script_text = script_path.read_text(encoding="utf-8")
    assert "@lookup(this,ptid)" in script_text
    assert "@lookup(this,dateoffset)" in script_text
    assert "@ptid" not in script_text.split("PatientID")[0]  # patient tags patched in file

    tag_keep = controller.anonymizer.model._tag_keep
    assert tag_keep.get("00100020") == "@lookup(this,ptid)"
    assert tag_keep.get("00080020") == "@lookup(this,dateoffset)"
    assert tag_keep.get("00080021") == "@lookup(this,dateoffset)"


def test_full_reload_replaces_all_lookup_patients(controller, tmp_path: Path) -> None:
    first_props = tmp_path / "first.properties"
    _write_properties(
        first_props,
        [
            "ptid/OLD-1=527408-000001",
            "ptid/OLD-2=527408-000002",
        ],
    )
    commit_ctp_lookup(controller, preview_ctp_lookup(first_props))

    second_props = tmp_path / "second.properties"
    expected_second = _synthetic_trial_properties(second_props, with_dateoffset=True)
    commit_ctp_lookup(controller, preview_ctp_lookup(second_props))

    model = controller.anonymizer.model
    assert model.get_lookup_patient("OLD-1") is None
    assert model.get_lookup_patient("OLD-2") is None
    _assert_model_matches_expected(model, expected_second)

    db_rows = _lookup_rows_from_db(Path(controller.model.get_db_url().replace("sqlite:///", "")))
    assert len(db_rows) == len(expected_second)
    assert all(row[0].startswith("MRN-") for row in db_rows)


def test_commit_writes_files_and_sql(controller, tmp_path: Path) -> None:
    props = tmp_path / "trial.properties"
    _write_properties(
        props,
        [
            "ptid/12345=527408-000042",
            "dateoffset/12345=127",
        ],
    )
    preview = preview_ctp_lookup(props)
    script_path = commit_ctp_lookup(controller, preview)

    private = controller.model.private_dir()
    assert (private / f"{controller.model.site_id}-lookup.properties").is_file()
    assert script_path.is_file()
    assert controller.model.anonymizer_script_path == script_path

    row = controller.anonymizer.model.get_lookup_patient("12345")
    assert row is not None
    assert row.anon_patient_id == "527408-000042"
    assert row.date_offset == 127
    assert "@lookup(this,ptid)" in controller.anonymizer.model._tag_keep.get("00100020", "")


def test_replace_lookup_patients_replaces_all(tmp_path: Path) -> None:
    db_path = tmp_path / "lookup.db"
    model = AnonymizerModel(
        site_id=TEST_SITEID,
        uid_root=TEST_UIDROOT,
        script_path=DEFAULT_ANONYMIZER_SCRIPT,
        db_url=f"sqlite:///{db_path}",
    )
    model.replace_lookup_patients(
        [
            LookupPatient(patient_id="A", anon_patient_id="X-001", date_offset=1),
            LookupPatient(patient_id="B", anon_patient_id="X-002", date_offset=2),
        ]
    )
    assert model.get_lookup_patient("A") is not None
    model.replace_lookup_patients([LookupPatient(patient_id="C", anon_patient_id="X-003", date_offset=None)])
    assert model.get_lookup_patient("A") is None
    assert model.get_lookup_patient("C") is not None
