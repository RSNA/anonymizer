"""Public FALCON eligibility and prediction entry points."""

import logging
from pathlib import Path

from anonymizer.controller.falcon.pipeline import preprocess_series_directory
from anonymizer.controller.falcon.types import FalconEligibility, FalconPrediction

logger = logging.getLogger(__name__)

_PREDICT_STUB_ERROR = "FALCON inference is not yet implemented"


def check_falcon_eligibility(series_directories: list[Path]) -> list[FalconEligibility]:
    """Return preprocessing eligibility for each CT series directory."""
    if not series_directories:
        return []
    return [_eligibility_for_series(path) for path in series_directories]


def predict_falcon_series(series_directories: list[Path]) -> list[FalconPrediction]:
    """Run FALCON body-part and IV contrast inference on CT series directories."""
    if not series_directories:
        return []
    return [FalconPrediction.failure(path, _PREDICT_STUB_ERROR) for path in series_directories]


def _eligibility_for_series(series_directory: Path) -> FalconEligibility:
    series_directory = Path(series_directory)
    _, error = preprocess_series_directory(series_directory)
    if error is not None:
        logger.debug("FALCON ineligible series %s: %s", series_directory, error)
        return FalconEligibility(
            series_directory=series_directory,
            eligible=False,
            error=error,
        )
    return FalconEligibility(series_directory=series_directory, eligible=True)
