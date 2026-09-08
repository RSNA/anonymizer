"""Sequential AI batch processing for PHI Index study selection."""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from pydicom.errors import InvalidDicomError

from anonymizer.controller.ai.blur_face import (
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    SeriesVolumeContext,
    apply_series_face_blur_metadata,
    evaluate_face_blur_eligibility,
    face_blur_gate_message,
    face_blur_mode_display_label,
    format_face_blur_progress_status,
    preview_blurred_slice_frames,
    preview_face_blur,
)
from anonymizer.controller.ai.harmonize import (
    HarmonizeProgress,
    auto_apply_best_study_descriptions,
    format_harmonize_progress_message,
    harmonize_and_apply_series,
)
from anonymizer.controller.ai.harmonize.pipeline import (
    _load_harmonize_series_dataset,
    _load_series_dataset,
    _load_tseg_series_dataset,
)
from anonymizer.controller.ai.remove_pixel_phi import (
    OcrWhitelistMatchSettings,
    PixelPhiRemovalMode,
    apply_instance_pixel_phi_for_dcm,
    describe_match_settings,
    load_modality_whitelist,
    load_modality_whitelist_match_settings,
    pixel_phi_removal_mode_display_label,
    remove_pixel_phi,
)
from anonymizer.controller.ai.tseg.config import segmentation_mode_for_modality
from anonymizer.controller.ai.tseg.contrast import release_working_memory
from anonymizer.controller.ai.tseg.dicom_geometry import resolve_series_geometry, stackable_dicom_paths
from anonymizer.controller.runner import (
    Algorithm,
    enter_batch_phase,
    exit_batch_phase,
)
from anonymizer.controller.series_io import load_series_frames, save_series_frames
from anonymizer.utils.memory import MemoryGuard, MemorySnapshot, capture_memory_snapshot, collect_garbage_safe
from anonymizer.utils.translate import _

if TYPE_CHECKING:
    from easyocr import Reader

    from anonymizer.controller.anonymizer import AnonymizerController
    from anonymizer.controller.work_state import WorkState
    from anonymizer.model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)


class AiBatchAlgorithm(StrEnum):
    REMOVE_PIXEL_PHI = auto()
    HARMONIZE = auto()
    FACE_BLUR = auto()


CANONICAL_ALGORITHM_ORDER: tuple[AiBatchAlgorithm, ...] = (
    AiBatchAlgorithm.REMOVE_PIXEL_PHI,
    AiBatchAlgorithm.HARMONIZE,
    AiBatchAlgorithm.FACE_BLUR,
)

AI_BATCH_TO_RUNNER: dict[AiBatchAlgorithm, Algorithm] = {
    AiBatchAlgorithm.REMOVE_PIXEL_PHI: Algorithm.REMOVE_PIXEL_PHI,
    AiBatchAlgorithm.HARMONIZE: Algorithm.HARMONIZE,
    AiBatchAlgorithm.FACE_BLUR: Algorithm.FACE_BLUR,
}


@dataclass(frozen=True)
class AiBatchProcessOptions:
    algorithms: tuple[AiBatchAlgorithm, ...]
    blur_mode: FaceBlurMode = FaceBlurMode.GAUSSIAN
    pixel_phi_removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT
    use_modality_whitelist: bool = True
    include_brain_structures: bool = False


def whitelist_for_batch_ocr(*, use_modality_whitelist: bool) -> list[str] | None:
    """Return OCR whitelist for batch removal: None loads effective whitelist, [] disables filtering."""
    return None if use_modality_whitelist else []


def modalities_in_selected_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> tuple[str, ...]:
    """Collect unique DICOM modalities for series under the selected studies."""
    modalities: set[str] = set()
    for anon_patient_id, anon_study_uid in studies:
        study_path = images_dir / anon_patient_id / anon_study_uid
        if not study_path.is_dir():
            continue
        for series_path in sorted(
            (p for p in study_path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        ):
            with contextlib.suppress(ValueError, InvalidDicomError, AttributeError, OSError):
                ds = _load_series_dataset(series_path)
                modality = str(ds.get("Modality", "") or "").strip().upper()
                if modality:
                    modalities.add(modality)
    return tuple(sorted(modalities))


def effective_modality_whitelists(
    project_dir: Path | None,
    modalities: Sequence[str],
) -> dict[str, list[str]]:
    """Return effective whitelist terms per modality (same as batch OCR uses)."""
    return {modality: load_modality_whitelist(project_dir, modality) for modality in modalities}


def effective_modality_whitelist_match_settings(
    project_dir: Path | None,
    modalities: Sequence[str],
) -> dict[str, OcrWhitelistMatchSettings]:
    """Return per-modality OCR whitelist match settings (sidecar or defaults)."""
    return {
        modality: load_modality_whitelist_match_settings(project_dir, modality) for modality in modalities
    }


def format_modality_whitelist_heading(modality: str, term_count: int) -> str:
    """Single-line modality section heading for whitelist preview."""
    term_label = _("term") if term_count == 1 else _("terms")
    return f"{modality} ({term_count} {term_label})"


def format_modality_whitelist_preview(
    whitelists_by_modality: dict[str, list[str]],
    *,
    no_modalities_message: str,
    no_terms_label: str,
    match_settings_by_modality: dict[str, OcrWhitelistMatchSettings] | None = None,
) -> str:
    """Format read-only whitelist preview text grouped by modality."""
    if not whitelists_by_modality:
        return no_modalities_message

    sections: list[str] = []
    for modality in sorted(whitelists_by_modality):
        terms = whitelists_by_modality[modality]
        header = format_modality_whitelist_heading(modality, len(terms))
        match_line = ""
        if match_settings_by_modality and modality in match_settings_by_modality:
            match_line = f"\n  {_('Match strictness')}: {describe_match_settings(match_settings_by_modality[modality])}"
        body = (
            "\n".join(f"  {term}" for term in terms)
            if terms
            else f"  {no_terms_label}"
        )
        sections.append(f"{header}{match_line}\n{body}")
    return "\n\n".join(sections)


@dataclass(frozen=True)
class AiBatchOutcome:
    series_path: Path
    algorithm: AiBatchAlgorithm
    status: str
    message: str = ""


@dataclass(frozen=True)
class AiBatchAlgorithmTotals:
    applied: int = 0
    complete: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def modified(self) -> int:
        """Series this algorithm changed (pixels, description, or face blur)."""
        return self.applied


@dataclass(frozen=True)
class AiBatchSummary:
    processed: int = 0
    skipped: int = 0
    applied: int = 0
    failed: int = 0
    cancelled: bool = False
    series_count: int = 0
    algorithm_totals: tuple[tuple[AiBatchAlgorithm, AiBatchAlgorithmTotals], ...] = ()
    # Anonymized study UIDs that became fully Harmonized during this run (study desc still empty).
    newly_harmonized_study_uids: tuple[str, ...] = ()


AiBatchProgressCallback = Callable[
    [int, int, AiBatchAlgorithm, int, int, str, float],
    None,
]
AiBatchCancelledCallback = Callable[[], bool]
AiBatchWorkflowLogCallback = Callable[[str], None]
AiBatchMemoryCallback = Callable[[MemorySnapshot], None]

SeriesItem = tuple[int, int, Path]


def missing_series_description_label() -> str:
    return f"<{_('No Series Description')}>"


def _series_description(ds) -> str:
    if ds is None:
        return missing_series_description_label()
    description = str(ds.get("SeriesDescription", "") or "").strip()
    if description:
        return f'"{description}"'
    return missing_series_description_label()


def format_ai_batch_position(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
) -> str:
    position = _("Study") + f" {study_index}/{study_total}" if study_total > 1 else _("Study") + " 1/1"
    if series_total > 1:
        position += " · " + _("Series") + f" {series_index}/{series_total}"
    elif series_total == 1:
        position += " · " + _("Series") + " 1/1"
    return position


def strip_progress_pct_suffix(text: str) -> str:
    """Remove a trailing `` (NN%)`` suffix from progress status text."""
    return re.sub(r" \(\d+%\)$", "", text.rstrip())


def format_ai_batch_status_line(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    ds=None,
) -> str:
    """Progress label: current study/series position and description only."""
    return format_batch_series_context(
        study_index=study_index,
        study_total=study_total,
        series_index=series_index,
        series_total=series_total,
        ds=ds,
    )


def format_batch_workflow_log_line(message: str) -> str:
    if not message:
        return "\n"
    return f"{message}\n"


def format_batch_phase_banner(algorithm: AiBatchAlgorithm) -> str:
    return f"=== {algorithm_display_name(algorithm)} ==="


def format_batch_step_subline(message: str) -> str:
    return f"  {message.rstrip()}"


def _normalize_workflow_log_key(message: str) -> str:
    """Normalize progress text for duplicate detection in the workflow log."""
    text = strip_progress_pct_suffix(message).strip().rstrip("…").strip()
    return text.casefold()


def format_ai_batch_completion_summary(summary: AiBatchSummary) -> str:
    """User-facing batch completion summary with per-algorithm modified series counts."""
    series_count = summary.series_count
    series_label = _("series") if series_count == 1 else _("series")
    lines = [_("Complete") + f": {series_count} {series_label}"]
    for algorithm, totals in summary.algorithm_totals:
        if totals.modified <= 0:
            continue
        name = algorithm_display_name(algorithm)
        lines.append(f"  {name}: {totals.modified} " + _("modified"))
    return "\n".join(lines)


def should_log_harmonize_batch_step(progress: HarmonizeProgress) -> bool:
    """Keep batch harmonize logs concise; manual Harmonize dialog shows every stage."""
    message = (progress.message or "").strip()
    stage = progress.stage
    if stage in {"done", "failed", "tseg", "prepare", "merge", "contrast"}:
        return False
    if message in {
        "Anatomy regions summarized",
        "Analyzing contrast phase",
        "Contrast phase analysis complete",
        "Building harmonized description",
        "Harmonized description ready",
        "Segmenting anatomy",
        "Starting contrast phase analysis",
        "Summarizing anatomy regions",
    }:
        return False
    return not (stage == "segment" and "Anatomy" not in message and "cached" not in message.lower())


def format_batch_log_series_label(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    ds=None,
) -> str:
    """Study/series label for the workflow log (matches progress status line)."""
    return format_batch_series_context(
        study_index=study_index,
        study_total=study_total,
        series_index=series_index,
        series_total=series_total,
        ds=ds,
    )


def format_batch_series_context(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    ds=None,
) -> str:
    position = format_ai_batch_position(
        study_index=study_index,
        study_total=study_total,
        series_index=series_index,
        series_total=series_total,
    )
    description = _series_description(ds)
    return f"{position} · {description}"


def format_batch_series_header(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    ds=None,
) -> str:
    return format_batch_workflow_log_line(
        format_batch_log_series_label(
            study_index=study_index,
            study_total=study_total,
            series_index=series_index,
            series_total=series_total,
            ds=ds,
        )
    )


def face_blur_skip_counts_as_complete(outcome: AiBatchOutcome) -> bool:
    """Ineligible face-blur skips log as Skipped but count as complete in batch totals."""
    if outcome.algorithm is not AiBatchAlgorithm.FACE_BLUR or outcome.status != "skipped":
        return False
    message = outcome.message or ""
    if message == _("Face blur already applied"):
        return False
    for reason in FaceBlurGateReason:
        if reason in {
            FaceBlurGateReason.ALREADY_APPLIED,
            FaceBlurGateReason.INSUFFICIENT_FACE_MASK,
        }:
            continue
        if message == face_blur_gate_message(reason):
            return True
    return message in {_("Not a CT series"), _("Not a CT/MR series")}


def harmonize_skip_counts_as_complete(outcome: AiBatchOutcome) -> bool:
    """Ineligible Harmonize skips (SC/OT/DOC, etc.) count as complete in batch totals."""
    if outcome.algorithm is not AiBatchAlgorithm.HARMONIZE or outcome.status != "skipped":
        return False
    return (outcome.message or "") == _("Not a CT/MR/XR/US/MG series or no DICOM files")


def _increment_algorithm_totals(
    totals: AiBatchAlgorithmTotals,
    outcome: AiBatchOutcome,
) -> AiBatchAlgorithmTotals:
    if outcome.status == "ok":
        return AiBatchAlgorithmTotals(
            applied=totals.applied + 1,
            complete=totals.complete,
            skipped=totals.skipped,
            failed=totals.failed,
        )
    if outcome.status == "complete":
        return AiBatchAlgorithmTotals(
            applied=totals.applied,
            complete=totals.complete + 1,
            skipped=totals.skipped,
            failed=totals.failed,
        )
    if outcome.status == "skipped":
        if face_blur_skip_counts_as_complete(outcome) or harmonize_skip_counts_as_complete(outcome):
            return AiBatchAlgorithmTotals(
                applied=totals.applied,
                complete=totals.complete + 1,
                skipped=totals.skipped,
                failed=totals.failed,
            )
        return AiBatchAlgorithmTotals(
            applied=totals.applied,
            complete=totals.complete,
            skipped=totals.skipped + 1,
            failed=totals.failed,
        )
    if outcome.status == "failed":
        return AiBatchAlgorithmTotals(
            applied=totals.applied,
            complete=totals.complete,
            skipped=totals.skipped,
            failed=totals.failed + 1,
        )
    return totals


def format_batch_outcome_subline(outcome: AiBatchOutcome) -> str:
    if outcome.status == "ok":
        label = _("Applied")
        detail = outcome.message or _("Complete")
    elif outcome.status == "complete":
        label = _("Complete")
        detail = outcome.message or ""
    elif outcome.status == "skipped":
        label = _("Skipped")
        detail = outcome.message or ""
    else:
        label = _("Failed")
        detail = outcome.message or _("Unknown error")
    if detail:
        return format_batch_step_subline(f"{label}: {detail}")
    return format_batch_step_subline(label)


def format_batch_algorithm_result_line(
    *,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    algorithm: AiBatchAlgorithm,
    outcome: AiBatchOutcome,
    ds=None,
) -> str:
    context = format_batch_log_series_label(
        study_index=study_index,
        study_total=study_total,
        series_index=series_index,
        series_total=series_total,
        ds=ds,
    )
    outcome_line = format_batch_outcome_subline(outcome)
    return format_batch_workflow_log_line(f"{context}\n{outcome_line}")


def _unique_non_empty_texts(texts: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for text in texts:
        stripped = str(text).strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return unique


def _format_quoted_texts(texts: Sequence[str], *, max_shown: int = 6) -> str:
    unique = _unique_non_empty_texts(texts)
    if not unique:
        return ""
    shown = unique[:max_shown]
    parts = ", ".join(f'"{item}"' for item in shown)
    remaining = len(unique) - len(shown)
    if remaining > 0:
        parts += f" (+{remaining} " + _("more") + ")"
    return parts


def format_remove_pixel_phi_series_message(
    *,
    modified_count: int,
    total: int,
    texts_removed: Sequence[str],
    pixels_changed: int = 0,
    removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
) -> str:
    summary = _("Modified") + f" {modified_count}/{total}"
    text_summary = _format_quoted_texts(texts_removed)
    if text_summary:
        summary = f"{summary} · {_('removed')}: {text_summary}"
    if pixels_changed > 0:
        if removal_mode is PixelPhiRemovalMode.BLACKOUT:
            summary += f" · {pixels_changed:,} {_('pixels blacked out')}"
        else:
            summary += f" · {pixels_changed:,} {_('pixels modified')}"
    return summary


def format_remove_pixel_phi_instance_detail(
    *,
    instance_index: int,
    instance_total: int,
    modified: bool,
    texts: Sequence[str],
    removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
    pixels_changed: int = 0,
) -> str:
    position = _("Instance") + f" {instance_index}/{instance_total}"
    text_summary = _format_quoted_texts(texts, max_shown=8)
    if modified and text_summary:
        action = pixel_phi_removal_mode_display_label(removal_mode)
        detail = f"{position}: {action} {text_summary}"
        if pixels_changed > 0:
            detail += f" ({pixels_changed:,} {_('px')})"
        return detail
    if text_summary:
        return f"{position}: {_('detected')} {text_summary} ({_('pixels unchanged')})"
    return f"{position}: {_('no burnt-in text detected')}"


def _log_workflow_progress_step(
    log_workflow: Callable[[str], None],
    step_progress: Callable[[float, str], None],
    *,
    fraction: float,
    message: str,
    stage_key: str | None,
    last_stage_key: list[str | None],
    skip_log: bool = False,
) -> None:
    step_progress(fraction, message)
    if skip_log:
        return
    log_line = strip_progress_pct_suffix(message).strip()
    if not log_line:
        return
    dedupe_key = _normalize_workflow_log_key(log_line)
    if dedupe_key and dedupe_key == last_stage_key[0]:
        return
    last_stage_key[0] = dedupe_key
    log_workflow(format_batch_step_subline(log_line))


def _prepare_ct_volume_context(series_path: Path) -> SeriesVolumeContext | None:
    with contextlib.suppress(ValueError, InvalidDicomError):
        if _load_tseg_series_dataset(series_path) is None:
            return None
        loaded = load_series_frames(series_path)
        reference_ds, frames, slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
        return SeriesVolumeContext(
            reference_ds=reference_ds,
            slice_frames=frames,
            slice_paths=tuple(slice_paths),
        )
    return None


def _load_series_metadata(series_path: Path):
    with contextlib.suppress(ValueError, InvalidDicomError):
        return _load_series_dataset(series_path)
    return None


def normalize_selected_algorithms(algorithms: Sequence[AiBatchAlgorithm]) -> tuple[AiBatchAlgorithm, ...]:
    """Return selected algorithms in fixed execution order."""
    selected = set(algorithms)
    return tuple(algo for algo in CANONICAL_ALGORITHM_ORDER if algo in selected)


def algorithm_display_name(algorithm: AiBatchAlgorithm) -> str:
    match algorithm:
        case AiBatchAlgorithm.REMOVE_PIXEL_PHI:
            return _("Remove Burnt-in Annotation")
        case AiBatchAlgorithm.HARMONIZE:
            return _("Harmonize")
        case AiBatchAlgorithm.FACE_BLUR:
            return _("Face De-identify")
        case _:
            return str(algorithm)


def format_ai_batch_phase_label(
    algorithm: AiBatchAlgorithm,
    *,
    algorithm_index: int,
    algorithms_total: int,
) -> str:
    """Current algorithm phase label for the batch progress dialog."""
    name = algorithm_display_name(algorithm)
    if algorithms_total > 1:
        return f"{name} ({algorithm_index}/{algorithms_total})"
    return name


def enumerate_series_for_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[tuple[int, int, Path]]:
    """Return (study_index, study_total, series_path) preserving study selection order."""
    study_total = len(studies)
    items: list[tuple[int, int, Path]] = []
    for study_index, (anon_patient_id, anon_study_uid) in enumerate(studies):
        study_path = images_dir / anon_patient_id / anon_study_uid
        if not study_path.is_dir():
            continue
        for series_path in sorted(
            (p for p in study_path.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        ):
            items.append((study_index + 1, study_total, series_path))
    return items


def series_needs_pixel_phi(anon_model: AnonymizerModel | None, series_path: Path) -> bool:
    if anon_model is None:
        return True
    with contextlib.suppress(ValueError, InvalidDicomError, AttributeError):
        ds = _load_series_dataset(series_path)
        return not anon_model.series_pixel_phi_scanned(str(ds.SeriesInstanceUID))
    return True


def series_needs_harmonize(anon_model: AnonymizerModel | None, series_path: Path) -> bool:
    """True when series is CT|MR|XR|US|MG and not yet marked harmonized in the model."""
    with contextlib.suppress(ValueError, InvalidDicomError, OSError):
        ds = _load_harmonize_series_dataset(series_path)
        if ds is None:
            return False
        if anon_model is None:
            return True
        return not anon_model.series_is_harmonized(str(ds.SeriesInstanceUID))
    return False


def _face_blur_batch_eligibility(
    series_path: Path,
    *,
    anon_model: AnonymizerModel | None,
):
    ds = _load_tseg_series_dataset(series_path)
    if ds is None:
        return None
    if anon_model is not None and anon_model.series_has_face_blur(str(ds.SeriesInstanceUID)):
        return evaluate_face_blur_eligibility(
            series_path,
            ds=ds,
            geometry=resolve_series_geometry(series_path),
            face_blur_already_applied=True,
        )
    return evaluate_face_blur_eligibility(
        series_path,
        ds=ds,
        geometry=resolve_series_geometry(series_path),
    )


def series_needs_face_blur(
    anon_model: AnonymizerModel | None,
    series_path: Path,
) -> bool:
    with contextlib.suppress(ValueError, InvalidDicomError, OSError):
        eligibility = _face_blur_batch_eligibility(series_path, anon_model=anon_model)
        if eligibility is None:
            return False
        return eligibility.decision is FaceBlurGateDecision.ALLOW
    return False


def skip_message_for_face_blur_series(
    anon_model: AnonymizerModel | None,
    series_path: Path,
) -> str:
    with contextlib.suppress(ValueError, InvalidDicomError, OSError):
        eligibility = _face_blur_batch_eligibility(series_path, anon_model=anon_model)
        if eligibility is None:
            return _("Not a CT/MR series")
        if eligibility.reason is FaceBlurGateReason.ALREADY_APPLIED:
            return _("Face blur already applied")
        if eligibility.decision is not FaceBlurGateDecision.ALLOW:
            return face_blur_gate_message(eligibility.reason)
    return skip_message_for_algorithm(AiBatchAlgorithm.FACE_BLUR)


def skip_message_for_harmonize_series(
    anon_model: AnonymizerModel | None,
    series_path: Path,
) -> str:
    with contextlib.suppress(ValueError, InvalidDicomError, OSError):
        ds = _load_harmonize_series_dataset(series_path)
        if ds is None:
            return _("Not a CT/MR/XR/US/MG series or no DICOM files")
        if anon_model is not None and anon_model.series_is_harmonized(str(ds.SeriesInstanceUID)):
            return _("Already harmonized (model)")
    return skip_message_for_algorithm(AiBatchAlgorithm.HARMONIZE)


def batch_skip_message_for_series(
    algorithm: AiBatchAlgorithm,
    *,
    anon_model: AnonymizerModel | None,
    series_path: Path,
) -> str:
    if algorithm is AiBatchAlgorithm.FACE_BLUR:
        return skip_message_for_face_blur_series(anon_model, series_path)
    if algorithm is AiBatchAlgorithm.HARMONIZE:
        return skip_message_for_harmonize_series(anon_model, series_path)
    return skip_message_for_algorithm(algorithm)


def filter_pending_series(
    series_items: list[SeriesItem],
    anon_model: AnonymizerModel | None,
    algorithm: AiBatchAlgorithm,
) -> list[SeriesItem]:
    match algorithm:
        case AiBatchAlgorithm.REMOVE_PIXEL_PHI:

            def predicate(path: Path) -> bool:
                return series_needs_pixel_phi(anon_model, path)

        case AiBatchAlgorithm.HARMONIZE:

            def predicate(path: Path) -> bool:
                return series_needs_harmonize(anon_model, path)

        case AiBatchAlgorithm.FACE_BLUR:

            def predicate(path: Path) -> bool:
                return series_needs_face_blur(anon_model, path)

        case _:
            return list(series_items)
    return [item for item in series_items if predicate(item[2])]


def skip_message_for_algorithm(algorithm: AiBatchAlgorithm) -> str:
    match algorithm:
        case AiBatchAlgorithm.REMOVE_PIXEL_PHI:
            return _("Pixel PHI already scanned")
        case AiBatchAlgorithm.HARMONIZE:
            return _("Already harmonized (model)")
        case AiBatchAlgorithm.FACE_BLUR:
            return _("Face blur already applied")
    return _("Already processed")


def count_pending_series(
    series_items: list[SeriesItem],
    anon_model: AnonymizerModel | None,
    algorithms: tuple[AiBatchAlgorithm, ...],
) -> dict[AiBatchAlgorithm, int]:
    return {algorithm: len(filter_pending_series(series_items, anon_model, algorithm)) for algorithm in algorithms}


def _apply_remove_pixel_phi_series(
    series_path: Path,
    *,
    anon_model: AnonymizerModel,
    ocr_reader: Reader,
    on_log_detail: Callable[[str], None] | None = None,
    removal_mode: PixelPhiRemovalMode = PixelPhiRemovalMode.BLACKOUT,
    project_dir: Path | None = None,
    use_modality_whitelist: bool = True,
) -> AiBatchOutcome:
    try:
        ds = _load_series_dataset(series_path)
    except ValueError as exc:
        return AiBatchOutcome(series_path, AiBatchAlgorithm.REMOVE_PIXEL_PHI, "failed", str(exc))

    series_uid = str(ds.SeriesInstanceUID)
    series_modality = str(ds.get("Modality", "") or "")
    if anon_model.series_pixel_phi_scanned(series_uid):
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            "skipped",
            _("Pixel PHI already scanned"),
        )

    try:
        dcm_paths = stackable_dicom_paths(series_path)
    except ValueError:
        from anonymizer.utils.storage import get_dcm_files

        dcm_paths = sorted(get_dcm_files(series_path))

    if not dcm_paths:
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            "failed",
            _("No DICOM files found"),
        )

    modified_count = 0
    unchanged_count = 0
    all_removed_texts: list[str] = []
    total_pixels_changed = 0
    instance_total = len(dcm_paths)
    ocr_whitelist = whitelist_for_batch_ocr(use_modality_whitelist=use_modality_whitelist)
    whitelist_match = load_modality_whitelist_match_settings(project_dir, series_modality or None)
    for instance_index, dcm_path in enumerate(dcm_paths, start=1):
        try:
            modified, texts, pixels_changed = remove_pixel_phi(
                dcm_path,
                ocr_reader,
                removal_mode=removal_mode,
                project_dir=project_dir,
                modality=series_modality or None,
                whitelist=ocr_whitelist,
                whitelist_match_settings=whitelist_match,
            )
        except Exception as exc:
            logger.error("Remove Pixel PHI failed for %s: %s", dcm_path, exc)
            return AiBatchOutcome(
                series_path,
                AiBatchAlgorithm.REMOVE_PIXEL_PHI,
                "failed",
                str(exc),
            )
        if modified and pixels_changed > 0:
            apply_instance_pixel_phi_for_dcm(anon_model, dcm_path, texts)
            all_removed_texts.extend(texts)
            modified_count += 1
            total_pixels_changed += pixels_changed
            if on_log_detail is not None and texts:
                on_log_detail(
                    format_remove_pixel_phi_instance_detail(
                        instance_index=instance_index,
                        instance_total=instance_total,
                        modified=True,
                        texts=texts,
                        removal_mode=removal_mode,
                        pixels_changed=pixels_changed,
                    )
                )
        elif texts:
            all_removed_texts.extend(texts)
            if on_log_detail is not None:
                on_log_detail(
                    format_remove_pixel_phi_instance_detail(
                        instance_index=instance_index,
                        instance_total=instance_total,
                        modified=False,
                        texts=texts,
                        removal_mode=removal_mode,
                    )
                )
        else:
            unchanged_count += 1
            if on_log_detail is not None and texts:
                on_log_detail(
                    format_remove_pixel_phi_instance_detail(
                        instance_index=instance_index,
                        instance_total=instance_total,
                        modified=False,
                        texts=texts,
                        removal_mode=removal_mode,
                    )
                )

    if on_log_detail is not None and unchanged_count > 0 and modified_count > 0:
        on_log_detail(f"{unchanged_count}/{instance_total} " + _("instances") + ": " + _("no burnt-in text detected"))

    anon_model.set_series_pixel_phi_scanned(series_uid, scanned=True)

    if modified_count == 0:
        message = _("No burnt-in text detected")
        if instance_total > 1:
            message += f" ({instance_total} " + _("instances scanned") + ")"
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.REMOVE_PIXEL_PHI,
            "complete",
            message,
        )
    return AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        "ok",
        format_remove_pixel_phi_series_message(
            modified_count=modified_count,
            total=instance_total,
            texts_removed=all_removed_texts,
            pixels_changed=total_pixels_changed,
            removal_mode=removal_mode,
        ),
    )


def _apply_harmonize_series(
    series_path: Path,
    *,
    anon_model: AnonymizerModel | None,
    progress: Callable[[HarmonizeProgress], None] | None,
    include_brain_structures: bool = False,
) -> tuple[AiBatchOutcome, list[str]]:
    from anonymizer.controller.ai.harmonize import format_harmonize_batch_contrast_log_lines

    apply_outcome = harmonize_and_apply_series(
        series_path,
        anon_model=anon_model,
        progress=progress,
        include_brain_structures=include_brain_structures,
    )
    log_lines: list[str] = []
    if apply_outcome.status == "ok" and apply_outcome.harmonized is not None:
        log_lines = format_harmonize_batch_contrast_log_lines(apply_outcome.harmonized)
    return (
        AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.HARMONIZE,
            apply_outcome.status,
            apply_outcome.message,
        ),
        log_lines,
    )


def _apply_face_blur_series(
    series_path: Path,
    *,
    anon_model: AnonymizerModel,
    blur_mode: FaceBlurMode,
    progress: Callable | None,
    volume_context: SeriesVolumeContext | None = None,
) -> AiBatchOutcome:
    ds = _load_tseg_series_dataset(series_path)
    if ds is None:
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "skipped",
            _("Not a CT/MR series"),
        )

    series_uid = str(ds.SeriesInstanceUID)
    if anon_model.series_has_face_blur(series_uid):
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "skipped",
            _("Face blur already applied"),
        )

    eligibility = evaluate_face_blur_eligibility(
        series_path,
        ds=ds,
        geometry=resolve_series_geometry(series_path),
    )
    if eligibility.decision is not FaceBlurGateDecision.ALLOW:
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "skipped",
            face_blur_gate_message(eligibility.reason),
        )

    preview = preview_face_blur(
        series_path,
        blur_mode=blur_mode,
        progress=progress,
        volume_context=volume_context,
    )
    if preview.error is not None:
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "failed",
            preview.error,
        )
    if preview.qa_stats is not None and not preview.qa_stats.outside_clean:
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "failed",
            _("QA FAIL") + " — " + _("pixels changed outside the face mask"),
        )

    try:
        if volume_context is not None and preview.blurred_slice_frames is not None:
            blurred_slices = preview.blurred_slice_frames
            ds = volume_context.reference_ds
        else:
            loaded = load_series_frames(series_path)
            ds, frames, _slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
            blurred_slices = preview_blurred_slice_frames(
                preview,
                reference_ds=ds,
                frame_dtype=frames.dtype,
            )
        if not save_series_frames(series_path, blurred_slices, ds):
            return AiBatchOutcome(
                series_path,
                AiBatchAlgorithm.FACE_BLUR,
                "failed",
                _("Failed to save blurred frames"),
            )
        from anonymizer.controller.create_projections import invalidate_projection_cache

        invalidate_projection_cache(series_path)
        apply_series_face_blur_metadata(anon_model, series_uid, preview.blur_mode.value)
    except Exception as exc:
        logger.exception("Face blur batch apply failed for %s", series_path)
        return AiBatchOutcome(
            series_path,
            AiBatchAlgorithm.FACE_BLUR,
            "failed",
            str(exc),
        )

    return AiBatchOutcome(
        series_path,
        AiBatchAlgorithm.FACE_BLUR,
        "ok",
        face_blur_mode_display_label(preview.blur_mode),
    )


def _handle_batch_series_preamble(
    *,
    series_path: Path,
    pending_paths: set[Path],
    algorithm: AiBatchAlgorithm,
    study_index: int,
    study_total: int,
    series_index: int,
    series_total: int,
    log_workflow: Callable[[str], None],
    record_outcome: Callable[..., None],
    report_progress: Callable[..., None],
    algorithm_index: int,
    item_study_total: int,
    on_step_complete: Callable[[], None],
    outcome_detail: Callable[[AiBatchOutcome], str],
    anon_model: AnonymizerModel | None = None,
) -> object | None:
    """
    Load metadata, skip already-processed series, or return ds for processing.

    Returns ``ds`` for processing, or ``None`` when the series was skipped (outcome recorded).
    """
    ds = _load_series_metadata(series_path)
    if series_path not in pending_paths:
        log_workflow(
            format_batch_log_series_label(
                study_index=study_index,
                study_total=study_total,
                series_index=series_index,
                series_total=series_total,
                ds=ds,
            )
        )
        outcome = AiBatchOutcome(
            series_path,
            algorithm,
            "skipped",
            batch_skip_message_for_series(
                algorithm,
                anon_model=anon_model,
                series_path=series_path,
            ),
        )
        record_outcome(
            outcome,
            study_index=study_index,
            study_total=study_total,
            series_index=series_index,
            algorithm=algorithm,
            ds=ds,
        )
        on_step_complete()
        report_progress(
            series_index=series_index,
            study_index=study_index,
            study_total=item_study_total,
            algorithm=algorithm,
            algorithm_index=algorithm_index,
            detail=outcome_detail(outcome),
            step_fraction=1.0,
            ds=ds,
        )
        return None
    log_workflow(
        format_batch_log_series_label(
            study_index=study_index,
            study_total=study_total,
            series_index=series_index,
            series_total=series_total,
            ds=ds,
        )
    )
    report_progress(
        series_index=series_index,
        study_index=study_index,
        study_total=item_study_total,
        algorithm=algorithm,
        algorithm_index=algorithm_index,
        detail="",
        step_fraction=0.0,
        ds=ds,
    )
    return ds


def ai_batch_process(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
    options: AiBatchProcessOptions,
    *,
    anon_model: AnonymizerModel | None = None,
    anon_controller: AnonymizerController | None = None,
    progress: AiBatchProgressCallback | None = None,
    cancelled: AiBatchCancelledCallback | None = None,
    on_log: AiBatchWorkflowLogCallback | None = None,
    memory_callback: AiBatchMemoryCallback | None = None,
    work_state: WorkState | None = None,
) -> AiBatchSummary:
    """Run selected AI algorithms in fixed order, one algorithm phase at a time."""
    # Harmonize uses workstation resolution from AI Features (get_ct/mr_segmentation_mode).

    algorithms = normalize_selected_algorithms(options.algorithms)
    if not algorithms:
        return AiBatchSummary()

    series_items = enumerate_series_for_studies(images_dir, studies)
    series_total = len(series_items)
    study_total = len(studies)
    if series_total == 0:
        if progress is not None:
            progress(0, 0, algorithms[0], 0, len(algorithms), _("No series found for selected studies"), 1.0)
        if on_log is not None:
            on_log(format_batch_workflow_log_line(_("No series found for selected studies")))
        return AiBatchSummary()

    total_steps = series_total * len(algorithms)
    completed_steps = 0
    summary = AiBatchSummary(series_count=series_total)
    algorithm_totals: dict[AiBatchAlgorithm, AiBatchAlgorithmTotals] = {
        algorithm: AiBatchAlgorithmTotals() for algorithm in algorithms
    }
    volume_contexts: dict[Path, SeriesVolumeContext] = {}
    memory_guard = MemoryGuard()
    defer_volume_to_face_blur = AiBatchAlgorithm.HARMONIZE in algorithms and AiBatchAlgorithm.FACE_BLUR in algorithms
    newly_harmonized_study_uids: set[str] = set()

    def log_workflow(message: str) -> None:
        if work_state is not None:
            work_state.append_log(format_batch_workflow_log_line(message.rstrip("\n")))
        if on_log is not None:
            on_log(format_batch_workflow_log_line(message.rstrip("\n")))

    def emit_memory_snapshot() -> MemorySnapshot | None:
        snapshot = capture_memory_snapshot()
        if snapshot is None:
            return None
        if memory_callback is not None:
            memory_callback(snapshot)
        return snapshot

    def check_memory_guard() -> bool:
        """Return True when batch should stop due to low memory."""
        snapshot = emit_memory_snapshot()
        if snapshot is None:
            return False
        pressure = memory_guard.check(snapshot)
        if pressure == "abort":
            log_workflow(
                format_batch_step_subline(
                    _("Stopped: low memory") + f" ({snapshot.available_mb:.0f} MB {_('available')})"
                )
            )
            mark_cancelled()
            return True
        if pressure == "warn" and memory_guard.should_log_warn():
            log_workflow(
                format_batch_step_subline(_("Memory warning") + f": {snapshot.available_mb:.0f} MB {_('available')}")
            )
        return False

    def report_progress(
        *,
        series_index: int,
        study_index: int,
        study_total: int,
        algorithm: AiBatchAlgorithm,
        algorithm_index: int,
        detail: str,
        step_fraction: float,
        ds=None,
    ) -> None:
        if progress is None:
            return
        overall = (completed_steps + min(1.0, max(0.0, step_fraction))) / total_steps
        message = format_ai_batch_status_line(
            study_index=study_index,
            study_total=study_total,
            series_index=series_index,
            series_total=series_total,
            ds=ds,
        )
        progress(
            series_index,
            series_total,
            algorithm,
            algorithm_index + 1,
            len(algorithms),
            message,
            overall,
        )
        if work_state is not None:
            work_state.set_status(message)

    def record_outcome(
        outcome: AiBatchOutcome,
        *,
        study_index: int,
        study_total: int,
        series_index: int,
        algorithm: AiBatchAlgorithm,
        ds=None,
    ) -> None:
        nonlocal summary
        totals = algorithm_totals[algorithm]
        totals = _increment_algorithm_totals(totals, outcome)
        algorithm_totals[algorithm] = totals
        summary = AiBatchSummary(
            processed=summary.processed + 1,
            skipped=summary.skipped
            + (
                1
                if outcome.status == "skipped"
                and not face_blur_skip_counts_as_complete(outcome)
                and not harmonize_skip_counts_as_complete(outcome)
                else 0
            ),
            applied=summary.applied + (1 if outcome.status == "ok" else 0),
            failed=summary.failed + (1 if outcome.status == "failed" else 0),
            cancelled=summary.cancelled,
            series_count=series_total,
            algorithm_totals=tuple(algorithm_totals.items()),
            newly_harmonized_study_uids=tuple(sorted(newly_harmonized_study_uids)),
        )
        if on_log is not None:
            on_log(format_batch_workflow_log_line(format_batch_outcome_subline(outcome)))

    def is_cancelled() -> bool:
        if work_state is not None and work_state.should_cancel():
            return True
        return cancelled is not None and cancelled()

    def mark_cancelled() -> None:
        nonlocal summary
        summary = AiBatchSummary(
            processed=summary.processed,
            skipped=summary.skipped,
            applied=summary.applied,
            failed=summary.failed,
            cancelled=True,
            series_count=series_total,
            algorithm_totals=tuple(algorithm_totals.items()),
            newly_harmonized_study_uids=tuple(sorted(newly_harmonized_study_uids)),
        )

    def outcome_detail(outcome: AiBatchOutcome) -> str:
        if outcome.status == "ok":
            if outcome.algorithm is AiBatchAlgorithm.HARMONIZE and outcome.message:
                return _("Applied") + f': "{outcome.message}"'
            return outcome.message or _("Complete")
        if outcome.status == "complete":
            return _("Complete") + (f": {outcome.message}" if outcome.message else "")
        if outcome.status == "skipped":
            return _("Skipped") + (f": {outcome.message}" if outcome.message else "")
        return _("Failed") + (f": {outcome.message}" if outcome.message else "")

    def advance_completed_step() -> None:
        nonlocal completed_steps
        completed_steps += 1

    for algorithm_index, algorithm in enumerate(algorithms):
        if summary.cancelled or is_cancelled():
            mark_cancelled()
            break

        log_workflow(format_batch_phase_banner(algorithm))

        pending_items = filter_pending_series(series_items, anon_model, algorithm)
        pending_paths = {item[2] for item in pending_items}
        if not pending_paths:
            log_workflow(format_batch_step_subline(_("All series already processed — skipping phase")))
            completed_steps += series_total
            if progress is not None:
                progress(
                    series_total,
                    series_total,
                    algorithm,
                    algorithm_index + 1,
                    len(algorithms),
                    _("Phase skipped"),
                    completed_steps / total_steps,
                )
            continue

        emit_memory_snapshot()

        runner_alg = AI_BATCH_TO_RUNNER[algorithm]
        runner, handle = enter_batch_phase(runner_alg)
        try:
            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                log_workflow(format_batch_step_subline(_("Preparing OCR models") + "…"))
                if not options.use_modality_whitelist:
                    log_workflow(
                        format_batch_step_subline(
                            _("OCR whitelist disabled") + " — " + _("all detected text will be removed")
                        )
                    )
            elif algorithm is AiBatchAlgorithm.HARMONIZE:
                if any(_load_tseg_series_dataset(path) is not None for path in pending_paths):
                    log_workflow(format_batch_step_subline(_("Loading anatomy analysis models") + "…"))
                else:
                    log_workflow(format_batch_step_subline(_("Harmonizing series descriptions") + "…"))
            else:
                log_workflow(format_batch_step_subline(_("Loading face segmentation models") + "…"))

            for series_index, (study_index, item_study_total, series_path) in enumerate(series_items, start=1):
                if is_cancelled():
                    mark_cancelled()
                    break
                if check_memory_guard():
                    break

                ds = _handle_batch_series_preamble(
                    series_path=series_path,
                    pending_paths=pending_paths,
                    algorithm=algorithm,
                    study_index=study_index,
                    study_total=study_total,
                    series_index=series_index,
                    series_total=series_total,
                    log_workflow=log_workflow,
                    record_outcome=record_outcome,
                    report_progress=report_progress,
                    algorithm_index=algorithm_index,
                    item_study_total=item_study_total,
                    on_step_complete=advance_completed_step,
                    outcome_detail=outcome_detail,
                    anon_model=anon_model,
                )
                if ds is None:
                    continue

                if algorithm is AiBatchAlgorithm.HARMONIZE and not defer_volume_to_face_blur:
                    volume_context = _prepare_ct_volume_context(series_path)
                    if volume_context is not None:
                        volume_contexts[series_path] = volume_context

                last_progress_stage: list[str | None] = [None]

                def step_progress(
                    step_fraction: float,
                    detail: str,
                    *,
                    _series_index: int = series_index,
                    _study_index: int = study_index,
                    _study_total: int = item_study_total,
                    _ds=ds,
                    _algorithm=algorithm,
                    _algorithm_index: int = algorithm_index,
                ) -> None:
                    report_progress(
                        series_index=_series_index,
                        study_index=_study_index,
                        study_total=_study_total,
                        algorithm=_algorithm,
                        algorithm_index=_algorithm_index,
                        detail=detail,
                        step_fraction=step_fraction,
                        ds=_ds,
                    )

                if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                    log_workflow(format_batch_step_subline(_("Scanning instances for burnt-in text") + "…"))
                    assert anon_model is not None
                    assert handle.reader is not None
                    project_dir = anon_controller.project_model.storage_dir if anon_controller is not None else None

                    def log_pixel_phi_detail(message: str) -> None:
                        log_workflow(format_batch_step_subline(message))

                    outcome = _apply_remove_pixel_phi_series(
                        series_path,
                        anon_model=anon_model,
                        ocr_reader=handle.reader,
                        on_log_detail=log_pixel_phi_detail,
                        removal_mode=options.pixel_phi_removal_mode,
                        project_dir=project_dir,
                        use_modality_whitelist=options.use_modality_whitelist,
                    )
                elif algorithm is AiBatchAlgorithm.HARMONIZE:

                    def harmonize_progress(
                        item_progress: HarmonizeProgress,
                        *,
                        _last_progress_stage: list[str | None] = last_progress_stage,
                        _ds=ds,
                    ) -> None:
                        message = format_harmonize_progress_message(
                            item_progress,
                            include_pct=False,
                            segmentation_mode=segmentation_mode_for_modality(
                                getattr(_ds, "Modality", None) if _ds is not None else None
                            ),
                        )
                        _log_workflow_progress_step(
                            log_workflow,
                            step_progress,
                            fraction=item_progress.fraction,
                            message=message,
                            stage_key=item_progress.stage,
                            last_stage_key=_last_progress_stage,
                            skip_log=(
                                item_progress.stage in {"done", "failed"}
                                or not should_log_harmonize_batch_step(item_progress)
                            ),
                        )

                    outcome, harmonize_log_lines = _apply_harmonize_series(
                        series_path,
                        anon_model=anon_model,
                        progress=harmonize_progress,
                        include_brain_structures=options.include_brain_structures,
                    )
                    for line in harmonize_log_lines:
                        log_workflow(format_batch_workflow_log_line(format_batch_step_subline(line)))
                    if outcome.status == "ok" and anon_model is not None:
                        # Collect candidates; maybe_offer_study_description_harmonize
                        # gates CT/MR vs pure XR/US/MG readiness at dialog time.
                        newly_harmonized_study_uids.add(series_path.parent.name)
                else:
                    volume_context = volume_contexts.pop(series_path, None)
                    if volume_context is None:
                        volume_context = _prepare_ct_volume_context(series_path)

                    def face_progress(
                        item,
                        *,
                        _last_progress_stage: list[str | None] = last_progress_stage,
                    ) -> None:
                        message = format_face_blur_progress_status(item, include_pct=False)
                        _log_workflow_progress_step(
                            log_workflow,
                            step_progress,
                            fraction=item.fraction,
                            message=message,
                            stage_key=item.stage,
                            last_stage_key=_last_progress_stage,
                            skip_log=item.stage == "done",
                        )

                    assert anon_model is not None
                    outcome = _apply_face_blur_series(
                        series_path,
                        anon_model=anon_model,
                        blur_mode=options.blur_mode,
                        progress=face_progress,
                        volume_context=volume_context,
                    )
                    volume_context = None
                    collect_garbage_safe()
                    release_working_memory(stage="ai_batch_after_face_blur_series", preserve_accelerator=True)

                record_outcome(
                    outcome,
                    study_index=study_index,
                    study_total=study_total,
                    series_index=series_index,
                    algorithm=algorithm,
                    ds=ds,
                )
                completed_steps += 1
                step_progress(1.0, outcome_detail(outcome))
                if algorithm is AiBatchAlgorithm.HARMONIZE:
                    release_working_memory(stage="ai_batch_after_harmonize_series", preserve_accelerator=True)
        finally:
            exit_batch_phase(runner, handle)
            if algorithm is AiBatchAlgorithm.REMOVE_PIXEL_PHI:
                log_workflow(format_batch_step_subline(_("Releasing OCR models") + "…"))
                log_workflow(format_batch_step_subline(_("OCR models released")))
            elif algorithm is AiBatchAlgorithm.HARMONIZE:
                log_workflow(format_batch_step_subline(_("Anatomy analysis models released")))
            else:
                log_workflow(format_batch_step_subline(_("Face segmentation models released")))
            emit_memory_snapshot()

        if summary.cancelled:
            break

    if (
        not summary.cancelled
        and anon_model is not None
        and newly_harmonized_study_uids
        and AiBatchAlgorithm.HARMONIZE in algorithms
    ):
        applied_study_descs = auto_apply_best_study_descriptions(
            images_dir=images_dir,
            anon_model=anon_model,
            anon_study_uids=tuple(sorted(newly_harmonized_study_uids)),
        )
        for offer, updated in applied_study_descs:
            if not updated or not offer.matches:
                continue
            name = offer.matches[0].long_common_name
            log_workflow(
                format_batch_step_subline(
                    _("Auto-applied study description")
                    + f': "{name}" → {len(updated)} '
                    + (_("study") if len(updated) == 1 else _("studies"))
                )
            )

    volume_contexts.clear()
    if work_state is not None and not work_state.done:
        work_state.finish(summary)
    return summary
