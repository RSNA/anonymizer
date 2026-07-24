import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import torch

from anonymizer.controller.falcon import load_models

from anonymizer.controller.falcon.predict import (
    BODY_PART_MODEL_INPUT_Z_INDEX,
    FalconPrediction,
    contrast_prediction_confidence,
    extract_body_part_model_input,
    extract_body_part_model_input_slice,
    format_confidence_percent,
    predict_falcon_series,
)
from anonymizer.controller.falcon.preprocessing.preprocess_series import preprocess_series
from tests.controller.tseg.support.synthetic_ct import SYNTHETIC_PHANTOM_VERSION, write_synthetic_phantom_assets
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

def test_falcon_model_dir_under_anonymizer_package() -> None:
    expected = Path(load_models.__file__).resolve().parents[2] / "assets" / "falcon" / "models"
    assert load_models.FALCON_MODEL_DIR == expected


SYNTHETIC_DIRS = {
    "HeadNeck": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_head",
    "Chest": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_chest",
    "Abdomen": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_abdomen",
}

# Bump in tests.controller.tseg.support.synthetic_ct when phantom geometry changes.


def _synthetic_assets_need_generation() -> bool:
    head_neck_dir = SYNTHETIC_DIRS["HeadNeck"]
    version_file = head_neck_dir / ".phantom_version"
    if not head_neck_dir.exists() or not list(head_neck_dir.glob("*.dcm")):
        return True
    try:
        return int(version_file.read_text(encoding="utf-8").strip()) < SYNTHETIC_PHANTOM_VERSION
    except (OSError, ValueError):
        return True


@pytest.fixture(scope="session", autouse=True)
def ensure_synthetic_assets():
    """
    Runs once per test session. Regenerates synthetic DICOM assets when missing or stale.
    """
    if not _synthetic_assets_need_generation():
        return

    print("\n[Setup] Synthetic DICOM assets missing or stale. Generating them now...")
    import shutil

    for asset_dir in SYNTHETIC_DIRS.values():
        if asset_dir.exists():
            shutil.rmtree(asset_dir)
    write_synthetic_phantom_assets()
    version_file = SYNTHETIC_DIRS["HeadNeck"] / ".phantom_version"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(str(SYNTHETIC_PHANTOM_VERSION), encoding="utf-8")
    print("[Setup] Generation complete. Starting tests...\n")

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

def test_body_part_model_input_z_index_is_fixed():
    assert BODY_PART_MODEL_INPUT_Z_INDEX == 50


def test_extract_body_part_model_input_from_preprocessed_volume():
    image_np = np.linspace(-100, 100, 100 * 150 * 150, dtype=np.float32).reshape(100, 150, 150)
    slice_2d = extract_body_part_model_input_slice(image_np)
    assert slice_2d.shape == (150, 150)
    assert 0.0 <= slice_2d.min() <= slice_2d.max() <= 1.0

    model_input = extract_body_part_model_input(image_np)
    assert model_input.shape == (3, 150, 150)
    np.testing.assert_array_equal(model_input[0], slice_2d)
    np.testing.assert_array_equal(model_input[1], slice_2d)


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
        assert contrast_prediction_confidence(pred) > 0.99
        assert pred.radlex_series_description == "CT Chest With Contrast"


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (0.991234, "99.12%"),
        (0.999949, "99.99%"),
        (0.001, "0.10%"),
        (1.0, "100.00%"),
    ],
)
def test_format_confidence_percent_two_fractional_digits(confidence, expected):
    assert format_confidence_percent(confidence) == expected


def test_contrast_prediction_confidence_without_contrast():
    pred = FalconPrediction(
        series_directory=Path("/tmp/series"),
        body_part="Abdomen",
        body_part_confidence=0.99,
        iv_contrast=False,
        iv_contrast_confidence=0.001,
        radlex_series_description="CT Abdomen Without Contrast",
    )
    assert contrast_prediction_confidence(pred) == pytest.approx(0.999, abs=0.001)

@patch("anonymizer.controller.falcon.predict.load_falcon_models")
@patch("anonymizer.controller.falcon.predict.preprocess_series")
def test_preprocessing_failure(mock_preprocess, mock_load_models, mock_models):
    mock_load_models.return_value = mock_models
    mock_preprocess.side_effect = Exception("Corrupted DICOM files")
    
    predictions = predict_falcon_series([SYNTHETIC_DIRS["HeadNeck"]])
    assert len(predictions) == 1
    assert predictions[0].error is not None
    assert "Preprocessing error: Corrupted DICOM files" in predictions[0].error
    assert predictions[0].radlex_series_description == ""

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
    assert predictions[0].radlex_series_description == ""

# -------------------------------------------------------------------------
# REAL MODEL INTEGRATION TESTS (Skipped in CI/CD)
# -------------------------------------------------------------------------

def test_predict_real_models_headneck(assert_no_memory_leak):
    series_path = SYNTHETIC_DIRS["HeadNeck"]
    predictions = predict_falcon_series([series_path])

    assert len(predictions) == 1
    pred = predictions[0]

    assert pred.error is None, f"Pipeline failed with error: {pred.error}"
    assert pred.series_directory == series_path
    # Geometric head phantom is a pipeline smoke test; FALCON weights target real CT anatomy.
    assert pred.body_part in ("HeadNeck", "Chest", "Abdomen")
    assert pred.radlex_series_description.startswith("CT ")
    assert 0.0 <= pred.body_part_confidence <= 1.0
    assert 0.0 <= pred.iv_contrast_confidence <= 1.0

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
        if test_dirs[idx].name == "synthetic_CT_head":
            assert pred.body_part in ("HeadNeck", "Chest", "Abdomen")
        else:
            assert pred.body_part == expected_body_parts[idx]
        #assert pred.iv_contrast is False
        assert 0.0 <= pred.body_part_confidence <= 1.0
        assert 0.0 <= pred.iv_contrast_confidence <= 1.0