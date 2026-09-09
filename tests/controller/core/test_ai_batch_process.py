"""Tests for AI batch process orchestrator."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom.dataset import Dataset

from anonymizer.controller.ai.blur_face import (
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    face_blur_gate_message,
)
from anonymizer.controller.ai.remove_pixel_phi import (
    OcrWhitelistMatchMode,
    OcrWhitelistMatchSettings,
    PixelPhiRemovalMode,
)
from anonymizer.controller.ai_batch_process import (
    AiBatchAlgorithm,
    AiBatchOutcome,
    AiBatchProcessOptions,
    _apply_face_blur_series,
    _apply_remove_pixel_phi_series,
    _log_workflow_progress_step,
    ai_batch_process,
    effective_modality_whitelists,
    enumerate_series_for_studies,
    face_blur_skip_counts_as_complete,
    format_ai_batch_completion_summary,
    format_ai_batch_phase_label,
    format_ai_batch_status_line,
    format_batch_algorithm_result_line,
    format_batch_log_series_label,
    format_batch_outcome_subline,
    format_batch_phase_banner,
    format_batch_series_header,
    format_batch_step_subline,
    format_batch_workflow_log_line,
    format_modality_whitelist_preview,
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
    harmonize_skip_counts_as_complete,
    modalities_in_selected_studies,
    normalize_selected_algorithms,
    series_needs_face_blur,
    series_needs_harmonize,
    skip_message_for_face_blur_series,
    skip_message_for_harmonize_series,
    strip_progress_pct_suffix,
    whitelist_for_batch_ocr,
)
from tests.controller.blur_face.test_face_blur_gate import _geometry, _write_chest_region_cache


def _batch_test_dataset(*, modality: str = "CT") -> Dataset:
    ds = Dataset()
    ds.Modality = modality
    ds.SeriesInstanceUID = "1.2.3.4.5"
    ds.SeriesDescription = "Test Series"
    return ds


def _pending_anon_model() -> MagicMock:
    model = MagicMock()
    model.series_pixel_phi_scanned.return_value = False
    model.series_is_harmonized.return_value = False
    model.series_has_face_blur.return_value = False
    return model


def _patch_batch_runners():
    handle = MagicMock(reader=MagicMock())
    runner = MagicMock()
    return (
        patch(
            "anonymizer.controller.ai_batch_process.enter_batch_phase",
            return_value=(runner, handle),
        ),
        patch("anonymizer.controller.ai_batch_process.exit_batch_phase"),
        handle,
        runner,
    )


@pytest.fixture
def images_layout(tmp_path: Path) -> tuple[Path, list[tuple[str, str]]]:
    images_dir = tmp_path / "public"
    study_path = images_dir / "anon_pt" / "anon_study"
    series_a = study_path / "series_a"
    series_b = study_path / "series_b"
    series_a.mkdir(parents=True)
    series_b.mkdir(parents=True)
    (series_a / "1.dcm").write_bytes(b"")
    (series_b / "1.dcm").write_bytes(b"")
    return images_dir, [("anon_pt", "anon_study")]


def test_normalize_selected_algorithms_preserves_canonical_order() -> None:
    selected = (
        AiBatchAlgorithm.FACE_BLUR,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        AiBatchAlgorithm.HARMONIZE,
    )
    assert normalize_selected_algorithms(selected) == (
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        AiBatchAlgorithm.HARMONIZE,
        AiBatchAlgorithm.FACE_BLUR,
    )


def test_enumerate_series_for_studies_preserves_study_order(images_layout: tuple[Path, list[tuple[str, str]]]) -> None:
    images_dir, studies = images_layout
    items = enumerate_series_for_studies(images_dir, studies)
    assert len(items) == 2
    assert items[0][0:2] == (1, 1)
    assert items[1][0:2] == (1, 1)
    assert items[0][2].name == "series_a"
    assert items[1][2].name == "series_b"


def test_format_ai_batch_phase_label_single_algorithm() -> None:
    text = format_ai_batch_phase_label(
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        algorithm_index=1,
        algorithms_total=1,
    )
    assert text == "Remove Burnt-in Annotation"


def test_format_ai_batch_phase_label_multiple_algorithms() -> None:
    text = format_ai_batch_phase_label(
        AiBatchAlgorithm.HARMONIZE,
        algorithm_index=2,
        algorithms_total=3,
    )
    assert text == "Harmonize (2/3)"


def test_format_ai_batch_status_line_shows_study_series_only() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Chest Ax C+"
    text = format_ai_batch_status_line(
        study_index=2,
        study_total=5,
        series_index=3,
        series_total=8,
        ds=ds,
    )
    assert text == 'Study 2/5 · Series 3/8 · "Chest Ax C+"'
    assert "Harmonize" not in text
    assert "Analyzing" not in text
    assert "series_" not in text


def test_format_ai_batch_status_line_without_description() -> None:
    text = format_ai_batch_status_line(
        study_index=1,
        study_total=1,
        series_index=2,
        series_total=4,
    )
    assert text == "Study 1/1 · Series 2/4 · <No Series Description>"


def test_format_ai_batch_status_line_missing_description_on_dataset() -> None:
    ds = Dataset()
    text = format_ai_batch_status_line(
        study_index=1,
        study_total=1,
        series_index=1,
        series_total=1,
        ds=ds,
    )
    assert text == "Study 1/1 · Series 1/1 · <No Series Description>"


def test_format_ai_batch_status_line_ignores_step_detail() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Bone Vol. CECT 0.5"
    text = format_ai_batch_status_line(
        study_index=1,
        study_total=3,
        series_index=1,
        series_total=3,
        ds=ds,
    )
    assert text == 'Study 1/3 · Series 1/3 · "Bone Vol. CECT 0.5"'
    assert "Segmenting" not in text
    assert "%" not in text


def test_strip_progress_pct_suffix() -> None:
    assert strip_progress_pct_suffix("Determining contrast phase… (92%)") == ("Determining contrast phase…")
    assert strip_progress_pct_suffix("No percent here") == "No percent here"


def test_log_workflow_progress_step_logs_each_stage_once() -> None:
    logged: list[str] = []
    last_stage: list[str | None] = [None]
    step_updates: list[tuple[float, str]] = []

    def log_workflow(message: str) -> None:
        logged.append(message)

    def step_progress(fraction: float, detail: str) -> None:
        step_updates.append((fraction, detail))

    for fraction in (0.14, 0.27, 0.41):
        _log_workflow_progress_step(
            log_workflow,
            step_progress,
            fraction=fraction,
            message="Segmenting anatomy (TotalSegmentator)…",
            stage_key="segment",
            last_stage_key=last_stage,
        )

    assert logged == ["  Segmenting anatomy (TotalSegmentator)…"]
    assert len(step_updates) == 3


def test_log_workflow_progress_step_logs_distinct_messages_for_same_stage() -> None:
    logged: list[str] = []
    last_stage: list[str | None] = [None]

    def log_workflow(message: str) -> None:
        logged.append(message)

    _log_workflow_progress_step(
        log_workflow,
        lambda _fraction, _detail: None,
        fraction=0.1,
        message="Computing organ HU statistics…",
        stage_key="contrast_stats",
        last_stage_key=last_stage,
    )
    _log_workflow_progress_step(
        log_workflow,
        lambda _fraction, _detail: None,
        fraction=0.3,
        message="Organ HU statistics complete",
        stage_key="contrast_stats",
        last_stage_key=last_stage,
    )

    assert logged == [
        "  Computing organ HU statistics…",
        "  Organ HU statistics complete",
    ]


def test_format_batch_log_series_label() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Head CT"
    label = format_batch_log_series_label(
        study_index=3,
        study_total=10,
        series_index=5,
        series_total=12,
        ds=ds,
    )
    assert label == 'Study 3/10 · Series 5/12 · "Head CT"'


def test_format_batch_series_header_matches_status_line() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Head CT"
    line = format_batch_series_header(
        study_index=1,
        study_total=2,
        series_index=1,
        series_total=3,
        ds=ds,
    )
    assert line == 'Study 1/2 · Series 1/3 · "Head CT"\n'


def test_format_batch_algorithm_result_line_ok() -> None:
    ds = Dataset()
    ds.SeriesDescription = "Chest"
    line = format_batch_algorithm_result_line(
        study_index=1,
        study_total=1,
        series_index=1,
        series_total=1,
        algorithm=AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        outcome=AiBatchOutcome(
            Path("/tmp/hidden_uid"),
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            "ok",
            format_remove_pixel_phi_series_message(
                modified_count=28,
                total=188,
                texts_removed=["JOHN DOE", "MRN 12345"],
            ),
        ),
        ds=ds,
    )
    assert 'Study 1/1 · Series 1/1 · "Chest"\n' in line
    assert "  Applied:" in line
    assert "Modified 28/188" in line
    assert "JOHN DOE" in line
    assert "Remove Burnt-in Annotation" not in line
    assert "hidden_uid" not in line


def test_format_batch_outcome_subline_skipped() -> None:
    line = format_batch_outcome_subline(
        AiBatchOutcome(
            Path("/tmp/x"),
            AiBatchAlgorithm.HARMONIZE,
            "skipped",
            "Already harmonized",
        )
    )
    assert line == "  Skipped: Already harmonized"


def test_format_batch_outcome_subline_complete() -> None:
    line = format_batch_outcome_subline(
        AiBatchOutcome(
            Path("/tmp/x"),
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            "complete",
            "No burnt-in text detected (188 instances scanned)",
        )
    )
    assert line == "  Complete: No burnt-in text detected (188 instances scanned)"


def test_format_batch_outcome_subline_workflow_log_ends_with_newline() -> None:
    line = format_batch_workflow_log_line(
        format_batch_outcome_subline(
            AiBatchOutcome(
                Path("/tmp/x"),
                AiBatchAlgorithm.REMOVE_PIXEL_PHI,
                "skipped",
                "Pixel PHI already scanned",
            )
        )
    )
    assert line == "  Skipped: Pixel PHI already scanned\n"


def test_format_batch_phase_banner() -> None:
    assert format_batch_phase_banner(AiBatchAlgorithm.HARMONIZE) == "=== Harmonize ==="


def test_format_batch_step_subline_indents() -> None:
    assert format_batch_step_subline("Loading anatomy analysis models…") == ("  Loading anatomy analysis models…")


def test_format_remove_pixel_phi_series_message_lists_unique_texts() -> None:
    message = format_remove_pixel_phi_series_message(
        modified_count=2,
        total=5,
        texts_removed=["Name", "Name", "ID", "ID"],
        pixels_changed=1234,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )
    assert "Modified 2/5" in message
    assert '"Name"' in message
    assert '"ID"' in message
    assert "1,234 pixels blacked out" in message


def test_format_remove_pixel_phi_instance_detail_inpainted() -> None:
    detail = format_remove_pixel_phi_instance_detail(
        instance_index=12,
        instance_total=188,
        modified=True,
        texts=["PATIENT", "DOB 1/1/80"],
        removal_mode=PixelPhiRemovalMode.INPAINT,
    )
    assert "Instance 12/188" in detail
    assert "blended" in detail.lower()
    assert "PATIENT" in detail


def test_format_remove_pixel_phi_instance_detail_no_text() -> None:
    detail = format_remove_pixel_phi_instance_detail(
        instance_index=3,
        instance_total=10,
        modified=False,
        texts=[],
    )
    assert "Instance 3/10" in detail
    assert "no burnt-in text" in detail.lower()


@patch("anonymizer.controller.ai_batch_process._apply_face_blur_series")
@patch("anonymizer.controller.ai_batch_process._apply_harmonize_series")
@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
def test_ai_batch_process_runs_algorithm_phases_in_order(
    mock_remove: MagicMock,
    mock_harmonize: MagicMock,
    mock_face_blur: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, handle, _runner = _patch_batch_runners()

    series_paths = [
        images_dir / "anon_pt" / "anon_study" / "series_a",
        images_dir / "anon_pt" / "anon_study" / "series_b",
    ]
    call_order: list[str] = []

    def _remove(series_path, **kwargs):
        call_order.append(f"remove:{series_path.name}")
        return AiBatchOutcome(series_path, AiBatchAlgorithm.REMOVE_PIXEL_PHI, "ok", "Modified 1/1")

    def _harmonize(series_path, **kwargs):
        call_order.append(f"harmonize:{series_path.name}")
        return AiBatchOutcome(series_path, AiBatchAlgorithm.HARMONIZE, "ok"), []

    mock_remove.side_effect = _remove
    mock_harmonize.side_effect = _harmonize

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_paths[0]), (1, 1, series_paths[1])],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
    ):
        ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(
                algorithms=(
                    AiBatchAlgorithm.REMOVE_PIXEL_PHI,
                    AiBatchAlgorithm.HARMONIZE,
                ),
            ),
            anon_model=_pending_anon_model(),
            anon_controller=MagicMock(),
        )

    assert call_order == [
        "remove:series_a",
        "remove:series_b",
        "harmonize:series_a",
        "harmonize:series_b",
    ]
    mock_face_blur.assert_not_called()


@patch("anonymizer.controller.ai_batch_process._apply_face_blur_series")
@patch("anonymizer.controller.ai_batch_process._apply_harmonize_series")
@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
def test_ai_batch_process_runs_algorithms_in_order_and_honours_cancel(
    mock_remove: MagicMock,
    mock_harmonize: MagicMock,
    mock_face_blur: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()

    series_paths = [images_dir / "anon_pt" / "anon_study" / "series_a"]
    call_order: list[str] = []
    cancelled = {"value": False}

    def _remove(series_path, **kwargs):
        call_order.append(f"remove:{series_path.name}")
        return AiBatchOutcome(series_path, AiBatchAlgorithm.REMOVE_PIXEL_PHI, "ok", "Modified 1/1")

    def _harmonize(series_path, **kwargs):
        call_order.append(f"harmonize:{series_path.name}")
        if series_path.name == "series_a":
            cancelled["value"] = True
        return AiBatchOutcome(series_path, AiBatchAlgorithm.HARMONIZE, "ok"), []

    mock_remove.side_effect = _remove
    mock_harmonize.side_effect = _harmonize

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_paths[0])],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(
                algorithms=(
                    AiBatchAlgorithm.REMOVE_PIXEL_PHI,
                    AiBatchAlgorithm.HARMONIZE,
                    AiBatchAlgorithm.FACE_BLUR,
                ),
                blur_mode=FaceBlurMode.GAUSSIAN,
            ),
            anon_model=_pending_anon_model(),
            anon_controller=MagicMock(),
            cancelled=lambda: cancelled["value"],
        )

    assert call_order == ["remove:series_a", "harmonize:series_a"]
    mock_face_blur.assert_not_called()
    assert summary.processed == 2
    assert summary.applied == 2
    assert summary.cancelled is True


@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
@patch("anonymizer.controller.ai_batch_process.release_working_memory")
def test_ai_batch_process_harmonize_only_releases_memory_after_series(
    mock_release: MagicMock,
    mock_harmonize: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

    mock_harmonize.return_value = HarmonizeApplyOutcome(series_path, "ok", "Applied")

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(),
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=_pending_anon_model(),
        )

    assert summary.processed == 1
    assert summary.applied == 1
    mock_harmonize.assert_called_once()
    mock_release.assert_any_call(stage="ai_batch_after_harmonize_series", preserve_accelerator=True)


@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
def test_ai_batch_process_uses_runner_reader_for_pixel_phi(
    mock_remove: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    enter_patch, exit_patch, handle, _runner = _patch_batch_runners()
    mock_remove.return_value = AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        "ok",
        "Modified 1/1",
    )

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
    ):
        ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.REMOVE_PIXEL_PHI,)),
            anon_model=_pending_anon_model(),
        )

    mock_remove.assert_called_once()
    assert mock_remove.call_args.kwargs["ocr_reader"] is handle.reader


@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
def test_ai_batch_process_forwards_pixel_phi_removal_mode(
    mock_remove: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    mock_remove.return_value = AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        "ok",
        "Modified 1/1",
    )

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="US"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="US"),
        ),
    ):
        ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(
                algorithms=(AiBatchAlgorithm.REMOVE_PIXEL_PHI,),
                pixel_phi_removal_mode=PixelPhiRemovalMode.INPAINT,
            ),
            anon_model=_pending_anon_model(),
        )

    assert mock_remove.call_args.kwargs["removal_mode"] is PixelPhiRemovalMode.INPAINT


@patch("anonymizer.controller.ai_batch_process._apply_face_blur_series")
@patch("anonymizer.controller.ai_batch_process._prepare_ct_volume_context")
@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
def test_ai_batch_process_defers_volume_context_when_harmonize_and_face_blur(
    mock_harmonize: MagicMock,
    mock_prepare_volume: MagicMock,
    mock_face_blur: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

    mock_harmonize.return_value = HarmonizeApplyOutcome(series_path, "ok", "Applied")
    mock_face_blur.return_value = AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.FACE_BLUR,
        "ok",
        "Applied",
    )
    allow = MagicMock()
    allow.decision = FaceBlurGateDecision.ALLOW

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._face_blur_batch_eligibility",
            return_value=allow,
        ),
    ):
        ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(
                algorithms=(AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithm.FACE_BLUR),
            ),
            anon_model=_pending_anon_model(),
        )

    mock_prepare_volume.assert_called_once_with(series_path)


@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
@patch("anonymizer.controller.ai_batch_process.enter_batch_phase")
def test_ai_batch_process_skips_harmonize_phase_when_all_harmonized(
    mock_enter: MagicMock,
    mock_harmonize: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    anon_model = _pending_anon_model()
    anon_model.series_is_harmonized.return_value = True

    with (
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=anon_model,
        )

    mock_enter.assert_not_called()
    mock_harmonize.assert_not_called()
    assert summary.skipped == 0
    assert summary.processed == 0


@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
@patch("anonymizer.controller.ai_batch_process.enter_batch_phase")
def test_ai_batch_process_skips_pixel_phi_phase_when_all_scanned(
    mock_enter: MagicMock,
    mock_remove: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    anon_model = _pending_anon_model()
    anon_model.series_pixel_phi_scanned.return_value = True

    with (
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="MR"),
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.REMOVE_PIXEL_PHI,)),
            anon_model=anon_model,
        )

    mock_enter.assert_not_called()
    mock_remove.assert_not_called()
    assert summary.processed == 0


@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
@patch("anonymizer.controller.ai_batch_process.MemoryGuard")
def test_ai_batch_process_memory_guard_cancels_between_series(
    mock_guard_cls: MagicMock,
    mock_harmonize: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    mock_guard_cls.return_value.check.side_effect = ["ok", "abort"]
    mock_guard_cls.return_value.should_log_warn.return_value = False
    series_paths = [
        images_dir / "anon_pt" / "anon_study" / "series_a",
        images_dir / "anon_pt" / "anon_study" / "series_b",
    ]
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

    mock_harmonize.side_effect = lambda series_path, **kwargs: HarmonizeApplyOutcome(series_path, "ok", "Applied")

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_paths[0]), (1, 1, series_paths[1])],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(),
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=_pending_anon_model(),
        )

    assert mock_harmonize.call_count == 1
    assert summary.cancelled is True


@patch("anonymizer.controller.ai_batch_process.resolve_series_geometry")
@patch("anonymizer.controller.ai_batch_process._load_tseg_series_dataset")
def test_series_needs_face_blur_false_for_cached_chest_abdomen(
    mock_load_ds: MagicMock,
    mock_geometry: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ds.return_value = _batch_test_dataset()
    mock_geometry.return_value = _geometry()

    assert series_needs_face_blur(_pending_anon_model(), series_dir) is False


@patch("anonymizer.controller.ai_batch_process.resolve_series_geometry")
@patch("anonymizer.controller.ai_batch_process._load_tseg_series_dataset")
def test_skip_message_for_face_blur_series_non_head(
    mock_load_ds: MagicMock,
    mock_geometry: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ds.return_value = _batch_test_dataset()
    mock_geometry.return_value = _geometry()

    message = skip_message_for_face_blur_series(_pending_anon_model(), series_dir)

    assert message == face_blur_gate_message(FaceBlurGateReason.CACHED_REGIONS_NON_HEAD)


@patch("anonymizer.controller.ai_batch_process.preview_face_blur")
@patch("anonymizer.controller.ai_batch_process.resolve_series_geometry")
@patch("anonymizer.controller.ai_batch_process._load_tseg_series_dataset")
def test_apply_face_blur_series_skips_non_head_before_segmentation(
    mock_load_ds: MagicMock,
    mock_geometry: MagicMock,
    mock_preview: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ds.return_value = _batch_test_dataset()
    mock_geometry.return_value = _geometry()

    outcome = _apply_face_blur_series(
        series_dir,
        anon_model=_pending_anon_model(),
        blur_mode=FaceBlurMode.GAUSSIAN,
        progress=None,
    )

    mock_preview.assert_not_called()
    assert outcome.status == "skipped"
    assert outcome.message == face_blur_gate_message(FaceBlurGateReason.CACHED_REGIONS_NON_HEAD)


def test_face_blur_ineligible_skip_counts_as_complete() -> None:
    outcome = AiBatchOutcome(
        Path("/tmp/x"),
        AiBatchAlgorithm.FACE_BLUR,
        "skipped",
        face_blur_gate_message(FaceBlurGateReason.CACHED_REGIONS_NON_HEAD),
    )
    assert face_blur_skip_counts_as_complete(outcome) is True

    already = AiBatchOutcome(
        Path("/tmp/x"),
        AiBatchAlgorithm.FACE_BLUR,
        "skipped",
        "Face blur already applied",
    )
    assert face_blur_skip_counts_as_complete(already) is False


def test_format_ai_batch_completion_summary_face_blur_complete_not_failed() -> None:
    from anonymizer.controller.ai_batch_process import AiBatchAlgorithmTotals, AiBatchSummary

    summary = AiBatchSummary(
        series_count=6,
        applied=10,
        algorithm_totals=(
            (AiBatchAlgorithm.REMOVE_PIXEL_PHI, AiBatchAlgorithmTotals(complete=6)),
            (AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithmTotals(applied=6)),
            (AiBatchAlgorithm.FACE_BLUR, AiBatchAlgorithmTotals(applied=4, complete=2)),
        ),
    )
    message = format_ai_batch_completion_summary(summary)
    assert message == (
        "Complete: 6 series (10 applied)\n  Harmonize: 6 modified\n  Face De-identify: 4 modified"
    )
    assert "Remove Burnt-in Annotation" not in message


def test_format_ai_batch_completion_summary_includes_failed_and_skipped() -> None:
    from anonymizer.controller.ai_batch_process import AiBatchAlgorithmTotals, AiBatchSummary

    summary = AiBatchSummary(
        series_count=4,
        applied=1,
        failed=2,
        skipped=1,
        algorithm_totals=(
            (AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithmTotals(applied=1, failed=2, skipped=1)),
        ),
    )
    message = format_ai_batch_completion_summary(summary)
    assert "2 failed" in message
    assert "1 skipped" in message
    assert "Harmonize: 1 modified, 2 failed, 1 skipped" in message


def test_batch_run_artifact_stem_sanitizes_names() -> None:
    from datetime import datetime

    from anonymizer.controller.ai_batch_process import batch_run_artifact_stem

    stem = batch_run_artifact_stem(
        site_id="Site/A",
        project_name="My Project!",
        when=datetime(2026, 9, 9, 14, 30, 0),
    )
    assert stem == "Site_A_My_Project_ai_batch_20260909_143000"


def test_batch_run_capture_writes_log_and_json(tmp_path: Path) -> None:
    from anonymizer.controller.ai_batch_process import (
        AiBatchAlgorithmTotals,
        AiBatchOutcome,
        AiBatchSummary,
        BatchRunCapture,
    )
    from anonymizer.model.project import ProjectModel

    model = ProjectModel()
    model.storage_dir = tmp_path / "proj"
    model.site_id = "SITE1"
    model.project_name = "Demo"
    model.__post_init__()

    capture = BatchRunCapture.open_for_project(model)
    capture.write_line("  Failed: Could not determine body part from DICOM metadata for planar Harmonize")
    summary = AiBatchSummary(
        series_count=1,
        processed=1,
        failed=1,
        algorithm_totals=((AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithmTotals(failed=1)),),
        outcomes=(
            AiBatchOutcome(
                Path("/tmp/series"),
                AiBatchAlgorithm.HARMONIZE,
                "failed",
                "Could not determine body part from DICOM metadata for planar Harmonize",
            ),
        ),
    )
    capture.finish(summary)

    log_text = capture.log_path.read_text(encoding="utf-8")
    assert "Failed: Could not determine body part" in log_text
    assert "1 failed" in log_text
    payload = json.loads(capture.result_path.read_text(encoding="utf-8"))
    assert payload["failed"] == 1
    assert payload["outcomes"][0]["status"] == "failed"
    assert capture.log_path.parent == model.batch_runs_dir()


def test_project_model_batch_runs_dir(tmp_path: Path) -> None:
    from anonymizer.model.project import ProjectModel

    model = ProjectModel()
    model.storage_dir = tmp_path / "proj"
    model.__post_init__()
    assert model.batch_runs_dir() == tmp_path / "proj" / model.PRIVATE_DIR / model.BATCH_RUNS_DIR


def test_project_dir_from_series_path_matches_batch_storage_dir(tmp_path: Path) -> None:
    from anonymizer.utils.storage import project_dir_from_series_path

    storage_dir = tmp_path / "my_project"
    series_path = storage_dir / "public" / "anon_pt" / "anon_study" / "series_a"
    series_path.mkdir(parents=True)

    assert project_dir_from_series_path(series_path) == storage_dir


@patch("anonymizer.controller.ai_batch_process._apply_remove_pixel_phi_series")
def test_ai_batch_process_forwards_project_storage_dir_for_pixel_phi(
    mock_remove: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    storage_dir = images_dir.parent
    enter_patch, exit_patch, handle, _runner = _patch_batch_runners()
    mock_remove.return_value = AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        "ok",
        "Modified 1/1",
    )
    anon_controller = MagicMock()
    anon_controller.project_model.storage_dir = storage_dir

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
    ):
        ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.REMOVE_PIXEL_PHI,)),
            anon_model=_pending_anon_model(),
            anon_controller=anon_controller,
        )

    assert mock_remove.call_args.kwargs["project_dir"] == storage_dir


@patch("anonymizer.controller.ai.remove_pixel_phi.load_modality_whitelist", return_value=["CUSTOMTERM"])
@patch("anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext")
def test_apply_remove_pixel_phi_series_uses_saved_modality_whitelist(
    mock_readtext: MagicMock,
    mock_load_whitelist: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, _apply_remove_pixel_phi_series

    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)

    storage_dir = tmp_path / "project"
    series_path = storage_dir / "public" / "anon_pt" / "anon_study" / "series_a"
    series_path.mkdir(parents=True)
    dcm_path = series_path / "1.dcm"
    shutil.copy(
        Path(__file__).resolve().parents[1] / "assets" / "test_dcm_files" / "davidson_cxr" / "davidson_cxr_monochrome1_uncompressed.dcm",
        dcm_path,
    )

    mock_readtext.return_value = [
        ([(0, 0), (40, 0), (40, 20), (0, 20)], "CUSTOMTERM", 0.95),
        ([(0, 0), (60, 0), (60, 20), (0, 20)], "SMITH", 0.92),
    ]

    outcome = _apply_remove_pixel_phi_series(
        series_path,
        anon_model=_pending_anon_model(),
        ocr_reader=MagicMock(),
        project_dir=storage_dir,
    )

    mock_load_whitelist.assert_called_once_with(storage_dir, "CR")
    assert outcome.status == "ok"
    assert outcome.algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI
    assert "SMITH" in outcome.message
    assert "CUSTOMTERM" not in outcome.message


def test_whitelist_for_batch_ocr() -> None:
    assert whitelist_for_batch_ocr(use_modality_whitelist=True) is None
    assert whitelist_for_batch_ocr(use_modality_whitelist=False) == []


@patch("anonymizer.controller.ai_batch_process._load_series_dataset")
def test_modalities_in_selected_studies_collects_unique_modalities(
    mock_load: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    series_b = images_dir / "anon_pt" / "anon_study" / "series_b"

    def _dataset_for_path(series_path: Path) -> Dataset:
        ds = Dataset()
        ds.Modality = "US" if series_path == series_b else "CR"
        return ds

    mock_load.side_effect = lambda path: _dataset_for_path(path)

    modalities = modalities_in_selected_studies(images_dir, studies)

    assert modalities == ("CR", "US")
    assert mock_load.call_count == 2


def test_effective_modality_whitelists_uses_project_whitelist_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("CUSTOMTERM\n", encoding="utf-8")

    whitelists = effective_modality_whitelists(project_dir, ("CR",))

    assert "CUSTOMTERM" in whitelists["CR"]
    assert "PORTABLE" not in whitelists["CR"]


def test_effective_modality_whitelists_excludes_removed_default_terms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pkg_dir = Path(__file__).resolve().parents[3] / "src" / "anonymizer"
    monkeypatch.chdir(pkg_dir)
    from anonymizer.utils.storage import load_default_whitelist

    project_dir = tmp_path / "project"
    defaults_without_bilateral = [
        term for term in load_default_whitelist("CR") if term != "BILATERAL"
    ]
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("\n".join(defaults_without_bilateral) + "\n", encoding="utf-8")

    whitelists = effective_modality_whitelists(project_dir, ("CR",))

    assert "PORTABLE" in whitelists["CR"]
    assert "BILATERAL" not in whitelists["CR"]


def test_format_modality_whitelist_preview_groups_by_modality() -> None:
    text = format_modality_whitelist_preview(
        {"CR": ["PORTABLE", "L"], "US": []},
        no_modalities_message="none",
        no_terms_label="(empty)",
        match_settings_by_modality={
            "CR": OcrWhitelistMatchSettings(match_mode=OcrWhitelistMatchMode.STANDARD),
        },
    )

    assert "CR (2" in text
    assert "  PORTABLE" in text
    assert "Match strictness" in text
    assert "US (0" in text
    assert "(empty)" in text


@patch("anonymizer.controller.ai_batch_process.remove_pixel_phi", return_value=(False, [], 0))
@patch("anonymizer.controller.ai_batch_process.stackable_dicom_paths")
@patch("anonymizer.controller.ai_batch_process._load_series_dataset")
def test_apply_remove_pixel_phi_series_whitelist_enabled_passes_none(
    mock_load: MagicMock,
    mock_stackable: MagicMock,
    mock_remove: MagicMock,
) -> None:
    ds = _batch_test_dataset(modality="CR")
    mock_load.return_value = ds
    mock_stackable.return_value = [Path("/tmp/instance.dcm")]

    _apply_remove_pixel_phi_series(
        Path("/tmp/series"),
        anon_model=_pending_anon_model(),
        ocr_reader=MagicMock(),
        use_modality_whitelist=True,
    )

    assert mock_remove.call_args.kwargs["whitelist"] is None


@patch("anonymizer.controller.ai_batch_process.remove_pixel_phi", return_value=(False, [], 0))
@patch("anonymizer.controller.ai_batch_process.stackable_dicom_paths")
@patch("anonymizer.controller.ai_batch_process._load_series_dataset")
def test_apply_remove_pixel_phi_series_whitelist_disabled_passes_empty_list(
    mock_load: MagicMock,
    mock_stackable: MagicMock,
    mock_remove: MagicMock,
) -> None:
    ds = _batch_test_dataset(modality="CR")
    mock_load.return_value = ds
    mock_stackable.return_value = [Path("/tmp/instance.dcm")]

    _apply_remove_pixel_phi_series(
        Path("/tmp/series"),
        anon_model=_pending_anon_model(),
        ocr_reader=MagicMock(),
        use_modality_whitelist=False,
    )

    assert mock_remove.call_args.kwargs["whitelist"] == []


@patch("anonymizer.controller.ai_batch_process._load_harmonize_series_dataset")
def test_series_needs_harmonize_true_for_planar_xr(mock_load: MagicMock, tmp_path: Path) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_load.return_value = _batch_test_dataset(modality="CR")
    assert series_needs_harmonize(_pending_anon_model(), series_dir) is True


@patch("anonymizer.controller.ai_batch_process._load_harmonize_series_dataset")
def test_series_needs_harmonize_false_for_non_harmonize_modality(mock_load: MagicMock, tmp_path: Path) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_load.return_value = None
    assert series_needs_harmonize(_pending_anon_model(), series_dir) is False


@patch("anonymizer.controller.ai_batch_process._load_harmonize_series_dataset")
def test_skip_message_for_harmonize_series_ineligible(mock_load: MagicMock, tmp_path: Path) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    mock_load.return_value = None
    assert skip_message_for_harmonize_series(None, series_dir) == (
        "Not a CT/MR/XR/US/MG series or no DICOM files"
    )


def test_harmonize_skip_counts_as_complete_for_ineligible() -> None:
    outcome = AiBatchOutcome(
        Path("/tmp/x"),
        AiBatchAlgorithm.HARMONIZE,
        "skipped",
        "Not a CT/MR/XR/US/MG series or no DICOM files",
    )
    assert harmonize_skip_counts_as_complete(outcome) is True


@patch("anonymizer.controller.ai_batch_process.auto_apply_best_study_descriptions")
@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
def test_ai_batch_process_auto_applies_study_description_without_dialog(
    mock_harmonize: MagicMock,
    mock_auto_apply: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome, StudyDescriptionOffer
    from anonymizer.controller.ai.harmonize.loinc_study import LoincStudyMatch

    mock_harmonize.return_value = HarmonizeApplyOutcome(series_path, "ok", "Chest AP")
    offer = StudyDescriptionOffer(
        anon_study_uid="anon_study",
        fingerprint=("Chest AP",),
        matches=(LoincStudyMatch("36572-6", "XR Chest AP", 500.0),),
        peer_study_uids=(),
        ambiguous=True,
    )
    mock_auto_apply.return_value = [(offer, ["anon_study"])]
    logs: list[str] = []

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=None,
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=_pending_anon_model(),
            on_log=logs.append,
        )

    assert summary.applied == 1
    mock_auto_apply.assert_called_once()
    assert any("XR Chest AP" in line for line in logs)
    assert any("Auto-applied study description" in line for line in logs)


@patch("anonymizer.controller.ai_batch_process.auto_apply_best_study_descriptions")
@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
def test_ai_batch_process_runs_harmonize_for_planar_us(
    mock_harmonize: MagicMock,
    mock_auto_apply: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome

    mock_harmonize.return_value = HarmonizeApplyOutcome(series_path, "ok", "Abdomen")
    mock_auto_apply.return_value = []

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="US"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(modality="US"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=None,
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=_pending_anon_model(),
        )

    mock_harmonize.assert_called_once()
    assert summary.applied == 1


@patch("anonymizer.controller.ai_batch_process.auto_apply_best_study_descriptions")
@patch("anonymizer.controller.ai_batch_process.harmonize_and_apply_series")
def test_ai_batch_failed_outcome_appears_in_work_state_logs(
    mock_harmonize: MagicMock,
    mock_auto_apply: MagicMock,
    images_layout: tuple[Path, list[tuple[str, str]]],
) -> None:
    from anonymizer.controller.ai.harmonize import HarmonizeApplyOutcome
    from anonymizer.controller.work_state import WorkState

    images_dir, studies = images_layout
    enter_patch, exit_patch, _handle, _runner = _patch_batch_runners()
    series_path = images_dir / "anon_pt" / "anon_study" / "series_a"
    fail_msg = "Could not determine body part from DICOM metadata for planar Harmonize"
    mock_harmonize.return_value = HarmonizeApplyOutcome(series_path, "failed", fail_msg)
    mock_auto_apply.return_value = []
    work_state = WorkState()
    work_state.prepare_job()

    with (
        enter_patch,
        exit_patch,
        patch(
            "anonymizer.controller.ai_batch_process.enumerate_series_for_studies",
            return_value=[(1, 1, series_path)],
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_harmonize_series_dataset",
            return_value=_batch_test_dataset(modality="CR"),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_tseg_series_dataset",
            return_value=None,
        ),
    ):
        summary = ai_batch_process(
            images_dir,
            studies,
            AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,)),
            anon_model=_pending_anon_model(),
            work_state=work_state,
        )

    logs = work_state.drain_logs()
    joined = "\n".join(logs)
    assert summary.failed == 1
    assert len(summary.outcomes) == 1
    assert summary.outcomes[0].status == "failed"
    assert f"Failed: {fail_msg}" in joined
    assert "1 failed" in format_ai_batch_completion_summary(summary)
