"""Unit tests for ProjectController.import_paths counts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from anonymizer.controller.project import ImportPathsResult, ProjectController
from anonymizer.utils.translate import _


def test_import_paths_counts_success_skip_failure() -> None:
    """Succeeded / already-stored skip / other failures are counted separately."""
    already_stored = _("Instance already stored")
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    success_ds = MagicMock()
    success_ds.PatientID = "ANON1"
    controller.anonymizer.anonymize_file.side_effect = [
        (None, success_ds),
        (already_stored, None),
        ("bad file", None),
        (None, success_ds),
    ]
    # Bind real method
    result = ProjectController.import_paths(
        controller,
        [Path("a.dcm"), Path("b.dcm"), Path("c.dcm"), Path("d.dcm")],
    )
    assert isinstance(result, ImportPathsResult)
    assert result.files_seen == 4
    assert result.succeeded == 2
    assert result.skipped == 1
    assert result.failed == 1
    assert result.anon_patient_ids == ["ANON1"]
    assert result.failures == [{"path": "c.dcm", "error": "bad file"}]


def test_import_paths_progress_callback() -> None:
    """Progress reports completed and total as ints."""
    controller = MagicMock(spec=ProjectController)
    controller.anonymizer = MagicMock()
    controller.anonymizer.anonymize_file.return_value = (None, None)
    events: list[tuple[int, int, str]] = []

    def on_progress(completed: int, total: int, message: str) -> None:
        events.append((completed, total, message))

    ProjectController.import_paths(
        controller,
        ["f1.dcm", "f2.dcm"],
        progress=on_progress,
    )
    assert events
    assert events[-1][0] == 2
    assert events[-1][1] == 2
