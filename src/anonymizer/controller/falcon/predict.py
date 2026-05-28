"""Public FALCON API: result types, eligibility checks, and series prediction."""

import gc
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from anonymizer.controller.falcon.load_models import load_falcon_models
from anonymizer.controller.falcon.preprocessing.preprocess_series import preprocess_series
from anonymizer.controller.falcon.resnet9 import ResNet9

# Determine device: GPU (CUDA) > Apple Silicon (MPS) > CPU
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")

logger = logging.getLogger(__name__)

FALCON_BODY_PARTS = ("HeadNeck", "Chest", "Abdomen")

BP_SLICE_RANGE = range(35, 65)
HN_SLICE_RANGE = range(35, 75)
CH_SLICE_RANGE = range(50, 80)
AB_SLICE_RANGE = range(20, 80)

BP_SLICE_IDX = 15
HN_SLICE_IDX = 20
CH_SLICE_IDX = 15
AB_SLICE_IDX = 43

def _get_contrast_slices(body_part: str) -> tuple[range, int]:
    if body_part == "HeadNeck":
        return HN_SLICE_RANGE, HN_SLICE_IDX
    if body_part == "Chest":
        return CH_SLICE_RANGE, CH_SLICE_IDX
    if body_part == "Abdomen":
        return AB_SLICE_RANGE, AB_SLICE_IDX
    raise ValueError(f"Unsupported body part for contrast inference: {body_part}")

@dataclass(frozen=True)
class FalconPrediction:
    series_directory: Path
    body_part: str
    body_part_confidence: float
    iv_contrast: bool
    iv_contrast_confidence: float
    error: str | None = None


def _error_prediction(series_directory: Path, error: str) -> FalconPrediction:

    return FalconPrediction(
        series_directory=Path(series_directory),
        body_part="",
        body_part_confidence=0.0,
        iv_contrast=False,
        iv_contrast_confidence=0.0,
        error=error
    )

def get_body_part_probabilities(model: ResNet9, image_np: np.ndarray) -> np.ndarray:
    """
    Run body part classification model and return probabilities for each class.

    Args:
        model: The ResNet9 model for body part classification.
        image_np: The numpy array of the image to classify.

    Returns:
        A numpy array of probabilities for each body part class.

    Raises:
        ValueError if the model output is not as expected.

    """
    data = image_np[BP_SLICE_RANGE, :, :]
    data = np.clip(data, a_min=-200, a_max=200)
    data_min, data_max = data.min(), data.max()
    data = np.zeros_like(data) if data_max == data_min else (data - data_min) / (data_max - data_min)
    data_single_slice = data[BP_SLICE_IDX, :, :]
    data_3ch = np.broadcast_to(data_single_slice[np.newaxis, ...], (3, *data_single_slice.shape))
    data_3ch = np.copy(data_3ch)
    tensor = torch.from_numpy(data_3ch).float().to(device)

    with torch.no_grad():
        output = model(tensor.unsqueeze(0)).cpu()

    probabilities = torch.softmax(output, dim=1).squeeze(0)
    return probabilities.cpu().numpy()



def get_contrast_probability(model: ResNet9, image_np: np.ndarray, body_part: str) -> float:
    """
    Run IV contrast inference on a CT image for a specific body part.

    Args:
        - model: The ResNet9 model for IV contrast classification corresponding to the body part.
        - image_np: The numpy array of the preprocessed image to classify.
        - body_part: The body part of the image ("HeadNeck", "Chest", or "Abdomen") to determine which slice range and index to use for inference.

    Returns:
        - A float representing the probability that IV contrast is present in the image.

    Raises:
        - ValueError if the body part is not recognized or if the model output is not as expected.

    """
    slice_range, slice_idx = _get_contrast_slices(body_part)
    data = image_np[slice_range, :, :]
    data = np.clip(data, a_min=-200, a_max=200)
    data_min, data_max = data.min(), data.max()
    data = np.zeros_like(data) if data_max == data_min else (data - data_min) / (data_max - data_min)
    data_single_slice = data[slice_idx, :, :]
    data_3ch = np.broadcast_to(data_single_slice[np.newaxis, ...], (3, *data_single_slice.shape))
    data_3ch = np.copy(data_3ch)
    tensor = torch.from_numpy(data_3ch).float().to(device)

    with torch.no_grad():
        output = model(tensor.unsqueeze(0)).cpu()

    probability = torch.sigmoid(output).squeeze().cpu().numpy()
    return float(probability.item())

def predict_falcon_series(series_directories: list[Path]) -> list[FalconPrediction]:
    """
    Run FALCON body-part and IV contrast inference on CT series directories.
    For each series directory, returns a FalconPrediction with results or error details.

    Args:
        series_directories: List of paths to CT series directories to predict on.

    Returns:
        List of FalconPrediction objects corresponding to each input series directory.

    Notes:
        - If the input list is empty or unable to load all the FALCON models, returns an empty list.
        - For each series directory, checks eligibility first. If ineligible, returns a prediction with error details in error field.
        - Loads FALCON models once if any series is eligible, and reuses them for all eligible series.
        - Handles exceptions gracefully, ensuring that one failed prediction does not affect others.
    """
    if not series_directories:
        logger.error("No series directories provided for FALCON prediction.")
        return []

    predictions: list[FalconPrediction] = []

    # Load ResNet9 models:
    part_model, hn_model, ch_model, ab_model = load_falcon_models(device=device)
    if any(model is None for model in (part_model, hn_model, ch_model, ab_model)):
        logger.error("Failed to load all FALCON models.")
        return []

    for series_dir in series_directories:
        image_np = None

        # PREPROCESSING
        try:
            image_np = preprocess_series(series_dir)
        except Exception as ex:
            logger.error(f"FALCON preprocessing failed for {series_dir}: {ex}")
            predictions.append(_error_prediction(series_dir, f"Preprocessing error: {ex}"))
            continue

        # INFERENCE
        try:
            body_part_probs = get_body_part_probabilities(part_model, image_np)
            body_part_idx = int(np.argmax(body_part_probs))
            body_part = FALCON_BODY_PARTS[body_part_idx]
            body_part_confidence = float(body_part_probs[body_part_idx])

            iv_contrast_prob = get_contrast_probability(
                hn_model if body_part == "HeadNeck" else ch_model if body_part == "Chest" else ab_model,
                image_np,
                body_part,
            )
            iv_contrast = iv_contrast_prob >= 0.5

            predictions.append(
                FalconPrediction(
                    series_directory=series_dir,
                    body_part=body_part,
                    body_part_confidence=body_part_confidence,
                    iv_contrast=iv_contrast,
                    iv_contrast_confidence=iv_contrast_prob,
                )
            )

        except Exception as ex:
            logger.error("FALCON prediction failed for %s: %s", series_dir, ex)
            predictions.append(_error_prediction(series_dir, f"Prediction error: {ex}"))

        finally:
            # Guarantee memory release for the 1GB objects on every iteration
            if image_np is not None:
                del image_np

            # Prevent accelerator and RAM fragmentation during large batches
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif torch.backends.mps.is_available():
                torch.mps.empty_cache()
            gc.collect()


    del part_model, hn_model, ch_model, ab_model
    gc.collect()

    return predictions
