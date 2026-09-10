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


def _series(uid: str, *, modality: str = "CT") -> PHI_SeriesIndexRecord:
    return PHI_SeriesIndexRecord(
        anon_series_uid=uid,
        modality=modality,
        description="Ax",
        harmonized_description="Ch Ax WO",
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
    view._tree.selection.return_value = ()
    view._dismiss_description_combo = MagicMock()
    view._open_projection_view = MagicMock()
    view._open_series_by_uid = MagicMock()
    view._edit_series_description = MagicMock()
    view._edit_study_description = MagicMock()
    view._controller = MagicMock()
    view._controller.anonymizer.model.get_study_harmonized_description.return_value = ""
    return view


def test_right_click_series_opens_series_view() -> None:
    view = _navigation_view()
    view._tree.identify_row.return_value = series_tree_iid("series-1")

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._tree.selection_set.assert_called_once_with(series_tree_iid("series-1"))
    view._open_series_by_uid.assert_called_once_with("series-1")
    view._open_projection_view.assert_not_called()
    view._edit_series_description.assert_not_called()


def test_right_click_study_opens_projection_view() -> None:
    view = _navigation_view()
    study = view._studies_by_uid["study-1"]
    view._tree.identify_row.return_value = study_tree_iid("study-1")

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._tree.selection_set.assert_called_once_with(study_tree_iid("study-1"))
    view._open_projection_view.assert_called_once_with([study])
    view._open_series_by_uid.assert_not_called()
    view._edit_study_description.assert_not_called()


def test_right_click_multi_series_opens_set_description() -> None:
    view = _navigation_view()
    study = view._studies_by_uid["study-1"]
    view._series_by_uid["series-2"] = (study, _series("series-2"))
    iid1 = series_tree_iid("series-1")
    iid2 = series_tree_iid("series-2")
    view._tree.selection.return_value = (iid1, iid2)
    view._tree.identify_row.return_value = iid1

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._edit_series_description.assert_called_once_with(iid1, "series-1")
    view._tree.selection_set.assert_not_called()
    view._open_series_by_uid.assert_not_called()


def test_right_click_multi_study_opens_set_description() -> None:
    view = _navigation_view()
    view._studies_by_uid["study-2"] = _study("study-2")
    view._series_by_uid["series-2"] = (view._studies_by_uid["study-2"], _series("series-2", modality="CR"))
    # Studies need a LOINC prefix path; mock selection classifier via real series modalities on studies.
    # study_loinc_prefix_for_edit needs model composition — stub selected targets instead.
    iid1 = study_tree_iid("study-1")
    iid2 = study_tree_iid("study-2")
    view._tree.selection.return_value = (iid1, iid2)
    view._tree.identify_row.return_value = iid2
    view._selected_description_targets = MagicMock(
        return_value=("study", ["study-1", "study-2"], SimpleNamespace(count=2, reason=""))
    )

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._edit_study_description.assert_called_once_with(iid2, "study-2")
    view._tree.selection_set.assert_not_called()
    view._open_projection_view.assert_not_called()


def test_right_click_multi_mixed_keeps_selection() -> None:
    view = _navigation_view()
    iid_series = series_tree_iid("series-1")
    iid_study = study_tree_iid("study-1")
    view._tree.selection.return_value = (iid_series, iid_study)
    view._tree.identify_row.return_value = iid_series

    view._on_tree_right_click(SimpleNamespace(y=12))

    view._edit_series_description.assert_not_called()
    view._edit_study_description.assert_not_called()
    view._open_series_by_uid.assert_not_called()
    view._open_projection_view.assert_not_called()
    view._tree.selection_set.assert_not_called()


def test_tree_row_tooltip_text_by_row_type() -> None:
    view = _navigation_view()

    view._tree.identify_row.return_value = study_tree_iid("study-1")
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) == (
        "Click description to choose a LOINC name · Right-click opens projections"
    )

    view._tree.identify_row.return_value = series_tree_iid("series-1")
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) == (
        "Click description to choose a RadLex name · Right-click opens Series View"
    )

    view._tree.identify_row.return_value = ""
    assert view._tree_row_tooltip_text(SimpleNamespace(y=1)) is None


def test_tree_row_tooltip_text_multi_select_series() -> None:
    view = _navigation_view()
    study = view._studies_by_uid["study-1"]
    view._series_by_uid["series-2"] = (study, _series("series-2"))
    iid1 = series_tree_iid("series-1")
    iid2 = series_tree_iid("series-2")
    view._tree.selection.return_value = (iid1, iid2)
    view._tree.identify_row.return_value = iid1

    tip = view._tree_row_tooltip_text(SimpleNamespace(y=1))
    assert tip == "Right-click to set the same RadLex description on 2 selected series"
