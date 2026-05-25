"""FALCON body-part and IV contrast inference for CT series."""

from anonymizer.controller.falcon.predict import check_falcon_eligibility, predict_falcon_series
from anonymizer.controller.falcon.types import FalconEligibility, FalconPrediction

__all__ = [
    "FalconEligibility",
    "FalconPrediction",
    "check_falcon_eligibility",
    "predict_falcon_series",
]
