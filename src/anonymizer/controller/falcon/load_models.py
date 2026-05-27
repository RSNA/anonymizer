"""If necessary download FALCON ResNet9 model weights from github and save to disk. When required load them from disk and return as PyTorch model objects."""

from pathlib import Path
import logging
import requests
import torch
from torch import nn

from anonymizer.controller.falcon.resnet9 import ResNet9

logger = logging.getLogger(__name__)

FALCON_UPSTREAM_COMMIT = "7c33595ff6f45e609b2b0a3f5168fec883b45f2c"
_FALCON_RAW_BASE = (
    f"https://raw.githubusercontent.com/FintelmannLabDevelopmentTeam/Falcon/{FALCON_UPSTREAM_COMMIT}/models"
)
FALCON_MODEL_DIR = Path("assets") / "falcon" / "models"

FALCON_MODEL_FILES: dict[str, str] = {
    "body_part": "body_part_model.pth",
    "headneck": "headneck_model.pth",
    "chest": "chest_model.pth",
    "abdomen": "abdomen_model.pth",
}

FALCON_MODEL_URLS: dict[str, str] = {
    key: f"{_FALCON_RAW_BASE}/{filename}" for key, filename in FALCON_MODEL_FILES.items()
}


class FalconModelDownloadError(RuntimeError):
    """Raised when a FALCON model weight file cannot be downloaded."""


def _download_model(filename: str, url: str, destination: Path) -> None:
    """
    Download a FALCON model weight file from the specified URL to the destination path.

    Args:
        filename: The name of the model file (for logging purposes).
        url: The URL to download the model from.
        destination: The local file path to save the downloaded model to.   

    Raises:
        FalconModelDownloadError if the download fails for any reason.
        
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with temp_path.open("wb") as out_file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out_file.write(chunk)
        temp_path.replace(destination)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise FalconModelDownloadError(f"Failed to download FALCON model {filename} from {url}: {exc}") from exc


def _remove_module_prefix(state_dict: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """
    Removes the ``_module.`` prefix that DataParallel adds to checkpoint keys.
    
    Args:
        state_dict: The state dictionary loaded from the checkpoint.
    
    Returns:     
        A new state dictionary with the prefix removed from keys if it was present.
    
    """
    adjusted: dict[str, torch.Tensor] = {}
    for key, value in state_dict.items():
        name = key[8:] if key.startswith("_module.") else key
        adjusted[name] = value
    return adjusted


def _load_resnet9(weights_path: Path, num_classes: int, device: torch.device) -> ResNet9:
    """
    Load a ResNet9 model from the specified weights file and move to device.

    Args:
        weights_path: Path to the .pth file containing the model weights.
        num_classes: Number of output classes for the model.
        device: torch.device to load the model onto.

    Returns:
        An instance of ResNet9 with loaded weights, set to eval mode.

    Raises:
        FileNotFoundError if the weights file does not exist.
        RuntimeError if the weights cannot be loaded or do not match the model architecture.    
    """
    model = ResNet9(
        in_channels=3,
        num_classes=num_classes,
        act_func=nn.Sigmoid,
        scale_norm=True,
        norm_layer="group",
    )
    state_dict = torch.load(weights_path, map_location=device, weights_only=True)
    model.load_state_dict(_remove_module_prefix(state_dict))
    model.to(device)
    model.eval()
    return model

def falcon_models_available() -> bool:
    return all((FALCON_MODEL_DIR / filename).is_file() for filename in FALCON_MODEL_FILES.values())


def ensure_falcon_models_downloaded() -> dict[str, Path]:
    """
    Ensure all FALCON model weight files exist locally, downloading any that are missing.
    
    Returns: 
        Dictionary mapping model keys to their local file paths.
    
    Raises: 
        FalconModelDownloadError if any model file cannot be downloaded.
    """
    FALCON_MODEL_DIR.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {}
    for key, filename in FALCON_MODEL_FILES.items():
        destination = FALCON_MODEL_DIR / filename
        if not destination.is_file():
            logger.info("Downloading FALCON model %s", filename)
            _download_model(filename, FALCON_MODEL_URLS[key], destination)
        paths[key] = destination

    return paths


def load_falcon_models(device: torch.device) -> tuple[ResNet9, ResNet9, ResNet9, ResNet9]:
    """
    Load the four FALCON ResNet9 models from disk to specified device.

    Returns:
        Tuple of (body_part_model, headneck_contrast_model, chest_contrast_model, abdomen_contrast_model)

    Raises:
        FalconModelDownloadError if any model file is missing and cannot be downloaded.
    """
    paths = ensure_falcon_models_downloaded()

    if len(paths) != 4:
        missing = set(FALCON_MODEL_FILES.keys()) - set(paths.keys())
        raise FalconModelDownloadError(f"Missing FALCON model files: {missing}")
    
    part_model = _load_resnet9(paths["body_part"], 3, device)
    hn_model = _load_resnet9(paths["headneck"], 1, device)
    ch_model = _load_resnet9(paths["chest"], 1, device)
    ab_model = _load_resnet9(paths["abdomen"], 1, device)

    return part_model, hn_model, ch_model, ab_model


