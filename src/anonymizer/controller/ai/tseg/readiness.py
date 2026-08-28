"""TotalSegmentator readiness: package/license probes and on-disk weight checks (no cached state)."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

_TSEG_INSTALL_HINT = "pip install rsna-anonymizer"
_TS_ACADEMIC_LICENSE_URL = "https://backend.totalsegmentator.com/license-academic/"
_CHECKPOINT_NAME = "checkpoint_final.pth"
_PLANS = "nnUNetPlans"
_MODEL = "3d_fullres"


class TsWeightKind(StrEnum):
    ANATOMY = "anatomy"  # CT Harmonize (total + contrast)
    ANATOMY_MR = "anatomy_mr"  # MR Harmonize (total_mr)
    FACE = "face"  # CT Face Blur
    FACE_MR = "face_mr"  # MR Face Blur
    BRAIN_STRUCTURES = "brain_structures"


def ts_academic_license_url() -> str:
    return _TS_ACADEMIC_LICENSE_URL


def totalsegmentator_available() -> bool:
    """True when the TotalSegmentator package is installed and importable."""
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


def xgboost_available() -> bool:
    try:
        from anonymizer.controller.ai.tseg.contrast import verify_xgboost_runtime

        verify_xgboost_runtime()
    except (RuntimeError, ImportError):
        return False
    return True


def get_stored_face_license() -> str:
    if not totalsegmentator_available():
        return ""
    try:
        from totalsegmentator.config import get_license_number

        return (get_license_number() or "").strip()
    except Exception:
        return ""


def face_license_available() -> bool:
    ok, _ = verify_face_license()
    return ok


def verify_face_license() -> tuple[bool, str]:
    if not totalsegmentator_available():
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


def _face_license_format_error(license_number: str) -> str | None:
    normalized = license_number.strip()
    if not normalized:
        return _("Enter your academic license number (aca_...).")
    if not normalized.startswith("aca_"):
        return _("License number must start with aca_.")
    if len(normalized) != 18:
        return _("License number must be exactly 18 characters (aca_ plus 14 characters).")
    return None


def apply_face_license(license_number: str) -> tuple[bool, str]:
    format_error = _face_license_format_error(license_number)
    if format_error is not None:
        return False, format_error
    normalized = license_number.strip()

    if not totalsegmentator_available():
        return False, _("TotalSegmentator not installed. Install with: {hint}").format(hint=_TSEG_INSTALL_HINT)

    try:
        from totalsegmentator.config import get_totalseg_dir, is_valid_license, setup_totalseg
    except ImportError as exc:
        return False, _("TotalSegmentator license setup unavailable: {error}").format(error=exc)

    setup_totalseg()
    config_path = get_totalseg_dir() / "config.json"
    if not config_path.is_file():
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
        return False, _(
            "Invalid license number. Check the value or request a free academic license at {url}"
        ).format(url=_TS_ACADEMIC_LICENSE_URL)

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

    licensed, message = verify_face_license()
    if licensed:
        return True, _("Academic license saved.")
    return False, message


def _face_task_spec() -> tuple[int, str, str]:
    return 303, "nnUNetTrainerNoMirroring", "3d_fullres"


def _face_mr_task_spec() -> tuple[int, str, str]:
    return 856, "nnUNetTrainer_2000epochs_NoMirroring", "3d_fullres"


def _brain_structures_task_spec() -> tuple[int, str, str]:
    return 409, "nnUNetTrainer_DASegOrd0", "3d_fullres_high"


def resolve_model_folder(task_id: int, trainer: str, model: str = _MODEL) -> Path | None:
    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
        from totalsegmentator.nnunet import get_output_folder

        setup_nnunet()
        setup_totalseg()
        return Path(get_output_folder(task_id, trainer, _PLANS, model))
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("TS weight folder lookup failed for task %s: %s", task_id, exc)
        return None


def checkpoint_ready(model_folder: Path | None) -> bool:
    """True when ``checkpoint_final.pth`` exists under the model folder (root or fold_*)."""
    if model_folder is None:
        return False
    root_checkpoint = model_folder / _CHECKPOINT_NAME
    if root_checkpoint.is_file():
        return True
    fold_checkpoint = model_folder / "fold_0" / _CHECKPOINT_NAME
    if fold_checkpoint.is_file():
        return True
    return any(model_folder.glob(f"fold_*/{_CHECKPOINT_NAME}"))


def _all_tasks_ready(task_ids: tuple[int, ...], *, resolve_folder) -> bool:
    if not task_ids:
        return False
    for task_id in task_ids:
        folder = resolve_folder(task_id)
        if not checkpoint_ready(folder):
            return False
    return True


def anatomy_ct_ready(mode: str | None = None) -> bool:
    """True when all CT Harmonize weight files for ``mode`` exist on disk."""
    if not totalsegmentator_available():
        return False
    from anonymizer.controller.ai.tseg.config import ENABLE_TS_CONTRAST, normalize_segmentation_mode
    from anonymizer.controller.ai.tseg.model_cache import (
        ct_anatomy_task_ids_for_mode,
        resolve_harmonize_model_folder,
    )

    resolved = normalize_segmentation_mode(mode)
    contrast = (776,) if ENABLE_TS_CONTRAST else ()
    task_ids = ct_anatomy_task_ids_for_mode(resolved) + contrast
    return _all_tasks_ready(task_ids, resolve_folder=resolve_harmonize_model_folder)


def anatomy_mr_ready(mode: str | None = None) -> bool:
    if not totalsegmentator_available():
        return False
    from anonymizer.controller.ai.tseg.config import normalize_segmentation_mode
    from anonymizer.controller.ai.tseg.model_cache import (
        mr_anatomy_task_ids_for_mode,
        resolve_harmonize_model_folder,
    )

    task_ids = mr_anatomy_task_ids_for_mode(normalize_segmentation_mode(mode))
    return _all_tasks_ready(task_ids, resolve_folder=resolve_harmonize_model_folder)


def face_ct_ready() -> bool:
    if not totalsegmentator_available():
        return False
    from anonymizer.controller.ai.tseg.model_cache import face_task_ids

    _task_id, trainer, model = _face_task_spec()
    return all(checkpoint_ready(resolve_model_folder(tid, trainer, model)) for tid in face_task_ids())


def face_mr_ready() -> bool:
    if not totalsegmentator_available():
        return False
    from anonymizer.controller.ai.tseg.model_cache import mr_face_task_ids

    _task_id, trainer, model = _face_mr_task_spec()
    return all(checkpoint_ready(resolve_model_folder(tid, trainer, model)) for tid in mr_face_task_ids())


def brain_structures_ready() -> bool:
    if not totalsegmentator_available():
        return False
    task_id, trainer, model = _brain_structures_task_spec()
    return checkpoint_ready(resolve_model_folder(task_id, trainer, model))


def weight_kind_ready(kind: TsWeightKind, *, mode: str | None = None) -> bool:
    if kind == TsWeightKind.ANATOMY:
        return anatomy_ct_ready(mode)
    if kind == TsWeightKind.ANATOMY_MR:
        return anatomy_mr_ready(mode)
    if kind == TsWeightKind.FACE:
        return face_ct_ready()
    if kind == TsWeightKind.FACE_MR:
        return face_mr_ready()
    if kind == TsWeightKind.BRAIN_STRUCTURES:
        return brain_structures_ready()
    raise ValueError(f"Unknown weight kind: {kind}")


def download_segmentation_model(
    kind: TsWeightKind,
    *,
    on_complete: Callable[[bool], None] | None = None,
) -> bool:
    """Download weights for ``kind``. Returns True when files exist afterward. No status cache."""
    from anonymizer.controller.ai.tseg.model_cache import download_segmentation_model_weights

    if weight_kind_ready(kind):
        logger.info("Segmentation models: %s already installed", kind.value)
        if on_complete is not None:
            on_complete(True)
        return True
    if not totalsegmentator_available():
        logger.warning("Segmentation models: %s unavailable (TotalSegmentator not installed)", kind.value)
        if on_complete is not None:
            on_complete(False)
        return False

    logger.info("Segmentation models: downloading %s weights …", kind.value)
    try:
        download_segmentation_model_weights(kind)
    except Exception as exc:
        logger.warning("Segmentation models: %s download failed: %s", kind.value, exc)
        if on_complete is not None:
            on_complete(False)
        return False

    ready = weight_kind_ready(kind)
    if ready:
        logger.info("Segmentation models: %s download finished successfully", kind.value)
    if on_complete is not None:
        on_complete(ready)
    return ready


def remove_segmentation_model(kind: TsWeightKind) -> bool:
    """Delete on-disk TotalSegmentator weights for one model kind."""
    import shutil

    from anonymizer.controller.ai.tseg.model_cache import (
        clear_predictor_cache,
        face_task_ids,
        harmonize_ts_task_ids,
        mr_anatomy_task_ids,
        mr_face_task_ids,
        resolve_harmonize_model_folder,
    )

    removed = False
    if kind == TsWeightKind.ANATOMY:
        for task_id in harmonize_ts_task_ids():
            folder = resolve_harmonize_model_folder(task_id)
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)
                removed = True
                logger.info("Removed CT harmonize TS model from %s (task %s)", folder, task_id)
    elif kind == TsWeightKind.ANATOMY_MR:
        for task_id in mr_anatomy_task_ids():
            folder = resolve_harmonize_model_folder(task_id)
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)
                removed = True
                logger.info("Removed MR harmonize TS model from %s (task %s)", folder, task_id)
    elif kind == TsWeightKind.FACE:
        trainer, model = _face_task_spec()[1], _face_task_spec()[2]
        for task_id in face_task_ids():
            folder = resolve_model_folder(task_id, trainer, model)
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)
                removed = True
                logger.info("Removed CT face segmentation model from %s (task %s)", folder, task_id)
    elif kind == TsWeightKind.FACE_MR:
        trainer, model = _face_mr_task_spec()[1], _face_mr_task_spec()[2]
        for task_id in mr_face_task_ids():
            folder = resolve_model_folder(task_id, trainer, model)
            if folder is not None and folder.is_dir():
                shutil.rmtree(folder)
                removed = True
                logger.info("Removed MR face segmentation model from %s (task %s)", folder, task_id)
    else:
        task_id, trainer, model = _brain_structures_task_spec()
        folder = resolve_model_folder(task_id, trainer, model)
        if folder is not None and folder.is_dir():
            shutil.rmtree(folder)
            removed = True
            logger.info("Removed %s segmentation model from %s", kind.value, folder)
    clear_predictor_cache()
    return removed


def log_runtime_status() -> None:
    """Log a concise file-based readiness summary (no cached status object)."""
    if not totalsegmentator_available():
        logger.info("Harmonize unavailable: TotalSegmentator not installed (%s)", _TSEG_INSTALL_HINT)
        logger.info("Face Blur unavailable: TotalSegmentator not installed (%s)", _TSEG_INSTALL_HINT)
        return

    if xgboost_available():
        logger.info("Harmonize: available — TotalSegmentator and XGBoost (contrast) are installed")
    else:
        logger.warning("Harmonize: unavailable — XGBoost or its platform OpenMP runtime is not available")

    from anonymizer.controller.ai.tseg.model_cache import (
        installed_ct_segmentation_modes,
        installed_mr_segmentation_modes,
    )

    ct_modes = installed_ct_segmentation_modes()
    mr_modes = installed_mr_segmentation_modes()
    logger.info(
        "  CT anatomy models: %s",
        ", ".join(ct_modes) if ct_modes else "not downloaded",
    )
    logger.info(
        "  MR anatomy models: %s",
        ", ".join(mr_modes) if mr_modes else "not downloaded",
    )

    licensed, license_message = verify_face_license()
    if licensed:
        logger.info("Face Blur: available — TotalSegmentator academic license is valid")
    else:
        logger.warning("Face Blur: unavailable — %s", license_message)
    logger.info("  CT face model: %s", "downloaded" if face_ct_ready() else "not downloaded")
    logger.info("  MR face model: %s", "downloaded" if face_mr_ready() else "not downloaded")
    logger.info(
        "  Brain structures model: %s",
        "downloaded" if brain_structures_ready() else "not downloaded",
    )


# Back-compat aliases used by older call sites during migration.
def _checkpoint_ready(model_folder: Path | None) -> bool:
    return checkpoint_ready(model_folder)


def _resolve_model_folder(task_id: int, trainer: str, model: str = _MODEL) -> Path | None:
    return resolve_model_folder(task_id, trainer, model)


def _totalsegmentator_import_ok() -> bool:
    return totalsegmentator_available()
