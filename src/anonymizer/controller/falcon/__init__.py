"""FALCON body-part and IV contrast inference for CT series."""

from anonymizer.controller.falcon.predict import (
    FALCON_BODY_PARTS,
    FalconEligibility,
    FalconPrediction,
    check_falcon_eligibility,
    predict_falcon_series,
)

__all__ = [
    "FALCON_BODY_PARTS",
    "FalconEligibility",
    "FalconPrediction",
    "check_falcon_eligibility",
    "predict_falcon_series",
]
