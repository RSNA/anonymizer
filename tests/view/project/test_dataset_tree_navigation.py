"""Unit tests for DatasetView tree navigation gestures."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from anonymizer.controller.phi_io import PHI_IndexRecord, PHI_SeriesIndexRecord
from anonymizer.view.project.dataset import (
    DatasetView,
    series_tree_iid,
    study_tree_iid,
)


def _study(uid: str, *, patient: str = "anon-1") -> PHI_IndexRecord:
    return PHI_IndexRecord(
        anon_patient_id=patient,
        anon_patient_name=patient,
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


def _series(uid: str) -> PHI_SeriesIndexRecord:
    return PHI_SeriesIndexRecord(
        anon_series_uid=uid,
        modality="CT",
        description="Ax",
        harmonized_description="",
        instance_count=5,
        face_blur_algorithm="",
        pixel_phi_removed=False,
        pixel_phi="",
    )


def _navigation_view() -> DatasetView:
    view = DatasetView.__new__(DatasetView)
    study = _study("study-1")
    view._studies_by_uid = {"study-1": study}
    view._series_by_uid = {"series-1": (study, _series("series-1"))}
    view._tree = MagicMock()
    view._open_projection_view = MagicMock()
    view._open_series_by_uid = MagicMock()
    view._last_tree_activate = None
    return view


def test_double_click_series_opens_series_view() -> None:
    view = _navigation_view()
    view._tree.identify_row.return_value = series_tree_iid("series-1")

    view._on_tree_double_click(SimpleNamespace(y=12, time=1))

    view._open_series_by_uid.assert_called_once_with("series-1")
    view._open_projection_view.assert_not_called()


def test_double_click_study_opens_projection_view() -> None:
    view = _navigation_view()
    study = view._studies_by_uid["study-1"]
    view._tree.identify_row.return_value = study_tree_iid("study-1")

    view._on_tree_double_click(SimpleNamespace(y=12, time=1))

    view._open_projection_view.assert_called_once_with([study])
    view._open_series_by_uid.assert_not_called()


def test_right_click_study_opens_projection_view() -> None:
    view = _navigation_view()
    study = view._studies_by_uid["study-1"]
    view._tree.identify_row.return_value = study_tree_iid("study-1")

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._tree.selection_set.assert_called_once_with(study_tree_iid("study-1"))
    view._open_projection_view.assert_called_once_with([study])


def test_tree_row_tooltip_text_by_row_type() -> None:
    view = _navigation_view()

    view._tree.identify_row.return_value = study_tree_iid("study-1")
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) is not None

    view._tree.identify_row.return_value = series_tree_iid("series-1")
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) is not None

    view._tree.identify_row.return_value = ""
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) is None
