"""Unit tests for FALCON eval_accuracy (metrics and label discovery, no models)."""

import csv
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pydicom
import pytest
from PIL import Image
from pydicom.data import get_testdata_file

from anonymizer.controller.falcon.eval_accuracy import (
    SUMMARY_CELL_SIZE,
    EvalRow,
    SavedEvalArtifact,
    _build_classifier_metrics,
    _metrics_from_confusion,
    body_part_artifact_title,
    body_part_error_artifact_path,
    body_part_error_summary_path,
    body_part_success_artifact_title,
    body_part_success_summary_path,
    collect_error_summary_entries,
    contrast_artifact_title,
    contrast_error_artifact_path,
    contrast_success_artifact_title,
    default_results_csv_path,
    discover_series_directories,
    evaluate_rows,
    falcon_prediction_from_results_csv_row,
    filter_body_part_error_artifacts_for_gt,
    filter_contrast_success_artifacts_for_category,
    filter_error_artifacts_for_category,
    format_classification_error,
    format_error_confidence_aggregate,
    format_error_summary_section,
    format_error_summary_table,
    load_eval_rows,
    load_existing_predictions_from_csv,
    parse_label_dirname,
    read_series_dicom_metadata,
    resolve_results_csv_path,
    save_body_part_error_summary_matrices,
    save_body_part_success_summary_matrices,
    save_category_summary_matrix_from_artifacts,
    save_classification_error_artifacts,
    save_contrast_success_artifacts,
    save_error_summary_matrices,
    save_success_summary_matrices,
    summary_grid_dimension,
    write_results_csv,
)
from anonymizer.controller.falcon.predict import FalconPrediction


def test_parse_label_dirname_examples():
    gt = parse_label_dirname("CT_HEAD_WITH_CONTRAST")
    assert gt.body_part == "HeadNeck"
    assert gt.iv_contrast is True

    gt = parse_label_dirname("CT_HEAT_WITH_CONTRAST")
    assert gt.body_part == "HeadNeck"

    gt = parse_label_dirname("CT_CHEST_WITHOUT_CONTRAST")
    assert gt.body_part == "Chest"
    assert gt.iv_contrast is False

    gt = parse_label_dirname("CT_ABDOMEN_WO")
    assert gt.body_part == "Abdomen"
    assert gt.iv_contrast is False


def test_parse_label_dirname_rejects_unknown():
    with pytest.raises(ValueError, match="body part"):
        parse_label_dirname("CT_UNKNOWN_WITH_CONTRAST")


def test_perfect_binary_metrics():
    truths = [False, True, True, False]
    preds = [False, True, True, False]
    metrics = _build_classifier_metrics(truths, preds)
    assert metrics.n == 4
    assert metrics.accuracy == 1.0
    assert metrics.macro_f1 == 1.0


def test_confusion_matrix_metrics():
    matrix = np.array([[2, 1, 0], [0, 3, 0], [1, 0, 2]], dtype=int)
    labels = ("HeadNeck", "Chest", "Abdomen")
    metrics = _metrics_from_confusion(matrix, labels)
    assert metrics.n == 9
    assert metrics.accuracy == pytest.approx(7 / 9)
    assert 0.0 <= metrics.macro_f1 <= 1.0


def _write_minimal_series(
    series_dir: Path,
    count: int = 12,
    *,
    series_description: str = "TEST SERIES",
    contrast_bolus_agent: str = "IODINE",
    contrast_bolus_route: str = "IV",
) -> None:
    series_dir.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        dataset = pydicom.dcmread(get_testdata_file("CT_small.dcm"))
        dataset.SeriesInstanceUID = "1.2.3"
        dataset.InstanceNumber = index + 1
        dataset.SOPInstanceUID = f"1.2.3.{index}"
        dataset.SeriesDescription = series_description
        dataset.ContrastBolusAgent = contrast_bolus_agent
        dataset.ContrastBolusRoute = contrast_bolus_route
        dataset.save_as(series_dir / f"slice_{index:03d}.dcm")


def test_discover_series_under_study(tmp_path: Path) -> None:
    label_root = tmp_path / "CT_HEAD_WITH_CONTRAST"
    study_dir = label_root / "1.2.3.study"
    _write_minimal_series(study_dir / "1.2.3.series_a")
    _write_minimal_series(study_dir / "1.2.3.series_b")

    discovered = discover_series_directories(label_root)
    assert {path.name for path in discovered} == {"1.2.3.series_a", "1.2.3.series_b"}


def test_load_eval_rows_multiple_series_per_study(tmp_path: Path) -> None:
    label_root = tmp_path / "CT_ABDOMEN_WO"
    study_dir = label_root / "study.1"
    _write_minimal_series(study_dir / "series.1")
    _write_minimal_series(study_dir / "series.2")

    rows = load_eval_rows(tmp_path)
    assert len(rows) == 2
    assert all(row.body_part == "Abdomen" and row.iv_contrast is False for row in rows)


def test_read_series_dicom_metadata(tmp_path: Path) -> None:
    series_dir = tmp_path / "series"
    _write_minimal_series(series_dir, series_description="CT HEAD W", contrast_bolus_agent="IOVERSOL")

    description, bolus_tags = read_series_dicom_metadata(series_dir)
    assert description == "CT HEAD W"
    assert "Agent=IOVERSOL" in bolus_tags
    assert "Route=IV" in bolus_tags


def test_format_classification_error_body_part_only_when_both_wrong():
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="Chest",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Chest Without Contrast",
    )
    message = format_classification_error(row, pred)
    assert "body_part" in message
    assert "iv_contrast" not in message


def test_format_classification_error_contrast_only():
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    message = format_classification_error(row, pred)
    assert "iv_contrast" in message
    assert "body_part" not in message


def test_error_summary_table(tmp_path: Path) -> None:
    series_dir = tmp_path / "bad_series"
    _write_minimal_series(series_dir)
    row = EvalRow(
        series_path=series_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    entries = collect_error_summary_entries([row], [pred])
    table = format_error_summary_table(entries)
    assert "bp_conf" in table
    assert "80.00%" in table
    assert "contrast_conf" in table
    assert "—" in table
    assert "body_part" in table
    assert str(series_dir) in table


def test_error_summary_sort_by_failed_task_confidence(tmp_path: Path) -> None:
    low_dir = tmp_path / "low_conf"
    high_dir = tmp_path / "high_conf"
    _write_minimal_series(low_dir)
    _write_minimal_series(high_dir)

    low_row = EvalRow(
        series_path=low_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    high_row = EvalRow(
        series_path=high_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    predictions = [
        FalconPrediction(
            series_directory=low_dir,
            body_part="Chest",
            body_part_confidence=0.55,
            iv_contrast=True,
            iv_contrast_confidence=0.9,
            radlex_series_description="CT Chest With Contrast",
        ),
        FalconPrediction(
            series_directory=high_dir,
            body_part="Chest",
            body_part_confidence=0.95,
            iv_contrast=True,
            iv_contrast_confidence=0.9,
            radlex_series_description="CT Chest With Contrast",
        ),
    ]
    entries = collect_error_summary_entries([high_row, low_row], predictions)
    assert str(low_dir) in entries[0].series_path
    assert str(high_dir) in entries[1].series_path


def test_error_confidence_aggregate(tmp_path: Path) -> None:
    series_dir = tmp_path / "bad_series"
    _write_minimal_series(series_dir)
    body_row = EvalRow(
        series_path=series_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    body_pred = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.95,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Chest Without Contrast",
    )
    contrast_row = EvalRow(
        series_path=Path("/other/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    contrast_pred = FalconPrediction(
        series_directory=Path("/other/series"),
        body_part="HeadNeck",
        body_part_confidence=0.99,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    aggregate = format_error_confidence_aggregate([body_row, contrast_row], [body_pred, contrast_pred])
    assert "body_part errors: n=1" in aggregate
    assert "95.00%" in aggregate
    assert "contrast errors: n=1" in aggregate
    assert "80.00%" in aggregate


def test_error_summary_section_includes_aggregate(tmp_path: Path) -> None:
    series_dir = tmp_path / "bad_series"
    _write_minimal_series(series_dir)
    row = EvalRow(
        series_path=series_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    section = format_error_summary_section([row], [pred])
    assert "Error confidence" in section


def test_error_summary_none():
    row = EvalRow(
        series_path=Path("/data/ok"),
        body_part="Chest",
        iv_contrast=True,
        label_dir="CT_CHEST_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=Path("/data/ok"),
        body_part="Chest",
        body_part_confidence=0.99,
        iv_contrast=True,
        iv_contrast_confidence=0.99,
        radlex_series_description="CT Chest With Contrast",
    )
    assert collect_error_summary_entries([row], [pred]) == []
    assert "(none)" in format_error_summary_section([row], [pred])


def test_default_results_csv_path(tmp_path: Path) -> None:
    assert default_results_csv_path(tmp_path) == tmp_path.resolve() / "falcon_eval_results.csv"


def test_resolve_results_csv_path(tmp_path: Path) -> None:
    custom = tmp_path / "out" / "custom.csv"
    assert resolve_results_csv_path(tmp_path, None, no_results_file=False) == default_results_csv_path(tmp_path)
    assert resolve_results_csv_path(tmp_path, custom, no_results_file=False) == custom.resolve()
    assert resolve_results_csv_path(tmp_path, custom, no_results_file=True) is None


def test_summary_grid_dimension():
    assert summary_grid_dimension(0) == 0
    assert summary_grid_dimension(12) == 4
    assert summary_grid_dimension(16) == 4
    assert summary_grid_dimension(20) == 5
    assert summary_grid_dimension(25) == 5
    assert summary_grid_dimension(26) == 6
    assert summary_grid_dimension(36) == 6


def test_filter_error_artifacts_for_category():
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    body_pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    contrast_pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    image_path = Path("/tmp/series.png")
    saved = [
        SavedEvalArtifact(row=row, prediction=body_pred, image_path=image_path, task_kind="body_part"),
        SavedEvalArtifact(row=row, prediction=contrast_pred, image_path=image_path, task_kind="contrast"),
    ]
    assert len(filter_error_artifacts_for_category(saved, "body_part")) == 1
    assert len(filter_error_artifacts_for_category(saved, "contrast_with_pred_without")) == 1
    assert filter_error_artifacts_for_category(saved, "contrast_without_pred_with") == []


def test_filter_contrast_success_artifacts_for_category():
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    contrast_pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=True,
        iv_contrast_confidence=0.8,
        radlex_series_description="CT Head Neck With Contrast",
    )
    image_path = Path("/tmp/series.png")
    saved = [
        SavedEvalArtifact(row=row, prediction=contrast_pred, image_path=image_path, task_kind="contrast"),
    ]
    assert len(filter_contrast_success_artifacts_for_category(saved, "contrast_with_pred_with")) == 1
    assert filter_contrast_success_artifacts_for_category(saved, "contrast_without_pred_without") == []


def test_body_part_summary_matrix_paths(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    assert body_part_error_summary_path(artifact_root, "HeadNeck").name == "headneck_errors.png"
    assert body_part_success_summary_path(artifact_root, "Chest").name == "chest_success.png"
    assert body_part_error_summary_path(artifact_root, "Abdomen").parent.name == "error"
    assert body_part_success_summary_path(artifact_root, "Abdomen").parent.name == "success"


def test_filter_body_part_error_artifacts_for_gt():
    head_row = EvalRow(
        series_path=Path("/data/head"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    chest_row = EvalRow(
        series_path=Path("/data/chest"),
        body_part="Chest",
        iv_contrast=False,
        label_dir="CT_CHEST_WITHOUT_CONTRAST",
    )
    image_path = Path("/tmp/series.png")
    head_pred = FalconPrediction(
        series_directory=Path("/data/head"),
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    chest_pred = FalconPrediction(
        series_directory=Path("/data/chest"),
        body_part="Abdomen",
        body_part_confidence=0.7,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Abdomen Without Contrast",
    )
    saved = [
        SavedEvalArtifact(row=head_row, prediction=head_pred, image_path=image_path, task_kind="body_part"),
        SavedEvalArtifact(row=chest_row, prediction=chest_pred, image_path=image_path, task_kind="body_part"),
    ]
    assert len(filter_body_part_error_artifacts_for_gt(saved, "HeadNeck")) == 1
    assert len(filter_body_part_error_artifacts_for_gt(saved, "Chest")) == 1
    assert filter_body_part_error_artifacts_for_gt(saved, "Abdomen") == []


def test_save_category_summary_matrix_from_artifacts(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    image_path = artifact_root / "errors" / "contrast" / "label" / "series.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (150, 150), color=(200, 100, 50)).save(image_path)

    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    prediction = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    saved = [
        SavedEvalArtifact(
            row=row,
            prediction=prediction,
            image_path=image_path,
            task_kind="contrast",
        )
    ]
    matrix_path = save_category_summary_matrix_from_artifacts(
        artifact_root / "error_summary_contrast_with_pred_without.png",
        saved,
        title="FALCON contrast errors: GT WITH->WITHOUT",
        count_label="error(s)",
        sort_descending=False,
    )
    assert matrix_path is not None
    assert matrix_path.name == "error_summary_contrast_with_pred_without.png"
    with Image.open(matrix_path) as matrix_image:
        assert matrix_image.size[0] > SUMMARY_CELL_SIZE


def test_save_error_summary_matrices_writes_only_non_empty_categories(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True)
    image_path = artifact_root / "series.png"
    Image.new("RGB", (150, 150), color=(100, 100, 100)).save(image_path)
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="Chest",
        iv_contrast=False,
        label_dir="CT_CHEST_WITHOUT_CONTRAST",
    )
    prediction = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="Abdomen",
        body_part_confidence=0.7,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Abdomen Without Contrast",
    )
    paths = save_error_summary_matrices(
        artifact_root,
        [SavedEvalArtifact(row=row, prediction=prediction, image_path=image_path, task_kind="body_part")],
    )
    assert len(paths) == 1
    assert paths[0].name == "chest_errors.png"
    assert paths[0].parent.name == "error"


def test_save_body_part_error_summary_matrices_only_writes_non_empty_classes(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True)
    image_path = artifact_root / "series.png"
    Image.new("RGB", (150, 150), color=(100, 100, 100)).save(image_path)
    head_row = EvalRow(
        series_path=Path("/data/head"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    chest_row = EvalRow(
        series_path=Path("/data/chest"),
        body_part="Chest",
        iv_contrast=False,
        label_dir="CT_CHEST_WITHOUT_CONTRAST",
    )
    saved = [
        SavedEvalArtifact(
            row=head_row,
            prediction=FalconPrediction(
                series_directory=Path("/data/head"),
                body_part="Chest",
                body_part_confidence=0.8,
                iv_contrast=True,
                iv_contrast_confidence=0.9,
                radlex_series_description="CT Chest With Contrast",
            ),
            image_path=image_path,
            task_kind="body_part",
        ),
        SavedEvalArtifact(
            row=chest_row,
            prediction=FalconPrediction(
                series_directory=Path("/data/chest"),
                body_part="Abdomen",
                body_part_confidence=0.7,
                iv_contrast=False,
                iv_contrast_confidence=0.1,
                radlex_series_description="CT Abdomen Without Contrast",
            ),
            image_path=image_path,
            task_kind="body_part",
        ),
    ]
    paths = save_body_part_error_summary_matrices(artifact_root, saved)
    assert len(paths) == 2
    assert {path.name for path in paths} == {"headneck_errors.png", "chest_errors.png"}


@patch("anonymizer.controller.falcon.eval_accuracy.preprocess_series")
def test_save_body_part_success_summary_matrices_on_the_fly(mock_preprocess, tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_CHEST_WITHOUT_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.95,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Chest Without Contrast",
    )
    mock_preprocess.return_value = np.zeros((100, 150, 150), dtype=np.float32)

    artifact_root = tmp_path / "artifacts"
    paths = save_body_part_success_summary_matrices(rows, [prediction], artifact_root)
    assert len(paths) == 1
    assert paths[0].name == "chest_success.png"
    assert paths[0].parent == artifact_root / "body_part" / "success"
    assert not (artifact_root / "errors").exists()


def test_save_success_summary_matrices_writes_only_non_empty_categories(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True)
    image_path = artifact_root / "series.png"
    Image.new("RGB", (150, 150), color=(100, 100, 100)).save(image_path)
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="Chest",
        iv_contrast=False,
        label_dir="CT_CHEST_WITHOUT_CONTRAST",
    )
    prediction = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="Chest",
        body_part_confidence=0.95,
        iv_contrast=False,
        iv_contrast_confidence=0.1,
        radlex_series_description="CT Chest Without Contrast",
    )
    with patch(
        "anonymizer.controller.falcon.eval_accuracy.save_body_part_success_summary_matrices",
        return_value=[artifact_root / "body_part" / "success" / "chest_success.png"],
    ):
        paths = save_success_summary_matrices(
            [row],
            [prediction],
            artifact_root,
            [
                SavedEvalArtifact(row=row, prediction=prediction, image_path=image_path, task_kind="contrast"),
            ],
        )
    assert len(paths) == 2
    assert paths[0].name == "chest_success.png"
    assert paths[1].name == "success_summary_contrast_without_pred_without.png"


def test_artifact_titles_include_confidence():
    row = EvalRow(
        series_path=Path("/data/series"),
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Chest Without Contrast",
    )
    assert body_part_artifact_title(row, pred) == "GT: HEADNECK->CHEST\n80%"
    assert contrast_artifact_title(row, pred) == "GT: WITH->WITHOUT\n80%"
    correct_pred = FalconPrediction(
        series_directory=Path("/data/series"),
        body_part="HeadNeck",
        body_part_confidence=0.95,
        iv_contrast=True,
        iv_contrast_confidence=0.88,
        radlex_series_description="CT Head Neck With Contrast",
    )
    assert body_part_success_artifact_title(row, correct_pred) == "GT: HEADNECK\n95%"
    assert contrast_success_artifact_title(row, correct_pred) == "GT: WITH\n88%"


def test_body_part_error_artifact_path(tmp_path: Path) -> None:
    series_dir = tmp_path / "study" / "1.2.3.series"
    row = EvalRow(
        series_path=series_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    path = body_part_error_artifact_path(tmp_path / "artifacts", row)
    assert path.name == "1_2_3_series.png"
    assert path.parent.name == "CT_HEAD_WITH_CONTRAST"
    assert "errors" in path.parts and "body_part" in path.parts


def test_contrast_error_artifact_path(tmp_path: Path) -> None:
    series_dir = tmp_path / "study" / "1.2.3.series"
    row = EvalRow(
        series_path=series_dir,
        body_part="HeadNeck",
        iv_contrast=True,
        label_dir="CT_HEAD_WITH_CONTRAST",
    )
    pred = FalconPrediction(
        series_directory=series_dir,
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    path = contrast_error_artifact_path(tmp_path / "artifacts", row)
    assert path.name == "1_2_3_series.png"
    assert "errors" in path.parts and "contrast" in path.parts


@patch("anonymizer.controller.falcon.eval_accuracy.save_contrast_model_input_png")
@patch("anonymizer.controller.falcon.eval_accuracy.save_body_part_model_input_png")
@patch("anonymizer.controller.falcon.eval_accuracy.preprocess_series")
def test_save_classification_error_artifacts(
    mock_preprocess,
    mock_save_body_png,
    mock_save_contrast_png,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    mock_preprocess.return_value = np.zeros((100, 150, 150), dtype=np.float32)

    def _write_placeholder(_image_np, output_path, **_kwargs) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"png")
        return output_path

    mock_save_body_png.side_effect = _write_placeholder
    mock_save_contrast_png.side_effect = _write_placeholder

    artifact_root = tmp_path / "falcon_eval_artifacts"
    saved = save_classification_error_artifacts(rows, [prediction], artifact_root)
    assert len(saved) == 1
    assert saved[0].task_kind == "body_part"
    assert saved[0].image_path.name == "series.png"
    mock_preprocess.assert_called_once_with(series_dir)
    mock_save_body_png.assert_called_once()
    assert mock_save_body_png.call_args.kwargs["title"] == "GT: HEADNECK->CHEST\n80%"
    mock_save_contrast_png.assert_not_called()


@patch("anonymizer.controller.falcon.eval_accuracy.save_contrast_model_input_png")
@patch("anonymizer.controller.falcon.eval_accuracy.save_body_part_model_input_png")
@patch("anonymizer.controller.falcon.eval_accuracy.preprocess_series")
def test_save_contrast_artifact_when_body_part_correct(
    mock_preprocess,
    mock_save_body_png,
    mock_save_contrast_png,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=False,
        iv_contrast_confidence=0.2,
        radlex_series_description="CT Head Neck Without Contrast",
    )
    mock_preprocess.return_value = np.zeros((100, 150, 150), dtype=np.float32)

    def _write_placeholder(*_args, **_kwargs) -> Path:
        output_path = Path(_kwargs.get("output_path", _args[-1]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"png")
        return output_path

    mock_save_body_png.side_effect = _write_placeholder
    mock_save_contrast_png.side_effect = _write_placeholder

    saved = save_classification_error_artifacts(rows, [prediction], tmp_path / "artifacts")
    assert len(saved) == 1
    assert saved[0].task_kind == "contrast"
    assert saved[0].image_path.name == "series.png"
    assert mock_save_contrast_png.call_args.kwargs["title"] == "GT: WITH->WITHOUT\n80%"
    mock_save_body_png.assert_not_called()


def test_save_body_part_pngs_skips_correct_series(tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_CHEST_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.99,
        iv_contrast=True,
        iv_contrast_confidence=0.99,
        radlex_series_description="CT Chest With Contrast",
    )
    saved = save_classification_error_artifacts(rows, [prediction], tmp_path / "artifacts")
    assert saved == []


@patch("anonymizer.controller.falcon.eval_accuracy.save_contrast_model_input_png")
@patch("anonymizer.controller.falcon.eval_accuracy.preprocess_series")
def test_save_contrast_success_artifacts(
    mock_preprocess,
    mock_save_contrast_png,
    tmp_path: Path,
) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="HeadNeck",
        body_part_confidence=0.95,
        iv_contrast=True,
        iv_contrast_confidence=0.88,
        radlex_series_description="CT Head Neck With Contrast",
    )
    mock_preprocess.return_value = np.zeros((100, 150, 150), dtype=np.float32)

    def _write_contrast_placeholder(*_args, **_kwargs) -> Path:
        output_path = Path(_kwargs.get("output_path", _args[-1]))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"png")
        return output_path

    mock_save_contrast_png.side_effect = _write_contrast_placeholder

    artifact_root = tmp_path / "falcon_eval_artifacts"
    saved = save_contrast_success_artifacts(rows, [prediction], artifact_root)
    assert len(saved) == 1
    assert saved[0].task_kind == "contrast"
    assert mock_save_contrast_png.call_args.kwargs["title"] == "GT: WITH\n88%"
    assert "success" in saved[0].image_path.parts and "contrast" in saved[0].image_path.parts


@patch("anonymizer.controller.falcon.eval_accuracy.predict_falcon_series")
def test_evaluate_rows_skips_series_with_existing_results(mock_predict, tmp_path: Path) -> None:
    series_a = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series_a"
    series_b = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series_b"
    _write_minimal_series(series_a)
    _write_minimal_series(series_b)
    rows = load_eval_rows(tmp_path)

    cached_prediction = FalconPrediction(
        series_directory=series_a,
        body_part="HeadNeck",
        body_part_confidence=0.9,
        iv_contrast=True,
        iv_contrast_confidence=0.8,
        radlex_series_description="CT Head Neck With Contrast",
    )
    new_prediction = FalconPrediction(
        series_directory=series_b,
        body_part="HeadNeck",
        body_part_confidence=0.85,
        iv_contrast=True,
        iv_contrast_confidence=0.75,
        radlex_series_description="CT Head Neck With Contrast",
    )
    mock_predict.return_value = [new_prediction]

    report, predictions = evaluate_rows(
        rows,
        existing_predictions={series_a.resolve(): cached_prediction},
    )
    mock_predict.assert_called_once_with([series_b])
    assert len(predictions) == 2
    assert report.total == 2


def test_load_existing_predictions_from_csv_round_trip(tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="HeadNeck",
        body_part_confidence=0.91,
        iv_contrast=True,
        iv_contrast_confidence=0.88,
        radlex_series_description="CT Head Neck With Contrast",
    )
    csv_path = tmp_path / "falcon_eval_results.csv"
    write_results_csv(csv_path, rows, [prediction])

    loaded = load_existing_predictions_from_csv(csv_path)
    assert len(loaded) == 1
    restored = loaded[series_dir.resolve()]
    assert restored.body_part == "HeadNeck"
    assert restored.body_part_confidence == pytest.approx(0.91)


def test_falcon_prediction_from_results_csv_row_body_part_error():
    csv_row = {
        "series_path": "/data/series",
        "body_part_pred": "Chest",
        "body_part_confidence": "0.8",
        "radlex_series_description": "CT Chest With Contrast",
        "contrast_evaluated": "False",
        "error": "",
    }
    prediction = falcon_prediction_from_results_csv_row(csv_row)
    assert prediction is not None
    assert prediction.body_part == "Chest"
    assert prediction.iv_contrast is False


@patch("anonymizer.controller.falcon.eval_accuracy.preprocess_series")
def test_save_classification_error_artifacts_skips_existing_png(mock_preprocess, tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    artifact_root = tmp_path / "falcon_eval_artifacts"
    existing_png = body_part_error_artifact_path(artifact_root, rows[0])
    existing_png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (150, 150), color=(10, 10, 10)).save(existing_png)

    saved = save_classification_error_artifacts(rows, [prediction], artifact_root)
    assert len(saved) == 1
    mock_preprocess.assert_not_called()


def test_write_results_csv(tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir, series_description="CT HEAD W")
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    output_csv = tmp_path / "results.csv"
    write_results_csv(output_csv, rows, [prediction])

    with output_csv.open(encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))

    assert len(records) == 1
    row = records[0]
    assert row["series_description"] == "CT HEAD W"
    assert "body_part" in row["classification_error"]
    assert row["body_part_correct"] == "False"
    assert row["contrast_evaluated"] == "False"
    assert row.get("iv_contrast_class_confidence", "") == ""


def test_results_csv_omits_contrast_when_body_part_wrong(tmp_path: Path) -> None:
    series_dir = tmp_path / "CT_HEAD_WITH_CONTRAST" / "study" / "series"
    _write_minimal_series(series_dir)
    rows = load_eval_rows(tmp_path)
    prediction = FalconPrediction(
        series_directory=series_dir,
        body_part="Chest",
        body_part_confidence=0.8,
        iv_contrast=True,
        iv_contrast_confidence=0.9,
        radlex_series_description="CT Chest With Contrast",
    )
    output_csv = tmp_path / "results.csv"
    write_results_csv(output_csv, rows, [prediction])

    with output_csv.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))

    assert row["contrast_evaluated"] == "False"
    assert row.get("iv_contrast_correct", "") == ""
    assert "body_part" in row["classification_error"]
    assert "iv_contrast" not in row["classification_error"]


def test_load_eval_rows_from_label_dirs(tmp_path: Path) -> None:
    for name, _body_part, _contrast in (
        ("CT_HEAD_WITH_CONTRAST", "HeadNeck", True),
        ("CT_CHEST_WITHOUT_CONTRAST", "Chest", False),
    ):
        _write_minimal_series(tmp_path / name / "1.2.3.study" / "1.2.3.series")

    rows = load_eval_rows(tmp_path)
    assert len(rows) == 2
    assert {row.label_dir for row in rows} == {"CT_HEAD_WITH_CONTRAST", "CT_CHEST_WITHOUT_CONTRAST"}
    by_label = {(row.label_dir, row.body_part, row.iv_contrast) for row in rows}
    assert ("CT_HEAD_WITH_CONTRAST", "HeadNeck", True) in by_label
    assert ("CT_CHEST_WITHOUT_CONTRAST", "Chest", False) in by_label
