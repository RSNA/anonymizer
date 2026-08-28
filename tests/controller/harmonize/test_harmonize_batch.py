"""Tests for PHI Index batch harmonize helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from anonymizer.controller.ai.harmonize import (
    HarmonizedResult,
    apply_harmonized_description,
    enumerate_ct_series_for_studies,
    format_harmonize_batch_progress_text,
    format_harmonize_progress_message,
    harmonize_and_apply_series,
    harmonize_studies_batch,
    study_harmonize_status,
)
from anonymizer.controller.ai.tseg.segment import AnalysisProgress, TS_result, format_anatomy_regions_summary


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


@patch("anonymizer.controller.ai.harmonize.pipeline._load_ct_series_dataset")
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


@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
def test_study_harmonize_status_true_when_all_ct_series_harmonized(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    anon_model = MagicMock()
    anon_model.study_is_harmonized.return_value = True

    assert study_harmonize_status(anon_model, "anon_study") is True
    anon_model.study_is_harmonized.assert_called_once_with("anon_study")
    mock_load.assert_not_called()


@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
def test_study_harmonize_status_false_when_any_ct_series_not_harmonized(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    anon_model = MagicMock()
    anon_model.study_is_harmonized.return_value = False

    assert study_harmonize_status(anon_model, "anon_study") is False
    anon_model.study_is_harmonized.assert_called_once_with("anon_study")
    mock_load.assert_not_called()


@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
def test_study_harmonize_status_false_when_no_ct_series(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    anon_model = MagicMock()
    anon_model.study_is_harmonized.return_value = False

    assert study_harmonize_status(anon_model, "anon_study") is False
    anon_model.study_is_harmonized.assert_called_once_with("anon_study")
    mock_load.assert_not_called()


@patch("anonymizer.controller.ai.harmonize.pipeline.harmonize_series")
@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
def test_harmonize_and_apply_series_skips_when_model_harmonized(
    mock_load: MagicMock,
    mock_harmonize: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, _studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_ct"
    ds = _ct_dataset()
    ds.SeriesDescription = "CT Head Ax WO"
    mock_load.return_value = ds
    anon_model = MagicMock()
    anon_model.series_is_harmonized.return_value = True
    anon_model.get_series_processing_status.return_value = MagicMock(harmonized_description="CT Head Ax WO")

    outcome = harmonize_and_apply_series(series_path, anon_model=anon_model)

    assert outcome.status == "skipped"
    assert "model" in outcome.message.lower()
    mock_harmonize.assert_not_called()


@patch("anonymizer.controller.ai.harmonize.pipeline.harmonize_series")
@patch("anonymizer.controller.ai.harmonize.pipeline.series_description_is_harmonized", return_value=True)
@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
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


@patch("anonymizer.controller.ai.harmonize.pipeline.apply_harmonized_description", return_value=True)
@patch("anonymizer.controller.ai.harmonize.pipeline.harmonize_series")
@patch("anonymizer.controller.ai.harmonize.pipeline.series_description_is_harmonized", return_value=False)
@patch("anonymizer.controller.ai.harmonize.pipeline._load_tseg_series_dataset")
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


@patch("anonymizer.controller.series_io.apply_series_description", return_value=True)
@patch("anonymizer.controller.ai.harmonize.pipeline._load_series_dataset")
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


@patch("anonymizer.controller.series_io.apply_series_description", return_value=True)
@patch("anonymizer.controller.ai.harmonize.pipeline._load_series_dataset")
def test_apply_harmonized_description_skips_dicom_when_unchanged(
    mock_load: MagicMock,
    mock_apply_dicom: MagicMock,
    tmp_path: Path,
) -> None:
    series_path = tmp_path / "series"
    series_path.mkdir()
    anon_model = MagicMock()
    anon_model.set_series_harmonized_description.return_value = True
    ds = _ct_dataset()
    ds.SeriesDescription = "Ch Ax PortVen"
    mock_load.return_value = ds

    assert apply_harmonized_description(series_path, "Ch Ax PortVen", anon_model) is True

    mock_apply_dicom.assert_not_called()
    anon_model.set_series_harmonized_description.assert_called_once_with("1.2.3", "Ch Ax PortVen")


@patch("anonymizer.controller.ai.harmonize.pipeline.tseg_batch_session")
@patch("anonymizer.controller.ai.harmonize.pipeline.harmonize_and_apply_series")
@patch("anonymizer.controller.ai.harmonize.pipeline.enumerate_tseg_series_for_studies")
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
        from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

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


def test_format_ai_batch_completion_summary_per_algorithm() -> None:
    from anonymizer.controller.ai_batch_process import (
        AiBatchAlgorithm,
        AiBatchAlgorithmTotals,
        AiBatchSummary,
        format_ai_batch_completion_summary,
    )

    summary = AiBatchSummary(
        series_count=2,
        applied=4,
        skipped=2,
        failed=0,
        algorithm_totals=(
            (AiBatchAlgorithm.REMOVE_PIXEL_PHI, AiBatchAlgorithmTotals(complete=2)),
            (AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithmTotals(applied=2)),
            (AiBatchAlgorithm.FACE_BLUR, AiBatchAlgorithmTotals(applied=2)),
        ),
    )
    message = format_ai_batch_completion_summary(summary)
    assert message == ("Complete: 2 series\n  Harmonize: 2 modified\n  Face De-identify: 2 modified")
    assert "Remove Burnt-in Annotation" not in message


def test_should_log_harmonize_batch_step_skips_redundant_messages() -> None:
    from anonymizer.controller.ai_batch_process import should_log_harmonize_batch_step
    from anonymizer.controller.ai.tseg.segment import AnalysisProgress

    assert should_log_harmonize_batch_step(
        AnalysisProgress(
            stage="regions",
            message="Anatomy: Head (dominant: Head)",
            fraction=0.5,
            elapsed_sec=1.0,
        )
    )
    assert not should_log_harmonize_batch_step(
        AnalysisProgress(
            stage="merge",
            message="Building harmonized description",
            fraction=0.95,
            elapsed_sec=1.0,
        )
    )
    assert not should_log_harmonize_batch_step(
        AnalysisProgress(
            stage="contrast",
            message="Analyzing contrast phase",
            fraction=0.7,
            elapsed_sec=1.0,
        )
    )


def test_log_workflow_progress_step_dedupes_ellipsis_variants() -> None:
    from anonymizer.controller.ai_batch_process import _log_workflow_progress_step

    logged: list[str] = []
    last_stage: list[str | None] = [None]

    def log_workflow(message: str) -> None:
        logged.append(message)

    _log_workflow_progress_step(
        log_workflow,
        lambda _fraction, _detail: None,
        fraction=0.1,
        message="Determining contrast phase",
        stage_key="contrast",
        last_stage_key=last_stage,
    )
    _log_workflow_progress_step(
        log_workflow,
        lambda _fraction, _detail: None,
        fraction=0.2,
        message="Determining contrast phase…",
        stage_key="contrast",
        last_stage_key=last_stage,
    )
    assert logged == ["  Determining contrast phase"]


def test_format_harmonize_progress_message_geometry_stage() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="geometry",
            message="Geometry analysis: Axial · Diagnostic 3D volume · TS ok",
            fraction=0.08,
            elapsed_sec=1.0,
        ),
        include_pct=False,
    )
    assert message == "Axial · Diagnostic 3D volume · TS ok"


def test_format_harmonize_progress_message_geometry_stage_with_pct() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="geometry",
            message="Geometry analysis: Axial · Diagnostic 3D volume · TS ok",
            fraction=0.08,
            elapsed_sec=1.0,
        )
    )
    assert message == "Axial · Diagnostic 3D volume · TS ok (8%)"


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


def test_format_harmonize_progress_message_failed_stage() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="failed",
            message="ValueError: example failure",
            fraction=1.0,
            elapsed_sec=3.0,
        ),
        include_pct=False,
    )
    assert message == "Harmonize analysis failed: ValueError: example failure"


def test_format_harmonize_progress_message_passes_through_cache_summaries() -> None:
    message = format_harmonize_progress_message(
        AnalysisProgress(
            stage="contrast_stats_cached",
            message="Using cached organ HU statistics: liver=120 HU, aorta=180 HU",
            fraction=0.3,
            elapsed_sec=1.0,
        ),
        include_pct=False,
    )
    assert message == "Using cached organ HU statistics: liver=120 HU, aorta=180 HU"


def test_format_anatomy_regions_summary_includes_dominant_region() -> None:
    summary = format_anatomy_regions_summary(
        TS_result(
            series_directory=Path("/tmp/series"),
            dominant_region="Head",
            body_parts_present="Head+Chest",
            multi_region=True,
            region_fraction=0.6,
            iv_contrast=False,
            contrast_phase="",
            phase_probability=0.0,
        )
    )
    assert summary == "Head, Chest (dominant: Head)"


def test_format_playbook_analysis_log_lines_match_table() -> None:
    from anonymizer.controller.ai.tseg.dicom_geometry import SeriesGeometryResult
    from anonymizer.controller.ai.harmonize.playbook import (
        PlaybookHarmonizeAttributes,
        format_playbook_analysis_log_lines,
        harmonize_analysis_rows,
    )

    tseg = TS_result(
        series_directory=Path("/tmp/series"),
        dominant_region="Abdomen",
        body_parts_present="Head+Abdomen",
        multi_region=True,
        region_fraction=0.727,
        iv_contrast=True,
        contrast_phase="portal_venous",
        phase_probability=0.91,
    )
    geometry = SeriesGeometryResult(
        plane="axial",
        plane_confidence=0.99,
        slice_normal_lps=(0.0, 0.0, 1.0),
        plane_angles_deg={"axial": 5.0, "coronal": 85.0, "sagittal": 85.0},
        dimensionality="volume_3d",
        n_slices=24,
        through_plane_extent_mm=150.0,
        slice_spacing_mm=5.0,
        spacing_regularity=1.0,
        provenance="original",
        provenance_confidence=0.9,
        image_type=("ORIGINAL", "PRIMARY", "AXIAL"),
        source_series_uids=(),
        ts_suitable=True,
        metadata_suspect=False,
        method="dicom_headers",
        notes="",
    )
    attributes = PlaybookHarmonizeAttributes(
        body_part_code="Abdomen",
        anatomic_plane_code="Ax",
        iv_contrast_code="C+",
        series_type_code="",
        body_part_confidence=0.727,
        plane_confidence=0.99,
        contrast_confidence=0.91,
        contrast_phase="portal_venous",
    )
    rows = harmonize_analysis_rows(attributes, geometry=geometry, tseg=tseg)
    lines = format_playbook_analysis_log_lines(attributes, geometry=geometry, tseg=tseg)
    assert len(lines) >= 3
    assert "Head, Abdomen (dominant: Abdomen)" in rows[0][3]
    assert "Axial · Diagnostic 3D volume · TS ok" in rows[1][3]
    assert "portal venous ·" in rows[2][3]
    assert any("Head, Abdomen (dominant: Abdomen)" in line for line in lines)
    assert any("Axial · Diagnostic 3D volume · TS ok" in line for line in lines)
    assert any("portal venous ·" in line for line in lines)


def test_format_harmonize_batch_contrast_log_lines(tmp_path: Path) -> None:
    from anonymizer.controller.ai.harmonize import HarmonizedResult, format_harmonize_batch_contrast_log_lines
    from anonymizer.controller.ai.tseg.contrast import save_contrast_statistics
    from anonymizer.controller.ai.harmonize.playbook import PlaybookHarmonizeAttributes
    from anonymizer.controller.ai.tseg.segment import series_cache_dir

    series_dir = tmp_path / "series"
    series_dir.mkdir()
    cache_dir = series_cache_dir(series_dir)
    cache_dir.mkdir(parents=True)
    save_contrast_statistics(
        {
            "liver": {"intensity": 120.0, "volume": 5000.0},
            "aorta": {"intensity": 180.0, "volume": 800.0},
            "inferior_vena_cava": {"intensity": 90.0, "volume": 600.0},
            "portal_vein_and_splenic_vein": {"intensity": 110.0, "volume": 400.0},
            "brain": {"intensity": 30.0, "volume": 100.0},
        },
        cache_dir / "contrast_stats.json",
    )
    tseg = TS_result(
        series_directory=series_dir,
        dominant_region="Abdomen",
        body_parts_present="Abdomen",
        multi_region=False,
        region_fraction=0.9,
        iv_contrast=True,
        contrast_phase="portal_venous",
        phase_probability=0.91,
    )
    result = HarmonizedResult(
        series_directory=series_dir,
        radlex_series_description="Abd Ax C+",
        tseg=tseg,
        playbook=PlaybookHarmonizeAttributes(
            body_part_code="Abd",
            anatomic_plane_code="Ax",
            iv_contrast_code="C+",
            series_type_code="",
            body_part_confidence=0.9,
            plane_confidence=0.99,
            contrast_confidence=0.91,
            contrast_phase="portal_venous",
        ),
    )

    lines = format_harmonize_batch_contrast_log_lines(result)

    assert len(lines) == 2
    assert lines[0].startswith("IV Contrast Phase:")
    assert "91.00% confidence" in lines[0]
    assert "portal venous" in lines[0]
    assert lines[1].startswith("Dominant organ HU:")
    assert "90–180 HU" in lines[1]
    assert "liver=120 HU" in lines[1]
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


@patch("anonymizer.controller.ai.harmonize.pipeline.tseg_batch_session")
@patch("anonymizer.controller.ai.harmonize.pipeline.harmonize_and_apply_series")
@patch("anonymizer.controller.ai.harmonize.pipeline.enumerate_tseg_series_for_studies")
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

    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

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


@patch("anonymizer.controller.ai.tseg.model_cache.preload_harmonize_models")
@patch("anonymizer.controller.ai.tseg.model_cache._install_predictor_cache_patch")
def test_tseg_batch_session_preloads_once(
    mock_install: MagicMock,
    mock_preload: MagicMock,
) -> None:
    from anonymizer.controller.ai.tseg.model_cache import tseg_batch_session

    with tseg_batch_session(preload=True):
        with tseg_batch_session(preload=True):
            pass

    mock_install.assert_called()
    mock_preload.assert_called_once()


@patch("anonymizer.controller.ai.tseg.contrast.collect_garbage_safe")
@patch("anonymizer.controller.ai.tseg.contrast.release_accelerator_caches")
def test_release_working_memory_skips_accelerator_clear_during_batch(
    mock_release_caches: MagicMock,
    mock_gc: MagicMock,
) -> None:
    from anonymizer.controller.ai.tseg.contrast import release_working_memory
    from anonymizer.controller.ai.tseg.model_cache import tseg_batch_session

    with patch("anonymizer.controller.ai.tseg.model_cache.preload_harmonize_models"):
        with patch("anonymizer.controller.ai.tseg.model_cache._install_predictor_cache_patch"):
            with tseg_batch_session(preload=False):
                release_working_memory(stage="during_batch")
                mock_release_caches.assert_called()
                mock_gc.assert_not_called()

    mock_gc.reset_mock()
    mock_release_caches.reset_mock()
    release_working_memory(stage="after_batch")
    mock_release_caches.assert_called_once()
    mock_gc.assert_called_once()
