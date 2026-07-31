"""Combine TotalSegmentator anatomy analysis into Playbook-compliant series descriptions."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydicom import Dataset, dcmread

from anonymizer.controller.tseg.config import (
    CONTRAST_PHASE_CACHE_FILENAME,
    CONTRAST_STATS_FILENAME,
    CONTRAST_STATS_HN_FILENAME,
    ENABLE_TS_CONTRAST,
    ROI_SUBSET,
)
from anonymizer.controller.tseg.contrast import (
    contrast_phase_cache_is_valid,
    load_contrast_phase_cache,
    load_contrast_statistics,
    log_memory_usage,
    phase_to_iv_contrast,
    release_working_memory,
)
from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    format_geometry_progress_message,
    geometry_analysis_progress_prefix,
    load_geometry_cache,
    resolve_series_geometry,
    sorted_dicom_paths,
    ts_regions_eligible,
)
from anonymizer.controller.tseg.model_cache import tseg_batch_session
from anonymizer.controller.tseg.radlex_playbook import (
    PlaybookHarmonizeAttributes,
    build_harmonized_series_description,
    build_localizer_harmonized_series_description,
    is_localizer_geometry,
)
from anonymizer.controller.tseg.runtime import log_active_threads
from anonymizer.controller.tseg.segment import (
    AnalysisProgress,
    ProgressCallback,
    TS_result,
    analyze_tseg_contrast,
    analyze_tseg_regions,
    body_parts_present,
    collect_structure_voxels,
    dominant_region_from_voxels,
    estimate_tseg_contrast_remaining_sec,
    series_cache_dir,
)
from anonymizer.controller.tseg.segment import (
    _region_ts_result as region_ts_result_from_summary,
)
from anonymizer.controller.tseg.segment import (
    _segmentation_cache_valid as segmentation_cache_valid,
)
from anonymizer.utils.translate import _

if TYPE_CHECKING:
    from anonymizer.model.anonymizer import AnonymizerModel

logger = logging.getLogger(__name__)

HarmonizeProgress = AnalysisProgress

# Progress fractions for sequential harmonize stages (single-threaded worker).
_GEOMETRY_FRAC = (0.0, 0.08)
_TSEG_SEG_FRAC = (0.08, 0.62)
_TSEG_CONTRAST_FRAC = (0.62, 0.92)
_MERGE_FRAC = (0.92, 1.0)


@dataclass(frozen=True)
class HarmonizedResult:
    series_directory: Path
    radlex_series_description: str
    tseg: TS_result | None
    geometry: SeriesGeometryResult | None = None
    playbook: PlaybookHarmonizeAttributes | None = None
    error: str | None = None


def _load_series_dataset(series_directory: Path):
    paths = sorted_dicom_paths(series_directory)
    if not paths:
        raise ValueError(f"No DICOM files found in {series_directory}")
    return dcmread(paths[0], stop_before_pixels=True)


def _merge_localizer_result(
    series_directory: Path,
    geometry: SeriesGeometryResult,
    tseg: TS_result | None,
) -> HarmonizedResult:
    if (
        tseg is not None
        and tseg.body_parts_present.strip()
        and tseg.contrast_phase
        and tseg.error is None
    ):
        try:
            ds = _load_series_dataset(series_directory)
            description, playbook = build_harmonized_series_description(tseg, geometry, ds=ds)
        except ValueError as exc:
            logger.warning("Harmonize localizer merge via TS failed for %s: %s", series_directory, exc)
        else:
            return HarmonizedResult(
                series_directory=series_directory,
                radlex_series_description=description,
                tseg=tseg,
                geometry=geometry,
                playbook=playbook,
            )

    try:
        ds = _load_series_dataset(series_directory)
        description, playbook = build_localizer_harmonized_series_description(ds, geometry)
    except ValueError as exc:
        logger.warning("Harmonize localizer merge failed for %s: %s", series_directory, exc)
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=str(exc),
        )

    return HarmonizedResult(
        series_directory=series_directory,
        radlex_series_description=description,
        tseg=tseg,
        geometry=geometry,
        playbook=playbook,
    )


def _merge_result(
    series_directory: Path,
    tseg: TS_result | None,
    *,
    geometry: SeriesGeometryResult | None = None,
) -> HarmonizedResult:
    if geometry is None:
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=None,
            error="Series geometry is required for Playbook harmonization",
        )

    if is_localizer_geometry(geometry):
        return _merge_localizer_result(series_directory, geometry, tseg)

    if tseg is None or not tseg.body_parts_present.strip():
        error = tseg.error if tseg is not None and tseg.error else "TotalSegmentator anatomy analysis unavailable"
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=error,
        )

    if tseg.error and not tseg.contrast_phase:
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=tseg.error,
        )

    if not tseg.contrast_phase:
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error="TotalSegmentator contrast phase is required for Playbook harmonization",
        )

    try:
        ds = _load_series_dataset(series_directory)
        description, playbook = build_harmonized_series_description(tseg, geometry, ds=ds)
    except ValueError as exc:
        logger.warning("Harmonize merge failed for %s: %s", series_directory, exc)
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=str(exc),
        )

    return HarmonizedResult(
        series_directory=series_directory,
        radlex_series_description=description,
        tseg=tseg,
        geometry=geometry,
        playbook=playbook,
    )


def _tseg_result_from_cache(series_directory: Path) -> TS_result | None:
    """Rebuild anatomy + contrast TS_result from ``A_TS_SEG`` without running ML."""
    cache_dir = series_cache_dir(series_directory)
    seg_dir = cache_dir / "seg"
    structures = list(ROI_SUBSET)
    if not segmentation_cache_valid(seg_dir, structures):
        return None

    structure_voxels = collect_structure_voxels(seg_dir, structures)
    region = dominant_region_from_voxels(structure_voxels)
    regions_label = body_parts_present(region.region_voxels)
    if not regions_label:
        return None

    region_result = region_ts_result_from_summary(
        series_directory,
        region=region,
        regions_label=regions_label,
    )

    contrast_stats_path = cache_dir / CONTRAST_STATS_FILENAME
    contrast_stats_hn_path = cache_dir / CONTRAST_STATS_HN_FILENAME
    contrast_phase_path = cache_dir / CONTRAST_PHASE_CACHE_FILENAME
    if not contrast_stats_path.is_file() or not contrast_phase_path.is_file():
        return None

    try:
        existing_stats = load_contrast_statistics(contrast_stats_path)
        cached = load_contrast_phase_cache(contrast_phase_path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("Harmonize cache: contrast artifacts unreadable for %s: %s", series_directory, exc)
        return None

    needs_head_neck = existing_stats["brain"]["volume"] > 100
    if not contrast_phase_cache_is_valid(
        contrast_phase_path,
        contrast_stats_path,
        stats_hn_path=contrast_stats_hn_path,
        require_stats_hn=needs_head_neck,
    ):
        return None

    phase = str(cached["phase"])
    return TS_result(
        series_directory=series_directory,
        dominant_region=region_result.dominant_region,
        body_parts_present=region_result.body_parts_present,
        multi_region=region_result.multi_region,
        region_fraction=region_result.region_fraction,
        iv_contrast=phase_to_iv_contrast(phase),
        contrast_phase=phase,
        phase_probability=float(cached.get("probability", 0.0)),
        radlex_series_description="",
        structures_present=dict(region_result.structures_present),
    )


def harmonized_description_from_cache(
    series_directory: Path,
    *,
    ds: Dataset | None = None,
) -> str | None:
    """
    Reconstruct the Playbook series description from cached harmonize inputs.

    Returns the expected description when geometry and TS caches are complete,
    or ``None`` when harmonize must run before the outcome can be known.
    """
    series_directory = Path(series_directory)
    geometry = load_geometry_cache(series_directory)
    if geometry is None:
        return None

    if ds is None:
        try:
            ds = _load_series_dataset(series_directory)
        except ValueError:
            return None

    if is_localizer_geometry(geometry):
        merged = _merge_localizer_result(series_directory, geometry, None)
        if merged.error:
            return None
        description = (merged.radlex_series_description or "").strip()
        return description or None

    if not ts_regions_eligible(geometry) or not ENABLE_TS_CONTRAST:
        return None

    tseg = _tseg_result_from_cache(series_directory)
    if tseg is None:
        return None

    merged = _merge_result(series_directory, tseg, geometry=geometry)
    if merged.error:
        return None
    description = (merged.radlex_series_description or "").strip()
    return description or None


def series_description_is_harmonized(series_directory: Path, ds: Dataset) -> bool | None:
    """
    Return whether ``SeriesDescription`` matches the cached Playbook harmonization.

    ``True`` / ``False`` when TS cache is complete; ``None`` when unknown.
    """
    expected = harmonized_description_from_cache(series_directory, ds=ds)
    if expected is None:
        return None
    current = str(ds.get("SeriesDescription", "") or "").strip()
    return current == expected


def harmonize_context_hint(series_directory: Path, ds: Dataset | None) -> str | None:
    """Optional Series View geometry-line suffix when harmonization is already up to date."""
    if ds is None or getattr(ds, "Modality", None) != "CT":
        return None
    if series_description_is_harmonized(series_directory, ds) is not True:
        return None
    return _(
        "Series description already harmonized — use Clear TS Cache to re-run analysis"
    )


@dataclass(frozen=True)
class HarmonizeApplyOutcome:
    series_path: Path
    status: str
    message: str = ""


@dataclass(frozen=True)
class HarmonizeStudiesSummary:
    processed: int = 0
    skipped: int = 0
    applied: int = 0
    failed: int = 0
    cancelled: bool = False


HarmonizeStudiesProgressCallback = Callable[[int, int, str, float], None]
HarmonizeStudiesCancelledCallback = Callable[[], bool]
HarmonizeStudiesLogCallback = Callable[[HarmonizeApplyOutcome], None]
HarmonizeStudiesBatchHook = Callable[[], None]


def _format_progress_pct(fraction: float) -> str:
    pct = min(100, max(0, int(round(fraction * 100))))
    return f" ({pct}%)"


def format_harmonize_progress_message(
    progress: AnalysisProgress,
    *,
    include_pct: bool = True,
) -> str:
    """Translate harmonize pipeline stages to clinician-friendly status text."""
    message = (progress.message or "").strip()
    stage = progress.stage
    geometry_prefix = geometry_analysis_progress_prefix()
    pct = _format_progress_pct(progress.fraction) if include_pct else ""

    if stage == "done":
        return _("Harmonize analysis complete")

    if stage == "geometry" and message.startswith(geometry_prefix):
        return _("Scan geometry analyzed") + pct
    if stage == "tseg" and message.startswith(geometry_prefix):
        return _("Anatomy analysis not available for this series") + pct

    stage_labels: dict[str, str] = {
        "geometry": _("Analyzing scan geometry"),
        "prepare": _("Preparing CT volume"),
        "segment": _("Segmenting anatomy (TotalSegmentator)"),
        "regions": _("Summarizing anatomy regions"),
        "tseg": _("Analyzing anatomy"),
        "contrast": _("Determining contrast phase"),
        "contrast_stats": _("Computing organ HU statistics"),
        "contrast_stats_cached": _("Using cached organ HU statistics"),
        "contrast_stats_hn": _("Computing head/neck vessel statistics"),
        "contrast_stats_hn_cached": _("Using cached head/neck vessel statistics"),
        "contrast_stats_hn_skip": _("Head/neck statistics not required"),
        "contrast_xgboost": _("Classifying contrast phase"),
        "contrast_phase_cache": _("Using cached contrast phase classification"),
        "merge": _("Building standardized series description"),
    }

    if stage in stage_labels:
        return stage_labels[stage] + "…" + pct

    known_messages = {
        "Starting contrast phase analysis": _("Starting contrast phase analysis"),
        "Contrast phase analysis complete": _("Contrast phase analysis complete"),
        "Segmenting anatomy": _("Segmenting anatomy (TotalSegmentator)"),
        "Preparing CT volume": _("Preparing CT volume"),
        "Summarizing anatomy regions": _("Summarizing anatomy regions"),
        "Building harmonized description": _("Building standardized series description"),
        "Harmonized description ready": _("Standardized series description ready"),
        "Analyzing contrast phase": _("Determining contrast phase"),
    }
    if message in known_messages:
        return known_messages[message] + pct

    if message:
        return message + pct

    return _("Processing") + "…" + pct


def format_harmonize_batch_series_label(series_path: Path, ds: Dataset | None = None) -> str:
    """Compact series label for batch harmonize progress."""
    series_path = Path(series_path)
    if ds is not None:
        description = str(ds.get("SeriesDescription", "") or "").strip()
        series_no = ds.get("SeriesNumber")
        if description:
            if series_no not in (None, ""):
                return _("Series") + f" #{series_no}: \"{description}\""
            return _("Series") + f": \"{description}\""
    return _("Series") + f" {series_path.name}"


def format_harmonize_batch_progress_text(
    *,
    series_index: int,
    total: int,
    progress: AnalysisProgress,
    series_path: Path,
    ds: Dataset | None = None,
) -> str:
    """Full batch progress line: series position, context, and friendly stage."""
    series_label = format_harmonize_batch_series_label(series_path, ds)
    stage_text = format_harmonize_progress_message(progress)
    if total > 1:
        position = _("Series") + f" {series_index}/{total}"
        return f"{position} · {series_label} · {stage_text}"
    return f"{series_label} · {stage_text}"


def _iter_study_series_dirs(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[Path]:
    series_paths: list[Path] = []
    for anon_patient_id, anon_study_uid in studies:
        study_path = images_dir / anon_patient_id / anon_study_uid
        if not study_path.is_dir():
            continue
        for series_path in study_path.iterdir():
            if series_path.is_dir() and not series_path.name.startswith("."):
                series_paths.append(series_path)
    return series_paths


def _load_ct_series_dataset(series_path: Path) -> Dataset | None:
    try:
        ds = _load_series_dataset(series_path)
    except ValueError:
        return None
    if getattr(ds, "Modality", None) != "CT":
        return None
    return ds


def enumerate_ct_series_for_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[Path]:
    """Return CT series directories under the selected anonymized studies."""
    ct_series: list[Path] = []
    for series_path in _iter_study_series_dirs(images_dir, studies):
        if _load_ct_series_dataset(series_path) is not None:
            ct_series.append(series_path)
    return ct_series


def study_harmonize_status(
    anon_model: "AnonymizerModel",
    anon_study_uid: str,
) -> bool:
    """
    Return True when every eligible CT series in the study is harmonized.

    Uses ORM ``Series.harmonized_description`` metadata (no filesystem or TS cache reads).
    """
    return anon_model.study_is_harmonized(anon_study_uid)


def apply_harmonized_description(
    series_path: Path,
    description: str,
    anon_model: AnonymizerModel | None,
) -> bool:
    """Apply harmonized SeriesDescription to DICOM when needed and update the project database."""
    from anonymizer.controller.create_projections import apply_series_description

    description = description.strip()
    if not description:
        return False

    try:
        ds = _load_series_dataset(series_path)
    except ValueError:
        return False

    current = str(ds.get("SeriesDescription", "") or "").strip()
    if current != description and not apply_series_description(series_path, description):
        return False

    if anon_model is None:
        return True
    return anon_model.set_series_harmonized_description(str(ds.SeriesInstanceUID), description)


def harmonize_and_apply_series(
    series_path: Path,
    *,
    anon_model: AnonymizerModel | None = None,
    progress: ProgressCallback | None = None,
) -> HarmonizeApplyOutcome:
    """Run harmonize for one CT series and auto-apply the merged description."""
    series_path = Path(series_path)
    ds = _load_ct_series_dataset(series_path)
    if ds is None:
        return HarmonizeApplyOutcome(series_path, "failed", "Not a CT series or no DICOM files")

    if series_description_is_harmonized(series_path, ds) is True:
        return HarmonizeApplyOutcome(series_path, "skipped", "Already harmonized")

    results = harmonize_series([series_path], progress=progress)
    if not results:
        return HarmonizeApplyOutcome(series_path, "failed", "No harmonize result")

    merged = results[0]
    if merged.error:
        return HarmonizeApplyOutcome(series_path, "failed", merged.error)

    description = (merged.radlex_series_description or "").strip()
    if not description:
        return HarmonizeApplyOutcome(series_path, "failed", "Empty harmonized description")

    if not apply_harmonized_description(series_path, description, anon_model):
        return HarmonizeApplyOutcome(series_path, "failed", "Failed to apply description")

    return HarmonizeApplyOutcome(series_path, "ok", description)


def harmonize_studies_batch(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
    *,
    anon_model: AnonymizerModel | None = None,
    progress: HarmonizeStudiesProgressCallback | None = None,
    cancelled: HarmonizeStudiesCancelledCallback | None = None,
    on_outcome: HarmonizeStudiesLogCallback | None = None,
    on_batch_start: HarmonizeStudiesBatchHook | None = None,
    on_batch_end: HarmonizeStudiesBatchHook | None = None,
) -> HarmonizeStudiesSummary:
    """Harmonize all CT series under selected studies, auto-applying descriptions."""
    series_paths = enumerate_ct_series_for_studies(images_dir, studies)
    total = len(series_paths)
    summary = HarmonizeStudiesSummary()

    if progress is not None and total == 0:
        progress(0, 0, _("No CT series found for selected studies"), 1.0)

    with tseg_batch_session(preload=True):
        if on_batch_start is not None:
            on_batch_start()
        if progress is not None and total > 0:
            progress(0, total, _("Loading anatomy analysis models") + "…", 0.0)

        try:
            for index, series_path in enumerate(series_paths):
                if cancelled is not None and cancelled():
                    summary = HarmonizeStudiesSummary(
                        processed=summary.processed,
                        skipped=summary.skipped,
                        applied=summary.applied,
                        failed=summary.failed,
                        cancelled=True,
                    )
                    break

                try:
                    ds = _load_ct_series_dataset(series_path)
                except (OSError, ValueError):
                    ds = None
                base_fraction = index / total if total else 1.0

                def series_progress(
                    item_progress: AnalysisProgress,
                    *,
                    _index: int = index,
                    _series_path: Path = series_path,
                    _ds: Dataset | None = ds,
                    _base_fraction: float = base_fraction,
                ) -> None:
                    if progress is None or total == 0:
                        return
                    overall = _base_fraction + (item_progress.fraction / total)
                    message = format_harmonize_batch_progress_text(
                        series_index=_index + 1,
                        total=total,
                        progress=item_progress,
                        series_path=_series_path,
                        ds=_ds,
                    )
                    progress(_index + 1, total, message, overall)

                outcome = harmonize_and_apply_series(
                    series_path,
                    anon_model=anon_model,
                    progress=series_progress,
                )
                if on_outcome is not None:
                    on_outcome(outcome)

                summary = HarmonizeStudiesSummary(
                    processed=summary.processed + 1,
                    skipped=summary.skipped + (1 if outcome.status == "skipped" else 0),
                    applied=summary.applied + (1 if outcome.status == "ok" else 0),
                    failed=summary.failed + (1 if outcome.status == "failed" else 0),
                    cancelled=summary.cancelled,
                )

                if progress is not None:
                    fraction = (index + 1) / total if total else 1.0
                    if outcome.status == "skipped":
                        status_text = _("Already harmonized")
                    elif outcome.status == "ok":
                        status_text = _("Applied standardized description")
                    elif outcome.status == "failed":
                        status_text = _("Failed") + f": {outcome.message or outcome.status}"
                    else:
                        status_text = outcome.message or outcome.status
                    series_label = format_harmonize_batch_series_label(series_path, ds)
                    if total > 1:
                        message = _("Series") + f" {index + 1}/{total} · {series_label} · {status_text}"
                    else:
                        message = f"{series_label} · {status_text}"
                    progress(index + 1, total, message, fraction)
        finally:
            if on_batch_end is not None:
                on_batch_end()

    return summary


def _scaled_progress(
    callback: ProgressCallback | None,
    *,
    started: float,
    frac_range: tuple[float, float],
    stage_label: str,
) -> ProgressCallback | None:
    if callback is None:
        return None
    frac_start, frac_end = frac_range
    span = frac_end - frac_start

    def wrapped(progress: AnalysisProgress) -> None:
        callback(
            AnalysisProgress(
                stage=progress.stage,
                message=progress.message or stage_label,
                fraction=frac_start + progress.fraction * span,
                elapsed_sec=time.perf_counter() - started,
                remaining_sec=progress.remaining_sec,
                geometry=progress.geometry,
                tseg=progress.tseg,
                radlex_series_description=progress.radlex_series_description,
            )
        )

    return wrapped


def harmonize_series(
    series_directories: list[Path],
    *,
    progress: ProgressCallback | None = None,
) -> list[HarmonizedResult]:
    """
    Run harmonize sequentially per series: geometry → TS segmentation → TS contrast → Playbook merge.

    Geometry is cached under ``<series>/A_TS_SEG/geometry.json``. TotalSegmentator is skipped when
    ``geometry.ts_suitable`` is false (localizers, single-slice 2D, derived 3D renders, etc.).

    Series descriptions are built only from TotalSegmentator anatomy and contrast plus DICOM geometry
    (Playbook body part, IV contrast phase, anatomic plane). FALCON is not used.
    """
    if not series_directories:
        return []

    if not ENABLE_TS_CONTRAST:
        logger.warning("Harmonize: ENABLE_TS_CONTRAST=False; contrast phase is required for Playbook merge")

    logger.info(
        "Harmonize starting for %d series (geometry → TS seg → TS contrast → Playbook merge)",
        len(series_directories),
    )
    started = time.perf_counter()
    log_memory_usage("harmonize_start")
    log_active_threads("harmonize_start")

    def _report(
        stage: str,
        message: str,
        fraction: float,
        remaining_sec: float | None = None,
        *,
        geometry: SeriesGeometryResult | None = None,
        tseg: TS_result | None = None,
        radlex_series_description: str | None = None,
    ) -> None:
        if progress is None:
            return
        progress(
            HarmonizeProgress(
                stage=stage,
                message=message,
                fraction=fraction,
                elapsed_sec=time.perf_counter() - started,
                remaining_sec=remaining_sec,
                geometry=geometry,
                tseg=tseg,
                radlex_series_description=radlex_series_description,
            )
        )

    harmonized: list[HarmonizedResult] = []
    n_series = len(series_directories)

    for index, series_dir in enumerate(series_directories, start=1):
        series_dir = Path(series_dir)
        logger.info("=== Harmonize [%d/%d] %s ===", index, n_series, series_dir)

        geometry = resolve_series_geometry(series_dir)
        _report(
            "geometry",
            format_geometry_progress_message(geometry),
            _GEOMETRY_FRAC[1],
            geometry=geometry,
        )
        logger.info(
            "Harmonize geometry: plane=%s dimensionality=%s provenance=%s ts_suitable=%s",
            geometry.plane,
            geometry.dimensionality,
            geometry.provenance,
            geometry.ts_suitable,
        )

        _report("tseg", "Segmenting anatomy", _TSEG_SEG_FRAC[0], remaining_sec=60.0)
        if ts_regions_eligible(geometry):
            logger.info("Harmonize stage 1/3: TS segmentation for %s", series_dir)
            tseg_progress = _scaled_progress(
                progress,
                started=started,
                frac_range=_TSEG_SEG_FRAC,
                stage_label="Segmenting anatomy",
            )
            region_result, nifti_path = analyze_tseg_regions(series_dir, progress=tseg_progress)
            if region_result.body_parts_present.strip() and region_result.error is None:
                _report(
                    "regions",
                    "Anatomy regions summarized",
                    _TSEG_SEG_FRAC[1],
                    geometry=geometry,
                    tseg=region_result,
                )
        else:
            logger.info(
                "Harmonize stage 1/3: TS segmentation skipped for %s (%s)",
                series_dir,
                geometry.notes or geometry.dimensionality,
            )
            _report(
                "tseg",
                format_geometry_progress_message(geometry),
                _TSEG_SEG_FRAC[1],
            )
            region_result = TS_result(
                series_directory=series_dir,
                dominant_region="",
                body_parts_present="",
                multi_region=False,
                region_fraction=0.0,
                iv_contrast=False,
                contrast_phase="",
                phase_probability=0.0,
                radlex_series_description="",
                error=geometry.notes or f"TS skipped ({geometry.dimensionality})",
            )
            nifti_path = None

        tseg: TS_result | None = region_result
        if (
            ENABLE_TS_CONTRAST
            and nifti_path is not None
            and region_result.body_parts_present.strip()
            and region_result.error is None
        ):
            _report(
                "contrast",
                "Analyzing contrast phase",
                _TSEG_CONTRAST_FRAC[0],
                remaining_sec=estimate_tseg_contrast_remaining_sec(series_dir),
            )
            logger.info("Harmonize stage 2/3: TS contrast for %s (nifti=%s)", series_dir, nifti_path)
            contrast_progress = _scaled_progress(
                progress,
                started=started,
                frac_range=_TSEG_CONTRAST_FRAC,
                stage_label="Analyzing contrast phase",
            )
            tseg = analyze_tseg_contrast(
                series_dir,
                nifti_path,
                region_result,
                progress=contrast_progress,
            )
            _report(
                "contrast",
                "Contrast phase analysis complete",
                _TSEG_CONTRAST_FRAC[1],
                geometry=geometry,
                tseg=tseg,
            )
        elif not ENABLE_TS_CONTRAST:
            logger.warning("Harmonize: TS contrast disabled; cannot build Playbook description for %s", series_dir)
        elif region_result.error:
            logger.warning("Harmonize skipping TS contrast (regions error): %s", region_result.error)
        else:
            logger.warning("Harmonize skipping TS contrast (no regions detected)")

        release_working_memory(stage="harmonize_after_tseg_contrast")

        _report(
            "merge",
            "Building harmonized description",
            _MERGE_FRAC[0],
            remaining_sec=0.0,
            geometry=geometry,
            tseg=tseg,
        )
        merged = _merge_result(series_dir, tseg, geometry=geometry)
        harmonized.append(merged)
        if merged.error:
            logger.warning(
                "Harmonize [%d/%d] %s failed: %s",
                index,
                n_series,
                series_dir,
                merged.error,
            )
        else:
            logger.info(
                "Harmonize [%d/%d] %s: description=%r body=%s contrast=%s plane=%s series_type=%s",
                index,
                n_series,
                series_dir,
                merged.radlex_series_description,
                merged.playbook.body_part_code if merged.playbook else "",
                merged.playbook.iv_contrast_code if merged.playbook else "",
                merged.playbook.anatomic_plane_code if merged.playbook else "",
                merged.playbook.series_type_code if merged.playbook else "",
            )
            _report(
                "merge",
                "Harmonized description ready",
                _MERGE_FRAC[1],
                geometry=geometry,
                tseg=tseg,
                radlex_series_description=merged.radlex_series_description,
            )

    _report("done", "Harmonize complete", 1.0, remaining_sec=0.0)
    log_memory_usage("harmonize_end")
    logger.info("Harmonize finished: %d result(s) in %.1fs", len(harmonized), time.perf_counter() - started)
    return harmonized
