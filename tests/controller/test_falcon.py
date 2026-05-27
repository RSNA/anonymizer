"""FALCON controller tests using real preprocessing and on-demand model weights."""

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pydicom
import pytest
import torch

from anonymizer.controller.falcon import (
    FALCON_BODY_PARTS,
    check_falcon_eligibility,
    predict_falcon_series,
)
from anonymizer.controller.falcon.model_paths import FALCON_MODEL_DIR, FALCON_MODEL_FILES, ensure_models
from anonymizer.controller.falcon.load_models import load_models, remove_module_prefix
from anonymizer.controller.falcon.resnet9 import ResNet9
from tests.controller.dicom_test_files import CT_STUDY_1_SERIES_4_IMAGES



@pytest.fixture(scope="session")
def falcon_weights() -> dict[str, Path]:
    """Download missing FALCON weights once per test session (same path as production)."""
    return ensure_models()


class TestSyntheticCtFixtures:
    def test_ct_small_series_has_twelve_valid_dicom_slices(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "series")

        dcm_files = list_dcm_files(series_dir)

        assert len(dcm_files) == DEFAULT_SYNTHETIC_SLICE_COUNT
        for dcm_path in dcm_files:
            dataset = pydicom.dcmread(dcm_path)
            assert dataset.Modality == "CT"
            assert dataset.pixel_array.shape == (128, 128)

    def test_ct_small_series_has_sorted_distinct_z_positions(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "series")

        z_positions = [
            float(pydicom.dcmread(path, stop_before_pixels=True).ImagePositionPatient[2])
            for path in list_dcm_files(series_dir)
        ]

        assert len(z_positions) == DEFAULT_SYNTHETIC_SLICE_COUNT
        assert z_positions == sorted(z_positions)
        assert len(set(z_positions)) == DEFAULT_SYNTHETIC_SLICE_COUNT

    def test_build_rejects_fewer_than_eleven_slices(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="num_slices must be at least 11"):
            build_synthetic_ct_small_series(tmp_path / "series", num_slices=10)

    def test_pydicom_stock_ct_has_fewer_than_falcon_minimum_slices(self) -> None:
        assert len(CT_STUDY_1_SERIES_4_IMAGES) < FALCON_MIN_SLICES


class TestSyntheticBodyPartPhantoms:
    @pytest.mark.parametrize(
        ("builder", "body_part"),
        [
            (build_synthetic_head_ct_series, "HEAD"),
            (build_synthetic_chest_ct_series, "CHEST"),
            (build_synthetic_abdomen_ct_series, "ABDOMEN"),
        ],
    )
    def test_phantom_series_has_valid_dicom_slices(
        self,
        tmp_path: Path,
        builder,
        body_part: str,
    ) -> None:
        series_dir = builder(tmp_path / body_part.lower())

        dcm_files = list_dcm_files(series_dir)
        assert len(dcm_files) == DEFAULT_PHANTOM_SLICE_COUNT

        first = pydicom.dcmread(dcm_files[0])
        last = pydicom.dcmread(dcm_files[-1])
        assert first.Modality == "CT"
        assert first.pixel_array.shape == (DEFAULT_PHANTOM_MATRIX, DEFAULT_PHANTOM_MATRIX)
        assert first.BodyPartExamined == body_part
        assert not np.array_equal(first.pixel_array, last.pixel_array)

    @pytest.mark.falcon_memory(max_rss_delta_mb=250)
    @pytest.mark.parametrize(
        "builder",
        [
            build_synthetic_head_ct_series,
            build_synthetic_chest_ct_series,
            build_synthetic_abdomen_ct_series,
        ],
    )
    def test_phantom_series_is_eligible(self, tmp_path: Path, builder) -> None:
        series_dir = builder(tmp_path / "phantom")

        result = check_falcon_eligibility([series_dir])[0]

        assert result.eligible is True
        assert result.error is None

    @pytest.mark.falcon_memory(max_rss_delta_mb=450)
    @pytest.mark.parametrize(
        "builder",
        [
            build_synthetic_head_ct_series,
            build_synthetic_chest_ct_series,
            build_synthetic_abdomen_ct_series,
        ],
    )
    def test_phantom_series_returns_valid_prediction(
        self,
        falcon_weights: dict[str, Path],
        tmp_path: Path,
        builder,
    ) -> None:
        series_dir = builder(tmp_path / "predict")

        result = predict_falcon_series([series_dir])[0]

        assert result.error is None
        assert result.body_part in FALCON_BODY_PARTS
        assert 0.0 < result.body_part_confidence <= 1.0
        assert isinstance(result.iv_contrast, bool)
        assert 0.0 < result.iv_contrast_confidence <= 1.0


class TestModelPaths:
    def test_falcon_model_dir_matches_easyocr_relative_layout(self) -> None:
        assert FALCON_MODEL_DIR == Path("assets") / "falcon" / "models"

    def test_ensure_models_provides_all_weight_files(self, falcon_weights: dict[str, Path]) -> None:
        assert set(falcon_weights) == set(FALCON_MODEL_FILES)
        for path in falcon_weights.values():
            assert path.is_file()
            assert path.stat().st_size > 0


class TestModels:
    def test_remove_module_prefix_strips_data_parallel_keys(self) -> None:
        state_dict = {
            "_module.conv1.0.weight": torch.zeros(64, 3, 3, 3),
            "classifier.weight": torch.zeros(3, 1024),
        }

        adjusted = remove_module_prefix(state_dict)

        assert "conv1.0.weight" in adjusted
        assert "_module.conv1.0.weight" not in adjusted

    def test_load_models_returns_four_eval_resnet9_modules(self, falcon_weights: dict[str, Path]) -> None:
        part_model, hn_model, ch_model, ab_model = load_models(device="cpu")

        for model in (part_model, hn_model, ch_model, ab_model):
            assert isinstance(model, ResNet9)
            assert model.training is False

        assert part_model.classifier.out_features == 3
        assert hn_model.classifier.out_features == 1
        assert ch_model.classifier.out_features == 1
        assert ab_model.classifier.out_features == 1


class TestEligibility:
    def test_empty_list_returns_empty_list(self) -> None:
        assert check_falcon_eligibility([]) == []

    @pytest.mark.falcon_memory(max_rss_delta_mb=200)
    def test_twelve_slice_series_is_eligible(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "eligible")

        result = check_falcon_eligibility([series_dir])[0]

        assert result.eligible is True
        assert result.error is None

    def test_too_few_slices_is_ineligible(self, tmp_path: Path) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "short", num_slices=11)
        list_dcm_files(series_dir)[-1].unlink()

        result = check_falcon_eligibility([series_dir])[0]

        assert result.eligible is False
        assert result.error is not None
        assert "10" in result.error

    def test_empty_directory_is_ineligible(self, tmp_path: Path) -> None:
        series_dir = tmp_path / "empty"
        series_dir.mkdir()

        result = check_falcon_eligibility([series_dir])[0]

        assert result.eligible is False
        assert result.error is not None


class TestPredict:
    def test_empty_list_returns_empty_list(self) -> None:
        assert predict_falcon_series([]) == []

    @pytest.mark.falcon_memory(max_rss_delta_mb=450)
    def test_synthetic_series_returns_valid_prediction(
        self,
        falcon_weights: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "predict")

        result = predict_falcon_series([series_dir])[0]

        assert result.error is None
        assert result.body_part in FALCON_BODY_PARTS
        assert isinstance(result.body_part_confidence, float)
        assert 0.0 < result.body_part_confidence <= 1.0
        assert isinstance(result.iv_contrast, bool)
        assert isinstance(result.iv_contrast_confidence, float)
        assert 0.0 < result.iv_contrast_confidence <= 1.0

    def test_preprocessing_failure_returns_error_prediction(
        self,
        falcon_weights: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        series_dir = tmp_path / "empty"
        series_dir.mkdir()

        result = predict_falcon_series([series_dir])[0]

        assert result.error is not None
        assert result.body_part is None

    @pytest.mark.falcon_memory(max_rss_delta_mb=550)
    def test_batch_preserves_order(
        self,
        falcon_weights: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        eligible = build_synthetic_ct_small_series(tmp_path / "a")
        ineligible = tmp_path / "b"
        ineligible.mkdir()

        results = predict_falcon_series([eligible, ineligible])

        assert len(results) == 2
        assert results[0].error is None
        assert results[1].error is not None

    def test_predict_runs_eligibility_before_loading_models(
        self,
        falcon_weights: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        series_dir = build_synthetic_ct_small_series(tmp_path / "eligible")
        call_order: list[str] = []

        def track_eligibility(series_directories):
            call_order.append("eligibility")
            return check_falcon_eligibility(series_directories)

        def track_load_models(*args, **kwargs):
            call_order.append("load_models")
            return load_models(*args, **kwargs)

        with (
            patch(
                "anonymizer.controller.falcon.predict.check_falcon_eligibility",
                side_effect=track_eligibility,
            ),
            patch(
                "anonymizer.controller.falcon.predict.load_models",
                side_effect=track_load_models,
            ),
        ):
            predict_falcon_series([series_dir])

        assert call_order == ["eligibility", "load_models"]

    def test_predict_skips_model_load_when_all_series_ineligible(
        self,
        tmp_path: Path,
    ) -> None:
        ineligible = tmp_path / "empty"
        ineligible.mkdir()

        with patch("anonymizer.controller.falcon.predict.load_models") as mock_load_models:
            results = predict_falcon_series([ineligible])

        mock_load_models.assert_not_called()
        assert len(results) == 1
        assert results[0].error is not None
