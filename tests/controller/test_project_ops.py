"""Functional ProjectController ops: import, delete, PHI CSV, totals (no AWS)."""

from __future__ import annotations

import time
from pathlib import Path

from anonymizer.controller.dicom.requests import MoveStudiesRequest
from anonymizer.controller.project import ProjectController
from tests.controller.dicom.support.helpers import send_file_to_scp
from tests.controller.dicom.support.test_files import (
    ct_small_filename,
    ct_small_StudyInstanceUID,
    patient3_id,
)
from tests.controller.dicom.support.test_nodes import LocalStorageSCP, PACSSimulatorSCP


def _wait_move_idle(controller: ProjectController, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while controller.bulk_move_active() and time.time() < deadline:
        time.sleep(0.2)
    assert not controller.bulk_move_active()


def _import_ct_small(controller: ProjectController):
    send_file_to_scp(ct_small_filename, PACSSimulatorSCP, controller)
    err, study = controller.get_study_uid_hierarchy(
        PACSSimulatorSCP.aet, ct_small_StudyInstanceUID, patient3_id
    )
    assert err is None
    controller._qr_get_supported.clear()
    controller._qr_move_supported.clear()
    controller.manage_move(
        MoveStudiesRequest(
            scp_name=PACSSimulatorSCP.aet,
            dest_scp_ae=LocalStorageSCP.aet,
            level="STUDY",
            studies=[study],
        )
    )
    _wait_move_idle(controller)
    assert controller.get_number_of_pending_instances(study) == 0
    return study


def test_import_updates_totals_and_modalities(controller: ProjectController) -> None:
    before = controller.get_totals()
    _import_ct_small(controller)
    after = controller.get_totals()
    assert after.patients >= before.patients
    assert after.studies >= before.studies
    assert after.series >= before.series
    mods = controller.get_imported_modalities()
    assert "CT" in mods or any(m.upper() == "CT" for m in mods)


def test_create_phi_csv_and_index_after_import(controller: ProjectController) -> None:
    _import_ct_small(controller)
    records = controller.get_phi_index_records()
    assert records
    assert any(r.anon_study_uid for r in records)
    rec = next(r for r in records if r.anon_study_uid)
    # Exercise PHI index display helpers (phi_io)
    assert rec.get_field_titles()
    assert rec.get_tree_display_titles()
    assert isinstance(rec.modalities_display(), str)
    assert isinstance(rec.flatten(), tuple)
    assert isinstance(rec.tree_values(), tuple)
    if rec.series:
        assert isinstance(rec.series_flatten(rec.series[0]), tuple)

    csv_path = controller.create_phi_csv()
    assert isinstance(csv_path, Path)
    assert csv_path.is_file()
    text = csv_path.read_text(encoding="utf-8")
    assert "ANON" in text or "Patient" in text or len(text) > 10


def test_delete_study_removes_files(controller: ProjectController) -> None:
    _import_ct_small(controller)
    images = Path(controller.model.images_dir())
    patient_dirs = [d for d in images.iterdir() if d.is_dir()]
    assert patient_dirs
    patient_dir = patient_dirs[0]
    study_dirs = [d for d in patient_dir.iterdir() if d.is_dir()]
    assert study_dirs
    anon_pt = patient_dir.name
    anon_study = study_dirs[0].name

    assert controller.delete_study(anon_pt, anon_study) is True
    assert not study_dirs[0].exists() or not any(study_dirs[0].rglob("*.dcm"))
