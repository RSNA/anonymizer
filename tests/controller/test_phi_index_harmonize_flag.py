"""Dataset Harmonized (green) flag for CT/MR and planar XR/US/MG studies."""

from __future__ import annotations

import types
from types import SimpleNamespace

from anonymizer.controller.phi_io import _study_index_harmonized
from anonymizer.model.anonymizer import Study


def _series(modality: str, harmonized: str | None) -> SimpleNamespace:
    series = SimpleNamespace(modality=modality, harmonized_description=harmonized)
    series.is_description_harmonized = lambda: bool((harmonized or "").strip())
    return series


def _study(series: list[SimpleNamespace]) -> SimpleNamespace:
    study = SimpleNamespace(series=series)
    study.harmonize_series = types.MethodType(Study.harmonize_series, study)
    study.all_series_harmonized = types.MethodType(Study.all_series_harmonized, study)
    return study


def test_study_index_harmonized_pure_xr() -> None:
    study = _study([_series("CR", "Chest AP")])
    assert _study_index_harmonized(study)
    study_incomplete = _study([_series("CR", None)])
    assert not _study_index_harmonized(study_incomplete)


def test_study_index_harmonized_pure_us() -> None:
    study = _study([_series("US", "Abdomen")])
    assert _study_index_harmonized(study)


def test_study_index_harmonized_mixed_requires_planar_siblings() -> None:
    """Mixed CT + DX: planar sibling must also be harmonized for study green."""
    study = _study(
        [
            _series("CT", "Brain Ax WO"),
            _series("DX", None),
        ]
    )
    assert not _study_index_harmonized(study)
    study_done = _study(
        [
            _series("CT", "Brain Ax WO"),
            _series("DX", "Chest AP"),
        ]
    )
    assert _study_index_harmonized(study_done)


def test_study_index_harmonized_mr() -> None:
    study = _study([_series("MR", "Brain Ax WO")])
    assert _study_index_harmonized(study)
    assert not _study_index_harmonized(_study([_series("MR", "")]))


def test_study_index_harmonized_sc_only_false() -> None:
    study = _study([_series("SC", "whatever")])
    assert not _study_index_harmonized(study)


def test_study_index_harmonized_report_only_false() -> None:
    """SR/DOC/PDF alone do not turn the study row green (imaging gate only)."""
    study = _study([_series("SR", "Radiation Dose Information")])
    assert not _study_index_harmonized(study)


def test_study_index_harmonized_planar_plus_doc_ignores_doc() -> None:
    """DOC siblings must not block planar study green."""
    study = _study([_series("CR", "Chest PA"), _series("DOC", None)])
    assert _study_index_harmonized(study)
