"""Tests for PHI Index batch harmonize helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from anonymizer.controller.harmonize import (
    HarmonizedResult,
    apply_harmonized_description,
    format_harmonize_batch_progress_text,
    format_harmonize_progress_message,
    harmonize_and_apply_series,
    harmonize_studies_batch,
    enumerate_ct_series_for_studies,
    study_harmonize_status,
)
from anonymizer.controller.tseg.segment import AnalysisProgress


@pytest.fixture
def images_layout(tmp_path: Path) -> tuple[Path, list[tuple[str, str]]]:
    images_dir = tmp_path / "public"
    study_path = images_dir / "anon_pt" / "anon_study"
    ct_series = study_path / "series_ct"
    mr_series = study_path / "series_mr"
    ct_series.mkdir(parents=True)
    mr_series.mkdir(parents=True)
    (ct_series / "1.dcm").write_bytes(b"")
    (mr_series / "1.dcm").write_bytes(b"")
    return images_dir, [("anon_pt", "anon_study")]


def _ct_dataset() -> Dataset:
    ds = Dataset()
    ds.Modality = "CT"
    ds.SeriesInstanceUID = "1.2.3"
    return ds


@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_enumerate_ct_series_for_studies_filters_non_ct(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout

    def _load(path: Path) -> Dataset | None:
        if path.name == "series_ct":
            return _ct_dataset()
        return None

    mock_load.side_effect = _load
    series_paths = enumerate_ct_series_for_studies(images_dir, studies)
    assert len(series_paths) == 1
    assert series_paths[0].name == "series_ct"


@patch("anonymizer.controller.harmonize.series_description_is_harmonized")
@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_study_harmonize_status_true_when_all_ct_series_harmonized(
    mock_load: MagicMock,
    mock_is_harmonized: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    mock_load.return_value = _ct_dataset()
    mock_is_harmonized.return_value = True

    assert study_harmonize_status(images_dir, "anon_pt", "anon_study") is True


@patch("anonymizer.controller.harmonize.series_description_is_harmonized")
@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_study_harmonize_status_false_when_any_ct_series_not_harmonized(
    mock_load: MagicMock,
    mock_is_harmonized: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    mock_load.return_value = _ct_dataset()
    mock_is_harmonized.return_value = False

    assert study_harmonize_status(images_dir, "anon_pt", "anon_study") is False


@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_study_harmonize_status_false_when_no_ct_series(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, _studies = images_layout
    mock_load.return_value = None

    assert study_harmonize_status(images_dir, "anon_pt", "anon_study") is False


@patch("anonymizer.controller.harmonize.harmonize_series")
@patch("anonymizer.controller.harmonize.series_description_is_harmonized", return_value=True)
@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_harmonize_and_apply_series_skips_already_harmonized(
    mock_load: MagicMock,
    mock_is_harmonized: MagicMock,
    mock_harmonize: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, _studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_ct"
    mock_load.return_value = _ct_dataset()

    outcome = harmonize_and_apply_series(series_path)

    assert outcome.status == "skipped"
    assert outcome.message == "Already harmonized"
    mock_is_harmonized.assert_called_once()
    mock_harmonize.assert_not_called()


@patch("anonymizer.controller.harmonize.apply_harmonized_description", return_value=True)
@patch("anonymizer.controller.harmonize.harmonize_series")
@patch("anonymizer.controller.harmonize.series_description_is_harmonized", return_value=False)
@patch("anonymizer.controller.harmonize._load_ct_series_dataset")
def test_harmonize_and_apply_series_applies_merged_description(
    mock_load: MagicMock,
    _mock_is_harmonized: MagicMock,
    mock_harmonize: MagicMock,
    _mock_apply: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_ct"
    mock_load.return_value = _ct_dataset()
    mock_harmonize.return_value = [
        HarmonizedResult(
            series_directory=series_path,
            radlex_series_description="Ch Ax PortVen",
            tseg=None,
        )
    ]

    outcome = harmonize_and_apply_series(series_path)
    assert outcome.status == "ok"
    assert outcome.message == "Ch Ax PortVen"


@patch("anonymizer.controller.create_projections.apply_series_description", return_value=True)
@patch("anonymizer.controller.harmonize._load_series_dataset")
def test_apply_harmonized_description_uses_set_series_harmonized_description(
    mock_load: MagicMock,
    _mock_apply_dicom: MagicMock,
    tmp_path: Path,
) -> None:
    series_path = tmp_path / "series"
    series_path.mkdir()
    anon_model = MagicMock()
    anon_model.set_series_harmonized_description.return_value = True
    ds = _ct_dataset()
    mock_load.return_value = ds

    assert apply_harmonized_description(series_path, "Ch Ax PortVen", anon_model) is True

    anon_model.set_series_harmonized_description.assert_called_once_with("1.2.3", "Ch Ax PortVen")


@patch("anonymizer.controller.harmonize.tseg_batch_session")
@patch("anonymizer.controller.harmonize.harmonize_and_apply_series")
@patch("anonymizer.controller.harmonize.enumerate_ct_series_for_studies")
def test_harmonize_studies_batch_honours_cancel(
    mock_enumerate: MagicMock,
    mock_apply_series: MagicMock,
    mock_batch_session: MagicMock,
    tmp_path: Path,
) -> None:
    series_paths = [tmp_path / "s1", tmp_path / "s2"]
    mock_enumerate.return_value = series_paths
    mock_batch_session.return_value.__enter__ = MagicMock(return_value=None)
    mock_batch_session.return_value.__exit__ = MagicMock(return_value=False)
    cancelled = {"value": False}

    def _apply(series_path: Path, **kwargs):
        if series_path == series_paths[0]:
            cancelled["value"] = True
        from anonymizer.controller.harmonize import HarmonizeApplyOutcome

        return HarmonizeApplyOutcome(series_path, "ok")

    mock_apply_series.side_effect = _apply

    summary = harmonize_studies_batch(
        tmp_path,
        [("pt", "study")],
        cancelled=lambda: cancelled["value"],
    )
    assert summary.processed == 1
    assert summary.applied == 1
    assert summary.cancelled is True


def test_format_harmonize_progress_message_geometry_stage() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="geometry",
            message="ignored",
            fraction=0.08,
            elapsed_sec=1.0,
        )
    )
    assert message.startswith("Analyzing scan geometry")
    assert message.endswith("(8%)")


def test_format_harmonize_progress_message_segment_stage() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="segment",
            message="Segmenting anatomy",
            fraction=0.25,
            elapsed_sec=2.0,
        )
    )
    assert "Segmenting anatomy (TotalSegmentator)" in message


def test_format_harmonize_batch_progress_text_includes_series_context() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Chest Ax C+"
    ds.SeriesNumber = 3
    series_path = Path("/tmp/series_ct")

    text = format_harmonize_batch_progress_text(
        series_index=2,
        total=5,
        progress=AnalysisProgress(
            stage="contrast",
            message="Analyzing contrast phase",
            fraction=0.7,
            elapsed_sec=3.0,
        ),
        series_path=series_path,
        ds=ds,
    )
    assert "Series 2/5" in text
    assert "Chest Ax C+" in text
    assert "Determining contrast phase" in text


@patch("anonymizer.controller.harmonize.tseg_batch_session")
@patch("anonymizer.controller.harmonize.harmonize_and_apply_series")
@patch("anonymizer.controller.harmonize.enumerate_ct_series_for_studies")
def test_harmonize_studies_batch_uses_tseg_batch_session_and_hooks(
    mock_enumerate: MagicMock,
    mock_apply_series: MagicMock,
    mock_batch_session: MagicMock,
    tmp_path: Path,
) -> None:
    series_paths = [tmp_path / "s1", tmp_path / "s2"]
    mock_enumerate.return_value = series_paths
    mock_batch_session.return_value.__enter__ = MagicMock(return_value=None)
    mock_batch_session.return_value.__exit__ = MagicMock(return_value=False)

    from anonymizer.controller.harmonize import HarmonizeApplyOutcome

    mock_apply_series.return_value = HarmonizeApplyOutcome(series_paths[0], "ok")
    progress_messages: list[str] = []
    batch_events: list[str] = []

    summary = harmonize_studies_batch(
        tmp_path,
        [("pt", "study")],
        progress=lambda _index, _total, message, _fraction: progress_messages.append(message),
        on_batch_start=lambda: batch_events.append("start"),
        on_batch_end=lambda: batch_events.append("end"),
    )

    mock_batch_session.assert_called_once_with(preload=True)
    assert batch_events == ["start", "end"]
    assert summary.processed == 2
    assert summary.applied == 2
    assert any("Loading anatomy analysis models" in message for message in progress_messages)


@patch("anonymizer.controller.tseg.model_cache.preload_harmonize_models")
@patch("anonymizer.controller.tseg.model_cache._install_predictor_cache_patch")
def test_tseg_batch_session_preloads_once(
    mock_install: MagicMock,
    mock_preload: MagicMock,
) -> None:
    from anonymizer.controller.tseg.model_cache import tseg_batch_session

    with tseg_batch_session(preload=True):
        with tseg_batch_session(preload=True):
            pass

    mock_install.assert_called()
    mock_preload.assert_called_once()


@patch("anonymizer.controller.tseg.contrast.release_accelerator_memory")
def test_release_working_memory_skips_accelerator_clear_during_batch(
    mock_release_accelerator: MagicMock,
) -> None:
    from anonymizer.controller.tseg.contrast import release_working_memory
    from anonymizer.controller.tseg.model_cache import tseg_batch_session

    with patch("anonymizer.controller.tseg.model_cache.preload_harmonize_models"):
        with patch("anonymizer.controller.tseg.model_cache._install_predictor_cache_patch"):
            with tseg_batch_session(preload=False):
                release_working_memory(stage="during_batch")
                mock_release_accelerator.assert_not_called()

    release_working_memory(stage="after_batch")
    mock_release_accelerator.assert_called_once()
