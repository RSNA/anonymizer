"""Unit tests for step-6 NER residual text cleanup."""

from __future__ import annotations

from pydicom.dataset import Dataset

from prototyping.pseudo_phi_deid.pipeline.ner_residual_cleanup import (
    cleanup_dataset_residuals,
    cleanup_residual_text,
)


def test_dangling_for_after_name_blank() -> None:
    assert cleanup_residual_text("XR CHEST AP PORTABLE for") == "XR CHEST AP PORTABLE"
    assert cleanup_residual_text("XR CHEST AP PORTABLE for  ") == "XR CHEST AP PORTABLE"


def test_forfile_prefix() -> None:
    assert (
        cleanup_residual_text("FORFILE CT ABD AND/OR PEL - CD")
        == "CT ABD AND/OR PEL - CD"
    )
    assert cleanup_residual_text("FOR FILE CT CHEST") == "CT CHEST"


def test_month_year_tokens() -> None:
    assert cleanup_residual_text("PARENCHYMAL PHASE Sep1999") == "PARENCHYMAL PHASE"
    assert cleanup_residual_text("PARENCHYMAL PHASE Sep199") == "PARENCHYMAL PHASE"
    assert cleanup_residual_text("PHASE Sep 1999 axial") == "PHASE axial"
    assert cleanup_residual_text("scan December-2010 done") == "scan done"


def test_combined_forfile_and_for() -> None:
    assert (
        cleanup_residual_text("FORFILE CT CH/AB/PEL - CD for")
        == "CT CH/AB/PEL - CD"
    )
    assert (
        cleanup_residual_text("FORFILE CT CH/AB/PEL - CD for 8155012288")
        == "CT CH/AB/PEL - CD"
    )


def test_preserves_for_patient_phrase() -> None:
    assert (
        cleanup_residual_text("Ordered by Dr. for Patient")
        == "Ordered by Dr. for Patient"
    )


def test_preserves_trailing_comma_on_technical_lo() -> None:
    raw = "measured,, 0.096000 cm-1,"
    assert cleanup_residual_text(raw) == raw


def test_dataset_walk_updates_study_description() -> None:
    ds = Dataset()
    ds.StudyDescription = "XR CHEST AP PORTABLE for"
    ds.SeriesDescription = "PARENCHYMAL PHASE Sep1999"
    n = cleanup_dataset_residuals(ds)
    assert n == 2
    assert ds.StudyDescription == "XR CHEST AP PORTABLE"
    assert ds.SeriesDescription == "PARENCHYMAL PHASE"
