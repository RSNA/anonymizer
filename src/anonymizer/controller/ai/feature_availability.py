"""AI feature readiness gates (Controller): install/run enablement predicates.

Public API
----------
embedded_phi_allowed() -> bool
    Embedded phi allowed.

harmonize_allowed() -> bool
    True when Harmonize can run for at least one modality.

harmonize_allowed_for_modality(modality: str | None) -> bool
    True when Harmonize models/path for modality are ready.

face_blur_allowed() -> bool
    Face blur allowed.

brain_structures_allowed() -> bool
    Brain structures allowed.

any_ai_batch_feature_allowed() -> bool
    Any ai batch feature allowed.

embedded_phi_has_models() -> bool
    OCR ∧ NER — Series View / pixel_report / batch Embedded PHI.

report_text_phi_ready() -> bool
    NER only — Encapsulated PDF text layer and SR Report View detect.

harmonize_has_models() -> bool
    Harmonize has models.

harmonize_ct_has_models() -> bool
    Harmonize ct has models.

harmonize_mr_has_models() -> bool
    Harmonize mr has models.

brain_structures_has_models() -> bool
    Brain structures has models.

face_blur_has_models() -> bool
    Face blur has models.

face_ct_has_models() -> bool
    Face ct has models.

face_mr_has_models() -> bool
    Face mr has models.

embedded_phi_needs_download() -> bool
    Embedded phi needs download.

harmonize_ct_needs_download() -> bool
    True when the active CT workstation resolution pack is not on disk.

harmonize_mr_needs_download() -> bool
    True when the active MR workstation resolution pack is not on disk.

brain_structures_needs_download() -> bool
    Brain structures needs download.

face_blur_needs_license() -> bool
    Face blur needs license.

face_ct_needs_download() -> bool
    Face ct needs download.

face_mr_needs_download() -> bool
    Face mr needs download.

harmonize_xr_bodypart_has_models() -> bool
    Harmonize xr bodypart has models.

harmonize_xr_bodypart_needs_download() -> bool
    Harmonize xr bodypart needs download.

harmonize_cxr_view_has_models() -> bool
    Harmonize cxr view has models.

harmonize_cxr_view_needs_download() -> bool
    Harmonize cxr view needs download.

deid_option_ready(code) -> bool
    Whether a de-identification option may be selected given model readiness.
"""
from anonymizer.controller.ai.embedded_phi.ner.cache import NerModelStatus, ner_ready, probe_ner_models
from anonymizer.controller.ai.embedded_phi.pixel.cache import OcrModelStatus, ocr_models_ready, probe_ocr_models
from anonymizer.controller.ai.harmonize.xp_bodypart import (
    XpBodypartModelStatus,
    probe_xp_bodypart_models,
    xp_bodypart_ready,
)
from anonymizer.controller.ai.harmonize.xr_chest_view import CxpViewModelStatus, cxp_view_ready, probe_cxp_view_models
from anonymizer.controller.ai.tseg.config import get_ct_segmentation_mode, get_mr_segmentation_mode
from anonymizer.controller.ai.tseg.model_cache import installed_ct_segmentation_modes, installed_mr_segmentation_modes
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
from anonymizer.model.project import AT_INGEST
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.utils.modalities import (
    ContentClass,
    Modality,
    get_modality_catalog,
)


def embedded_phi_allowed() -> bool:
    return embedded_phi_has_models()


def harmonize_allowed() -> bool:
    """True when Harmonize can run for at least one modality.

    Planar XR/US/MG Harmonize needs no TotalSegmentator models, so this is always True.
    Per-series readiness for CT/MR still uses harmonize_allowed_for_modality.
    """
    return True


def harmonize_allowed_for_modality(modality: str | None) -> bool:
    """True when Harmonize models/path for modality are ready."""

    parsed = Modality.from_code(modality)
    if parsed is None or not get_modality_catalog()[parsed].harmonize:
        return False
    cls = get_modality_catalog()[parsed].content_class
    if cls is ContentClass.D2 or cls is ContentClass.TEXT:
        return True
    if parsed not in {Modality.CT, Modality.MR}:
        return False
    if not totalsegmentator_available():
        return False
    if parsed is Modality.MR:
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
    return embedded_phi_allowed() or harmonize_allowed() or face_blur_allowed()


def embedded_phi_has_models() -> bool:
    """OCR ∧ NER — Series View / pixel_report / batch Embedded PHI."""
    return ocr_models_ready() and ner_ready()


def report_text_phi_ready() -> bool:
    """NER only — Encapsulated PDF text layer and SR Report View detect."""
    return ner_ready()


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


def embedded_phi_needs_download() -> bool:
    ocr_status, _ = probe_ocr_models()
    ner_status, _ = probe_ner_models()
    ocr_needs = ocr_status in {OcrModelStatus.MISSING, OcrModelStatus.FAILED}
    ner_needs = ner_status in {NerModelStatus.MISSING, NerModelStatus.FAILED}
    return ocr_needs or ner_needs


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


def harmonize_xr_bodypart_has_models() -> bool:
    return xp_bodypart_ready()


def harmonize_xr_bodypart_needs_download() -> bool:
    status, _ = probe_xp_bodypart_models()
    return status in {XpBodypartModelStatus.MISSING, XpBodypartModelStatus.FAILED}


def harmonize_cxr_view_has_models() -> bool:
    return cxp_view_ready()


def harmonize_cxr_view_needs_download() -> bool:
    status, _ = probe_cxp_view_models()
    return status in {CxpViewModelStatus.MISSING, CxpViewModelStatus.FAILED}


def deid_option_ready(code: DeidMethodCode) -> bool:
    """
    Whether the option can be selected: its AI feature reports ready.

    Ingest options need no download and are always ready; options no task
    executes are never ready.

    Args:
        code: De-identification option code.

    Returns:
        True when the option may be selected.
    """
    code = DeidMethodCode(code)
    if code in AT_INGEST:
        return True
    if code is DeidMethodCode.CLEAN_PIXEL_DATA:
        return embedded_phi_allowed()
    if code in (DeidMethodCode.CLEAN_STRUCTURED_CONTENT, DeidMethodCode.CLEAN_DESCRIPTORS):
        return report_text_phi_ready()
    if code is DeidMethodCode.CLEAN_VISUAL_FEATURES:
        return face_blur_allowed()
    return False

