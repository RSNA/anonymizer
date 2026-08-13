"""Tests for AI batch process orchestrator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom.dataset import Dataset

from anonymizer.controller.ai_batch_process import (
    AiBatchAlgorithm,
    AiBatchOutcome,
    AiBatchProcessOptions,
    _apply_face_blur_series,
    _log_workflow_progress_step,
    ai_batch_process,
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
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
    normalize_selected_algorithms,
    series_needs_face_blur,
    skip_message_for_face_blur_series,
    strip_progress_pct_suffix,
)
from anonymizer.controller.ai.blur_face import (
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    face_blur_gate_message,
)
from anonymizer.controller.ai.remove_pixel_phi import PixelPhiRemovalMode
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
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
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
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
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
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
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
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
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
        patch(
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
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
            "anonymizer.controller.ai_batch_process._load_ct_series_dataset",
            return_value=_batch_test_dataset(),
        ),
        patch(
            "anonymizer.controller.ai_batch_process._load_series_dataset",
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
@patch("anonymizer.controller.ai_batch_process._load_ct_series_dataset")
def test_series_needs_face_blur_false_for_cached_chest_abdomen(
    mock_load_ct: MagicMock,
    mock_geometry: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ct.return_value = _batch_test_dataset()
    mock_geometry.return_value = _geometry()

    assert series_needs_face_blur(_pending_anon_model(), series_dir) is False


@patch("anonymizer.controller.ai_batch_process.resolve_series_geometry")
@patch("anonymizer.controller.ai_batch_process._load_ct_series_dataset")
def test_skip_message_for_face_blur_series_non_head(
    mock_load_ct: MagicMock,
    mock_geometry: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ct.return_value = _batch_test_dataset()
    mock_geometry.return_value = _geometry()

    message = skip_message_for_face_blur_series(_pending_anon_model(), series_dir)

    assert message == face_blur_gate_message(FaceBlurGateReason.CACHED_REGIONS_NON_HEAD)


@patch("anonymizer.controller.ai_batch_process.preview_face_blur")
@patch("anonymizer.controller.ai_batch_process.resolve_series_geometry")
@patch("anonymizer.controller.ai_batch_process._load_ct_series_dataset")
def test_apply_face_blur_series_skips_non_head_before_segmentation(
    mock_load_ct: MagicMock,
    mock_geometry: MagicMock,
    mock_preview: MagicMock,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    _write_chest_region_cache(series_dir)
    mock_load_ct.return_value = _batch_test_dataset()
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
        algorithm_totals=(
            (AiBatchAlgorithm.REMOVE_PIXEL_PHI, AiBatchAlgorithmTotals(complete=6)),
            (AiBatchAlgorithm.HARMONIZE, AiBatchAlgorithmTotals(applied=6)),
            (AiBatchAlgorithm.FACE_BLUR, AiBatchAlgorithmTotals(applied=4, complete=2)),
        ),
    )
    message = format_ai_batch_completion_summary(summary)
    assert message == ("Complete: 6 series\n  Harmonize: 6 modified\n  Face De-identify: 4 modified")
    assert "Remove Burnt-in Annotation" not in message
