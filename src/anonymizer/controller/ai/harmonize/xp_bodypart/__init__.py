"""XR (CR/DX) pixel body-part classification for planar Harmonize."""

from anonymizer.controller.ai.harmonize.xp_bodypart.cache import (
    XP_BODYPART_DIR,
    XpBodypartModelStatus,
    download_xp_bodypart_models,
    probe_xp_bodypart_models,
    remove_xp_bodypart_models,
    xp_bodypart_ready,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.labels import (
    XP_BODYPART_LABELS,
    map_xp_label_to_planar_anatomy,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.predict import (
    XpBodypartPrediction,
    predict_body_part,
    predict_body_part_from_array,
)

__all__ = [
    "XP_BODYPART_DIR",
    "XP_BODYPART_LABELS",
    "XpBodypartModelStatus",
    "XpBodypartPrediction",
    "download_xp_bodypart_models",
    "map_xp_label_to_planar_anatomy",
    "predict_body_part",
    "predict_body_part_from_array",
    "probe_xp_bodypart_models",
    "remove_xp_bodypart_models",
    "xp_bodypart_ready",
]
