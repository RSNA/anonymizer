"""Algorithm-agnostic background runners for Series View and batch.

Public API
----------
Algorithm
    Algorithm type.

CANONICAL_ALGORITHM_ORDER
    Canonical algorithm order.

RunOptions
    Per-run options (edit context, whitelist, match mode, removal mode).

ModelHandle
    ModelHandle type.

BatchSpec
    BatchSpec type.

BatchSummary
    BatchSummary type.

Runner
    Runner type.

RemovePixelPhiRunner
    OCR detect (Series View) or per-instance PHI removal (batch).

HarmonizeRunner
    Batch harmonize phase: owns TotalSegmentator session for the algorithm pass.

FaceBlurRunner
    Batch face-blur phase: owns face-segmentation model preload for the algorithm pass.

RUNNERS
    Runners.

runner_for(algorithm: Algorithm) -> Runner
    Runner for.

enter_batch_phase(algorithm: Algorithm) -> tuple[Runner, ModelHandle]
    Load models once for an entire batch algorithm phase.

exit_batch_phase(runner: Runner, handle: ModelHandle) -> None
    Exit batch phase.

process_series(algorithm: Algorithm, work_state: WorkState, handle: ModelHandle, *, options: RunOptions | None=None) -> None
    Process series.

run_job(algorithm: Algorithm, work_state: WorkState, *, options: RunOptions | None=None) -> None
    Run job.

run_batch(work_state: WorkState, batch: BatchSpec, *, on_series_start: Callable[[Path, Algorithm], None] | None=None) -> BatchSummary
    Run batch.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from easyocr import Reader

from anonymizer.controller.ai.embedded_phi.ner.cache import download_ner_models
from anonymizer.controller.ai.embedded_phi.pixel.cache import OCR_LANGS, OCR_MODEL_DIR, download_ocr_models
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import ocr_image_for_frame
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    annotate_ner,
    detect_text,
    filter_ocr_noise,
    log_ocr_decisions,
    make_annotate_whitelist,
    pipe,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import _ocr_use_gpu, remove_pixel_phi
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrEditContext, OcrRemoveMode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_modality_whitelist
from anonymizer.controller.ai.feature_availability import embedded_phi_has_models
from anonymizer.controller.ai.tseg.contrast import release_working_memory
from anonymizer.controller.ai.tseg.model_cache import clear_predictor_cache, preload_face_models, tseg_batch_session
from anonymizer.controller.jobs.work_state import Algorithm, WorkState
from anonymizer.controller.series.series_io import load_series_frames
from anonymizer.controller.series.series_overlay import OCRText
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


CANONICAL_ALGORITHM_ORDER: tuple[Algorithm, ...] = (
    Algorithm.REMOVE_PIXEL_PHI,
    Algorithm.HARMONIZE,
    Algorithm.FACE_BLUR,
)


@dataclass
class RunOptions:
    edit_context: OcrEditContext = OcrEditContext.SERIES
    whitelist: list[str] | None = None
    project_dir: Path | None = None
    removal_mode: object | None = None  # PixelPhiRemovalMode when batch applies PHI removal
    match_mode: PhiMatchMode = PhiMatchMode.STANDARD
    remove_mode: OcrRemoveMode = OcrRemoveMode.NON_WHITELISTED


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
        if not embedded_phi_has_models():
            logger.info("Embedded PHI models missing; downloading OCR + NER")
            download_ocr_models()
            download_ner_models()
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

        self._process_detect_only(work_state, handle, whitelist, options)

    def _process_detect_only(
        self,
        work_state: WorkState,
        handle: ModelHandle,
        whitelist: list[str] | None,
        options: RunOptions,
    ) -> None:
        """Series View Detect: same EasyOCR + noise filter as batch; annotate NER labels."""
        edit_context = options.edit_context
        logger.info("RemovePixelPhiRunner._process_detect_only edit_context=%s", edit_context)
        assert handle.reader is not None
        ds = work_state.ds
        assert ds is not None
        modality = str(ds.get("Modality", "") or "")
        # Series View passes PhiMatchMode from the toolbar; do not reload over it.
        match_mode = options.match_mode
        terms = list(whitelist) if whitelist is not None else load_modality_whitelist(
            options.project_dir, modality or None
        )
        process = pipe(
            lambda texts: filter_ocr_noise(texts, modality=modality),
            make_annotate_whitelist(terms),
            lambda texts: annotate_ner(texts, modality=modality),
        )

        total = work_state.frame_count(Algorithm.REMOVE_PIXEL_PHI)
        indices = (
            [work_state.frame_index]
            if edit_context is OcrEditContext.FRAME
            else list(range(total))
        )

        detections: dict[int, list[OCRText]] = {}
        for frame_index in indices:
            if work_state.should_cancel():
                logger.info(f"OCR detect cancelled at frame_index={frame_index}")
                work_state.result = dict(detections)
                return

            ocr_pixels = work_state.ocr_pixels
            if ocr_pixels is not None and frame_index < ocr_pixels.shape[0]:
                pixels = ocr_pixels[frame_index]
            else:
                frame = work_state.frame_at(frame_index, Algorithm.REMOVE_PIXEL_PHI)
                pixels = ocr_image_for_frame(ds, frame)
            detected = detect_text(pixels, handle.reader, modality=modality)
            annotated = process(detected)
            # Full annotated cache; Remove Scope re-filters in the view for WYSIWYG.
            if annotated:
                log_ocr_decisions(
                    annotated,
                    match_mode,
                    remove_mode=options.remove_mode.value,
                )
                detections[frame_index] = annotated
                logger.info(
                    f"OCR frame_index={frame_index}: {len(annotated)} detection(s) "
                    f"match_mode={match_mode.value} remove_mode={options.remove_mode.value}"
                )
            work_state.result = dict(detections)
            work_state.set_progress(
                frame_index,
                _("Detecting text") + f"… {_('image')} {frame_index + 1} {_('of')} {total}",
            )

        work_state.result = dict(detections)
        logger.info(f"RemovePixelPhiRunner detect complete: {len(detections)} frames with text")

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
        for index, dcm_path in enumerate(paths, start=1):
            if work_state.should_cancel():
                return
            work_state.set_status(_("Scanning instances for burnt-in text") + f" ({index}/{len(paths)})")
            remove_pixel_phi(
                dcm_path,
                handle.reader,
                removal_mode=options.removal_mode,
                remove_mode=options.remove_mode,
                project_dir=options.project_dir,
                modality=modality or None,
                whitelist=options.whitelist,
                match_mode=options.match_mode,
            )


class HarmonizeRunner:
    """Batch harmonize phase: owns TotalSegmentator session for the algorithm pass."""

    def enter_models(self) -> ModelHandle:

        logger.info("HarmonizeRunner.enter_models")
        session = tseg_batch_session(preload=True)
        session.__enter__()
        return ModelHandle(_extra={"tseg_session": session})

    def exit_models(self, handle: ModelHandle) -> None:

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

        logger.info("FaceBlurRunner.enter_models")
        session = tseg_batch_session(preload=False)
        session.__enter__()
        preload_face_models()
        return ModelHandle(_extra={"tseg_session": session})

    def exit_models(self, handle: ModelHandle) -> None:

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
