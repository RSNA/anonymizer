"""Stable paths to shared controller test assets."""

from __future__ import annotations

from pathlib import Path

CONTROLLER_TESTS_ROOT = Path(__file__).resolve().parent
CONTROLLER_ASSETS = CONTROLLER_TESTS_ROOT / "assets"
CONTROLLER_TEST_DCM_FILES_DIR = CONTROLLER_ASSETS / "test_dcm_files"
JAVA_GENERATED_INDEX = CONTROLLER_ASSETS / "JavaGeneratedIndex.xlsx"
