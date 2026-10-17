"""XR chest view: CXR projection (AP/PA/Lateral) + rotation for planar Harmonize.

Upstream weights come from MedicalAILabo ``CXp-Projection-Rotation-Mislabel-Checker``
(directory/API name historically ``cxp_view``). Product feature: **XR chest view**.
"""

from anonymizer.controller.ai.harmonize.xr_chest_view.cache import (
    CXP_VIEW_DIR,
    XR_CHEST_VIEW_DIR,
    CxpViewModelStatus,
    XrChestViewModelStatus,
    cxp_view_ready,
    download_cxp_view_models,
    download_xr_chest_view_models,
    probe_cxp_view_models,
    probe_xr_chest_view_models,
    remove_cxp_view_models,
    remove_xr_chest_view_models,
    xr_chest_view_ready,
)
from anonymizer.controller.ai.harmonize.xr_chest_view.labels import (
    CXP_PROJECTION_LABELS,
    CXP_ROTATION_LABELS,
    map_projection_to_playbook_view,
)
from anonymizer.controller.ai.harmonize.xr_chest_view.predict import (
    CxpViewPrediction,
    predict_cxp_view,
    predict_cxp_view_from_array,
)

__all__ = [
    "CXP_PROJECTION_LABELS",
    "CXP_ROTATION_LABELS",
    "CXP_VIEW_DIR",
    "XR_CHEST_VIEW_DIR",
    "CxpViewModelStatus",
    "XrChestViewModelStatus",
    "CxpViewPrediction",
    "cxp_view_ready",
    "xr_chest_view_ready",
    "download_cxp_view_models",
    "download_xr_chest_view_models",
    "map_projection_to_playbook_view",
    "predict_cxp_view",
    "predict_cxp_view_from_array",
    "probe_cxp_view_models",
    "probe_xr_chest_view_models",
    "remove_cxp_view_models",
    "remove_xr_chest_view_models",
]
