"""Dataset Harmonized (green) flag for CT/MR and planar XR/US/MG studies."""

from __future__ import annotations

from types import SimpleNamespace

from anonymizer.controller.phi_io import _study_index_harmonized


def _series(modality: str, harmonized: str | None) -> SimpleNamespace:
    return SimpleNamespace(modality=modality, harmonized_description=harmonized)


def test_study_index_harmonized_pure_xr() -> None:
    study = SimpleNamespace(series=[_series("CR", "Chest AP")])
    assert _study_index_harmonized(study)
    study_incomplete = SimpleNamespace(series=[_series("CR", None)])
    assert not _study_index_harmonized(study_incomplete)


def test_study_index_harmonized_pure_us() -> None:
    study = SimpleNamespace(series=[_series("US", "Abdomen")])
    assert _study_index_harmonized(study)


def test_study_index_harmonized_ct_ignores_unharmonized_dx_scout() -> None:
    study = SimpleNamespace(
        series=[
            _series("CT", "Brain Ax WO"),
            _series("DX", None),
        ]
    )
    assert _study_index_harmonized(study)


def test_study_index_harmonized_mr() -> None:
    study = SimpleNamespace(series=[_series("MR", "Brain Ax WO")])
    assert _study_index_harmonized(study)
    assert not _study_index_harmonized(SimpleNamespace(series=[_series("MR", "")]))


def test_study_index_harmonized_sc_only_false() -> None:
    study = SimpleNamespace(series=[_series("SC", "whatever")])
    assert not _study_index_harmonized(study)
