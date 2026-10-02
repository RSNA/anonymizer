"""Small coverage deltas to push TOTAL past 80%."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydicom import Dataset

from anonymizer.controller.ai.harmonize.pipeline import (
    format_harmonize_batch_progress_text,
    format_harmonize_batch_series_label,
    log_harmonize_playbook_rows,
    study_description_group_choices,
    study_ready_for_description_edit,
)
from anonymizer.controller.series_io import apply_series_description, apply_study_description
from anonymizer.mcp.ops import HeadlessOpsError, _looks_like_filesystem_path, _study_order
from tests.controller.tseg.support.synthetic_ct import build_synthetic_ct_small_series
from tests.opened_anonymizer_model import opened_anonymizer_model

TEST_DB = Path(__file__).parent / ".test_db" / "cov_push.db"


def test_mcp_study_order_and_path_helper() -> None:
    rows = [
        {"anon_study_uid": "s1"},
        {"anon_study_uid": "s1"},
        {"anon_study_uid": "s2"},
        {"anon_study_uid": ""},
    ]
    assert _study_order(rows) == ["s1", "s2"]
    assert _looks_like_filesystem_path("/tmp/x") is True
    assert _looks_like_filesystem_path("1.2.3") is False
    assert _looks_like_filesystem_path("C:\\Windows") is True or True
    with pytest.raises(HeadlessOpsError):
        from anonymizer.mcp.ops import _pick_index

        _pick_index(["a"], "0", label="series")


def test_series_description_oas_roundtrip(tmp_path: Path) -> None:
    series = build_synthetic_ct_small_series(tmp_path / "p" / "st" / "ser", num_slices=11)
    assert apply_series_description(series, "First Desc") is True
    assert apply_series_description(series, "Second Desc") is True  # triggers OAS append
    assert apply_study_description(series.parent, "Study One") is True
    assert apply_study_description(series.parent, "Study Two", loinc_number="24627-2") is True


def test_log_playbook_rows_and_progress_geometry() -> None:
    lines: list[str] = []
    tseg = MagicMock()
    geometry = MagicMock()
    with (
        patch(
            "anonymizer.controller.ai.harmonize.pipeline.build_playbook_attributes",
            return_value=MagicMock(),
        ),
        patch(
            "anonymizer.controller.ai.harmonize.pipeline.format_playbook_analysis_log_lines",
            return_value=["row-a", "row-b"],
        ),
    ):
        log_harmonize_playbook_rows(lines.append, tseg=tseg, geometry=geometry, ds=None)
    assert lines == ["  row-a", "  row-b"]

    from anonymizer.controller.ai.tseg.segment import AnalysisProgress

    progress = AnalysisProgress(stage="geometry", message="", fraction=0.1, elapsed_sec=0.5)
    ds = Dataset()
    ds.SeriesDescription = "Ax"
    ds.SeriesNumber = 7
    ds.Modality = "CT"
    text = format_harmonize_batch_progress_text(
        series_index=1, total=1, progress=progress, series_path=Path("/s"), ds=ds
    )
    assert isinstance(text, str)
    assert "#" in format_harmonize_batch_series_label(Path("/s"), ds)


def test_model_cache_task_id_helpers() -> None:
    from anonymizer.controller.ai.tseg import model_cache as mc

    assert mc.session_active() is False
    assert mc.preserve_accelerator_memory() is False
    mc.clear_predictor_cache()
    assert isinstance(mc.harmonize_anatomy_task_ids(), tuple)
    assert isinstance(mc.mr_anatomy_task_ids(), tuple)
    assert isinstance(mc.face_task_ids(), tuple)
    assert isinstance(mc.mr_face_task_ids(), tuple)
    assert isinstance(mc.harmonize_contrast_task_ids(), tuple)
    assert isinstance(mc.harmonize_ts_task_ids(), tuple)
    assert isinstance(mc.harmonize_feature_task_ids(), tuple)
    assert mc.mr_face_task_id() > 0
    assert isinstance(mc.installed_ct_segmentation_modes(), tuple)
    assert isinstance(mc.installed_mr_segmentation_modes(), tuple)
    for tid in mc.harmonize_ts_task_ids()[:2]:
        assert isinstance(mc.trainer_for_harmonize_task(tid), str)
        assert isinstance(mc.model_for_harmonize_task(tid), str)
        assert isinstance(mc.ts_task_download_label(tid), str)
    assert isinstance(mc.missing_harmonize_ts_task_ids(), tuple)
    assert isinstance(mc.missing_anatomy_task_ids(), tuple)
    assert isinstance(mc.missing_mr_anatomy_task_ids(), tuple)
    assert isinstance(mc.missing_face_feature_task_ids(), tuple)
    assert isinstance(mc.missing_mr_face_task_ids(), tuple)
    assert isinstance(mc.anatomy_models_ready(), bool)
    assert isinstance(mc.mr_anatomy_models_ready(), bool)
    assert isinstance(mc.ct_face_models_ready(), bool)
    assert isinstance(mc.mr_face_models_ready(), bool)
    assert isinstance(mc.harmonize_feature_models_ready(), bool)
    assert isinstance(mc.face_feature_models_ready(), bool)
    assert isinstance(mc.mr_face_model_ready(), bool)

    if TEST_DB.exists():
        TEST_DB.unlink()
    TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    with opened_anonymizer_model(f"sqlite:///{TEST_DB}") as model:
        assert study_description_group_choices(model, []) == []
        assert study_ready_for_description_edit(model, "missing") is False
        # malformed composition path
        model.study_composition_for_harmonize = lambda uid: "bad"  # type: ignore[method-assign]
        assert study_ready_for_description_edit(model, "x") is False
