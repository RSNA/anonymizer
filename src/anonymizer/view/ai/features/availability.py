"""AI Features availability: gates, status, inventory, download manager, license UX."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from anonymizer.controller.ai.remove_pixel_phi import (
    OcrModelStatus,
    ocr_models_ready,
    probe_ocr_models,
)
from anonymizer.controller.ai.tseg.config import (
    DEFAULT_SEGMENTATION_MODE,
    SegmentationMode,
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    normalize_segmentation_mode,
)
from anonymizer.controller.ai.tseg.modality_profile import is_mr_modality
from anonymizer.controller.ai.tseg.model_cache import (
    ct_face_models_ready,
    face_task_ids,
    harmonize_ts_task_ids,
    installed_ct_segmentation_modes,
    installed_mr_segmentation_modes,
    missing_harmonize_ts_task_ids,
    missing_mr_anatomy_task_ids,
    mr_anatomy_task_ids,
    mr_face_models_ready,
    mr_face_task_ids,
)
from anonymizer.controller.ai.tseg.readiness import (
    TsWeightKind,
    anatomy_ct_ready,
    anatomy_mr_ready,
    brain_structures_ready,
    face_ct_ready,
    face_license_available,
    face_mr_ready,
    totalsegmentator_available,
    ts_academic_license_url,
    xgboost_available,
)
from anonymizer.utils.storage import (
    any_model_download_active,
    begin_model_download,
    end_model_download,
    get_model_download_progress,
    is_model_download_active,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.catalog import (
    DOWNLOAD_ID_BRAIN,
    DOWNLOAD_ID_FACE_CT,
    DOWNLOAD_ID_FACE_MR,
    DOWNLOAD_ID_HARMONIZE_CT,
    DOWNLOAD_ID_HARMONIZE_MR,
    DOWNLOAD_ID_OCR,
    AiFeatureId,
    AiFeatureSpec,
    AiModelGroupId,
    AiModelGroupSpec,
    download_kind,
    download_ocr,
    feature_description,
    feature_summary,
    feature_title,
    install_registry,
    remove_kind,
    remove_ocr,
)

logger = logging.getLogger(__name__)

_BRAIN_STRUCTURES_TASK_ID = 409
_CT_1_5_PARTS = (291, 292, 293, 294, 295)
_MR_1_5_PARTS = (850, 851)
_CT_1_5_PART_N: dict[int, int] = {291: 1, 292: 2, 293: 3, 294: 4, 295: 5}
_MR_1_5_PART_N: dict[int, int] = {850: 1, 851: 2}
_FRIENDLY_TASK_LABELS: dict[int, str] = {
    297: "CT anatomy 3 mm",
    298: "CT crop / 6 mm",
    303: "CT face 1.5 mm",
    409: "CT brain structures 0.5×0.5×1 mm",
    776: "CT contrast (head/neck)",
    852: "MR anatomy 3 mm",
    853: "MR anatomy 6 mm",
    856: "MR face 1.5 mm",
}


# --- Readiness gates ---


def pixel_phi_allowed() -> bool:
    return ocr_models_ready()


def harmonize_allowed() -> bool:
    """True when TotalSegmentator can run Harmonize for any installed CT or MR pack."""
    if not totalsegmentator_available():
        return False
    if installed_mr_segmentation_modes():
        return True
    return bool(installed_ct_segmentation_modes()) and xgboost_available()


def harmonize_allowed_for_modality(modality: object | None) -> bool:
    """True when Harmonize models for ``modality`` are installed and runnable."""
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


# --- Model presence / needs-download ---


def _download_in_progress(download_id: str) -> bool:
    return get_model_download_progress(download_id) is not None


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


# --- Status lines ---


def _segmentation_mode_short_label(mode: object | None) -> str:
    return {
        "1.5mm": "1.5 mm",
        "3mm": "3 mm",
        "6mm": "6 mm",
    }[normalize_segmentation_mode(mode)]


def _harmonize_resolution_status(*, active: object | None, installed: tuple[str, ...]) -> str:
    """Compact status; dropdown already shows the active resolution."""
    active_mode = normalize_segmentation_mode(active)
    installed_modes = tuple(normalize_segmentation_mode(mode) for mode in installed)
    if not installed_modes:
        return _("Not installed.")
    if active_mode not in installed_modes:
        return _("Download selected resolution.")
    others = [_segmentation_mode_short_label(mode) for mode in installed_modes if mode != active_mode]
    if others:
        return _("Also installed: {others}.").format(others=", ".join(others))
    return ""


def ai_feature_status_remove_pixel_phi() -> str:
    ocr_status, _detail = probe_ocr_models()
    if ocr_status == OcrModelStatus.READY:
        return _("Installed.")
    if ocr_status == OcrModelStatus.DOWNLOADING:
        return _("Downloading…")
    if ocr_status == OcrModelStatus.MISSING:
        return _("Not installed.")
    if ocr_status == OcrModelStatus.FAILED:
        return _("Download failed.")
    return _("Setup required.")


def ai_feature_status_harmonize() -> str:
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if not xgboost_available():
        return _("OpenMP required (e.g. brew install libomp).")
    if _download_in_progress(DOWNLOAD_ID_HARMONIZE_CT) or _download_in_progress(DOWNLOAD_ID_HARMONIZE_MR):
        return _("Downloading…")
    return ""


def ai_feature_status_harmonize_ct() -> str:
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if not xgboost_available():
        return _("OpenMP required (e.g. brew install libomp).")
    if _download_in_progress(DOWNLOAD_ID_HARMONIZE_CT):
        return _("Downloading…")
    return _harmonize_resolution_status(
        active=get_ct_segmentation_mode(),
        installed=installed_ct_segmentation_modes(),
    )


def ai_feature_status_harmonize_mr() -> str:
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if _download_in_progress(DOWNLOAD_ID_HARMONIZE_MR):
        return _("Downloading…")
    return _harmonize_resolution_status(
        active=get_mr_segmentation_mode(),
        installed=installed_mr_segmentation_modes(),
    )


def ai_feature_status_brain_structures() -> str:
    if brain_structures_has_models():
        return _("Installed (0.5×0.5×1 mm).")
    if _download_in_progress(DOWNLOAD_ID_BRAIN):
        return _("Downloading…")
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if not face_license_available():
        return _("Academic license required.")
    return _("Not installed.")


def ai_feature_status_face_blur() -> str:
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if not face_license_available():
        return _("Academic license required.")
    if _download_in_progress(DOWNLOAD_ID_FACE_CT) or _download_in_progress(DOWNLOAD_ID_FACE_MR):
        return _("Downloading…")
    return ""


def _face_modality_status(*, ready: bool, downloading: bool) -> str:
    if not totalsegmentator_available():
        return _("TotalSegmentator unavailable.")
    if not face_license_available():
        return _("Academic license required.")
    if downloading:
        return _("Downloading…")
    if ready:
        return _("Installed (1.5 mm).")
    return _("Not installed.")


def ai_feature_status_face_ct() -> str:
    return _face_modality_status(
        ready=face_ct_has_models(),
        downloading=_download_in_progress(DOWNLOAD_ID_FACE_CT),
    )


def ai_feature_status_face_mr() -> str:
    return _face_modality_status(
        ready=face_mr_has_models(),
        downloading=_download_in_progress(DOWNLOAD_ID_FACE_MR),
    )


# --- Inventory / labels ---


def friendly_task_label(task_id: int) -> str:
    """User-facing label for one TotalSegmentator weight pack."""
    if task_id in _CT_1_5_PART_N:
        return _("CT anatomy 1.5 mm (part {n}/5)").format(n=_CT_1_5_PART_N[task_id])
    if task_id in _MR_1_5_PART_N:
        return _("MR anatomy 1.5 mm (part {n}/2)").format(n=_MR_1_5_PART_N[task_id])
    msgid = _FRIENDLY_TASK_LABELS.get(task_id)
    if msgid is None:
        return _("Model {task_id}").format(task_id=task_id)
    return _(msgid)


def collapse_inventory_labels(ready_task_ids: tuple[int, ...] | list[int]) -> tuple[str, ...]:
    """Map ready task IDs to inventory lines, collapsing multi-part packs."""
    ready = set(ready_task_ids)
    labels: list[str] = []
    consumed: set[int] = set()

    if set(_CT_1_5_PARTS).issubset(ready):
        labels.append(_("CT anatomy 1.5 mm (parts 1–5)"))
        consumed.update(_CT_1_5_PARTS)
    if set(_MR_1_5_PARTS).issubset(ready):
        labels.append(_("MR anatomy 1.5 mm (parts 1–2)"))
        consumed.update(_MR_1_5_PARTS)

    for task_id in sorted(ready):
        if task_id in consumed:
            continue
        labels.append(friendly_task_label(task_id))
    return tuple(labels)


def _ready_harmonize_ct_task_ids() -> tuple[int, ...]:
    missing = set(missing_harmonize_ts_task_ids())
    return tuple(task_id for task_id in harmonize_ts_task_ids() if task_id not in missing)


def _ready_harmonize_mr_task_ids() -> tuple[int, ...]:
    missing = set(missing_mr_anatomy_task_ids())
    return tuple(task_id for task_id in mr_anatomy_task_ids() if task_id not in missing)


def installed_task_ids(group: AiModelGroupId) -> tuple[int, ...]:
    """Return on-disk TotalSegmentator task IDs for ``group`` (empty for OCR)."""
    if group == AiModelGroupId.HARMONIZE_CT:
        return _ready_harmonize_ct_task_ids()
    if group == AiModelGroupId.HARMONIZE_MR:
        return _ready_harmonize_mr_task_ids()
    if group == AiModelGroupId.FACE_CT:
        return face_task_ids() if ct_face_models_ready() else ()
    if group == AiModelGroupId.FACE_MR:
        return mr_face_task_ids() if mr_face_models_ready() else ()
    if group == AiModelGroupId.BRAIN_STRUCTURES:
        return (_BRAIN_STRUCTURES_TASK_ID,) if brain_structures_ready() else ()
    return ()


def installed_model_inventory(group: AiModelGroupId) -> tuple[str, ...]:
    """Friendly inventory lines for models currently installed for ``group``."""
    if group == AiModelGroupId.OCR:
        return (_("OCR models"),) if ocr_models_ready() else ()
    task_ids = installed_task_ids(group)
    if not task_ids:
        return ()
    if group in {AiModelGroupId.FACE_CT, AiModelGroupId.FACE_MR, AiModelGroupId.BRAIN_STRUCTURES}:
        return tuple(friendly_task_label(task_id) for task_id in task_ids)
    return collapse_inventory_labels(task_ids)


def format_installed_inventory_status(
    group: AiModelGroupId,
    *,
    resolution_line: str = "",
) -> str:
    """Build the Installed status block for a model group (resolution + bullet inventory)."""
    inventory = installed_model_inventory(group)
    if not inventory:
        return ""
    lines: list[str] = []
    if resolution_line:
        lines.append(resolution_line)
    if group == AiModelGroupId.OCR:
        return _("Installed. Test in Series View before batch use.")
    if group in {AiModelGroupId.FACE_CT, AiModelGroupId.FACE_MR}:
        return _("Installed: 1.5 mm.")
    if group == AiModelGroupId.BRAIN_STRUCTURES:
        return _("Installed: 0.5×0.5×1 mm.")
    if not resolution_line:
        lines.append(_("Installed."))
    for item in inventory:
        lines.append(f"• {item}")
    return "\n".join(lines)


# --- Segmentation mode menus ---


def segmentation_mode_menu_values() -> tuple[str, ...]:
    return (_("1.5 mm"), _("3 mm"), _("6 mm"))


def segmentation_mode_menu_label(mode: object | None) -> str:
    return _(_segmentation_mode_short_label(mode))


def segmentation_mode_from_menu_label(label: object | None) -> SegmentationMode:
    text = str(label or "").strip().lower()
    if text.startswith("1.5"):
        return "1.5mm"
    if text.startswith("6"):
        return "6mm"
    if text.startswith("3"):
        return "3mm"
    return DEFAULT_SEGMENTATION_MODE  # type: ignore[return-value]


def default_installed_segmentation_mode(modes: tuple[str, ...] | list[str]) -> SegmentationMode:
    """Prefer 3 mm when installed; otherwise the first installed mode."""
    normalized = tuple(normalize_segmentation_mode(mode) for mode in modes)
    if "3mm" in normalized:
        return "3mm"  # type: ignore[return-value]
    if normalized:
        return normalized[0]
    return DEFAULT_SEGMENTATION_MODE  # type: ignore[return-value]


def installed_segmentation_mode_menu_values(modes: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(segmentation_mode_menu_label(mode) for mode in modes)


# --- License UX ---


def face_license_request_instructions() -> str:
    return _("Free academic license (aca_…) from {url}").format(url=ts_academic_license_url())


def validate_face_license_format(license_number: str) -> str | None:
    """Return a translated error when format is invalid, else None."""
    normalized = license_number.strip()
    if not normalized:
        return _("Enter your academic license number (aca_...).")
    if not normalized.startswith("aca_"):
        return _("License number must start with aca_.")
    if len(normalized) != 18:
        return _("License number must be exactly 18 characters (aca_ plus 14 characters).")
    return None


# --- Download manager ---


@dataclass(frozen=True)
class DownloadCompleteEvent:
    download_id: str
    result: object
    error: BaseException | None = None


class AiFeatureDownloadManager:
    """Ensure only one model download runs; OCR and TotalSegmentator share this path."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pending_download_id: str | None = None

    @property
    def pending_download_id(self) -> str | None:
        return self._pending_download_id

    def busy(self) -> bool:
        if any_model_download_active():
            return True
        thread = self._thread
        return thread is not None and thread.is_alive()

    def is_in_progress(self, download_id: str) -> bool:
        if is_model_download_active(download_id):
            return True
        return self._pending_download_id == download_id

    def start(
        self,
        download_id: str,
        worker: Callable[[], object],
        *,
        on_complete: Callable[[DownloadCompleteEvent], None],
        preparing_message: str = "Preparing model download…",
    ) -> bool:
        """Start a download if idle. Returns False when another download is already running."""
        with self._lock:
            if self.busy():
                logger.info("AI Features: download already in progress (requested %s)", download_id)
                return False
            self._pending_download_id = download_id
            begin_model_download(download_id, message=preparing_message)

            def run() -> None:
                result: object = None
                error: BaseException | None = None
                try:
                    result = worker()
                except BaseException as exc:
                    logger.exception("AI Features: download worker failed for %s", download_id)
                    error = exc
                on_complete(DownloadCompleteEvent(download_id=download_id, result=result, error=error))

            self._thread = threading.Thread(target=run, name=f"AiFeatureDownload-{download_id}", daemon=True)
            self._thread.start()
            return True

    def clear_pending(self, download_id: str) -> None:
        """Clear pending state and storage progress after the UI drains completion."""
        with self._lock:
            if self._pending_download_id == download_id:
                self._pending_download_id = None
            self._thread = None
        end_model_download(download_id)


_manager: AiFeatureDownloadManager | None = None


def get_download_manager() -> AiFeatureDownloadManager:
    global _manager
    if _manager is None:
        _manager = AiFeatureDownloadManager()
    return _manager


def _install_feature_registry() -> None:
    model_groups = {
        AiModelGroupId.OCR: AiModelGroupSpec(
            id=AiModelGroupId.OCR,
            download_id=DOWNLOAD_ID_OCR,
            title=partial(feature_title, AiFeatureId.REMOVE_PIXEL_PHI.value),
            summary=partial(feature_summary, AiFeatureId.REMOVE_PIXEL_PHI.value),
            status=ai_feature_status_remove_pixel_phi,
            needs_download=remove_pixel_phi_needs_download,
            has_models=remove_pixel_phi_has_models,
            download=download_ocr,
            remove=remove_ocr,
        ),
        AiModelGroupId.HARMONIZE_CT: AiModelGroupSpec(
            id=AiModelGroupId.HARMONIZE_CT,
            download_id=DOWNLOAD_ID_HARMONIZE_CT,
            title=partial(feature_title, AiModelGroupId.HARMONIZE_CT.value),
            summary=partial(feature_summary, AiModelGroupId.HARMONIZE_CT.value),
            status=ai_feature_status_harmonize_ct,
            needs_download=harmonize_ct_needs_download,
            has_models=harmonize_ct_has_models,
            download=lambda: download_kind(TsWeightKind.ANATOMY),
            remove=lambda: remove_kind(TsWeightKind.ANATOMY),
            has_resolution_picker=True,
        ),
        AiModelGroupId.HARMONIZE_MR: AiModelGroupSpec(
            id=AiModelGroupId.HARMONIZE_MR,
            download_id=DOWNLOAD_ID_HARMONIZE_MR,
            title=partial(feature_title, AiModelGroupId.HARMONIZE_MR.value),
            summary=partial(feature_summary, AiModelGroupId.HARMONIZE_MR.value),
            status=ai_feature_status_harmonize_mr,
            needs_download=harmonize_mr_needs_download,
            has_models=harmonize_mr_has_models,
            download=lambda: download_kind(TsWeightKind.ANATOMY_MR),
            remove=lambda: remove_kind(TsWeightKind.ANATOMY_MR),
            has_resolution_picker=True,
        ),
        AiModelGroupId.BRAIN_STRUCTURES: AiModelGroupSpec(
            id=AiModelGroupId.BRAIN_STRUCTURES,
            download_id=DOWNLOAD_ID_BRAIN,
            title=partial(feature_title, AiFeatureId.BRAIN_STRUCTURES.value),
            summary=partial(feature_summary, AiFeatureId.BRAIN_STRUCTURES.value),
            status=ai_feature_status_brain_structures,
            needs_download=brain_structures_needs_download,
            has_models=brain_structures_has_models,
            download=lambda: download_kind(TsWeightKind.BRAIN_STRUCTURES),
            remove=lambda: remove_kind(TsWeightKind.BRAIN_STRUCTURES),
        ),
        AiModelGroupId.FACE_CT: AiModelGroupSpec(
            id=AiModelGroupId.FACE_CT,
            download_id=DOWNLOAD_ID_FACE_CT,
            title=partial(feature_title, AiModelGroupId.FACE_CT.value),
            summary=partial(feature_summary, AiModelGroupId.FACE_CT.value),
            status=ai_feature_status_face_ct,
            needs_download=face_ct_needs_download,
            has_models=face_ct_has_models,
            download=lambda: download_kind(TsWeightKind.FACE),
            remove=lambda: remove_kind(TsWeightKind.FACE),
        ),
        AiModelGroupId.FACE_MR: AiModelGroupSpec(
            id=AiModelGroupId.FACE_MR,
            download_id=DOWNLOAD_ID_FACE_MR,
            title=partial(feature_title, AiModelGroupId.FACE_MR.value),
            summary=partial(feature_summary, AiModelGroupId.FACE_MR.value),
            status=ai_feature_status_face_mr,
            needs_download=face_mr_needs_download,
            has_models=face_mr_has_models,
            download=lambda: download_kind(TsWeightKind.FACE_MR),
            remove=lambda: remove_kind(TsWeightKind.FACE_MR),
        ),
    }
    features = {
        AiFeatureId.REMOVE_PIXEL_PHI: AiFeatureSpec(
            id=AiFeatureId.REMOVE_PIXEL_PHI,
            title=partial(feature_title, AiFeatureId.REMOVE_PIXEL_PHI.value),
            description=partial(feature_description, AiFeatureId.REMOVE_PIXEL_PHI.value),
            summary=partial(feature_summary, AiFeatureId.REMOVE_PIXEL_PHI.value),
            status=ai_feature_status_remove_pixel_phi,
            model_group_ids=(AiModelGroupId.OCR,),
        ),
        AiFeatureId.HARMONIZE: AiFeatureSpec(
            id=AiFeatureId.HARMONIZE,
            title=partial(feature_title, AiFeatureId.HARMONIZE.value),
            description=partial(feature_description, AiFeatureId.HARMONIZE.value),
            summary=partial(feature_summary, AiFeatureId.HARMONIZE.value),
            status=ai_feature_status_harmonize,
            model_group_ids=(AiModelGroupId.HARMONIZE_CT, AiModelGroupId.HARMONIZE_MR),
        ),
        AiFeatureId.BRAIN_STRUCTURES: AiFeatureSpec(
            id=AiFeatureId.BRAIN_STRUCTURES,
            title=partial(feature_title, AiFeatureId.BRAIN_STRUCTURES.value),
            description=partial(feature_description, AiFeatureId.BRAIN_STRUCTURES.value),
            summary=partial(feature_summary, AiFeatureId.BRAIN_STRUCTURES.value),
            status=ai_feature_status_brain_structures,
            model_group_ids=(AiModelGroupId.BRAIN_STRUCTURES,),
        ),
        AiFeatureId.FACE_BLUR: AiFeatureSpec(
            id=AiFeatureId.FACE_BLUR,
            title=partial(feature_title, AiFeatureId.FACE_BLUR.value),
            description=partial(feature_description, AiFeatureId.FACE_BLUR.value),
            summary=partial(feature_summary, AiFeatureId.FACE_BLUR.value),
            status=ai_feature_status_face_blur,
            model_group_ids=(AiModelGroupId.FACE_CT, AiModelGroupId.FACE_MR),
        ),
    }
    install_registry(model_groups, features)


_install_feature_registry()
