"""Session-scoped TotalSegmentator nnUNet predictor cache for batch harmonize."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

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

    from anonymizer.controller.tseg.config import SEGMENTATION_MODE
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
    if SEGMENTATION_MODE == "6mm":
        task_id = 298
        trainer = "nnUNetTrainer_4000epochs_NoMirroring"
    elif SEGMENTATION_MODE == "1.5mm":
        logger.info("TS model cache preload skipped for 1.5mm mode (multi-model)")
        return
    else:
        task_id = 297
        trainer = "nnUNetTrainer_4000epochs_NoMirroring"

    import totalsegmentator.nnunet as nnunet_module
    from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor

    download_pretrained_weights(task_id)
    model_folder = get_output_folder(task_id, trainer, "nnUNetPlans", "3d_fullres")
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
        logger.info("TS model cache: harmonize segmentation model preloaded (task %s)", task_id)
    except Exception as exc:
        logger.warning("TS model cache preload failed: %s", exc)


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
