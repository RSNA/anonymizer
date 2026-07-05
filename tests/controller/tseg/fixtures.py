"""Shared synthetic CT DICOM fixtures for tseg and FALCON controller tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR
from tests.controller.tseg.support.synthetic_ct import (
    build_synthetic_abdomen_ct_series,
    build_synthetic_chest_ct_series,
    build_synthetic_head_ct_series,
    list_dcm_files,
    write_synthetic_phantom_assets,
)

SYNTHETIC_CT_HEAD_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_head"
SYNTHETIC_CT_CHEST_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_chest"
SYNTHETIC_CT_ABDOMEN_ASSET_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_abdomen"

SYNTHETIC_CT_ASSET_DIRS: dict[str, Path] = {
    "head": SYNTHETIC_CT_HEAD_ASSET_DIR,
    "chest": SYNTHETIC_CT_CHEST_ASSET_DIR,
    "abdomen": SYNTHETIC_CT_ABDOMEN_ASSET_DIR,
}


def ensure_synthetic_ct_assets() -> dict[str, Path]:
    """Write committed phantom asset dirs when missing (session-safe)."""
    head_dir = SYNTHETIC_CT_HEAD_ASSET_DIR
    if not head_dir.exists() or not list_dcm_files(head_dir):
        return write_synthetic_phantom_assets()
    return {
        head_dir.name: head_dir,
        SYNTHETIC_CT_CHEST_ASSET_DIR.name: SYNTHETIC_CT_CHEST_ASSET_DIR,
        SYNTHETIC_CT_ABDOMEN_ASSET_DIR.name: SYNTHETIC_CT_ABDOMEN_ASSET_DIR,
    }


@pytest.fixture(scope="session")
def synthetic_ct_asset_dirs() -> dict[str, Path]:
    assets = ensure_synthetic_ct_assets()
    return {
        "head": assets[SYNTHETIC_CT_HEAD_ASSET_DIR.name],
        "chest": assets[SYNTHETIC_CT_CHEST_ASSET_DIR.name],
        "abdomen": assets[SYNTHETIC_CT_ABDOMEN_ASSET_DIR.name],
    }


@pytest.fixture
def synthetic_head_series(tmp_path: Path) -> Path:
    return build_synthetic_head_ct_series(tmp_path / "head")


@pytest.fixture
def synthetic_chest_series(tmp_path: Path) -> Path:
    return build_synthetic_chest_ct_series(tmp_path / "chest")


@pytest.fixture
def synthetic_abdomen_series(tmp_path: Path) -> Path:
    return build_synthetic_abdomen_ct_series(tmp_path / "abdomen")
