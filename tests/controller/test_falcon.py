import os
import sys
import gc
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import psutil
import torch

from anonymizer.controller.falcon.predict import predict_falcon_series, FalconPrediction

BASE_TEST_DIR = Path("tests/controller/assets/test_dcm_files")

SYNTHETIC_DIRS = {
    "HeadNeck": BASE_TEST_DIR / "synthetic_CT_head",
    "Chest": BASE_TEST_DIR / "synthetic_CT_chest",
    "Abdomen": BASE_TEST_DIR / "synthetic_CT_abdomen"
}

# -------------------------------------------------------------------------
# FIXTURES
# -------------------------------------------------------------------------
@pytest.fixture
def mock_models():
    """Creates dummy ResNet9 models that output deterministic tensors."""
    mock_part_model = MagicMock()
    # Output shape (1, 3). High value at index 1 -> Chest prediction
    mock_part_model.return_value = torch.tensor([[-10.0, 10.0, -10.0]])
    
    mock_hn_model = MagicMock()
    mock_ch_model = MagicMock()
    mock_ab_model = MagicMock()
    
    # 10.0 -> Sigmoid -> ~1.0 (Contrast Present); -10.0 -> ~0.0 (No Contrast)
    mock_hn_model.return_value = torch.tensor([[10.0]])
    mock_ch_model.return_value = torch.tensor([[10.0]])
    mock_ab_model.return_value = torch.tensor([[-10.0]])
    
    return mock_part_model, mock_hn_model, mock_ch_model, mock_ab_model

@pytest.fixture
def mock_preprocess():
    """Mocks the preprocessing to return a dummy 3D numpy array instead of hitting disk."""
    dummy_array = np.zeros((100, 200, 200), dtype=np.float32)
    return dummy_array

# -------------------------------------------------------------------------
# MOCKED UNIT TESTS (Run on every commit)
# -------------------------------------------------------------------------

def test_empty_directory_list():
    predictions = predict_falcon_series([])
    assert isinstance(predictions, list)
    assert len(predictions) == 0

@patch("anonymizer.controller.falcon.predict.load_falcon_models")
def test_model_load_failure(mock_load):
    mock_load.return_value = (MagicMock(), None, MagicMock(), MagicMock())
    predictions = predict_falcon_series([SYNTHETIC_DIRS["Chest"]])
    assert len(predictions) == 0
    mock_load.assert_called_once()

@patch("anonymizer.controller.falcon.predict.load_falcon_models")
@patch("anonymizer.controller.falcon.predict.preprocess_series")
def test_successful_predictions(mock_preprocess, mock_load_models, mock_models):
    mock_load_models.return_value = mock_models
    mock_preprocess.return_value = np.zeros((100, 200, 200), dtype=np.float32)
    
    test_dirs = list(SYNTHETIC_DIRS.values())
    predictions = predict_falcon_series(test_dirs)
    
    assert len(predictions) == 3
    for pred in predictions:
        assert isinstance(pred, FalconPrediction)
        assert pred.error is None
        assert pred.body_part == "Chest"
        assert pred.body_part_confidence > 0.99
        assert pred.iv_contrast is True
        assert pred.iv_contrast_confidence > 0.99

@patch("anonymizer.controller.falcon.predict.load_falcon_models")
@patch("anonymizer.controller.falcon.predict.preprocess_series")
def test_preprocessing_failure(mock_preprocess, mock_load_models, mock_models):
    mock_load_models.return_value = mock_models
    mock_preprocess.side_effect = Exception("Corrupted DICOM files")
    
    predictions = predict_falcon_series([SYNTHETIC_DIRS["HeadNeck"]])
    assert len(predictions) == 1
    assert predictions[0].error is not None
    assert "Preprocessing error: Corrupted DICOM files" in predictions[0].error

@patch("anonymizer.controller.falcon.predict.load_falcon_models")
@patch("anonymizer.controller.falcon.predict.preprocess_series")
@patch("anonymizer.controller.falcon.predict.get_body_part_probabilities")
def test_inference_failure(mock_get_probs, mock_preprocess, mock_load_models, mock_models):
    mock_load_models.return_value = mock_models
    mock_preprocess.return_value = np.zeros((100, 200, 200))
    mock_get_probs.side_effect = RuntimeError("CUDA out of memory")
    
    predictions = predict_falcon_series([SYNTHETIC_DIRS["Abdomen"]])
    assert len(predictions) == 1
    assert predictions[0].error is not None
    assert "Prediction error: CUDA out of memory" in predictions[0].error
    assert predictions[0].iv_contrast is False

# -------------------------------------------------------------------------
# REAL MODEL INTEGRATION TESTS (Skipped in CI/CD)
# -------------------------------------------------------------------------

@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_predict_real_models_headneck(assert_no_memory_leak):
    series_path = SYNTHETIC_DIRS["HeadNeck"]
    predictions = predict_falcon_series([series_path])
    
    assert len(predictions) == 1
    pred = predictions[0]
    
    assert pred.error is None, f"Pipeline failed with error: {pred.error}"
    assert pred.series_directory == series_path
    
    # Assert reliable body part and non-contrast state
    assert pred.body_part == "HeadNeck"
    assert pred.iv_contrast is False
    assert 0.0 <= pred.body_part_confidence <= 1.0
    assert 0.0 <= pred.iv_contrast_confidence <= 1.0

@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_predict_real_models_chest(assert_no_memory_leak):
    series_path = SYNTHETIC_DIRS["Chest"]
    predictions = predict_falcon_series([series_path])
    
    assert len(predictions) == 1
    pred = predictions[0]
    
    assert pred.error is None, f"Pipeline failed with error: {pred.error}"
    assert pred.series_directory == series_path
    
    # Assert reliable body part and non-contrast state
    assert pred.body_part == "Chest"
    # assert pred.iv_contrast is False &&TODO: Update when we have a real non-contrast chest series in the test assets
    assert 0.0 <= pred.body_part_confidence <= 1.0
    assert 0.0 <= pred.iv_contrast_confidence <= 1.0

@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_predict_real_models_abdomen(assert_no_memory_leak):
    series_path = SYNTHETIC_DIRS["Abdomen"]
    predictions = predict_falcon_series([series_path])
    
    assert len(predictions) == 1
    pred = predictions[0]
    
    assert pred.error is None, f"Pipeline failed with error: {pred.error}"
    assert pred.series_directory == series_path
    
    # Assert reliable body part and non-contrast state
    assert pred.body_part == "Abdomen"
    assert pred.iv_contrast is False
    assert 0.0 <= pred.body_part_confidence <= 1.0
    assert 0.0 <= pred.iv_contrast_confidence <= 1.0

@pytest.mark.skipif(os.getenv("CI") == "true", reason="Skip test for CI")
def test_predict_real_models_batch(assert_no_memory_leak):
    test_dirs = [
        SYNTHETIC_DIRS["HeadNeck"],
        SYNTHETIC_DIRS["Chest"],
        SYNTHETIC_DIRS["Abdomen"]
    ]
    expected_body_parts = ["HeadNeck", "Chest", "Abdomen"]
    
    predictions = predict_falcon_series(test_dirs)
    assert len(predictions) == 3
    
    for idx, pred in enumerate(predictions):
        assert pred.error is None, f"Pipeline failed on series {idx} with error: {pred.error}"
        assert pred.series_directory == test_dirs[idx]
        assert pred.body_part == expected_body_parts[idx]
        #assert pred.iv_contrast is False
        assert 0.0 <= pred.body_part_confidence <= 1.0
        assert 0.0 <= pred.iv_contrast_confidence <= 1.0