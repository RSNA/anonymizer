"""Algorithm-agnostic background runners for Series View and batch."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum, auto
from pathlib import Path
from typing import Callable, Protocol

from easyocr import Reader

from anonymizer.controller.ai.ocr_whitelist_match import OcrWhitelistMatchSettings
from anonymizer.controller.ai.remove_pixel_phi import (
    OCR_LANGS,
    OCR_MODEL_DIR,
    _ocr_use_gpu,
    detect_text,
    download_ocr_models,
    load_modality_whitelist,
    ocr_image_for_frame,
    ocr_models_ready,
    remove_pixel_phi,
)
from anonymizer.controller.series_io import load_series_frames
from anonymizer.controller.series_overlay import OCRText
from anonymizer.controller.work_state import WorkState
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class Algorithm(StrEnum):
    REMOVE_PIXEL_PHI = auto()
    HARMONIZE = auto()
    FACE_BLUR = auto()


CANONICAL_ALGORITHM_ORDER: tuple[Algorithm, ...] = (
    Algorithm.REMOVE_PIXEL_PHI,
    Algorithm.HARMONIZE,
    Algorithm.FACE_BLUR,
)


class OcrEditContext(StrEnum):
    FRAME = "FRAME"
    SERIES = "SERIES"


@dataclass
class RunOptions:
    edit_context: OcrEditContext = OcrEditContext.SERIES
    whitelist: list[str] | None = None
    project_dir: Path | None = None
    removal_mode: object | None = None  # PixelPhiRemovalMode when batch applies PHI removal
    whitelist_match: OcrWhitelistMatchSettings | None = None


@dataclass
class ModelHandle:
    reader: Reader | None = None
    _extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchSpec:
    series_paths: tuple[Path, ...]
    algorithms: tuple[Algorithm, ...]
    options: RunOptions = field(default_factory=RunOptions)


@dataclass
class BatchSummary:
    processed: int = 0
    failed: int = 0
    cancelled: bool = False


class Runner(Protocol):
    def enter_models(self) -> ModelHandle: ...
    def exit_models(self, handle: ModelHandle) -> None: ...
    def process_series(self, work_state: WorkState, handle: ModelHandle, *, options: RunOptions) -> None: ...


class RemovePixelPhiRunner:
    """OCR detect (Series View) or per-instance PHI removal (batch)."""

    def enter_models(self) -> ModelHandle:
        logger.info("RemovePixelPhiRunner.enter_models")
        if not ocr_models_ready():
            logger.info("OCR models missing; downloading to %s", OCR_MODEL_DIR)
            download_ocr_models()
        reader = Reader(
            lang_list=list(OCR_LANGS),
            model_storage_directory=str(OCR_MODEL_DIR),
            gpu=_ocr_use_gpu(),
        )
        logger.info("EasyOCR Reader ready at %s", OCR_MODEL_DIR)
        return ModelHandle(reader=reader)

    def exit_models(self, handle: ModelHandle) -> None:
        logger.info("RemovePixelPhiRunner.exit_models")
        handle.reader = None

    def process_series(self, work_state: WorkState, handle: ModelHandle, *, options: RunOptions) -> None:
        if handle.reader is None:
            raise RuntimeError("OCR Reader not loaded")
        if work_state.ds is None or work_state.frames is None:
            raise RuntimeError("WorkState not bound")

        ds = work_state.ds
        modality = str(ds.get("Modality", "") or "")
        whitelist = options.whitelist
        if whitelist is None:
            whitelist = load_modality_whitelist(options.project_dir, modality or None)

        if options.removal_mode is not None:
            self._process_batch_removal(work_state, handle, options)
            return

        self._process_detect_only(work_state, handle, whitelist, options.edit_context)

    def _process_detect_only(
        self,
        work_state: WorkState,
        handle: ModelHandle,
        whitelist: list[str] | None,
        edit_context: OcrEditContext,
    ) -> None:
        logger.info("RemovePixelPhiRunner._process_detect_only edit_context=%s", edit_context)
        assert handle.reader is not None
        ds = work_state.ds
        assert ds is not None
        modality = str(ds.get("Modality", "") or "")

        total = work_state.frame_count(Algorithm.REMOVE_PIXEL_PHI)
        indices = (
            [work_state.frame_index]
            if edit_context is OcrEditContext.FRAME
            else list(range(total))
        )

        detections: dict[int, list[OCRText]] = {}
        for frame_index in indices:
            if work_state.should_cancel():
                logger.info("OCR detect cancelled at frame_index=%s", frame_index)
                work_state.result = dict(detections)
                return

            ocr_pixels = work_state.ocr_pixels
            if ocr_pixels is not None and frame_index < ocr_pixels.shape[0]:
                logger.debug(
                    "OCR frame_index=%s using Series View pixels shape=%s",
                    frame_index,
                    ocr_pixels[frame_index].shape,
                )
                raw = detect_text(
                    ocr_pixels[frame_index],
                    handle.reader,
                    draw_boxes_and_text=False,
                    modality=modality,
                    apply_noise_filter=False,
                    whitelist=whitelist,
                )
            else:
                frame = work_state.frame_at(frame_index, Algorithm.REMOVE_PIXEL_PHI)
                bgr = ocr_image_for_frame(ds, frame)
                logger.debug("OCR frame_index=%s bgr_shape=%s", frame_index, bgr.shape)
                raw = detect_text(
                    bgr,
                    handle.reader,
                    draw_boxes_and_text=False,
                    modality=modality,
                    apply_noise_filter=False,
                    whitelist=whitelist,
                )
            filtered = raw or []
            logger.debug(
                "OCR frame_index=%s: %d detection(s) (Series View detect, noise_filter=False)",
                frame_index,
                len(filtered),
            )
            if filtered:
                detections[frame_index] = filtered
                all_texts = [t.text for t in filtered]
                logger.info(
                    "OCR frame_index=%s: %d detection(s): %s",
                    frame_index,
                    len(all_texts),
                    all_texts,
                )
                preview = all_texts[:5]
                if len(filtered) > 5:
                    logger.debug(
                        "OCR frame_index=%s: %d detection(s) after filter: %s (showing 5 of %d)",
                        frame_index,
                        len(filtered),
                        preview,
                        len(filtered),
                    )
                else:
                    logger.debug(
                        "OCR frame_index=%s: %d detection(s) after filter: %s",
                        frame_index,
                        len(filtered),
                        preview,
                    )
            work_state.result = dict(detections)
            work_state.set_progress(
                frame_index,
                _("Detecting text") + f"… {_('image')} {frame_index + 1} {_('of')} {total}",
            )

        work_state.result = dict(detections)
        logger.info("RemovePixelPhiRunner detect complete: %s frames with text", len(detections))

    def _process_batch_removal(
        self,
        work_state: WorkState,
        handle: ModelHandle,
        options: RunOptions,
    ) -> None:
        assert handle.reader is not None
        assert work_state.slice_paths is not None
        paths = sorted(set(work_state.slice_paths))
        logger.info("RemovePixelPhiRunner batch removal: %s instance files", len(paths))
        modality = str(work_state.ds.get("Modality", "") or "") if work_state.ds else ""
        whitelist_match = options.whitelist_match
        if whitelist_match is None and options.project_dir is not None:
            from anonymizer.utils.storage import load_modality_whitelist_match_settings

            whitelist_match = load_modality_whitelist_match_settings(options.project_dir, modality or None)
        for index, dcm_path in enumerate(paths, start=1):
            if work_state.should_cancel():
                return
            work_state.set_status(_("Scanning instances for burnt-in text") + f" ({index}/{len(paths)})")
            remove_pixel_phi(
                dcm_path,
                handle.reader,
                removal_mode=options.removal_mode,
                project_dir=options.project_dir,
                modality=modality or None,
                whitelist=options.whitelist,
                whitelist_match_settings=whitelist_match,
            )


class HarmonizeRunner:
    """Batch harmonize phase: owns TotalSegmentator session for the algorithm pass."""

    def enter_models(self) -> ModelHandle:
        from anonymizer.controller.ai.tseg.model_cache import tseg_batch_session

        logger.info("HarmonizeRunner.enter_models")
        session = tseg_batch_session(preload=True)
        session.__enter__()
        return ModelHandle(_extra={"tseg_session": session})

    def exit_models(self, handle: ModelHandle) -> None:
        from anonymizer.controller.ai.tseg.contrast import release_working_memory

        logger.info("HarmonizeRunner.exit_models")
        session = handle._extra.pop("tseg_session", None)
        if session is not None:
            session.__exit__(None, None, None)
        release_working_memory(stage="batch_after_harmonize_phase", preserve_accelerator=True)

    def process_series(self, work_state: WorkState, handle: ModelHandle, *, options: RunOptions) -> None:
        raise NotImplementedError("Harmonize batch uses harmonize_and_apply_series from batch_process")


class FaceBlurRunner:
    """Batch face-blur phase: owns face-segmentation model preload for the algorithm pass."""

    def enter_models(self) -> ModelHandle:
        from anonymizer.controller.ai.tseg.model_cache import preload_face_models, tseg_batch_session

        logger.info("FaceBlurRunner.enter_models")
        session = tseg_batch_session(preload=False)
        session.__enter__()
        preload_face_models()
        return ModelHandle(_extra={"tseg_session": session})

    def exit_models(self, handle: ModelHandle) -> None:
        from anonymizer.controller.ai.tseg.contrast import release_working_memory
        from anonymizer.controller.ai.tseg.model_cache import clear_predictor_cache

        logger.info("FaceBlurRunner.exit_models")
        session = handle._extra.pop("tseg_session", None)
        if session is not None:
            session.__exit__(None, None, None)
        clear_predictor_cache()
        release_working_memory(stage="batch_after_face_blur_phase", preserve_accelerator=True)

    def process_series(self, work_state: WorkState, handle: ModelHandle, *, options: RunOptions) -> None:
        raise NotImplementedError("Face blur batch uses preview_face_blur from batch_process")


RUNNERS: dict[Algorithm, Runner] = {
    Algorithm.REMOVE_PIXEL_PHI: RemovePixelPhiRunner(),
    Algorithm.HARMONIZE: HarmonizeRunner(),
    Algorithm.FACE_BLUR: FaceBlurRunner(),
}


def runner_for(algorithm: Algorithm) -> Runner:
    return RUNNERS[algorithm]


def enter_batch_phase(algorithm: Algorithm) -> tuple[Runner, ModelHandle]:
    """Load models once for an entire batch algorithm phase."""
    runner = runner_for(algorithm)
    return runner, runner.enter_models()


def exit_batch_phase(runner: Runner, handle: ModelHandle) -> None:
    runner.exit_models(handle)


def process_series(
    algorithm: Algorithm,
    work_state: WorkState,
    handle: ModelHandle,
    *,
    options: RunOptions | None = None,
) -> None:
    logger.info("process_series algorithm=%s", algorithm)
    RUNNERS[algorithm].process_series(work_state, handle, options=options or RunOptions())


def run_job(
    algorithm: Algorithm,
    work_state: WorkState,
    *,
    options: RunOptions | None = None,
) -> None:
    logger.info("run_job start algorithm=%s", algorithm)
    runner = RUNNERS[algorithm]
    handle = runner.enter_models()
    try:
        process_series(algorithm, work_state, handle, options=options)
        if not work_state.should_cancel() and not work_state.done:
            work_state.finish(work_state.result)
    except Exception as exc:
        logger.exception("run_job failed algorithm=%s", algorithm)
        work_state.fail(str(exc))
    finally:
        runner.exit_models(handle)
    logger.info("run_job end algorithm=%s done=%s", algorithm, work_state.done)


def run_batch(
    work_state: WorkState,
    batch: BatchSpec,
    *,
    on_series_start: Callable[[Path, Algorithm], None] | None = None,
) -> BatchSummary:
    logger.info(
        "run_batch start: %s algorithms, %s series",
        len(batch.algorithms),
        len(batch.series_paths),
    )
    summary = BatchSummary()
    for algorithm in batch.algorithms:
        if work_state.should_cancel():
            summary.cancelled = True
            break
        runner = RUNNERS[algorithm]
        handle = runner.enter_models()
        try:
            for series_path in batch.series_paths:
                if work_state.should_cancel():
                    summary.cancelled = True
                    break
                if on_series_start is not None:
                    on_series_start(series_path, algorithm)
                logger.info("run_batch load_series_frames %s", series_path)
                loaded = load_series_frames(series_path)
                work_state.bind(
                    loaded.metadata,
                    loaded.frames,
                    loaded.slice_paths,
                    loaded.default_window,
                    single_frame=loaded.is_single_frame,
                )
                options = batch.options
                if algorithm is Algorithm.REMOVE_PIXEL_PHI:
                    runner.process_series(work_state, handle, options=options)
                else:
                    logger.warning("run_batch skipping unimplemented algorithm=%s", algorithm)
                summary.processed += 1
        finally:
            runner.exit_models(handle)
    if not work_state.done:
        work_state.finish(summary)
    logger.info("run_batch end processed=%s cancelled=%s", summary.processed, summary.cancelled)
    return summary
