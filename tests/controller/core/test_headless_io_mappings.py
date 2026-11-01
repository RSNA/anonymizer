"""Headless MIDI mapping CSV export."""

from __future__ import annotations

import csv
from pathlib import Path

from anonymizer.controller.headless_io import write_patid_mapping, write_uid_mapping
from anonymizer.model.anonymizer import PHI
from tests.opened_anonymizer_model import opened_anonymizer_model


def test_write_uid_and_patid_mapping(tmp_path: Path) -> None:
    db_url = f"sqlite:///{tmp_path / 'anonymizer.db'}"
    with opened_anonymizer_model(db_url) as model:
        model.get_or_create_anon_uid("1.2.3.phi")
        model.session.add(
            PHI(
                patient_id="SMOKE_PAT",
                anon_patient_id="990001-000001",
            )
        )
        model.session.commit()

        uid_csv = tmp_path / "uid_mapping.csv"
        pat_csv = tmp_path / "patid_mapping.csv"
        n_uid = write_uid_mapping(model, uid_csv)
        n_pat = write_patid_mapping(model, pat_csv)

    assert n_uid >= 1
    assert n_pat >= 1
    with uid_csv.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["id_old"]
    assert rows[0]["id_new"]
    with pat_csv.open(newline="", encoding="utf-8") as fh:
        prows = list(csv.DictReader(fh))
    assert any(r["id_old"] == "SMOKE_PAT" for r in prows)
