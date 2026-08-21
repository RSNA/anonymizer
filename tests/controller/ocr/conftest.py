"""Helpers for tests that use checked-in DICOM fixtures under assets/test_dcm_files."""

from __future__ import annotations

from pathlib import Path

import pytest

from anonymizer.controller.ai.remove_pixel_phi import ocr_models_ready
from tests.paths import REPO_ROOT

# EasyOCR cache is relative to the anonymizer package root (assets/ai/ocr/model).
_ANONYMIZER_PKG_ROOT = REPO_ROOT / "src" / "anonymizer"


def assert_dcm(path: Path) -> Path:
    """Fail loudly when a tracked asset DICOM is missing (do not skip)."""
    assert path.is_file(), f"Missing checked-in test DICOM: {path}"
    return path


def assert_dcm_dir(path: Path) -> Path:
    assert path.is_dir(), f"Missing checked-in test DICOM directory: {path}"
    assert any(path.glob("*.dcm")), f"No .dcm files in {path}"
    return path


@pytest.fixture(autouse=True)
def _anonymizer_package_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Match app cwd so relative OCR/whitelist asset paths resolve."""
    monkeypatch.chdir(_ANONYMIZER_PKG_ROOT)


@pytest.fixture
def require_ocr() -> None:
    """Skip when `-m ocr_integration` is selected but EasyOCR weights are absent."""
    if not ocr_models_ready():
        pytest.skip(
            "EasyOCR models not available under assets/ai/ocr/model — "
            "download via AI Features or download_ocr_models()"
        )
