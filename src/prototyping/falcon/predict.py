"""Public FALCON API: result types, eligibility checks, and series prediction."""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from prototyping.falcon.load_models import load_falcon_models
from prototyping.falcon.preprocessing.preprocess_series import preprocess_series
from prototyping.falcon.resnet9 import ResNet9
from anonymizer.utils.memory import collect_garbage_safe

# Determine device: GPU (CUDA) > Apple Silicon (MPS) > CPU
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")

logger = logging.getLogger(__name__)

FALCON_BODY_PARTS = ("HeadNeck", "Chest", "Abdomen")

_BODY_PART_RADLEX_LABELS: dict[str, str] = {
    "HeadNeck": "Head Neck",
    "Chest": "Chest",
    "Abdomen": "Abdomen",
}

BP_SLICE_RANGE = range(35, 65)
HN_SLICE_RANGE = range(35, 75)
CH_SLICE_RANGE = range(50, 80)
AB_SLICE_RANGE = range(20, 80)

BP_SLICE_IDX = 15
BODY_PART_MODEL_INPUT_Z_INDEX = BP_SLICE_RANGE.start + BP_SLICE_IDX
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


def _format_radlex_series_description(body_part: str, iv_contrast: bool, modality: str = "CT") -> str:
    """
    Build a RadLex-style CT series description from FALCON inference results.
    Args:
        - body_part: The body part predicted by FALCON ("HeadNeck", "Chest", or "Abdomen").
        - iv_contrast: A boolean indicating whether IV contrast is present.
        - modality: The modality of the series (default is "CT").
    Returns:
        - A string representing the RadLex-style series description.
    """
    body_label = _BODY_PART_RADLEX_LABELS.get(body_part)

    if body_label is None:
        raise ValueError(f"Unsupported body part for RadLex description: {body_part}")

    contrast_label = "With Contrast" if iv_contrast else "Without Contrast"
    return f"{modality} {body_label} {contrast_label}"


@dataclass(frozen=True)
class FalconPrediction:
    series_directory: Path
    body_part: str
    body_part_confidence: float
    iv_contrast: bool
    # Sigmoid output: P(IV contrast present). Threshold 0.5 yields iv_contrast.
    iv_contrast_confidence: float
    radlex_series_description: str
    error: str | None = None


def format_confidence_percent(confidence: float) -> str:
    """Format a 0–1 confidence as a percentage with two fractional digits (e.g. 99.87%)."""
    return f"{confidence * 100.0:.2f}%"


def contrast_prediction_confidence(prediction: FalconPrediction) -> float:
    """
    Confidence in the predicted contrast class (With or Without), analogous to body-part softmax max prob.

    iv_contrast_confidence is always P(contrast present); for a Without prediction that value is low
    even when the model is highly confident.
    """
    if prediction.iv_contrast:
        return prediction.iv_contrast_confidence
    return 1.0 - prediction.iv_contrast_confidence


def _error_prediction(series_directory: Path, error: str) -> FalconPrediction:
    return FalconPrediction(
        series_directory=Path(series_directory),
        body_part="",
        body_part_confidence=0.0,
        iv_contrast=False,
        iv_contrast_confidence=0.0,
        radlex_series_description="",
        error=error,
    )


def extract_body_part_model_input_slice(image_np: np.ndarray) -> np.ndarray:
    """
    Return the normalized 2D slice (H, W) in [0, 1] used as ResNet9 channel 0 for body-part inference.

    ``image_np`` must be the volume produced by ``preprocess_series`` (typically shape 100×150×150).
    """
    data = image_np[BP_SLICE_RANGE, :, :]
    data = np.clip(data, a_min=-200, a_max=200)
    data_min, data_max = data.min(), data.max()
    data = np.zeros_like(data) if data_max == data_min else (data - data_min) / (data_max - data_min)
    return np.asarray(data[BP_SLICE_IDX, :, :], dtype=np.float32)


def extract_body_part_model_input(image_np: np.ndarray) -> np.ndarray:
    """Return the 3-channel float array (3, H, W) passed to the body-part ResNet9."""
    slice_2d = extract_body_part_model_input_slice(image_np)
    return np.broadcast_to(slice_2d[np.newaxis, ...], (3, *slice_2d.shape)).copy()


def extract_contrast_model_input_slice(image_np: np.ndarray, body_part: str) -> np.ndarray:
    """
    Return the normalized 2D slice (H, W) in [0, 1] used as ResNet9 channel 0 for contrast inference.

    Uses the slice range for ``body_part`` (predicted body part in production).
    """
    slice_range, slice_idx = _get_contrast_slices(body_part)
    data = image_np[slice_range, :, :]
    data = np.clip(data, a_min=-200, a_max=200)
    data_min, data_max = data.min(), data.max()
    data = np.zeros_like(data) if data_max == data_min else (data - data_min) / (data_max - data_min)
    return np.asarray(data[slice_idx, :, :], dtype=np.float32)


def extract_contrast_model_input(image_np: np.ndarray, body_part: str) -> np.ndarray:
    """Return the 3-channel float array (3, H, W) passed to the contrast ResNet9."""
    slice_2d = extract_contrast_model_input_slice(image_np, body_part)
    return np.broadcast_to(slice_2d[np.newaxis, ...], (3, *slice_2d.shape)).copy()


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
    data_3ch = extract_body_part_model_input(image_np)
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
    data_3ch = extract_contrast_model_input(image_np, body_part)
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

    logger.info("FALCON predict starting for {} series on {}".format(len(series_directories), device))

    predictions: list[FalconPrediction] = []

    try:
        part_model, hn_model, ch_model, ab_model = load_falcon_models(device=device)
        if any(m is None for m in (part_model, hn_model, ch_model, ab_model)):
            logger.error("Failed to load all FALCON models.")
            return []
    except Exception as ex:
        logger.exception("Failed to load FALCON models: {}".format(ex))
        return []

    for series_dir in series_directories:
        image_np = None

        try:
            logger.info("FALCON preprocessing series: {}".format(series_dir))
            image_np = preprocess_series(series_dir)
        except Exception as ex:
            logger.error("FALCON preprocessing failed for {}: {}".format(series_dir, ex))
            predictions.append(_error_prediction(series_dir, f"Preprocessing error: {ex}"))
            continue

        logger.info("FALCON running inference for {}".format(series_dir))

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
            radlex_description = _format_radlex_series_description(body_part, iv_contrast)

            contrast_class_confidence = iv_contrast_prob if iv_contrast else 1.0 - iv_contrast_prob
            logger.info(
                "FALCON inference results for {}: body_part={} ({:.3f}), "
                "iv_contrast={} (P_present={:.3f}, class_confidence={:.3f}), "
                "radlex_series_description={}".format(
                    series_dir,
                    body_part,
                    body_part_confidence,
                    iv_contrast,
                    iv_contrast_prob,
                    contrast_class_confidence,
                    radlex_description,
                )
            )

            predictions.append(
                FalconPrediction(
                    series_directory=series_dir,
                    body_part=body_part,
                    body_part_confidence=body_part_confidence,
                    iv_contrast=iv_contrast,
                    iv_contrast_confidence=iv_contrast_prob,
                    radlex_series_description=radlex_description,
                )
            )

        except Exception as ex:
            logger.error("FALCON prediction failed for {}: {}".format(series_dir, ex))
            predictions.append(_error_prediction(series_dir, f"Prediction error: {ex}"))

        finally:
            if image_np is not None:
                del image_np

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif torch.backends.mps.is_available():
                torch.mps.empty_cache()
            collect_garbage_safe()

    del part_model, hn_model, ch_model, ab_model
    collect_garbage_safe()

    logger.info("FALCON predict finished: {} result(s)".format(len(predictions)))
    return predictions
