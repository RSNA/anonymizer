"""AI feature readiness gates (Controller): install/run enablement predicates.

View imports these directly. Status strings, download manager, and catalog registry stay in View.
"""

from __future__ import annotations

from anonymizer.controller.ai.remove_pixel_phi import (
    OcrModelStatus,
    ocr_models_ready,
    probe_ocr_models,
)
from anonymizer.controller.ai.tseg.config import (
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
)
from anonymizer.controller.ai.tseg.model_cache import (
    installed_ct_segmentation_modes,
    installed_mr_segmentation_modes,
)
from anonymizer.controller.ai.tseg.readiness import (
    anatomy_ct_ready,
    anatomy_mr_ready,
    brain_structures_ready,
    face_ct_ready,
    face_license_available,
    face_mr_ready,
    totalsegmentator_available,
    xgboost_available,
)


def pixel_phi_allowed() -> bool:
    return ocr_models_ready()


def harmonize_allowed() -> bool:
    """True when Harmonize can run for at least one modality.

    Planar XR/US/MG Harmonize needs no TotalSegmentator models, so this is always True.
    Per-series readiness for CT/MR still uses ``harmonize_allowed_for_modality``.
    """
    return True


def harmonize_allowed_for_modality(modality: object | None) -> bool:
    """True when Harmonize models/path for ``modality`` are ready."""
    from anonymizer.utils.modalities import is_mr_modality, is_planar_harmonize_modality, is_tseg_modality

    if is_planar_harmonize_modality(modality):
        return True
    if not is_tseg_modality(modality):
        return False
    if not totalsegmentator_available():
        return False
    if is_mr_modality(modality):
        return bool(installed_mr_segmentation_modes())
    return bool(installed_ct_segmentation_modes()) and xgboost_available()


def face_blur_allowed() -> bool:
    return totalsegmentator_available() and face_license_available() and (face_ct_ready() or face_mr_ready())


def brain_structures_allowed() -> bool:
    return (
        totalsegmentator_available()
        and xgboost_available()
        and face_license_available()
        and brain_structures_ready()
    )


def any_ai_batch_feature_allowed() -> bool:
    return pixel_phi_allowed() or harmonize_allowed() or face_blur_allowed()


def remove_pixel_phi_has_models() -> bool:
    return ocr_models_ready()


def harmonize_has_models() -> bool:
    return bool(installed_ct_segmentation_modes() or installed_mr_segmentation_modes())


def harmonize_ct_has_models() -> bool:
    return bool(installed_ct_segmentation_modes())


def harmonize_mr_has_models() -> bool:
    return bool(installed_mr_segmentation_modes())


def brain_structures_has_models() -> bool:
    return brain_structures_ready()


def face_blur_has_models() -> bool:
    return face_ct_ready() or face_mr_ready()


def face_ct_has_models() -> bool:
    return face_ct_ready()


def face_mr_has_models() -> bool:
    return face_mr_ready()


def remove_pixel_phi_needs_download() -> bool:
    ocr_status, _ = probe_ocr_models()
    return ocr_status in {OcrModelStatus.MISSING, OcrModelStatus.FAILED}


def harmonize_ct_needs_download() -> bool:
    """True when the active CT workstation resolution pack is not on disk."""
    return (
        totalsegmentator_available()
        and xgboost_available()
        and not anatomy_ct_ready(get_ct_segmentation_mode())
    )


def harmonize_mr_needs_download() -> bool:
    """True when the active MR workstation resolution pack is not on disk."""
    return totalsegmentator_available() and not anatomy_mr_ready(get_mr_segmentation_mode())


def brain_structures_needs_download() -> bool:
    return totalsegmentator_available() and face_license_available() and not brain_structures_has_models()


def face_blur_needs_license() -> bool:
    return totalsegmentator_available() and not face_license_available()


def face_ct_needs_download() -> bool:
    return totalsegmentator_available() and face_license_available() and not face_ct_has_models()


def face_mr_needs_download() -> bool:
    return totalsegmentator_available() and face_license_available() and not face_mr_has_models()
