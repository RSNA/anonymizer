"""Tests for Dataset View / workspace navigation helpers."""

from unittest.mock import MagicMock

from anonymizer.view.common.navigation import (
    find_dataset_view_parent,
    return_after_workspace,
    return_to_dataset_view,
)
from anonymizer.view.project.dataset import DatasetView


def test_find_dataset_view_parent_returns_index_ancestor() -> None:
    index = MagicMock(spec=DatasetView)
    index.IS_DATASET_VIEW = True
    child = MagicMock()
    child.master = index

    assert find_dataset_view_parent(child) is index


def test_return_to_dataset_view_refreshes_and_focuses_index() -> None:
    index = MagicMock(spec=DatasetView)
    index.IS_DATASET_VIEW = True
    index._update_tree_from_phi_index = MagicMock()
    index.lift = MagicMock()
    index.focus_force = MagicMock()

    child = MagicMock()
    child.master = index

    return_to_dataset_view(child)

    index._update_tree_from_phi_index.assert_called_once()
    index.lift.assert_called_once()
    index.focus_force.assert_called_once()


def test_return_after_workspace_focuses_opener_not_dataset() -> None:
    """Closing Series View opened from View Projections must focus projections."""
    index = MagicMock(spec=DatasetView)
    index.IS_DATASET_VIEW = True
    index._update_tree_from_phi_index = MagicMock()
    index.lift = MagicMock()
    index.focus_force = MagicMock()

    projections = MagicMock()
    projections.master = index
    projections.winfo_exists.return_value = True
    projections.lift = MagicMock()
    projections.focus_force = MagicMock()

    series_view = MagicMock()
    series_view.master = projections

    return_after_workspace(series_view, projections)

    index._update_tree_from_phi_index.assert_called_once()
    projections.lift.assert_called_once()
    projections.focus_force.assert_called_once()
    index.lift.assert_not_called()
    index.focus_force.assert_not_called()


def test_return_after_workspace_falls_back_to_dataset_when_opener_gone() -> None:
    index = MagicMock(spec=DatasetView)
    index.IS_DATASET_VIEW = True
    index._update_tree_from_phi_index = MagicMock()
    index.lift = MagicMock()
    index.focus_force = MagicMock()
    index.winfo_exists.return_value = True

    projections = MagicMock()
    projections.master = index
    projections.winfo_exists.return_value = False

    series_view = MagicMock()
    series_view.master = projections

    return_after_workspace(series_view, projections)

    index._update_tree_from_phi_index.assert_called_once()
    index.lift.assert_called_once()
    index.focus_force.assert_called_once()
