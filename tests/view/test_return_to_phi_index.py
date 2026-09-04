"""Tests for PHI Index navigation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from anonymizer.view.common.navigation import find_dataset_view_parent, return_to_dataset_view
from anonymizer.view.project.dataset import DatasetView


def test_find_dataset_view_parent_returns_index_ancestor() -> None:
    index = MagicMock(spec=DatasetView)
    child = MagicMock()
    child.master = index

    assert find_dataset_view_parent(child) is index


def test_return_to_dataset_view_refreshes_and_focuses_index() -> None:
    index = MagicMock(spec=DatasetView)
    index._update_tree_from_phi_index = MagicMock()
    index.lift = MagicMock()
    index.focus_force = MagicMock()

    child = MagicMock()
    child.master = index

    return_to_dataset_view(child)

    index._update_tree_from_phi_index.assert_called_once()
    index.lift.assert_called_once()
    index.focus_force.assert_called_once()
