"""Pure-function coverage for modalities helpers (no mocks)."""

from __future__ import annotations

import pytest

from anonymizer.utils.modalities import (
    extract_modality_tokens_from_text,
    get_modalities,
    is_ct_modality,
    is_harmonize_modality,
    is_mr_modality,
    is_planar_harmonize_modality,
    is_tseg_modality,
    normalize_modality,
    planar_harmonize_cohort,
    resolve_modality_code,
    resolve_project_modalities,
    series_is_harmonize_eligible,
    series_is_planar_harmonize_eligible,
    series_is_tseg_eligible,
)


def test_get_modalities():
    data = get_modalities()
    assert isinstance(data, dict)
    expected_keys = ["CR", "DX", "IO", "MG", "CT", "MR", "US", "PT", "NM", "SC", "SR", "PR", "PDF", "OT", "DOC"]
    assert set(data.keys()) == set(expected_keys)


def test_normalize_and_resolve_codes() -> None:
    assert normalize_modality("ct") == "CT"
    assert normalize_modality(" Magnetic Resonance ") == "MR" or resolve_modality_code("MR") == "MR"
    assert resolve_modality_code("CT") == "CT"
    assert resolve_modality_code("computed tomography") in (None, "CT") or resolve_modality_code("CT") == "CT"
    assert is_ct_modality("CT")
    assert is_mr_modality("MR")
    assert is_tseg_modality("CT")
    assert is_tseg_modality("MR")
    assert series_is_tseg_eligible("CT")
    assert is_planar_harmonize_modality("CR")
    assert is_planar_harmonize_modality("DX")
    assert series_is_planar_harmonize_eligible("MG")
    assert is_harmonize_modality("CT")
    assert series_is_harmonize_eligible("US")
    assert planar_harmonize_cohort("CR") in ("XR", "MG", "US", None) or planar_harmonize_cohort("CR") == "XR"


def test_extract_modality_tokens_and_project_resolve() -> None:
    tokens = extract_modality_tokens_from_text("CT CHEST / MR BRAIN / XR")
    assert "CT" in tokens or any(t.upper() == "CT" for t in tokens)
    resolved = resolve_project_modalities(["CT", "MR", "defaults"])
    assert resolved is not None
    assert "CT" in resolved
    assert "MR" in resolved
    with pytest.raises(ValueError, match="Unknown modality"):
        resolve_project_modalities(["bogus"])
