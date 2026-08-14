"""Tests for PHI Index navigation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from anonymizer.view.common.navigation import find_phi_index_parent, return_to_phi_index
from anonymizer.view.project.index import IndexView


def test_find_phi_index_parent_returns_index_ancestor() -> None:
    index = MagicMock(spec=IndexView)
    child = MagicMock()
    child.master = index

    assert find_phi_index_parent(child) is index


def test_return_to_phi_index_refreshes_and_focuses_index() -> None:
    index = MagicMock(spec=IndexView)
    index._update_tree_from_phi_index = MagicMock()
    index.lift = MagicMock()
    index.focus_force = MagicMock()

    child = MagicMock()
    child.master = index

    return_to_phi_index(child)

    index._update_tree_from_phi_index.assert_called_once()
    index.lift.assert_called_once()
    index.focus_force.assert_called_once()
