"""Session-scoped TotalSegmentator nnUNet predictor cache for batch harmonize."""

from __future__ import annotations

import logging
import shutil
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from anonymizer.controller.tseg.runtime_status import TsWeightKind

logger = logging.getLogger(__name__)

_session_lock = threading.Lock()
_session_depth = 0
_predictor_cache: dict[tuple[Any, ...], Any] = {}
_original_nnUNetv2_predict = None
_patch_installed = False


def session_active() -> bool:
    """Return True while a harmonize batch session keeps TS predictors resident."""
    return _session_depth > 0


def preserve_accelerator_memory() -> bool:
    """When True, skip torch cache clears so loaded TS weights stay resident."""
    return session_active()


def clear_predictor_cache() -> None:
    """Drop cached nnUNet predictors (e.g. on application shutdown)."""
    with _session_lock:
        count = len(_predictor_cache)
        _predictor_cache.clear()
    if count:
        logger.info("TS model cache: cleared %d cached predictor(s)", count)


def _predictor_cache_key(
    *,
    model_folder: str,
    folds: tuple[Any, ...] | None,
    checkpoint_name: str,
    device: Any,
    step_size: float,
    disable_tta: bool,
    perform_everything_on_gpu: bool,
) -> tuple[Any, ...]:
    return (
        model_folder,
        folds,
        checkpoint_name,
        str(device),
        step_size,
        disable_tta,
        perform_everything_on_gpu,
    )


def _create_predictor(
    *,
    step_size: float,
    disable_tta: bool,
    device: Any,
    quiet: bool,
    nnunet_module: Any,
    nnUNetPredictor: Any,
) -> Any:
    allow_tqdm = not quiet
    if nnunet_module.supports_keyword_argument(nnUNetPredictor, "perform_everything_on_gpu"):
        return nnUNetPredictor(
            tile_step_size=step_size,
            use_gaussian=True,
            use_mirroring=not disable_tta,
            perform_everything_on_gpu=True,
            device=device,
            verbose=False,
            verbose_preprocessing=False,
            allow_tqdm=allow_tqdm,
        )
    return nnUNetPredictor(
        tile_step_size=step_size,
        use_gaussian=True,
        use_mirroring=not disable_tta,
        perform_everything_on_device=True,
        device=device,
        verbose=False,
        verbose_preprocessing=False,
        allow_tqdm=allow_tqdm,
    )


def _get_or_create_predictor(
    *,
    model_folder: str,
    folds: list[int] | None,
    checkpoint_name: str,
    device: Any,
    step_size: float,
    disable_tta: bool,
    nnunet_module: Any,
    nnUNetPredictor: Any,
    quiet: bool,
) -> Any:
    perform_flag = nnunet_module.supports_keyword_argument(nnUNetPredictor, "perform_everything_on_gpu")
    fold_key = tuple(folds or ())
    key = _predictor_cache_key(
        model_folder=model_folder,
        folds=fold_key,
        checkpoint_name=checkpoint_name,
        device=device,
        step_size=step_size,
        disable_tta=disable_tta,
        perform_everything_on_gpu=perform_flag,
    )
    with _session_lock:
        cached = _predictor_cache.get(key)
        if cached is not None:
            logger.debug("TS model cache: reusing predictor for %s", model_folder)
            return cached

        predictor = _create_predictor(
            step_size=step_size,
            disable_tta=disable_tta,
            device=device,
            quiet=quiet,
            nnunet_module=nnunet_module,
            nnUNetPredictor=nnUNetPredictor,
        )
        predictor.initialize_from_trained_model_folder(
            model_folder,
            use_folds=folds,
            checkpoint_name=checkpoint_name,
        )
        _predictor_cache[key] = predictor
        logger.info("TS model cache: loaded predictor for %s", model_folder)
        return predictor


def _cached_nnUNetv2_predict(
    dir_in,
    dir_out,
    task_id,
    model="3d_fullres",
    folds=None,
    trainer="nnUNetTrainer",
    tta=False,
    num_threads_preprocessing=3,
    num_threads_nifti_save=2,
    plans="nnUNetPlans",
    device="cuda",
    quiet=False,
    step_size=0.5,
    save_probabilities_path=None,
    use_cropped_logits_resampling=False,
):
    if not session_active() or _original_nnUNetv2_predict is None:
        return _original_nnUNetv2_predict(
            dir_in,
            dir_out,
            task_id,
            model=model,
            folds=folds,
            trainer=trainer,
            tta=tta,
            num_threads_preprocessing=num_threads_preprocessing,
            num_threads_nifti_save=num_threads_nifti_save,
            plans=plans,
            device=device,
            quiet=quiet,
            step_size=step_size,
            save_probabilities_path=save_probabilities_path,
            use_cropped_logits_resampling=use_cropped_logits_resampling,
        )

    import torch
    import totalsegmentator.nnunet as nnunet_module
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor
    from nnunetv2.utilities.file_path_utilities import get_output_folder

    dir_in = str(dir_in)
    dir_out = str(dir_out)
    model_folder = get_output_folder(task_id, trainer, plans, model)

    assert device in ["cpu", "cuda", "mps"] or isinstance(device, torch.device), (
        f"-device must be either cpu, mps or cuda. Got: {device}."
    )
    if device == "cpu":
        import multiprocessing

        torch.set_num_threads(multiprocessing.cpu_count())
        resolved_device = torch.device("cpu")
    elif device == "cuda":
        torch.set_num_threads(1)
        resolved_device = torch.device("cuda")
    elif isinstance(device, torch.device):
        torch.set_num_threads(1)
        resolved_device = device
    else:
        resolved_device = torch.device("mps")

    disable_tta = not tta
    save_probabilities = save_probabilities_path is not None
    checkpoint_name = "checkpoint_final.pth"

    predictor = _get_or_create_predictor(
        model_folder=model_folder,
        folds=folds,
        checkpoint_name=checkpoint_name,
        device=resolved_device,
        step_size=step_size,
        disable_tta=disable_tta,
        nnunet_module=nnunet_module,
        nnUNetPredictor=nnUNetPredictor,
        quiet=quiet,
    )

    predict_kwargs: dict[str, Any] = {}
    if (
        use_cropped_logits_resampling
        and not save_probabilities
        and nnunet_module.supports_keyword_argument(
            predictor.predict_from_files,
            "use_cropped_logits_resampling",
        )
    ):
        predict_kwargs["use_cropped_logits_resampling"] = True

    predictor.predict_from_files(
        dir_in,
        dir_out,
        save_probabilities=save_probabilities,
        overwrite=True,
        num_processes_preprocessing=num_threads_preprocessing,
        num_processes_segmentation_export=num_threads_nifti_save,
        folder_with_segs_from_prev_stage=None,
        num_parts=1,
        part_id=0,
        **predict_kwargs,
    )

    if save_probabilities and save_probabilities_path is not None:
        import shutil
        from pathlib import Path

        save_path = Path(save_probabilities_path)
        shutil.copy(Path(dir_out) / "s01.npz", save_path)
        shutil.copy(Path(dir_out) / "s01.pkl", save_path.with_suffix(".pkl"))


def _install_predictor_cache_patch() -> None:
    global _original_nnUNetv2_predict, _patch_installed
    if _patch_installed:
        return
    try:
        import totalsegmentator.nnunet as nnunet_module
    except ImportError:
        logger.debug("TotalSegmentator not installed; predictor cache disabled")
        return

    _original_nnUNetv2_predict = nnunet_module.nnUNetv2_predict
    nnunet_module.nnUNetv2_predict = _cached_nnUNetv2_predict
    _patch_installed = True
    logger.debug("TS model cache: installed nnUNetv2_predict patch")


def _resolve_totalseg_device(device: str) -> str:
    import torch

    if device == "gpu":
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"
    if device == "mps" and torch.backends.mps.is_available():
        return "mps"
    if device == "cpu":
        return "cpu"
    return device


def _anatomy_preload_trainer() -> str:
    return "nnUNetTrainer_4000epochs_NoMirroring"


def harmonize_anatomy_task_ids() -> tuple[int, ...]:
    """
    TotalSegmentator task IDs downloaded during harmonize anatomy segmentation.

    With ``roi_subset`` + ``body_seg`` (see ``run_segmentation``), TotalSegmentator
    downloads the main task (3mm/6mm/1.5mm) plus task 298 for rough ROI cropping on CT.
    """
    from anonymizer.controller.tseg.config import SEGMENTATION_MODE

    if SEGMENTATION_MODE == "6mm":
        return (298,)
    if SEGMENTATION_MODE == "1.5mm":
        return (291, 292, 293, 294, 295, 298)
    return (297, 298)


def harmonize_contrast_task_ids() -> tuple[int, ...]:
    """
    TotalSegmentator task IDs for harmonize IV contrast (head/neck vessel statistics).

    ``predict_contrast_phase`` runs ``task=headneck_bones_vessels`` (task 776) when brain
    volume is present in organ statistics.
    """
    from anonymizer.controller.tseg.config import ENABLE_TS_CONTRAST

    if not ENABLE_TS_CONTRAST:
        return ()
    return (776,)


def harmonize_ts_task_ids() -> tuple[int, ...]:
    """All TotalSegmentator weight tasks required for harmonize (segmentation + contrast)."""
    return harmonize_anatomy_task_ids() + harmonize_contrast_task_ids()


def trainer_for_harmonize_task(task_id: int) -> str:
    if task_id in (297, 298):
        return "nnUNetTrainer_4000epochs_NoMirroring"
    if task_id in (291, 292, 293, 294, 295):
        return "nnUNetTrainerNoMirroring"
    if task_id == 776:
        return "nnUNetTrainer_DASegOrd0_NoMirroring"
    return _anatomy_preload_trainer()


def model_for_harmonize_task(task_id: int) -> str:
    if task_id == 776:
        return "3d_fullres_high"
    return "3d_fullres"


def trainer_for_anatomy_task(task_id: int) -> str:
    return trainer_for_harmonize_task(task_id)


def resolve_harmonize_model_folder(task_id: int) -> Path | None:
    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
        from totalsegmentator.nnunet import get_output_folder

        setup_nnunet()
        setup_totalseg()
        trainer = trainer_for_harmonize_task(task_id)
        model = model_for_harmonize_task(task_id)
        return Path(get_output_folder(task_id, trainer, "nnUNetPlans", model))
    except ImportError:
        return None
    except Exception as exc:
        logger.debug("TS harmonize weight folder lookup failed for task %s: %s", task_id, exc)
        return None


def resolve_anatomy_model_folder(task_id: int) -> Path | None:
    return resolve_harmonize_model_folder(task_id)


def missing_harmonize_ts_task_ids() -> tuple[int, ...]:
    return tuple(task_id for task_id in harmonize_ts_task_ids() if not _harmonize_task_checkpoint_ready(task_id))


def missing_anatomy_task_ids() -> tuple[int, ...]:
    return missing_harmonize_ts_task_ids()


def anatomy_models_ready() -> bool:
    return not missing_harmonize_ts_task_ids()


def _harmonize_task_checkpoint_ready(task_id: int) -> bool:
    from anonymizer.controller.tseg.runtime_status import _checkpoint_ready

    return _checkpoint_ready(resolve_harmonize_model_folder(task_id))


def _face_task_checkpoint_ready() -> bool:
    from anonymizer.controller.tseg.runtime_status import _checkpoint_ready

    return _checkpoint_ready(_resolve_task_model_folder(_FACE_TASK_ID, trainer=_FACE_TRAINER, model=_FACE_MODEL))


def _task_checkpoint_ready(task_id: int, *, trainer: str, model: str) -> bool:
    from anonymizer.controller.tseg.runtime_status import _checkpoint_ready

    return _checkpoint_ready(_resolve_task_model_folder(task_id, trainer=trainer, model=model))


def _anatomy_task_checkpoint_ready(task_id: int) -> bool:
    return _harmonize_task_checkpoint_ready(task_id)


_FACE_TASK_ID = 303
_FACE_TRAINER = "nnUNetTrainerNoMirroring"
_FACE_MODEL = "3d_fullres"
_NNUNET_PLANS = "nnUNetPlans"


def _resolve_task_model_folder(task_id: int, *, trainer: str, model: str) -> Path:
    from totalsegmentator.nnunet import get_output_folder

    return Path(get_output_folder(task_id, trainer, _NNUNET_PLANS, model))


def _remove_incomplete_dataset_dir(model_folder: Path) -> None:
    """Remove a dataset directory left behind by a failed or partial weight download."""
    dataset_dir = model_folder.parent
    if dataset_dir.is_dir():
        shutil.rmtree(dataset_dir)
        logger.info("TS weights: removed incomplete dataset cache at %s", dataset_dir)


def _ensure_pretrained_weights(task_id: int, *, trainer: str, model: str) -> None:
    """
    Download one TotalSegmentator task when its checkpoint is not ready.

    TotalSegmentator skips download when the dataset root folder exists, even if it
    contains no nnUNet checkpoint (e.g. after a partial download). Re-probe the
    checkpoint path and remove stale dataset directories before downloading.
    """
    from totalsegmentator.libs import download_pretrained_weights

    model_folder = _resolve_task_model_folder(task_id, trainer=trainer, model=model)
    if _task_checkpoint_ready(task_id, trainer=trainer, model=model):
        return
    _remove_incomplete_dataset_dir(model_folder)
    download_pretrained_weights(task_id)
    if not _task_checkpoint_ready(task_id, trainer=trainer, model=model):
        raise RuntimeError(f"TotalSegmentator weights for task {task_id} are still missing after download")


def download_segmentation_model_weights(kind: "TsWeightKind") -> None:
    """Download TotalSegmentator weights for anatomy or face segmentation (no predictor preload)."""
    from anonymizer.controller.tseg.runtime_status import (
        TsWeightKind as Kind,
    )
    from anonymizer.controller.tseg.runtime_status import (
        verify_face_license,
    )

    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
    except ImportError as exc:
        raise RuntimeError("TotalSegmentator is required. Install with pip install rsna-anonymizer") from exc

    setup_nnunet()
    setup_totalseg()

    from anonymizer.utils.download_progress import track_segmentation_download

    if kind == Kind.ANATOMY:
        task_ids = harmonize_ts_task_ids()
        if not task_ids:
            raise RuntimeError("Anatomy segmentation download is not supported for 1.5mm mode")
        for task_id in task_ids:
            trainer = trainer_for_harmonize_task(task_id)
            model = model_for_harmonize_task(task_id)
            with track_segmentation_download(kind, task_id=task_id):
                _ensure_pretrained_weights(task_id, trainer=trainer, model=model)
        still_missing = missing_harmonize_ts_task_ids()
        if still_missing:
            raise RuntimeError(f"Harmonize models are still missing after download (tasks {still_missing})")
        logger.info("TS weights: harmonize models downloaded (tasks %s)", task_ids)
        return

    if kind == Kind.FACE:
        licensed, message = verify_face_license()
        if not licensed:
            raise RuntimeError(message)
        with track_segmentation_download(kind, task_id=_FACE_TASK_ID):
            _ensure_pretrained_weights(_FACE_TASK_ID, trainer=_FACE_TRAINER, model=_FACE_MODEL)
        if not _face_task_checkpoint_ready():
            raise RuntimeError(f"Face segmentation model is still missing after download (task {_FACE_TASK_ID})")
        logger.info("TS weights: face segmentation model downloaded (task %s)", _FACE_TASK_ID)
        return

    raise ValueError(f"Unknown segmentation model kind: {kind}")


def preload_face_models(*, device: str | None = None) -> None:
    """
    Eager-load TotalSegmentator face segmentation weights.

    No-op when TotalSegmentator is not installed or academic license is missing.
    """
    from anonymizer.controller.tseg.runtime_status import verify_face_license

    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
        from totalsegmentator.libs import download_pretrained_weights
        from totalsegmentator.nnunet import get_output_folder
    except ImportError:
        logger.debug("TS face preload skipped (TotalSegmentator not installed)")
        return

    licensed, message = verify_face_license()
    if not licensed:
        logger.debug("TS face preload skipped: %s", message)
        return

    from anonymizer.controller.tseg.segment import resolve_device

    setup_nnunet()
    setup_totalseg()

    download_pretrained_weights(_FACE_TASK_ID)
    resolved = _resolve_totalseg_device(resolve_device(device))
    import torch
    import totalsegmentator.nnunet as nnunet_module
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

    if resolved == "cpu":
        torch_device: Any = torch.device("cpu")
    elif resolved == "cuda":
        torch_device = torch.device("cuda")
    else:
        torch_device = torch.device("mps")

    model_folder = get_output_folder(_FACE_TASK_ID, _FACE_TRAINER, "nnUNetPlans", "3d_fullres")
    try:
        _get_or_create_predictor(
            model_folder=model_folder,
            folds=[0],
            checkpoint_name="checkpoint_final.pth",
            device=torch_device,
            step_size=0.5,
            disable_tta=True,
            nnunet_module=nnunet_module,
            nnUNetPredictor=nnUNetPredictor,
            quiet=True,
        )
        logger.info("TS model cache: face segmentation model preloaded (task %s)", _FACE_TASK_ID)
    except Exception as exc:
        logger.warning("TS face preload failed: %s", exc)


def preload_harmonize_models(*, device: str | None = None) -> None:
    """
    Eager-load TotalSegmentator weights used by harmonize anatomy segmentation.

    Safe to call when TotalSegmentator is not installed (no-op).
    """
    try:
        from totalsegmentator.config import setup_nnunet, setup_totalseg
        from totalsegmentator.libs import download_pretrained_weights
        from totalsegmentator.nnunet import get_output_folder
    except ImportError:
        logger.debug("TS model cache preload skipped (TotalSegmentator not installed)")
        return

    from anonymizer.controller.tseg.segment import resolve_device

    setup_nnunet()
    setup_totalseg()

    resolved = _resolve_totalseg_device(resolve_device(device))
    import torch

    if resolved == "cpu":
        torch_device: Any = torch.device("cpu")
    elif resolved == "cuda":
        torch_device = torch.device("cuda")
    else:
        torch_device = torch.device("mps")
    task_ids = harmonize_ts_task_ids()
    if not task_ids:
        logger.info("TS model cache preload skipped for 1.5mm mode (multi-model)")
        return

    import totalsegmentator.nnunet as nnunet_module
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

    for task_id in task_ids:
        download_pretrained_weights(task_id)

    anatomy_task_ids = harmonize_anatomy_task_ids()
    preloaded: list[int] = []
    for task_id in anatomy_task_ids:
        trainer = trainer_for_harmonize_task(task_id)
        model = model_for_harmonize_task(task_id)
        model_folder = get_output_folder(task_id, trainer, "nnUNetPlans", model)
        try:
            _get_or_create_predictor(
                model_folder=model_folder,
                folds=[0],
                checkpoint_name="checkpoint_final.pth",
                device=torch_device,
                step_size=0.5,
                disable_tta=True,
                nnunet_module=nnunet_module,
                nnUNetPredictor=nnUNetPredictor,
                quiet=True,
            )
            preloaded.append(task_id)
        except Exception as exc:
            logger.warning("TS model cache preload failed for task %s: %s", task_id, exc)
    if preloaded:
        logger.info(
            "TS model cache: harmonize segmentation models preloaded (tasks %s, loaded %s)",
            task_ids,
            preloaded,
        )


def _release_batch_working_memory() -> None:
    """Release per-series allocations after a batch without dropping cached predictors."""
    from anonymizer.controller.tseg.contrast import log_memory_usage, release_working_memory

    release_working_memory(stage="tseg_batch_session_end", preserve_accelerator=True)
    log_memory_usage("tseg_batch_session_end")


@contextmanager
def tseg_batch_session(*, preload: bool = True) -> Iterator[None]:
    """
    Keep TotalSegmentator nnUNet predictors loaded across multiple harmonize series.

    Predictors remain cached after the context exits so a later batch in the same GUI
    session can reuse them. Call ``clear_predictor_cache()`` on shutdown if needed.
    """
    global _session_depth

    _install_predictor_cache_patch()
    with _session_lock:
        _session_depth += 1
        entering = _session_depth == 1

    try:
        if entering and preload:
            preload_harmonize_models()
        yield
    finally:
        with _session_lock:
            _session_depth -= 1
            exiting = _session_depth == 0
        if exiting:
            _release_batch_working_memory()
