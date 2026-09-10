"""Tests for Dataset description-click multi-select modifier masking."""

from __future__ import annotations

import sys

from anonymizer.view.project import dataset as dataset_mod


def test_tree_multiselect_state_excludes_windows_numlock_bits() -> None:
    """Num Lock is Mod1 (0x0008) on Windows — must not block description clicks."""
    mask = dataset_mod._TREE_MULTISELECT_STATE
    assert mask & 0x0001  # Shift
    assert mask & 0x0004  # Control
    if sys.platform != "darwin":
        assert not (mask & 0x0008), "Mod1/NumLock must not count as multi-select"
        assert not (mask & 0x0010), "Mod2 must not count as multi-select"
    else:
        assert mask & 0x00100000  # Command
        assert mask & 0x00080000  # Option
