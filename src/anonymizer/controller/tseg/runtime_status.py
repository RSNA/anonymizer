"""TotalSegmentator runtime readiness: packages, libomp, license, segmentation models."""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable

from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

_TSEG_INSTALL_HINT = "pip install rsna-anonymizer"
_TS_ACADEMIC_LICENSE_URL = "https://backend.totalsegmentator.com/license-academic/"
_CHECKPOINT_NAME = "checkpoint_final.pth"
_PLANS = "nnUNetPlans"
_MODEL = "3d_fullres"

_status_lock = threading.Lock()
_cached_status: TsegRuntimeStatus | None = None
_weight_overrides: dict[TsWeightKind, TsWeightState] = {}


@dataclass
class AiFeatureSession:
    """In-memory AI feature toggles for the current application session (not persisted)."""

    remove_pixel_phi: bool = False
    enable_harmonize: bool = False
    enable_face_blur: bool = False


_ai_session = AiFeatureSession()


def get_ai_session() -> AiFeatureSession:
    return _ai_session


def set_ai_session(
    *,
    remove_pixel_phi: bool | None = None,
    enable_harmonize: bool | None = None,
    enable_face_blur: bool | None = None,
) -> AiFeatureSession:
    if remove_pixel_phi is not None:
        _ai_session.remove_pixel_phi = remove_pixel_phi
    if enable_harmonize is not None:
        _ai_session.enable_harmonize = enable_harmonize
    if enable_face_blur is not None:
        _ai_session.enable_face_blur = enable_face_blur
    return _ai_session


def init_ai_session_from_runtime(*, force_refresh: bool = False) -> AiFeatureSession:
    """Enable session flags for features whose models are already on disk (not persisted)."""
    from anonymizer.controller.remove_pixel_phi import ocr_models_ready

    status = get_runtime_status(force_refresh=force_refresh)
    return set_ai_session(
        remove_pixel_phi=ocr_models_ready(),
        enable_harmonize=(status.harmonize_ready and status.anatomy_weights.status == TsWeightStatus.READY),
        enable_face_blur=(status.face_blur_ready and status.face_weights.status == TsWeightStatus.READY),
    )


class TsWeightKind(StrEnum):
    ANATOMY = "anatomy"
    FACE = "face"


class TsWeightStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class TsWeightState:
    kind: TsWeightKind
    status: TsWeightStatus
    task_id: int | None
    model_folder: Path | None
    detail: str = ""


@dataclass(frozen=True)
class TsegRuntimeStatus:
    totalsegmentator_available: bool
    xgboost_available: bool
    face_license_available: bool
    anatomy_weights: TsWeightState
    face_weights: TsWeightState
    harmonize_ready: bool
    face_blur_ready: bool
    messages: dict[str, str]


class TsegSetupRowKind(StrEnum):
    PACKAGE = "package"
    OPENMP = "openmp"
    LICENSE = "license"
    OCR_MODEL = "ocr_model"
    ANATOMY_MODEL = "anatomy_model"
    FACE_MODEL = "face_model"


@dataclass(frozen=True)
class TsegSetupRow:
    kind: TsegSetupRowKind
    title: str
    icon: str
    status_line: str
    fix_line: str
    download_kind: TsWeightKind | None = None
    download_enabled: bool = False
    ocr_download: bool = False


def tseg_install_hint() -> str:
    return _TSEG_INSTALL_HINT


def ts_academic_license_url() -> str:
    return _TS_ACADEMIC_LICENSE_URL


def face_license_request_instructions() -> str:
    return _(
        "Request a free academic license at {url} using your institutional email "
        "(university or hospital address). TotalSegmentator will email your aca_... license key."
    ).format(url=_TS_ACADEMIC_LICENSE_URL)


def openmp_setup_command() -> str:
    if sys.platform == "darwin":
        return "brew install libomp"
    if sys.platform.startswith("win"):
        return "Install Microsoft Visual C++ Redistributable (x64)"
    return "sudo apt install libgomp1"


def face_license_setup_command() -> str:
    return "totalseg_set_license -l aca_..."


def get_stored_face_license() -> str:
    """Return the license number stored in TotalSegmentator config, if any."""
    if not _totalsegmentator_import_ok():
        return ""
    try:
        from totalsegmentator.config import get_license_number

        return (get_license_number() or "").strip()
    except Exception:
        return ""


def validate_face_license_format(license_number: str) -> str | None:
    """Return an error message when format is invalid, else None."""
    normalized = license_number.strip()
    if not normalized:
        return _("Enter your academic license number (aca_...).")
    if not normalized.startswith("aca_"):
        return _("License number must start with aca_.")
    if len(normalized) != 18:
        return _("License number must be exactly 18 characters (aca_ plus 14 characters).")
    return None


def apply_face_license(license_number: str) -> tuple[bool, str]:
    """
    Validate and store a TotalSegmentator academic license in the local TS config.

    Uses online validation when network is available (same as totalseg_set_license).
    """
    format_error = validate_face_license_format(license_number)
    if format_error is not None:
        return False, format_error
    normalized = license_number.strip()

    if not _totalsegmentator_import_ok():
        return False, _("TotalSegmentator not installed. Install with: {hint}").format(hint=_TSEG_INSTALL_HINT)

    try:
        import json

        from totalsegmentator.config import get_totalseg_dir, is_valid_license, setup_totalseg
    except ImportError as exc:
        return False, _("TotalSegmentator license setup unavailable: {error}").format(error=exc)

    setup_totalseg()
    config_path = get_totalseg_dir() / "config.json"
    if not config_path.is_file():
        import json

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "totalseg_id": "anonymizer",
                    "send_usage_stats": True,
                    "prediction_counter": 0,
                },
                indent=4,
            ),
            encoding="utf-8",
        )

    try:
        online_valid = is_valid_license(normalized)
    except Exception as exc:
        logger.warning("Online license validation failed: %s", exc)
        return False, _(
            "Could not validate license online ({error}). Check your network connection and try again."
        ).format(error=exc)

    if not online_valid:
        return False, _("Invalid license number. Check the value or request a free academic license at {url}").format(
            url=_TS_ACADEMIC_LICENSE_URL
        )

    try:
        with config_path.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except OSError as exc:
        return False, _("Could not read TotalSegmentator config: {error}").format(error=exc)

    config["license_number"] = normalized
    try:
        with config_path.open("w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=4)
    except OSError as exc:
        return False, _("Could not save TotalSegmentator config: {error}").format(error=exc)

    get_runtime_status(force_refresh=True)
    licensed, message = verify_face_license()
    if licensed:
        return True, _("Academic license saved.")
    return False, message


def _model_download_status_line(state: TsWeightState) -> str:
    if state.status == TsWeightStatus.READY:
        return "Downloaded"
    if state.status == TsWeightStatus.MISSING:
        return f"Not downloaded ({state.detail})"
    if state.status == TsWeightStatus.DOWNLOADING:
        return "Downloading…"
    if state.status == TsWeightStatus.FAILED:
        return f"Download failed — {state.detail}"
    return state.detail or "Unavailable until TotalSegmentator is installed"


def _model_download_enabled(state: TsWeightState, *, prerequisite_ok: bool) -> bool:
    if not prerequisite_ok:
        return False
    return state.status in {TsWeightStatus.MISSING, TsWeightStatus.FAILED}


def build_tseg_setup_rows(status: TsegRuntimeStatus) -> list[TsegSetupRow]:
    """Build checklist rows for the TotalSegmentator setup dialog (all AI features)."""
    return build_ai_setup_rows(
        status,
        enable_ocr=True,
        enable_harmonize=True,
        enable_face_blur=True,
    )


def build_ai_setup_rows(
    status: TsegRuntimeStatus,
    *,
    enable_ocr: bool,
    enable_harmonize: bool,
    enable_face_blur: bool,
) -> list[TsegSetupRow]:
    """Build checklist rows filtered by project AI feature enable flags."""
    rows: list[TsegSetupRow] = []
    needs_tseg = enable_harmonize or enable_face_blur

    if enable_ocr:
        from anonymizer.controller.remove_pixel_phi import OcrModelStatus, probe_ocr_models

        ocr_status, ocr_detail = probe_ocr_models()
        if ocr_status == OcrModelStatus.READY:
            ocr_icon, ocr_line, ocr_fix = "✓", "Downloaded", ""
            ocr_dl = False
        elif ocr_status == OcrModelStatus.DOWNLOADING:
            ocr_icon, ocr_line, ocr_fix = "…", "Downloading…", ""
            ocr_dl = False
        else:
            ocr_icon, ocr_line, ocr_fix = "○", ocr_detail, "Download OCR models for pixel PHI removal"
            ocr_dl = ocr_status in {OcrModelStatus.MISSING, OcrModelStatus.FAILED}
        rows.append(
            TsegSetupRow(
                kind=TsegSetupRowKind.OCR_MODEL,
                title="OCR models (Remove Pixel PHI)",
                icon=ocr_icon,
                status_line=ocr_line,
                fix_line=ocr_fix,
                ocr_download=ocr_dl,
            )
        )

    if not needs_tseg:
        return rows

    tseg_rows = _build_tseg_core_rows(status, enable_harmonize=enable_harmonize, enable_face_blur=enable_face_blur)
    rows.extend(tseg_rows)
    return rows


def _build_tseg_core_rows(
    status: TsegRuntimeStatus,
    *,
    enable_harmonize: bool,
    enable_face_blur: bool,
) -> list[TsegSetupRow]:
    """Build TotalSegmentator package, OpenMP, license, and segmentation model rows."""
    rows: list[TsegSetupRow] = []

    if status.totalsegmentator_available:
        package_icon = "✓"
        package_status = "Installed"
        package_fix = ""
    else:
        package_icon = "○"
        package_status = "Not installed"
        package_fix = status.messages.get("packages", tseg_install_hint())

    rows.append(
        TsegSetupRow(
            kind=TsegSetupRowKind.PACKAGE,
            title="TotalSegmentator package",
            icon=package_icon,
            status_line=package_status,
            fix_line=package_fix,
        )
    )

    if enable_harmonize:
        if not status.totalsegmentator_available:
            openmp_icon = "○"
            openmp_status = "Waiting for TotalSegmentator package"
            openmp_fix = tseg_install_hint()
        elif status.xgboost_available:
            openmp_icon = "✓"
            openmp_status = "XGBoost and OpenMP runtime OK"
            openmp_fix = ""
        else:
            openmp_icon = "○"
            openmp_status = "XGBoost or OpenMP runtime missing (required for Harmonize contrast)"
            openmp_fix = status.messages.get("xgboost", openmp_setup_command())

        rows.append(
            TsegSetupRow(
                kind=TsegSetupRowKind.OPENMP,
                title="OpenMP / XGBoost (Harmonize contrast)",
                icon=openmp_icon,
                status_line=openmp_status,
                fix_line=openmp_fix,
            )
        )

    if enable_face_blur:
        if not status.totalsegmentator_available:
            license_icon = "○"
            license_status = "Waiting for TotalSegmentator package"
            license_fix = tseg_install_hint()
        elif status.face_license_available:
            license_icon = "✓"
            license_status = "Academic license valid"
            license_fix = ""
        else:
            license_icon = "○"
            license_status = "Academic license not configured (required for Face Blur)"
            license_fix = f"Request a free license: {ts_academic_license_url()}\nEnter your aca_... license below."
            extra = status.messages.get("face_license", "")
            if extra and "not configured" not in extra.lower():
                license_fix = f"{license_fix}\n{extra}"

        rows.append(
            TsegSetupRow(
                kind=TsegSetupRowKind.LICENSE,
                title="TotalSegmentator face license",
                icon=license_icon,
                status_line=license_status,
                fix_line=license_fix,
            )
        )

    if enable_harmonize:
        anatomy_icon = "✓" if status.anatomy_weights.status == TsWeightStatus.READY else "○"
        if status.anatomy_weights.status == TsWeightStatus.DOWNLOADING:
            anatomy_icon = "…"
        elif status.anatomy_weights.status == TsWeightStatus.FAILED:
            anatomy_icon = "!"

        rows.append(
            TsegSetupRow(
                kind=TsegSetupRowKind.ANATOMY_MODEL,
                title="Anatomy segmentation model",
                icon=anatomy_icon,
                status_line=_model_download_status_line(status.anatomy_weights),
                fix_line="" if status.anatomy_weights.status == TsWeightStatus.READY else status.anatomy_weights.detail,
                download_kind=TsWeightKind.ANATOMY,
                download_enabled=_model_download_enabled(
                    status.anatomy_weights,
                    prerequisite_ok=status.totalsegmentator_available,
                ),
            )
        )

    if enable_face_blur:
        face_icon = "✓" if status.face_weights.status == TsWeightStatus.READY else "○"
        if status.face_weights.status == TsWeightStatus.DOWNLOADING:
            face_icon = "…"
        elif status.face_weights.status == TsWeightStatus.FAILED:
            face_icon = "!"

        rows.append(
            TsegSetupRow(
                kind=TsegSetupRowKind.FACE_MODEL,
                title="Face segmentation model",
                icon=face_icon,
                status_line=_model_download_status_line(status.face_weights),
                fix_line="" if status.face_weights.status == TsWeightStatus.READY else status.face_weights.detail,
                download_kind=TsWeightKind.FACE,
                download_enabled=_model_download_enabled(
                    status.face_weights,
                    prerequisite_ok=status.face_license_available,
                ),
            )
        )

    return rows


def _anatomy_task_spec() -> tuple[int, str] | None:
    from anonymizer.controller.tseg.model_cache import harmonize_anatomy_task_ids, trainer_for_anatomy_task

    task_ids = harmonize_anatomy_task_ids()
    if not task_ids:
        return None
    return task_ids[0], trainer_for_anatomy_task(task_ids[0])


def _face_task_spec() -> tuple[int, str]:
    return 303, "nnUNetTrainerNoMirroring"


def _anatomy_missing_detail(missing_task_ids: tuple[int, ...]) -> str:
    if len(missing_task_ids) == 1:
        task_id = missing_task_ids[0]
        if task_id == 776:
            return "Task 776 (head/neck contrast) not downloaded (~230 MB)"
        return f"Task {task_id} not downloaded (~400 MB)"
    joined = ", ".join(str(task_id) for task_id in missing_task_ids)
    return f"Tasks {joined} not downloaded"


def _weight_detail(kind: TsWeightKind) -> str:
    if kind == TsWeightKind.ANATOMY:
        return "~400 MB per model; first Harmonize run will download if not prefetched"
    return "Licensed task; first Face Blur run will download if not prefetched"


def _totalsegmentator_import_ok() -> bool:
    """
    Return whether the TotalSegmentator Python package is installed and importable.

    Uses distribution metadata plus an import probe that skips cwd (sys.path[0]==""),
    because main() chdirs to install_dir and a stray totalsegmentator/ tree there would
    otherwise shadow the venv package.
    """
    import importlib
    import importlib.metadata as md
    import importlib.util

    try:
        md.version("totalsegmentator")
    except md.PackageNotFoundError:
        return False

    saved_path = sys.path
    try:
        sys.path = [entry for entry in sys.path if entry not in ("", ".")]
        spec = importlib.util.find_spec("totalsegmentator")
        if spec is None or spec.loader is None:
            return False
        importlib.import_module("totalsegmentator")
    except ImportError as exc:
        logger.debug("TotalSegmentator import check failed: %s", exc)
        return False
    finally:
        sys.path = saved_path
    return True


def _xgboost_import_ok() -> tuple[bool, str]:
    try:
        from anonymizer.controller.tseg.contrast import verify_xgboost_runtime

        verify_xgboost_runtime()
    except RuntimeError as exc:
        return False, str(exc)
    except ImportError:
        return False, f"XGBoost not installed. Install with: {_TSEG_INSTALL_HINT}"
    return True, ""


def verify_face_license() -> tuple[bool, str]:
    """Return whether TotalSegmentator academic license is configured and valid."""
    if not _totalsegmentator_import_ok():
        return False, f"TotalSegmentator not installed. Install with: {_TSEG_INSTALL_HINT}"
    try:
        from totalsegmentator.config import has_valid_license_offline
    except ImportError as exc:
        return False, f"TotalSegmentator license check unavailable: {exc}"
    try:
        valid, message = has_valid_license_offline()
    except Exception as exc:
        return False, f"License check failed: {exc}"
    if valid == "yes":
        return True, message
    return False, message


def _resolve_model_folder(task_id: int, trainer: str) -> Path | None:
    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
        from totalsegmentator.nnunet import get_output_folder

        setup_nnunet()
        setup_totalseg()
        return Path(get_output_folder(task_id, trainer, _PLANS, _MODEL))
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("TS weight folder lookup failed for task %s: %s", task_id, exc)
        return None


def _checkpoint_ready(model_folder: Path | None) -> bool:
    if model_folder is None:
        return False
    root_checkpoint = model_folder / _CHECKPOINT_NAME
    if root_checkpoint.is_file():
        return True
    fold_checkpoint = model_folder / "fold_0" / _CHECKPOINT_NAME
    if fold_checkpoint.is_file():
        return True
    return any(model_folder.glob(f"fold_*/{_CHECKPOINT_NAME}"))


def probe_weight_state(kind: TsWeightKind) -> TsWeightState:
    """Inspect on-disk segmentation model cache without downloading."""
    if not _totalsegmentator_import_ok():
        return TsWeightState(
            kind=kind,
            status=TsWeightStatus.UNAVAILABLE,
            task_id=None,
            model_folder=None,
            detail=f"Install with: {_TSEG_INSTALL_HINT}",
        )

    if kind == TsWeightKind.ANATOMY:
        from anonymizer.controller.tseg.model_cache import (
            harmonize_anatomy_task_ids,
            harmonize_ts_task_ids,
            missing_harmonize_ts_task_ids,
            resolve_harmonize_model_folder,
        )

        task_ids = harmonize_ts_task_ids()
        if not task_ids:
            return TsWeightState(
                kind=kind,
                status=TsWeightStatus.UNAVAILABLE,
                task_id=None,
                model_folder=None,
                detail="Anatomy segmentation preload not supported for 1.5mm mode",
            )
        anatomy_task_ids = harmonize_anatomy_task_ids()
        primary_task_id = anatomy_task_ids[0] if anatomy_task_ids else task_ids[0]
        primary_folder = resolve_harmonize_model_folder(primary_task_id)
        missing = missing_harmonize_ts_task_ids()
        if not missing:
            return TsWeightState(
                kind=kind,
                status=TsWeightStatus.READY,
                task_id=primary_task_id,
                model_folder=primary_folder,
            )
        return TsWeightState(
            kind=kind,
            status=TsWeightStatus.MISSING,
            task_id=primary_task_id,
            model_folder=primary_folder,
            detail=_anatomy_missing_detail(missing),
        )

    task_id, trainer = _face_task_spec()
    model_folder = _resolve_model_folder(task_id, trainer)
    if _checkpoint_ready(model_folder):
        return TsWeightState(
            kind=kind,
            status=TsWeightStatus.READY,
            task_id=task_id,
            model_folder=model_folder,
        )
    return TsWeightState(
        kind=kind,
        status=TsWeightStatus.MISSING,
        task_id=task_id,
        model_folder=model_folder,
        detail=_weight_detail(kind),
    )


def _merge_weight_state(kind: TsWeightKind, probed: TsWeightState) -> TsWeightState:
    with _status_lock:
        override = _weight_overrides.get(kind)
    if override is not None:
        return override
    return probed


def set_weight_state(state: TsWeightState) -> None:
    global _cached_status
    with _status_lock:
        if state.status in {TsWeightStatus.DOWNLOADING, TsWeightStatus.FAILED}:
            _weight_overrides[state.kind] = state
        else:
            _weight_overrides.pop(state.kind, None)
        _cached_status = None


def clear_weight_override(kind: TsWeightKind) -> None:
    with _status_lock:
        _weight_overrides.pop(kind, None)
        global _cached_status
        _cached_status = None


def update_weight_download_detail(kind: TsWeightKind, detail: str) -> None:
    """Update in-flight download detail text for one segmentation model kind."""
    global _cached_status
    with _status_lock:
        override = _weight_overrides.get(kind)
        if override is None or override.status != TsWeightStatus.DOWNLOADING:
            return
        _weight_overrides[kind] = TsWeightState(
            kind=kind,
            status=TsWeightStatus.DOWNLOADING,
            task_id=override.task_id,
            model_folder=override.model_folder,
            detail=detail,
        )
        _cached_status = None


def refresh_weight_status(kind: TsWeightKind) -> TsWeightState:
    """Re-probe disk state, clear download override, and refresh the runtime cache."""
    clear_weight_override(kind)
    state = probe_weight_state(kind)
    get_runtime_status(force_refresh=True)
    return state


def probe_runtime_status() -> TsegRuntimeStatus:
    totalsegmentator_available = _totalsegmentator_import_ok()
    xgboost_available = False
    face_license_available = False
    messages: dict[str, str] = {}

    if not totalsegmentator_available:
        messages["packages"] = f"Install TotalSegmentator with: {_TSEG_INSTALL_HINT}"
    else:
        xgboost_available, xgboost_message = _xgboost_import_ok()
        if not xgboost_available:
            messages["xgboost"] = xgboost_message
        face_license_available, license_message = verify_face_license()
        if not face_license_available:
            messages["face_license"] = license_message

    anatomy_weights = _merge_weight_state(TsWeightKind.ANATOMY, probe_weight_state(TsWeightKind.ANATOMY))
    face_weights = _merge_weight_state(TsWeightKind.FACE, probe_weight_state(TsWeightKind.FACE))

    if anatomy_weights.status == TsWeightStatus.MISSING:
        messages["anatomy_weights"] = anatomy_weights.detail
    if face_weights.status == TsWeightStatus.MISSING:
        messages["face_weights"] = face_weights.detail

    harmonize_ready = totalsegmentator_available and xgboost_available
    face_blur_ready = totalsegmentator_available and face_license_available

    return TsegRuntimeStatus(
        totalsegmentator_available=totalsegmentator_available,
        xgboost_available=xgboost_available,
        face_license_available=face_license_available,
        anatomy_weights=anatomy_weights,
        face_weights=face_weights,
        harmonize_ready=harmonize_ready,
        face_blur_ready=face_blur_ready,
        messages=messages,
    )


def get_runtime_status(*, force_refresh: bool = False) -> TsegRuntimeStatus:
    global _cached_status
    if not force_refresh:
        with _status_lock:
            if _cached_status is not None:
                return _cached_status
    status = probe_runtime_status()
    with _status_lock:
        _cached_status = status
    return status


def ai_feature_title_remove_pixel_phi() -> str:
    return _("Remove Burnt-in Annotation")


def ai_feature_title_harmonize() -> str:
    return _("Harmonize")


def ai_feature_title_face_blur() -> str:
    return _("Face De-identify")


def ai_feature_description_remove_pixel_phi() -> str:
    return _("Burnt-in text overlays in pixel data (OCR-based).")


def ai_feature_description_harmonize() -> str:
    return _("CT only. Updates SeriesDescription only.")


def ai_feature_description_face_blur() -> str:
    return _("CT head studies only. Blurs the segmented face region in pixel data.")


def ai_feature_summary_remove_pixel_phi() -> str:
    return _("Removes patient identifiers burned into image pixels.")


def ai_feature_summary_harmonize() -> str:
    return _("Analyzes CT anatomy and contrast to suggest a standardized series description using the RadLex playbook.")


def ai_feature_summary_face_blur() -> str:
    return _("Segments the face on head CT and blurs it to reduce the risk of patient recognition.")


def remove_pixel_phi_has_models() -> bool:
    from anonymizer.controller.remove_pixel_phi import ocr_models_ready

    return ocr_models_ready()


def harmonize_has_models() -> bool:
    status = get_runtime_status()
    return status.anatomy_weights.status == TsWeightStatus.READY


def face_blur_has_models() -> bool:
    status = get_runtime_status()
    return status.face_weights.status == TsWeightStatus.READY


def ai_feature_status_remove_pixel_phi() -> str:
    from anonymizer.controller.remove_pixel_phi import OcrModelStatus, probe_ocr_models

    ocr_status, _detail = probe_ocr_models()
    if ocr_status == OcrModelStatus.READY:
        return _(
            "OCR models are installed. Test pixel PHI removal using Series View first "
            "to build a suitable whitelist and ensure correct operation before running batch process."
        )
    if ocr_status == OcrModelStatus.DOWNLOADING:
        return _("OCR models are downloading. This may take a few minutes.")
    if ocr_status == OcrModelStatus.MISSING:
        return _("OCR models are not installed yet. Click Download models below to set up this tool.")
    if ocr_status == OcrModelStatus.FAILED:
        return _("OCR models could not be loaded. Click Download models below to try again.")
    return _("Additional setup is required before this tool can be used.")


def remove_pixel_phi_needs_download() -> bool:
    from anonymizer.controller.remove_pixel_phi import OcrModelStatus, probe_ocr_models

    ocr_status, _ = probe_ocr_models()
    return ocr_status in {OcrModelStatus.MISSING, OcrModelStatus.FAILED}


def ai_feature_status_harmonize() -> str:
    status = get_runtime_status()
    if status.harmonize_ready and status.anatomy_weights.status == TsWeightStatus.READY:
        return _(
            "Anatomy models are installed. Harmonize from the study index (batch) or from Series View (single series)."
        )
    if status.anatomy_weights.status == TsWeightStatus.DOWNLOADING:
        return _("Anatomy segmentation models are downloading. This may take several minutes.")
    if status.anatomy_weights.status == TsWeightStatus.FAILED:
        return _("The anatomy model download did not complete. Click Download models below to try again.")
    if not status.totalsegmentator_available:
        return _("TotalSegmentator is not available in this installation, so this tool cannot run yet.")
    if not status.xgboost_available:
        return _(
            "An additional OpenMP component is required for contrast analysis. "
            "On macOS, install it with: brew install libomp"
        )
    if status.anatomy_weights.status == TsWeightStatus.MISSING:
        return _("Anatomy segmentation models are not installed yet. Click Download models below to set up this tool.")
    return _("Additional setup is required before this tool can be used.")


def harmonize_needs_download() -> bool:
    status = get_runtime_status()
    return (
        status.totalsegmentator_available
        and status.xgboost_available
        and status.anatomy_weights.status == TsWeightStatus.MISSING
    )


def ai_feature_status_face_blur() -> str:
    status = get_runtime_status()
    if status.face_blur_ready and status.face_weights.status == TsWeightStatus.READY:
        return _("Face segmentation models are installed. De-identify faces from Series View on head CT.")
    if status.face_weights.status == TsWeightStatus.DOWNLOADING:
        return _("Face segmentation models are downloading. This may take several minutes.")
    if status.face_weights.status == TsWeightStatus.FAILED:
        return _("The face model download did not complete. Click Download models below to try again.")
    if not status.totalsegmentator_available:
        return _("TotalSegmentator is not available in this installation, so this tool cannot run yet.")
    if not status.face_license_available:
        return _(
            "A free academic TotalSegmentator license is required before face models can be downloaded. "
            "See the instructions below."
        )
    if status.face_weights.status == TsWeightStatus.MISSING:
        return _("Face segmentation models are not installed yet. Click Download models below to set up this tool.")
    return _("Additional setup is required before this tool can be used.")


def face_blur_needs_license() -> bool:
    status = get_runtime_status()
    return status.totalsegmentator_available and not status.face_license_available


def face_blur_needs_download() -> bool:
    status = get_runtime_status()
    return (
        status.totalsegmentator_available
        and status.face_license_available
        and status.face_weights.status == TsWeightStatus.MISSING
    )


def harmonize_allowed() -> bool:
    """True when Harmonize is enabled for the session and runtime prerequisites are met."""
    if not _ai_session.enable_harmonize:
        return False
    status = get_runtime_status()
    return status.harmonize_ready and status.anatomy_weights.status == TsWeightStatus.READY


def face_blur_allowed() -> bool:
    """True when CT De-identify Face is enabled for the session and runtime prerequisites are met."""
    if not _ai_session.enable_face_blur:
        return False
    status = get_runtime_status()
    return status.face_blur_ready and status.face_weights.status == TsWeightStatus.READY


def pixel_phi_allowed() -> bool:
    """True when Remove Pixel PHI is enabled for the session and OCR models are ready."""
    if not _ai_session.remove_pixel_phi:
        return False
    from anonymizer.controller.remove_pixel_phi import ocr_models_ready

    return ocr_models_ready()


def any_ai_batch_feature_allowed() -> bool:
    """True when at least one AI batch algorithm is enabled and ready."""
    return pixel_phi_allowed() or harmonize_allowed() or face_blur_allowed()


def log_runtime_status_for_session() -> None:
    """Log AI feature readiness for enabled session features only."""
    status = get_runtime_status(force_refresh=True)
    if _ai_session.remove_pixel_phi:
        from anonymizer.controller.remove_pixel_phi import OcrModelStatus, probe_ocr_models

        ocr_status, ocr_detail = probe_ocr_models()
        if ocr_status == OcrModelStatus.READY:
            logger.info("Remove Pixel PHI: enabled — OCR models downloaded")
        else:
            logger.info("Remove Pixel PHI: enabled — OCR models %s", ocr_detail.lower())
    if _ai_session.enable_harmonize:
        _log_feature_status(
            feature="Harmonize",
            available=status.harmonize_ready,
            available_reason="TotalSegmentator and XGBoost (contrast) are installed",
            unavailable_message=status.messages.get(
                "xgboost",
                "XGBoost or its platform OpenMP runtime is not available",
            ),
            model_label="Anatomy segmentation model",
            model_state=status.anatomy_weights,
        )
    if _ai_session.enable_face_blur:
        _log_feature_status(
            feature="Face Blur",
            available=status.face_blur_ready,
            available_reason="TotalSegmentator academic license is valid",
            unavailable_message=status.messages.get(
                "face_license",
                "TotalSegmentator academic license is not configured",
            ),
            model_label="Face segmentation model",
            model_state=status.face_weights,
        )


def log_runtime_status() -> TsegRuntimeStatus:
    """Log a concise startup summary and return the current runtime status."""
    status = get_runtime_status(force_refresh=True)

    if not status.totalsegmentator_available:
        logger.info(
            "Harmonize unavailable: TotalSegmentator not installed (%s)",
            status.messages.get("packages", _TSEG_INSTALL_HINT),
        )
        logger.info(
            "Face Blur unavailable: TotalSegmentator not installed (%s)",
            status.messages.get("packages", _TSEG_INSTALL_HINT),
        )
        return status

    _log_feature_status(
        feature="Harmonize",
        available=status.harmonize_ready,
        available_reason="TotalSegmentator and XGBoost (contrast) are installed",
        unavailable_message=status.messages.get(
            "xgboost",
            "XGBoost or its platform OpenMP runtime is not available",
        ),
        model_label="Anatomy segmentation model",
        model_state=status.anatomy_weights,
    )
    _log_feature_status(
        feature="Face Blur",
        available=status.face_blur_ready,
        available_reason="TotalSegmentator academic license is valid",
        unavailable_message=status.messages.get(
            "face_license",
            "TotalSegmentator academic license is not configured (totalseg_set_license -l aca_...)",
        ),
        model_label="Face segmentation model",
        model_state=status.face_weights,
    )

    return status


def _log_feature_status(
    *,
    feature: str,
    available: bool,
    available_reason: str,
    unavailable_message: str,
    model_label: str,
    model_state: TsWeightState,
) -> None:
    if available:
        logger.info("%s: available — %s", feature, available_reason)
        _log_model_download_status(model_label, model_state)
    else:
        logger.warning("%s: unavailable — %s", feature, unavailable_message)


def _log_model_download_status(label: str, state: TsWeightState) -> None:
    """Log segmentation model weight download/cache status (separate from feature availability)."""
    if state.status == TsWeightStatus.READY:
        logger.info("  %s: downloaded", label)
    elif state.status == TsWeightStatus.MISSING:
        logger.info("  %s: not downloaded (%s)", label, state.detail)
    elif state.status == TsWeightStatus.DOWNLOADING:
        logger.info("  %s: downloading", label)
    elif state.status == TsWeightStatus.FAILED:
        logger.warning("  %s: download failed — %s", label, state.detail)
    elif state.status == TsWeightStatus.UNAVAILABLE:
        logger.info("  %s: download status unknown (%s)", label, state.detail or "TotalSegmentator not installed")


def download_segmentation_model(
    kind: TsWeightKind,
    *,
    on_complete: Callable[[TsWeightState], None] | None = None,
) -> TsWeightState:
    """
    Download one segmentation model via TotalSegmentator and refresh runtime status.

    Blocks until complete; UI layers should call this from a worker thread.
    """
    from anonymizer.controller.tseg.model_cache import download_segmentation_model_weights

    probed = probe_weight_state(kind)
    if probed.status == TsWeightStatus.READY:
        logger.info("Segmentation models: %s already installed", kind.value)
        return probed
    if probed.status == TsWeightStatus.UNAVAILABLE:
        logger.warning("Segmentation models: %s unavailable (%s)", kind.value, probed.detail)
        return probed
    if probed.status == TsWeightStatus.MISSING:
        if kind == TsWeightKind.ANATOMY:
            logger.info("Anatomy models not found (%s)", probed.detail)
        else:
            logger.info("Face segmentation model not found (%s)", probed.detail)
    elif probed.status == TsWeightStatus.FAILED:
        logger.info(
            "Segmentation models: %s download previously failed (%s)",
            kind.value,
            probed.detail,
        )

    logger.info("Segmentation models: downloading %s weights …", kind.value)
    downloading = TsWeightState(
        kind=kind,
        status=TsWeightStatus.DOWNLOADING,
        task_id=probed.task_id,
        model_folder=probed.model_folder,
        detail="Downloading…",
    )
    set_weight_state(downloading)
    get_runtime_status(force_refresh=True)

    try:
        download_segmentation_model_weights(kind)
    except Exception as exc:
        logger.warning("Segmentation models: %s download failed: %s", kind.value, exc)
        failed = TsWeightState(
            kind=kind,
            status=TsWeightStatus.FAILED,
            task_id=probed.task_id,
            model_folder=probed.model_folder,
            detail=str(exc),
        )
        set_weight_state(failed)
        final = get_runtime_status(force_refresh=True)
        final_state = final.face_weights if kind == TsWeightKind.FACE else final.anatomy_weights
        if on_complete is not None:
            on_complete(final_state)
        return final_state

    final_state = refresh_weight_status(kind)
    get_runtime_status(force_refresh=True)
    if final_state.status == TsWeightStatus.READY:
        logger.info("Segmentation models: %s download finished successfully", kind.value)
    if on_complete is not None:
        on_complete(final_state)
    return final_state


def remove_segmentation_model(kind: TsWeightKind) -> bool:
    """Delete on-disk TotalSegmentator weights for one model kind."""
    import shutil

    from anonymizer.controller.tseg.model_cache import (
        clear_predictor_cache,
        harmonize_ts_task_ids,
        resolve_harmonize_model_folder,
    )

    removed = False
    if kind == TsWeightKind.ANATOMY:
        for task_id in harmonize_ts_task_ids():
            folder = resolve_harmonize_model_folder(task_id)
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)
                removed = True
                logger.info("Removed harmonize TS model from %s (task %s)", folder, task_id)
    else:
        state = probe_weight_state(kind)
        if state.model_folder is not None and state.model_folder.is_dir():
            shutil.rmtree(state.model_folder)
            removed = True
            logger.info("Removed %s segmentation model from %s", kind.value, state.model_folder)
    clear_predictor_cache()
    clear_weight_override(kind)
    get_runtime_status(force_refresh=True)
    return removed
