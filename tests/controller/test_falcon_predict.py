"""Tests for FALCON public API stubs and eligibility mapping."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from anonymizer.controller.falcon import (
    FalconEligibility,
    FalconPrediction,
    check_falcon_eligibility,
    predict_falcon_series,
)


class TestCheckFalconEligibility:
    def test_empty_list_returns_empty_list(self) -> None:
        assert check_falcon_eligibility([]) == []

    @patch("anonymizer.controller.falcon.predict.preprocess_series_directory")
    def test_single_series_dir_returns_one_result_with_correct_path(
        self,
        mock_preprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        series_dir = tmp_path / "series_a"
        series_dir.mkdir()
        mock_preprocess.return_value = (MagicMock(), None)

        results = check_falcon_eligibility([series_dir])

        assert len(results) == 1
        assert results[0].series_directory == series_dir
        mock_preprocess.assert_called_once_with(series_dir)

    @patch("anonymizer.controller.falcon.predict.preprocess_series_directory")
    def test_eligible_when_preprocessing_succeeds(
        self,
        mock_preprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        series_dir = tmp_path / "series_a"
        series_dir.mkdir()
        mock_preprocess.return_value = (MagicMock(), None)

        result = check_falcon_eligibility([series_dir])[0]

        assert result == FalconEligibility(series_directory=series_dir, eligible=True)

    @patch("anonymizer.controller.falcon.predict.preprocess_series_directory")
    def test_ineligible_when_preprocessing_fails(
        self,
        mock_preprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        series_dir = tmp_path / "series_a"
        series_dir.mkdir()
        mock_preprocess.return_value = (None, "Found only 10 slices; need at least 11")

        result = check_falcon_eligibility([series_dir])[0]

        assert result.eligible is False
        assert result.error == "Found only 10 slices; need at least 11"
        assert result.series_directory == series_dir

    @patch("anonymizer.controller.falcon.predict.preprocess_series_directory")
    def test_batch_of_n_dirs_returns_n_results_in_order(
        self,
        mock_preprocess: MagicMock,
        tmp_path: Path,
    ) -> None:
        series_dirs = [tmp_path / f"series_{index}" for index in range(4)]
        for series_dir in series_dirs:
            series_dir.mkdir()
        mock_preprocess.side_effect = [
            (MagicMock(), None),
            (None, "empty directory"),
            (MagicMock(), None),
            (None, "invalid DICOM"),
        ]

        results = check_falcon_eligibility(series_dirs)

        assert len(results) == 4
        assert [result.series_directory for result in results] == series_dirs
        assert [result.eligible for result in results] == [True, False, True, False]
        assert results[1].error == "empty directory"
        assert results[3].error == "invalid DICOM"


class TestPredictFalconSeries:
    def test_empty_list_returns_empty_list(self) -> None:
        assert predict_falcon_series([]) == []

    def test_single_series_dir_returns_one_failure_result(
        self,
        tmp_path: Path,
    ) -> None:
        series_dir = tmp_path / "series_a"
        series_dir.mkdir()

        results = predict_falcon_series([series_dir])

        assert len(results) == 1
        assert results[0].series_directory == series_dir
        assert results[0].error == "FALCON inference is not yet implemented"
        assert results[0].success is False

    def test_batch_of_n_dirs_returns_n_results_in_order(
        self,
        tmp_path: Path,
    ) -> None:
        series_dirs = [tmp_path / f"series_{index}" for index in range(3)]
        for series_dir in series_dirs:
            series_dir.mkdir()

        results = predict_falcon_series(series_dirs)

        assert len(results) == 3
        assert [result.series_directory for result in results] == series_dirs
        assert all(result.error == "FALCON inference is not yet implemented" for result in results)


class TestFalconPredictionFailure:
    def test_failure_classmethod_shape(self, tmp_path: Path) -> None:
        series_dir = tmp_path / "series_a"
        series_dir.mkdir()

        prediction = FalconPrediction.failure(series_dir, "preprocessing failed")

        assert prediction.series_directory == series_dir
        assert prediction.error == "preprocessing failed"
        assert prediction.body_part is None
        assert prediction.body_part_confidence is None
        assert prediction.iv_contrast is None
        assert prediction.iv_contrast_confidence is None
        assert prediction.success is False

    def test_successful_prediction_has_no_error(self) -> None:
        prediction = FalconPrediction(
            series_directory=Path("/tmp/series"),
            body_part="Chest",
            body_part_confidence=0.91,
            iv_contrast=True,
            iv_contrast_confidence=0.88,
        )

        assert prediction.success is True
        assert prediction.error is None
