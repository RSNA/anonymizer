"""Analytics layout verification helpers (docs_help-style fixture wiring)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docs_help.project_setup import TEST_DCM_ROOT, collect_import_paths, fixture_dirs

# Re-export for tests that need fixture paths.
__all__ = ["TEST_DCM_ROOT", "collect_import_paths", "fixture_dirs", "require_fixture"]


def require_fixture(*keys: str) -> list[str]:
    """Return DICOM paths for named fixtures, or skip if a fixture dir is missing."""
    dirs = fixture_dirs()
    missing = [key for key in keys if not (dirs.get(key) or TEST_DCM_ROOT / key).is_dir()]
    if missing:
        pytest.skip(f"Test DICOM fixtures missing: {missing}")
    return collect_import_paths(*keys)


@pytest.fixture
def dcm_root() -> Path:
    return TEST_DCM_ROOT
