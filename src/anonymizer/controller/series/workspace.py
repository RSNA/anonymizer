"""Series View workspace orchestration (load, save, OCR, annotate, face blur, tseg).

Public API
----------
SeriesLoadError
    Raised when DICOM series pixels cannot be loaded for Series View.

SeriesWorkspaceLoad
    Frames, projections, and optional geometry from load_series_workspace.

SeriesViewSaveRequest / SeriesViewSaveResult
    Inputs and outcome for save_series_view_edits (no Tk / ImageViewer).

OcrFrameRemoveResult
    Pixel frame and removed-text metadata after remove_ocr_from_frame.

SeriesWorkspace(project, series_path)
    Session façade for one open series: load, save, OCR job, annotate stroke,
    face-blur eligibility, and TotalSegmentator cache clear.

ocr_results_available_for_edit_context(...) -> bool
ocr_remove_enabled(...) -> bool
edit_context_toolbar_visible(*, single_frame) -> bool
filter_series_view_ocr_overlay(...) -> list[OCRText]
format_ocr_detection_complete_status(...) -> str
clear_cache_button_visible(...) -> bool
blur_face_toolbar_visible(...) -> bool
exclude_rects_fingerprint(...) -> tuple
commit_user_rects_to_exclude(overlay) -> int
    Pure toolbar / OCR helpers used by Series View and unit tests.

Also re-exports View-facing types and helpers (OCR menus, job enums, annotate
session types, face-blur gate types) so view/series/series.py does not import
controller.ai / annotations / jobs leaves directly.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from easyocr import Reader
from pydicom import Dataset

from anonymizer.controller.ai.blur_face import (
    CachedRegionSignal,
    FaceBlurEligibility,
    MetadataSignal,
    cached_region_signal,
    evaluate_face_blur_eligibility,
    metadata_signal,
)
from anonymizer.controller.ai.blur_face import (
    FaceBlurGateDecision as FaceBlurGateDecision,
)
from anonymizer.controller.ai.blur_face import (
    FaceBlurGateReason as FaceBlurGateReason,
)
from anonymizer.controller.ai.blur_face import (
    FaceBlurMode as FaceBlurMode,
)
from anonymizer.controller.ai.blur_face import (
    face_blur_gate_message as face_blur_gate_message,
)
from anonymizer.controller.ai.blur_face import (
    face_blur_status_applicable as face_blur_status_applicable,
)
from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.ai.embedded_phi.entity_labels import entity_label_display
from anonymizer.controller.ai.embedded_phi.ner.cache import download_ner_models
from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS
from anonymizer.controller.ai.embedded_phi.pixel.cache import OCR_LANGS, OCR_MODEL_DIR, download_ocr_models
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    OcrWhitelistMatchMode as OcrWhitelistMatchMode,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    OcrWhitelistMatchSettings,
    PixelPhiRemovalMode,
    build_series_view_ocr_pixels,
    describe_match_settings,
    detect_text,
    filter_ocr_outside_exclude_rects,
    filter_ocr_whitelist_only,
    ocr_image_for_frame,
    save_modality_whitelist_match_settings,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    default_whitelist_match_settings as default_whitelist_match_settings,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    load_modality_whitelist as load_modality_whitelist,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    load_modality_whitelist_match_settings as load_modality_whitelist_match_settings,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    match_mode_description as match_mode_description,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    match_mode_menu_label as match_mode_menu_label,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    match_mode_menu_labels as match_mode_menu_labels,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    normalize_pixel_phi_removal_mode as normalize_pixel_phi_removal_mode,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    pixel_phi_removal_mode_menu_labels as pixel_phi_removal_mode_menu_labels,
)
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    pixel_phi_removal_mode_option_label as pixel_phi_removal_mode_option_label,
)
from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import (
    filter_ocr_for_remove_mode,
)
from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import (
    modality_exclude_rects_for_series as modality_exclude_rects_for_series,
)
from anonymizer.controller.ai.embedded_phi.pixel.exclude_zones import (
    normalize_user_rects as normalize_user_rects,
)
from anonymizer.controller.ai.embedded_phi.pixel.ocr_transcript_sr import cleansed_ocr_lines, write_ocr_report_sr
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import (
    apply_series_view_embedded_phi,
    blackout_rectangular_areas,
    remove_ocr_text_from_frame,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import (
    collect_series_view_embedded_phi_texts as collect_series_view_embedded_phi_texts,
)
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_default_whitelist as load_default_whitelist,
)
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    load_project_exclude_rects as load_project_exclude_rects,
)
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import (
    save_project_exclude_rects,
    save_project_whitelist,
)
from anonymizer.controller.ai.feature_availability import (
    embedded_phi_has_models,
    face_blur_allowed,
)
from anonymizer.controller.ai.feature_availability import (
    harmonize_allowed_for_modality as harmonize_allowed_for_modality,
)
from anonymizer.controller.ai.tseg.cache import TsegCacheSummary, resolve_series_cache_dir, tseg_cache_summary
from anonymizer.controller.ai.tseg.config import TSEG_CACHE_DIRNAME as TSEG_CACHE_DIRNAME
from anonymizer.controller.ai.tseg.dicom_geometry import (
    SeriesGeometryResult,
    ensure_series_geometry,
    load_geometry_cache,
)
from anonymizer.controller.ai.tseg.dicom_geometry import (
    format_series_view_geometry_line as format_series_view_geometry_line,
)
from anonymizer.controller.ai.tseg.dicom_geometry import (
    stackable_dicom_paths as stackable_dicom_paths,
)
from anonymizer.controller.ai.tseg.seg_retention import (
    read_primary_segment_voxels as read_primary_segment_voxels,
)
from anonymizer.controller.ai.tseg.segment import (
    read_cached_segmentation_mode as read_cached_segmentation_mode,
)
from anonymizer.controller.analytics.dataset import upsert_series_ledger_from_cache
from anonymizer.controller.annotations import (
    AnnotateSession,
    ImportProfile,
    add_user_label,
    annotations_exist,
    begin_stroke_capture,
    commit_stroke_undo,
    detect_and_import,
    ensure_series_annotation_geometry,
    ensure_ts_edit,
    load_annotate_session,
    save_annotate_session,
    stamp_brush,
    undo_last_stroke,
)
from anonymizer.controller.annotations.import_nii import AnnotationGeometryUnsupported
from anonymizer.controller.jobs.runner import (
    Algorithm,
    OcrEditContext,
    OcrRemoveMode,
    RunOptions,
    run_job,
)
from anonymizer.controller.jobs.runner import (
    edit_context_display_label as edit_context_display_label,
)
from anonymizer.controller.jobs.runner import (
    edit_context_menu_values as edit_context_menu_values,
)
from anonymizer.controller.jobs.runner import (
    normalize_edit_context as normalize_edit_context,
)
from anonymizer.controller.jobs.runner import (
    normalize_ocr_remove_mode as normalize_ocr_remove_mode,
)
from anonymizer.controller.jobs.runner import (
    ocr_detect_tooltip as ocr_detect_tooltip,
)
from anonymizer.controller.jobs.runner import (
    ocr_remove_mode_display_label as ocr_remove_mode_display_label,
)
from anonymizer.controller.jobs.runner import (
    ocr_remove_mode_menu_labels as ocr_remove_mode_menu_labels,
)
from anonymizer.controller.jobs.runner import (
    ocr_remove_mode_tooltip as ocr_remove_mode_tooltip,
)
from anonymizer.controller.jobs.work_state import WorkState
from anonymizer.controller.project import ProjectController
from anonymizer.controller.series.create_projections import invalidate_projection_cache
from anonymizer.controller.series.series_io import (
    LoadedSeries,
    SeriesProjections,
    compute_series_projections,
    load_series_frames,
    save_series_frames,
)
from anonymizer.controller.series.series_overlay import OCRText, OverlayData, UserRectangle
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.memory import log_process_memory
from anonymizer.utils.modalities import Modality
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class SeriesLoadError(Exception):
    """Raised when DICOM series pixels cannot be loaded for Series View."""


@dataclass(frozen=True)
class SeriesWorkspaceLoad:
    """Payload from load_series_workspace for the Series View open path."""

    loaded: LoadedSeries
    frames: np.ndarray
    projections: SeriesProjections | None
    series_geometry: SeriesGeometryResult | None


@dataclass(frozen=True)
class SeriesViewSaveRequest:
    """Domain inputs for saving Series View pixel / exclude / whitelist edits."""

    series_path: Path
    frames: np.ndarray | None
    dataset: Dataset
    slice_paths: tuple[Path, ...]
    project_dir: Path
    anon_model: AnonymizerModel
    pixel_dirty: bool
    exclude_dirty: bool
    exclude_rects_normalized: list[dict]
    whitelist_items: list[str] | None
    whitelist_match_settings: OcrWhitelistMatchSettings | None
    texts_by_frame: Mapping[int, Sequence[str]]
    ocr_transcript_by_frame: Mapping[int, Sequence[str]]


@dataclass(frozen=True)
class SeriesViewSaveResult:
    """Outcome of save_series_view_edits for the View to apply UI side-effects."""

    ok: bool
    exclude_note: str = ""
    ocr_sr_note: str = ""
    should_close: bool = False
    error_message: str | None = None
    saved_exclude_fingerprint: tuple[tuple[float, float, float, float], ...] = field(
        default_factory=tuple
    )


@dataclass(frozen=True)
class OcrFrameRemoveResult:
    """Result of remove_ocr_from_frame for the View to update overlays and dirty state."""

    frame: np.ndarray
    removed_labels: tuple[str, ...]
    removed_keys: frozenset[tuple[str, tuple[int, int, int, int]]]


def ocr_results_available_for_edit_context(
    edit_context: OcrEditContext,
    *,
    current_frame_index: int,
    overlay_ocr_by_frame: dict[int, list],
) -> bool:
    """True when Detect left OCR overlays usable by Remove for the edit context."""
    if edit_context is OcrEditContext.FRAME:
        return bool(overlay_ocr_by_frame.get(current_frame_index))
    return any(texts for texts in overlay_ocr_by_frame.values())


def ocr_remove_enabled(
    *,
    interaction_allowed: bool,
    detecting: bool,
    results_available: bool,
) -> bool:
    """True when Remove may be clicked: text is identified for the edit context.

    Enablement follows the current Remove Scope filtering of the detected boxes,
    so changing scope never disables Remove while removable text remains in scope.
    """
    return interaction_allowed and not detecting and results_available


def edit_context_toolbar_visible(*, single_frame: bool) -> bool:
    """Show Edit Context only when the series has more than one frame to choose between."""
    return not single_frame


def filter_series_view_ocr_overlay(
    detections: Sequence[OCRText],
    *,
    remove_mode: OcrRemoveMode,
    whitelist: Sequence[str],
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    exclude_rects: Sequence[UserRectangle] | None = None,
) -> list[OCRText]:
    """WYSIWYG overlay: exclude zones, then remove-mode (PHI / whitelist / all)."""
    return filter_ocr_for_remove_mode(
        detections,
        remove_mode=remove_mode,
        whitelist=whitelist,
        whitelist_match_settings=whitelist_match_settings,
        exclude_rects=exclude_rects,
    )


def format_ocr_detection_complete_status(
    detections_by_frame: Mapping[int, Sequence[OCRText]],
    *,
    whitelist: Sequence[str],
    whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    exclude_rects_by_frame: Mapping[int, Sequence[UserRectangle]] | None = None,
    frames_scanned: int | None = None,
    remove_mode: OcrRemoveMode = OcrRemoveMode.NON_WHITELISTED,
) -> str:
    """Status line after Series View detect: totals, NER classes, exclude/whitelist hides."""
    exclude_map = exclude_rects_by_frame or {}
    active: list[OCRText] = []
    excluded = 0
    frames_with_text = 0
    for frame_i, texts in detections_by_frame.items():
        if not texts:
            continue
        kept_spatial = filter_ocr_outside_exclude_rects(texts, exclude_map.get(frame_i))
        excluded += len(texts) - len(kept_spatial)
        if kept_spatial:
            frames_with_text += 1
            active.extend(kept_spatial)
    total = len(active)
    if remove_mode is OcrRemoveMode.NON_WHITELISTED:
        shown = filter_ocr_whitelist_only(
            active,
            whitelist=whitelist,
            whitelist_match_settings=whitelist_match_settings,
        )
        whitelisted = max(0, total - len(shown))
    else:
        whitelisted = 0

    ner_counts: Counter[str] = Counter()
    unlabeled = 0
    for item in active:
        label = (item.phi_label or "").strip().upper()
        if label:
            ner_counts[label] += 1
        else:
            unlabeled += 1

    ner_parts: list[str] = []
    for label in SCORED_LABELS:
        n = ner_counts.get(label, 0)
        if n:
            ner_parts.append(f"{entity_label_display(label)} {n}")
    for label, n in sorted(ner_counts.items()):
        if label not in SCORED_LABELS and n:
            ner_parts.append(f"{entity_label_display(label)} {n}")
    if unlabeled:
        ner_parts.append(f"{_('unlabeled')} {unlabeled}")

    status = _("Text detection complete") + f": {total} " + _("detections")
    if ner_parts:
        status += f" ({', '.join(ner_parts)})"
    if excluded:
        status += f"; {excluded} " + _("excluded")
    if whitelisted:
        status += f"; {whitelisted} " + _("whitelisted")
    if frames_scanned is not None:
        status += f", {frames_with_text}/{frames_scanned} " + _("frames with text")
    return status


def clear_cache_button_visible(
    *,
    modality: str | None,
    already_harmonized: bool,
    has_segment_masks: bool = False,
) -> bool:
    """Show Clear when Harmonize completed or orphan segment masks remain on disk."""
    return Modality.from_code(modality) in {Modality.CT, Modality.MR} and (
        already_harmonized or has_segment_masks
    )


def blur_face_toolbar_visible(
    *,
    face_blur_models_ready: bool,
    face_blur_already_applied: bool,
    is_head_series: bool,
) -> bool:
    """Show Face Blur when models are ready, series is head, and ORM flag is unset."""
    if not face_blur_models_ready:
        return False
    if face_blur_already_applied:
        return False
    return is_head_series


def _exclude_rect_key(rect: dict) -> tuple[float, float, float, float]:
    return (
        round(float(rect["x1"]), 4),
        round(float(rect["y1"]), 4),
        round(float(rect["x2"]), 4),
        round(float(rect["y2"]), 4),
    )


def exclude_rects_fingerprint(
    rects: Sequence[dict],
) -> tuple[tuple[float, float, float, float], ...]:
    """Stable fingerprint of normalized exclude rect dicts."""
    return tuple(sorted(_exclude_rect_key(rect) for rect in rects))


def commit_user_rects_to_exclude(overlay: OverlayData) -> int:
    """
    Move pending user_rects onto exclude_rects for one frame overlay.

    Args:
        overlay: Frame overlay whose drawn rects should become exclude zones.

    Returns:
        Number of rectangles moved (0 when none pending).
    """
    pending = list(overlay.user_rects)
    if not pending:
        return 0
    overlay.exclude_rects.extend(pending)
    overlay.user_rects.clear()
    return len(pending)


def _persist_exclude_areas_note(
    project_dir: Path,
    modality: str,
    rects: list[dict],
) -> tuple[str, tuple[tuple[float, float, float, float], ...]]:
    save_project_exclude_rects(project_dir, modality, rects)
    fingerprint = exclude_rects_fingerprint(rects)
    if not rects:
        note = " — " + _("cleared exclude areas for {modality}").format(
            modality=modality.upper() or "?",
        )
    else:
        note = " — " + _("saved {count} exclude area(s) for {modality}").format(
            count=len(rects),
            modality=modality.upper() or "?",
        )
    return note, fingerprint


def _promote_ocr_report_note(
    series_path: Path,
    dataset: Dataset,
    ocr_transcript_by_frame: Mapping[int, Sequence[str]],
) -> tuple[str, bool]:
    """Write Basic Text SR for pixel text reports; return status suffix and whether cleared."""
    modality = str(getattr(dataset, "Modality", "") or "")
    if classify_series(series_path, modality=modality) is not SeriesKind.PIXEL_TEXT_REPORT:
        return "", False
    lines = cleansed_ocr_lines(dict(ocr_transcript_by_frame))
    out = write_ocr_report_sr(series_path, lines)
    if out is None:
        return "", False
    return " — " + _("Basic Text SR written for research use"), True


class SeriesWorkspace:
    """Session façade for one open series in Series View."""

    def __init__(self, project: ProjectController, series_path: Path) -> None:
        self.project = project
        self.series_path = Path(series_path)
        self._series_geometry: SeriesGeometryResult | None = None
        self._face_blur_eligibility_cache: FaceBlurEligibility | None = None
        self._face_blur_eligibility_geometry: SeriesGeometryResult | None = None

    def load_series_workspace(
        self,
        *,
        dcm_paths: list[Path] | None = None,
    ) -> SeriesWorkspaceLoad:
        """
        Load frames, optional projections, and cached geometry for CT/MR.

        Args:
            dcm_paths: Optional precomputed stackable DICOM paths.

        Returns:
            SeriesWorkspaceLoad for the View finish-loading path.

        Raises:
            SeriesLoadError: When frames cannot be loaded.
            ValueError, FileNotFoundError, PermissionError: Propagated from loaders.
        """
        series_path = self.series_path
        log_process_memory("load_series_data_start", extra=str(series_path.name))
        loaded = load_series_frames(series_path, dcm_paths=dcm_paths)
        frames = loaded.frames
        projections = compute_series_projections(frames) if not loaded.is_single_frame else None

        log_process_memory(
            "after_load_series",
            array=frames,
            extra=str(series_path.name),
        )

        series_geometry: SeriesGeometryResult | None = None
        if Modality.from_code(getattr(loaded.metadata, "Modality", None)) in {Modality.CT, Modality.MR}:
            series_geometry = load_geometry_cache(series_path)
            self._series_geometry = series_geometry

        log_process_memory(
            "load_series_data_done",
            array=frames,
            extra=str(series_path.name),
        )
        return SeriesWorkspaceLoad(
            loaded=loaded,
            frames=frames,
            projections=projections,
            series_geometry=series_geometry,
        )

    def ensure_geometry(self, *, ds: Dataset | None) -> SeriesGeometryResult | None:
        """
        Ensure series geometry is loaded/cached for the open series.

        Args:
            ds: Current series metadata dataset.

        Returns:
            Geometry result, or None when not applicable.
        """
        self._series_geometry = ensure_series_geometry(
            self.series_path,
            ds=ds,
            cached=self._series_geometry,
        )
        return self._series_geometry

    def set_geometry_cache(self, geometry: SeriesGeometryResult | None) -> None:
        """Replace the in-session geometry cache (e.g. after Harmonize)."""
        self._series_geometry = geometry
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None

    def cache_dir(self) -> Path:
        """Series TotalSegmentator / annotation cache directory."""
        return resolve_series_cache_dir(self.series_path)

    def seg_dir(self) -> Path:
        """Primary segment mask directory under the series cache."""
        return self.cache_dir() / "seg"

    def face_blur_eligibility(
        self,
        *,
        ds: Dataset | None,
        already_applied: bool,
    ) -> FaceBlurEligibility:
        """
        Cached face-blur gate decision for the open series.

        Args:
            ds: Current series metadata dataset.
            already_applied: True when the series already has face blur in the project model.

        Returns:
            FaceBlurEligibility (same object while geometry identity is unchanged).
        """
        geometry = self.ensure_geometry(ds=ds)
        if (
            self._face_blur_eligibility_cache is not None
            and geometry is self._face_blur_eligibility_geometry
        ):
            return self._face_blur_eligibility_cache
        eligibility = evaluate_face_blur_eligibility(
            self.series_path,
            ds=ds,
            geometry=geometry,
            enable_tseg_face=face_blur_allowed(),
            face_blur_already_applied=already_applied,
        )
        self._face_blur_eligibility_cache = eligibility
        self._face_blur_eligibility_geometry = geometry
        return eligibility

    def ensure_annotate_session(
        self,
        *,
        existing: AnnotateSession | None,
        frames: np.ndarray | None,
    ) -> AnnotateSession | None:
        """
        Load or create annotation geometry for the open series.

        Args:
            existing: Current View-held session, if any (reused when shape matches).
            frames: Reference pixel volume for geometry size checks.

        Returns:
            AnnotateSession, or None when geometry is unsupported / unavailable.
        """
        if existing is not None and frames is not None:
            z, y, x = frames.shape[:3]
            if existing.labels.shape == (z, y, x):
                return existing
            logger.warning(
                "Annotation labels shape %s does not match frames %s; recreating",
                existing.labels.shape,
                (z, y, x),
            )
        try:
            return ensure_series_annotation_geometry(
                self.series_path,
                self.cache_dir(),
                reference_frames=frames,
            )
        except AnnotationGeometryUnsupported as exc:
            logger.info("%s", exc)
            return None
        except Exception:
            logger.exception("Could not ensure annotation geometry for %s", self.series_path)
            return load_annotate_session(self.cache_dir())

    def apply_annotate_stroke(
        self,
        session: AnnotateSession,
        *,
        volume: np.ndarray,
        slice_index: int,
        cy: int,
        cx: int,
        radius: int,
        value: int,
        stroke_before: np.ndarray | None,
    ) -> np.ndarray:
        """
        Capture stroke undo baseline if needed and stamp the brush.

        Args:
            session: Active annotate session (marked dirty).
            volume: Label or TS-edit volume being painted.
            slice_index: Anatomical slice index.
            cy: Brush center row.
            cx: Brush center column.
            radius: Brush radius in pixels.
            value: Label value to stamp (0 erases).
            stroke_before: Prior capture for this stroke, or None to start one.

        Returns:
            Stroke-before slice capture for finish_annotate_stroke.
        """
        if stroke_before is None:
            stroke_before = begin_stroke_capture(volume, slice_index=slice_index)
        stamp_brush(volume, slice_index=slice_index, cy=cy, cx=cx, radius=radius, value=value)
        session.dirty = True
        return stroke_before

    def finish_annotate_stroke(
        self,
        session: AnnotateSession,
        *,
        kind: str,
        structure_name: str | None,
        slice_index: int,
        before_slice: np.ndarray,
    ) -> None:
        """
        Commit one completed stroke onto the session undo stack.

        Args:
            session: Active annotate session.
            kind: Stroke kind (user or ts_edit).
            structure_name: Structure name for TS edits, else None.
            slice_index: Anatomical slice index.
            before_slice: Capture from apply_annotate_stroke.
        """
        commit_stroke_undo(
            session,
            kind=kind,  # type: ignore[arg-type]
            structure_name=structure_name,
            slice_index=slice_index,
            before_slice=before_slice,
        )

    def flush_annotate_session(
        self,
        session: AnnotateSession | None,
        *,
        update_ledger: bool = True,
    ) -> None:
        """
        Persist a dirty annotate session to disk (and optionally the series ledger).

        Args:
            session: Session to flush, or None (no-op).
            update_ledger: When True, upsert analytics ledger from the cache dir.
        """
        if session is None or not session.dirty:
            return
        try:
            save_annotate_session(session)
            if update_ledger:
                upsert_series_ledger_from_cache(session.cache_dir)
        except Exception:
            logger.exception("Failed to save annotations")

    def tseg_cache_info(self) -> tuple[TsegCacheSummary, bool]:
        """
        Cache summary and whether ROI annotations exist under the series cache.

        Returns:
            (tseg_cache_summary result, annotations_exist).
        """
        return tseg_cache_summary(self.series_path), annotations_exist(self.cache_dir())

    def clear_series_tseg_cache(
        self,
        *,
        anon_series_uid: str | None,
        also_clear_annotations: bool,
    ) -> None:
        """
        Clear TotalSegmentator cache (and optionally annotations) via ProjectController.

        Args:
            anon_series_uid: Anonymized series UID for ledger/ORM updates.
            also_clear_annotations: When True, also remove ROI annotation files.
        """
        self.project.clear_series_tseg_cache(
            self.series_path,
            anon_series_uid=anon_series_uid,
            also_clear_annotations=also_clear_annotations,
        )
        self.set_geometry_cache(None)

    def prepare_ocr_job(
        self,
        work_state: WorkState,
        *,
        ds: Dataset,
        frames: np.ndarray,
        slice_paths: tuple[Path, ...],
        default_window: tuple[float, float],
        single_frame: bool,
        edit_context: OcrEditContext,
        frame_index: int,
        ocr_source_images: np.ndarray | None,
    ) -> RunOptions:
        """
        Bind WorkState for Series View OCR detect and return RunOptions.

        Args:
            work_state: Shared job state polled by the View.
            ds: Series metadata dataset.
            frames: Pixel volume.
            slice_paths: Per-slice DICOM paths.
            default_window: Window level / width for the series.
            single_frame: True when the series has one frame.
            edit_context: Frame vs series detect scope.
            frame_index: Current viewer frame when edit_context is FRAME.
            ocr_source_images: Optional viewer pixel stack for OCR (same layout as frames).

        Returns:
            RunOptions for run_ocr_job / run_job.
        """
        work_state.reset()
        work_state.bind(
            ds,
            frames,
            slice_paths,
            default_window,
            single_frame=single_frame,
        )
        if ocr_source_images is not None:
            work_state.ocr_pixels = build_series_view_ocr_pixels(ocr_source_images, ds)
        if edit_context is OcrEditContext.FRAME:
            work_state.frame_index = frame_index
        return RunOptions(
            edit_context=edit_context,
            whitelist=[],
            project_dir=self.project.model.storage_dir,
        )

    def run_ocr_job(self, work_state: WorkState, options: RunOptions) -> None:
        """
        Run OCR detect on a worker thread via the shared job runner.

        Args:
            work_state: Bound job state from prepare_ocr_job.
            options: Options from prepare_ocr_job.
        """
        run_job(Algorithm.REMOVE_PIXEL_PHI, work_state, options=options)

    def detect_text_on_frame_sync(self, *, ds: Dataset, frame: np.ndarray) -> list[OCRText]:
        """
        Synchronous single-frame OCR (fallback path; prefer background prepare_ocr_job).

        Args:
            ds: Series metadata dataset.
            frame: Raw pixel frame from the viewer stack.

        Returns:
            Detected OCRText boxes (may be empty).
        """
        if not embedded_phi_has_models():
            download_ocr_models()
            download_ner_models()
        reader = Reader(lang_list=list(OCR_LANGS), model_storage_directory=str(OCR_MODEL_DIR))
        bgr = ocr_image_for_frame(ds, frame)
        results = detect_text(
            bgr,
            reader,
            draw_boxes_and_text=False,
            modality=str(ds.get("Modality", "") or ""),
            apply_noise_filter=False,
            apply_phi_ner_filter=False,
            annotate_phi_labels=True,
        )
        return list(results or [])

    def remove_ocr_from_frame(
        self,
        *,
        raw_frame: np.ndarray,
        windowed_frame: np.ndarray,
        ocr_texts: list[OCRText],
        exclude_rects: Sequence[UserRectangle] | None,
        removal_mode: PixelPhiRemovalMode,
    ) -> OcrFrameRemoveResult | None:
        """
        Filter exclude zones and remove OCR text from one frame's pixels.

        Mutates ``ocr_texts`` in place (clears when removal applied).

        Args:
            raw_frame: Source pixel frame to mutate.
            windowed_frame: Windowed BGR used for text localization.
            ocr_texts: Detected boxes to remove (filtered in place for excludes).
            exclude_rects: Optional exclude zones to skip.
            removal_mode: Pixel PHI removal mode.

        Returns:
            OcrFrameRemoveResult, or None when nothing remains after exclude filter.
        """
        ocr_texts[:] = filter_ocr_outside_exclude_rects(ocr_texts, exclude_rects)
        if not ocr_texts:
            logger.info("No OCR text remains to remove after exclude-rect filter")
            return None
        removed_keys = frozenset((t.text, t.get_bounding_box()) for t in ocr_texts)
        removed_labels = tuple(t.text.strip() for t in ocr_texts if (t.text or "").strip())
        new_frame = remove_ocr_text_from_frame(
            raw_frame,
            windowed_frame,
            ocr_texts,
            removal_mode=removal_mode,
        )
        ocr_texts.clear()
        return OcrFrameRemoveResult(
            frame=new_frame,
            removed_labels=removed_labels,
            removed_keys=removed_keys,
        )

    def blackout_rects_on_frame(
        self,
        frame: np.ndarray,
        user_rects: list[UserRectangle],
    ) -> None:
        """
        Black out pending user rectangles on one frame and clear the list.

        Args:
            frame: Pixel frame mutated in place.
            user_rects: Rectangles to black out (cleared after apply).
        """
        blackout_rectangular_areas(frame, user_rects)
        user_rects.clear()

    def save_series_view_edits(self, request: SeriesViewSaveRequest) -> SeriesViewSaveResult:
        """
        Persist whitelist / exclude / pixel edits for the open series.

        Args:
            request: Domain inputs collected by the View (no Tk widgets).

        Returns:
            SeriesViewSaveResult describing status notes and whether to close the window.
        """
        dataset = request.dataset
        modality = str(dataset.get("Modality", "") or "")
        project_dir = request.project_dir
        exclude_note = ""
        fingerprint = exclude_rects_fingerprint(request.exclude_rects_normalized)

        if request.whitelist_items is not None and modality:
            try:
                path = save_project_whitelist(project_dir, modality, request.whitelist_items)
                logger.info("Saved series whitelist path=%s", path)
            except Exception as exc:
                logger.error("Error saving whitelist: %s", exc)

        if request.whitelist_match_settings is not None and modality:
            try:
                options_path = save_modality_whitelist_match_settings(
                    project_dir,
                    modality,
                    request.whitelist_match_settings,
                )
                logger.info(
                    "Saved whitelist match settings path=%s mode=%s",
                    options_path,
                    describe_match_settings(request.whitelist_match_settings),
                )
            except Exception as exc:
                logger.error("Error saving whitelist match settings: %s", exc)

        if not request.pixel_dirty:
            if request.exclude_dirty:
                exclude_note, fingerprint = _persist_exclude_areas_note(
                    project_dir,
                    modality,
                    list(request.exclude_rects_normalized),
                )
            return SeriesViewSaveResult(
                ok=True,
                exclude_note=exclude_note,
                should_close=False,
                saved_exclude_fingerprint=fingerprint,
            )

        if request.frames is None:
            return SeriesViewSaveResult(
                ok=False,
                error_message=_("Failed to save changes to series frames"),
            )

        if not save_series_frames(request.series_path, request.frames, dataset):
            logger.error("Failed to save series frames to %s", request.series_path)
            return SeriesViewSaveResult(
                ok=False,
                error_message=_("Failed to save changes to series frames"),
            )

        logger.info("Saved series frames to %s", request.series_path)
        invalidate_projection_cache(request.series_path)

        anon_series_uid = str(dataset.SeriesInstanceUID)
        texts_by_frame = {int(k): list(v) for k, v in request.texts_by_frame.items()}
        if texts_by_frame:
            apply_series_view_embedded_phi(
                request.anon_model,
                request.slice_paths,
                texts_by_frame,
                projection_frame_count=0,
                anon_series_uid=anon_series_uid,
            )
        elif request.pixel_dirty:
            request.anon_model.set_series_embedded_phi_scanned(anon_series_uid, scanned=True)

        if request.exclude_dirty:
            exclude_note, fingerprint = _persist_exclude_areas_note(
                project_dir,
                modality,
                list(request.exclude_rects_normalized),
            )

        ocr_sr_note, _cleared = _promote_ocr_report_note(
            request.series_path,
            dataset,
            request.ocr_transcript_by_frame,
        )
        return SeriesViewSaveResult(
            ok=True,
            exclude_note=exclude_note,
            ocr_sr_note=ocr_sr_note,
            should_close=True,
            saved_exclude_fingerprint=fingerprint,
        )

    def is_head_series(self, ds: Dataset | None) -> bool:
        """True when cached anatomy or DICOM metadata indicates a head series."""
        return (
            cached_region_signal(self.series_path) == CachedRegionSignal.HEAD
            or metadata_signal(ds) == MetadataSignal.HEAD
        )

    def undo_annotate_stroke(self, session: AnnotateSession) -> bool:
        """Undo the last annotate stroke on the session."""
        return undo_last_stroke(session)

    def ensure_ts_edit_volume(
        self,
        session: AnnotateSession,
        name: str,
        *,
        source_mask: np.ndarray,
    ) -> np.ndarray:
        """Ensure a TotalSegmentator edit volume exists for structure ``name``."""
        return ensure_ts_edit(session, name, source_mask=source_mask)

    def add_annotate_user_label(
        self,
        session: AnnotateSession,
        name: str,
        *,
        normative_organ: str | None = None,
    ):
        """Add a user annotation label to the session."""
        return add_user_label(session, name, normative_organ=normative_organ)

    def import_annotate_segments(
        self,
        session: AnnotateSession,
        *,
        paths: list[Path] | None,
        folder: Path | None,
        profile: ImportProfile,
    ):
        """Import researcher segment volumes into the annotate session."""
        return detect_and_import(session, paths=paths, folder=folder, profile=profile)
