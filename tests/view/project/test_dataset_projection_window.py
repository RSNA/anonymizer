"""Unit tests for DatasetView projection window management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.phi_io import PHI_IndexRecord
from anonymizer.view.project.dataset import DatasetView


def _study(uid: str) -> PHI_IndexRecord:
    return PHI_IndexRecord(
        anon_patient_id="anon-1",
        anon_patient_name="anon-1",
        phi_patient_name="Doe^Jane",
        phi_patient_id="P1",
        date_offset=0,
        phi_study_date="20200101",
        anon_accession="A1",
        phi_accession="ACC1",
        anon_study_uid=uid,
        phi_study_uid=f"phi-{uid}",
        study_description="Chest",
        num_series=1,
        num_instances=10,
    )


def _dataset_view() -> DatasetView:
    view = DatasetView.__new__(DatasetView)
    view._projection_views = {}
    view._projection_open_in_progress = False
    view._controller = MagicMock()
    view._controller.model.images_dir.return_value = MagicMock()
    view._fonts = MagicMock()
    return view


@patch("anonymizer.view.project.dataset.focus_app_window")
def test_open_projection_view_reuses_existing_same_study(mock_focus: MagicMock) -> None:
    view = _dataset_view()
    study = _study("study-1")
    existing = MagicMock()
    existing.winfo_exists.return_value = True
    view._projection_views[("study-1",)] = existing

    view._open_projection_view([study])

    mock_focus.assert_called_once_with(existing)


@patch("anonymizer.view.project.dataset.ProjectionView")
@patch("anonymizer.view.project.dataset.focus_app_window")
def test_open_projection_view_keeps_existing_for_different_study(
    mock_focus: MagicMock,
    mock_projection_cls: MagicMock,
) -> None:
    view = _dataset_view()
    existing = MagicMock()
    existing.winfo_exists.return_value = True
    view._projection_views[("study-1",)] = existing
    new_view = MagicMock()
    mock_projection_cls.return_value = new_view
    next_study = _study("study-2")

    view._open_projection_view([next_study])

    existing.load_phi_records.assert_not_called()
    existing.destroy.assert_not_called()
    mock_projection_cls.assert_called_once()
    mock_focus.assert_called_once_with(new_view)
    assert view._projection_views[("study-1",)] is existing
    assert view._projection_views[("study-2",)] is new_view


@patch("anonymizer.view.project.dataset.ProjectionView")
@patch("anonymizer.view.project.dataset.focus_app_window")
def test_open_projection_view_blocks_concurrent_create(mock_focus: MagicMock, mock_projection_cls: MagicMock) -> None:
    view = _dataset_view()
    view._projection_open_in_progress = True

    view._open_projection_view([_study("study-1")])

    mock_projection_cls.assert_not_called()
    mock_focus.assert_not_called()
