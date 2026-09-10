"""Combine TotalSegmentator anatomy analysis into Playbook-compliant series descriptions."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydicom import Dataset, dcmread

import anonymizer.controller.ai.tseg.config as tseg_config
from anonymizer.controller.ai.harmonize.playbook import (
    MetadataHarmonizeRoute,
    PlaybookHarmonizeAttributes,
    build_harmonized_series_description,
    build_localizer_harmonized_series_description,
    build_metadata_harmonized_series_description,
    build_playbook_attributes,
    format_playbook_analysis_log_lines,
    is_localizer_geometry,
    resolve_metadata_harmonize_route,
)
from anonymizer.controller.ai.harmonize.timings import HarmonizeStageTimings, HarmonizeTimingCollector
from anonymizer.controller.ai.tseg.config import (
    CONTRAST_PHASE_CACHE_FILENAME,
    CONTRAST_STATS_FILENAME,
    CONTRAST_STATS_HN_FILENAME,
    ENABLE_TS_CONTRAST,
    ROI_SUBSET,
)
from anonymizer.controller.ai.tseg.contrast import (
    contrast_phase_cache_is_valid,
    load_contrast_phase_cache,
    load_contrast_statistics,
    log_memory_usage,
    needs_head_neck_vessel_stats,
    phase_to_iv_contrast,
    release_working_memory,
)
from anonymizer.controller.ai.tseg.dicom_geometry import (
    SeriesGeometryResult,
    format_geometry_progress_message,
    geometry_analysis_progress_prefix,
    load_geometry_cache,
    resolve_series_geometry,
    sorted_dicom_paths,
    ts_regions_eligible,
)
from anonymizer.controller.ai.tseg.ml_env import log_active_threads
from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series
from anonymizer.controller.ai.tseg.model_cache import tseg_batch_session
from anonymizer.controller.ai.tseg.segment import (
    HARMONIZE_CANCELLED_MESSAGE,
    AnalysisProgress,
    ProgressCallback,
    TS_result,
    analyze_tseg_contrast,
    analyze_tseg_ct_single_pass,
    analyze_tseg_regions,
    body_parts_present,
    collect_structure_voxels,
    dominant_region_from_voxels,
    estimate_tseg_contrast_remaining_sec,
    harmonize_cancel_requested,
    series_cache_dir,
)
from anonymizer.controller.ai.tseg.segment import (
    _region_ts_result as region_ts_result_from_summary,
)
from anonymizer.controller.ai.tseg.segment import (
    _segmentation_cache_valid as segmentation_cache_valid,
)
from anonymizer.utils.translate import _

if TYPE_CHECKING:
    from anonymizer.model.anonymizer import AnonymizerModel

from anonymizer.controller.ai.harmonize.loinc_study import StudyDescriptionOffer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HarmonizeProgress:
    """Progress event for Harmonize UI/batch (includes Playbook description when ready)."""

    stage: str
    message: str
    fraction: float
    elapsed_sec: float
    remaining_sec: float | None = None
    geometry: SeriesGeometryResult | None = None
    tseg: TS_result | None = None
    radlex_series_description: str | None = None


HarmonizeProgressCallback = Callable[[HarmonizeProgress], None]

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
    planar: object | None = None  # PlanarPlaybookAttributes when metadata path used


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
    if tseg is not None and tseg.body_parts_present.strip() and tseg.contrast_phase and tseg.error is None:
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


def _merge_metadata_result(
    series_directory: Path,
    geometry: SeriesGeometryResult,
    tseg: TS_result | None,
    *,
    ds: Dataset,
    route: MetadataHarmonizeRoute,
) -> HarmonizedResult:
    try:
        description, playbook = build_metadata_harmonized_series_description(ds, geometry, route)
    except ValueError as exc:
        logger.warning("Harmonize metadata merge failed for %s: %s", series_directory, exc)
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


def _contrast_phase_required(series_directory: Path) -> bool:
    """CT (and unknown modalities) require contrast phase; MR profiles skip it."""
    profile = resolve_profile_for_series(series_directory)
    return profile is None or profile.enable_contrast_phase


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
            error=_("Series geometry is required for Playbook harmonization"),
        )

    if is_localizer_geometry(geometry):
        return _merge_localizer_result(series_directory, geometry, tseg)

    try:
        ds = _load_series_dataset(series_directory)
    except ValueError as exc:
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=str(exc),
        )

    metadata_route = resolve_metadata_harmonize_route(ds, geometry)
    if metadata_route is not None:
        return _merge_metadata_result(
            series_directory,
            geometry,
            tseg,
            ds=ds,
            route=metadata_route,
        )

    if tseg is None or not tseg.body_parts_present.strip():
        anatomy_fallback = resolve_metadata_harmonize_route(ds, geometry, tseg=tseg)
        if anatomy_fallback is not None:
            return _merge_metadata_result(
                series_directory,
                geometry,
                tseg,
                ds=ds,
                route=anatomy_fallback,
            )
        error = tseg.error if tseg is not None and tseg.error else _("TotalSegmentator anatomy analysis unavailable")
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

    if not tseg.contrast_phase and _contrast_phase_required(series_directory):
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            geometry=geometry,
            error=_("TotalSegmentator contrast phase is required for Playbook harmonization"),
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
    """Rebuild anatomy (+ contrast when required) TS_result from ``0_TS_SEG`` without running ML."""
    cache_dir = series_cache_dir(series_directory)
    seg_dir = cache_dir / "seg"
    profile = resolve_profile_for_series(series_directory)
    structures = list(profile.roi_subset if profile is not None else ROI_SUBSET)
    if not segmentation_cache_valid(seg_dir, structures):
        return None

    structure_voxels = collect_structure_voxels(seg_dir, structures)
    structure_to_region = profile.structure_to_region if profile is not None else None
    region = dominant_region_from_voxels(
        structure_voxels,
        structure_to_region=structure_to_region,
    )
    regions_label = body_parts_present(region.region_voxels)
    if not regions_label:
        return None

    region_result = region_ts_result_from_summary(
        series_directory,
        region=region,
        regions_label=regions_label,
    )

    if profile is not None and not profile.enable_contrast_phase:
        return region_result

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

    needs_head_neck = needs_head_neck_vessel_stats(
        existing_stats,
        body_parts_present=regions_label,
    )
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

    if not ts_regions_eligible(geometry):
        try:
            ds = _load_series_dataset(series_directory)
        except ValueError:
            return None
        metadata_route = resolve_metadata_harmonize_route(ds, geometry)
        if metadata_route is None:
            return None
        merged = _merge_metadata_result(
            series_directory,
            geometry,
            None,
            ds=ds,
            route=metadata_route,
        )
        if merged.error:
            return None
        description = (merged.radlex_series_description or "").strip()
        return description or None

    if _contrast_phase_required(series_directory) and not ENABLE_TS_CONTRAST:
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
    from anonymizer.utils.modalities import is_tseg_modality

    if ds is None or not is_tseg_modality(getattr(ds, "Modality", None)):
        return None
    if series_description_is_harmonized(series_directory, ds) is not True:
        return None
    return _("Series description already harmonized — use Clear to re-run analysis")


@dataclass(frozen=True)
class HarmonizeApplyOutcome:
    series_path: Path
    status: str
    message: str = ""
    harmonized: HarmonizedResult | None = None


@dataclass(frozen=True)
class HarmonizeStudiesSummary:
    processed: int = 0
    skipped: int = 0
    applied: int = 0
    failed: int = 0
    cancelled: bool = False


HarmonizeStudiesProgressCallback = Callable[[int, int, str, float], None]
HarmonizeStudiesCancelledCallback = Callable[[], bool]
HarmonizeCancelledCallback = HarmonizeStudiesCancelledCallback
HarmonizeStudiesLogCallback = Callable[[HarmonizeApplyOutcome], None]
HarmonizeStudiesBatchHook = Callable[[], None]


def missing_series_description_label() -> str:
    return f"<{_('No Series Description')}>"


def _format_progress_pct(fraction: float) -> str:
    pct = min(100, max(0, int(round(fraction * 100))))
    return f" ({pct}%)"


def format_harmonize_progress_message(
    progress: HarmonizeProgress,
    *,
    include_pct: bool = True,
    segmentation_mode: object | None = None,
) -> str:
    """Translate harmonize pipeline stages to clinician-friendly status text."""
    from anonymizer.controller.ai.tseg.config import segmentation_mode_display

    message = (progress.message or "").strip()
    stage = progress.stage
    geometry_prefix = geometry_analysis_progress_prefix()
    pct = _format_progress_pct(progress.fraction) if include_pct else ""
    resolution = (
        segmentation_mode_display(segmentation_mode) if segmentation_mode is not None else None
    )

    def _segmenting_anatomy_label() -> str:
        base = _("Segmenting anatomy (TotalSegmentator)")
        if resolution is None:
            return base
        return f"{base} · {resolution}"

    def _cached_anatomy_label() -> str:
        base = _("Using cached anatomy segmentation")
        if resolution is None:
            return base
        return f"{base} · {resolution}"

    if stage == "done":
        return _("Harmonize analysis complete")

    if stage == "failed":
        detail = message.strip()
        if detail:
            return _("Harmonize analysis failed") + f": {detail}"
        return _("Harmonize analysis failed")

    if stage == "geometry" and message.startswith(geometry_prefix):
        summary = message[len(geometry_prefix) :].strip()
        if summary:
            return summary + pct
        return _("Scan geometry analyzed") + pct
    if stage == "tseg" and message.startswith(geometry_prefix):
        return _("Anatomy analysis not available for this series") + pct

    known_messages = {
        "Starting contrast phase analysis": _("Starting contrast phase analysis"),
        "Contrast phase analysis complete": _("Contrast phase analysis complete"),
        "Reading IV contrast from DICOM": _("Reading IV contrast from DICOM"),
        "Contrast phase not applicable": _("Reading IV contrast from DICOM"),
        "Segmenting anatomy": _segmenting_anatomy_label(),
        "Segmenting face mask": _("Segmenting face mask"),
        "Segmenting brain structures": _("Segmenting brain structures"),
        "Preparing CT volume": _("Preparing CT volume"),
        "Preparing volume": _("Preparing volume"),
        "Using cached anatomy segmentation": _cached_anatomy_label(),
        "Summarizing anatomy regions": _("Summarizing anatomy regions"),
        "Building harmonized description": _("Building standardized series description"),
        "Harmonized description ready": _("Standardized series description ready"),
        "Analyzing contrast phase": _("Determining contrast phase"),
        "Computing organ HU statistics": _("Computing organ HU statistics"),
        "Organ HU statistics complete": _("Organ HU statistics complete"),
        "Computing head/neck vessel statistics": _("Computing head/neck vessel statistics"),
        "Head/neck vessel statistics complete": _("Head/neck vessel statistics complete"),
        "Head/neck statistics not required": _("Head/neck statistics not required"),
        "Classifying contrast phase (XGBoost)": _("Classifying contrast phase (XGBoost)"),
        "Contrast phase classification complete": _("Contrast phase classification complete"),
    }

    detail_message_stages = frozenset(
        {
            "regions",
            "contrast_stats_cached",
            "contrast_stats_hn_cached",
            "contrast_phase_cache",
        }
    )
    if stage in detail_message_stages and message:
        return known_messages.get(message, _(message)) + pct
    if stage == "segment" and "cached" in message.lower():
        return known_messages.get(message, _(message)) + pct

    stage_labels: dict[str, str] = {
        "geometry": _("Analyzing scan geometry"),
        "prepare": _("Preparing CT volume"),
        "segment": _segmenting_anatomy_label(),
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

    # Prefer specific pipeline messages (e.g. MR DICOM contrast) over generic stage labels.
    if message in known_messages:
        return known_messages[message] + "…" + pct

    if stage in stage_labels:
        return stage_labels[stage] + "…" + pct

    if message:
        return known_messages.get(message, _(message)) + pct

    return _("Processing") + "…" + pct


def log_harmonize_playbook_rows(
    log_workflow: Callable[[str], None],
    *,
    tseg: TS_result,
    geometry: SeriesGeometryResult,
    ds: Dataset | None = None,
) -> None:
    """Emit Playbook table rows to the batch workflow log."""
    attributes = build_playbook_attributes(tseg, geometry, ds=ds)
    for line in format_playbook_analysis_log_lines(
        attributes,
        geometry=geometry,
        ds=ds,
        tseg=tseg,
    ):
        log_workflow(f"  {line}")


def format_harmonize_batch_series_label(series_path: Path, ds: Dataset | None = None) -> str:
    """Compact series label for batch harmonize progress."""
    series_path = Path(series_path)
    if ds is not None:
        description = str(ds.get("SeriesDescription", "") or "").strip()
        series_no = ds.get("SeriesNumber")
        if description:
            if series_no not in (None, ""):
                return _("Series") + f' #{series_no}: "{description}"'
            return _("Series") + f': "{description}"'
        if series_no not in (None, ""):
            return _("Series") + f" #{series_no}: {missing_series_description_label()}"
        return _("Series") + f": {missing_series_description_label()}"
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
    from anonymizer.controller.ai.tseg.config import segmentation_mode_for_modality

    series_label = format_harmonize_batch_series_label(series_path, ds)
    stage_text = format_harmonize_progress_message(
        progress,
        segmentation_mode=segmentation_mode_for_modality(getattr(ds, "Modality", None) if ds else None),
    )
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
    """Load series dataset only when modality is CT (CT-only callers)."""
    from pydicom.errors import InvalidDicomError

    try:
        ds = _load_series_dataset(series_path)
    except (ValueError, OSError, InvalidDicomError):
        return None
    if getattr(ds, "Modality", None) != "CT":
        return None
    return ds


def _load_tseg_series_dataset(series_path: Path) -> Dataset | None:
    """Load series dataset when modality has a TSEG profile (CT or MR)."""
    from pydicom.errors import InvalidDicomError

    from anonymizer.controller.ai.tseg.modality_profile import profile_for_modality

    try:
        ds = _load_series_dataset(series_path)
    except (ValueError, OSError, InvalidDicomError):
        return None
    if profile_for_modality(getattr(ds, "Modality", None)) is None:
        return None
    return ds


def _load_planar_series_dataset(series_path: Path) -> Dataset | None:
    """Load series dataset when modality is XR (CR/DX), US, or MG — never CT/MR."""
    from pydicom.errors import InvalidDicomError

    from anonymizer.utils.modalities import is_planar_harmonize_modality, is_tseg_modality

    try:
        ds = _load_series_dataset(series_path)
    except (ValueError, OSError, InvalidDicomError):
        return None
    modality = getattr(ds, "Modality", None)
    # Isolation: never treat CT/MR as planar even if tags look radiographic.
    if is_tseg_modality(modality):
        return None
    if not is_planar_harmonize_modality(modality):
        return None
    return ds


def _load_harmonize_series_dataset(series_path: Path) -> Dataset | None:
    """Load dataset for any Harmonize-eligible series (TSEG or planar)."""
    return _load_tseg_series_dataset(series_path) or _load_planar_series_dataset(series_path)


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


def enumerate_tseg_series_for_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[Path]:
    """Return CT|MR series directories under the selected anonymized studies."""
    series_list: list[Path] = []
    for series_path in _iter_study_series_dirs(images_dir, studies):
        if _load_tseg_series_dataset(series_path) is not None:
            series_list.append(series_path)
    return series_list


def enumerate_planar_series_for_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[Path]:
    """Return XR/US/MG series directories under the selected anonymized studies."""
    series_list: list[Path] = []
    for series_path in _iter_study_series_dirs(images_dir, studies):
        if _load_planar_series_dataset(series_path) is not None:
            series_list.append(series_path)
    return series_list


def enumerate_harmonize_series_for_studies(
    images_dir: Path,
    studies: Sequence[tuple[str, str]],
) -> list[Path]:
    """Return CT|MR|XR|US|MG series directories (SC/OT/DOC excluded)."""
    return enumerate_tseg_series_for_studies(images_dir, studies) + enumerate_planar_series_for_studies(
        images_dir, studies
    )


def study_harmonize_status(
    anon_model: "AnonymizerModel",
    anon_study_uid: str,
) -> bool:
    """
    Return True when every eligible CT|MR series in the study is harmonized.

    Uses ORM ``Series.harmonized_description`` metadata (no filesystem or TS cache reads).
    """
    return anon_model.study_is_harmonized(anon_study_uid)


def apply_harmonized_description(
    series_path: Path,
    description: str,
    anon_model: AnonymizerModel | None,
) -> bool:
    """Apply harmonized SeriesDescription to DICOM when needed and update the project database."""
    from anonymizer.controller.series_io import apply_series_description

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

    if current != description:
        from anonymizer.controller.create_projections import invalidate_projection_cache

        invalidate_projection_cache(series_path)

    if anon_model is None:
        return True
    return anon_model.set_series_harmonized_description(str(ds.SeriesInstanceUID), description)


def study_root_for_series(series_path: Path) -> Path:
    """Return the anonymized study directory that contains ``series_path``."""
    return Path(series_path).resolve().parent


def study_series_description_fingerprint(
    anon_model: AnonymizerModel,
    anon_study_uid: str,
) -> tuple[str, ...]:
    """Sorted multiset fingerprint of CT Playbook series descriptions for a study."""
    from anonymizer.controller.ai.harmonize.loinc_study import fingerprint_for_harmonized_study

    return fingerprint_for_harmonized_study(anon_model, anon_study_uid)


def find_studies_with_fingerprint(
    anon_model: AnonymizerModel,
    fingerprint: tuple[str, ...],
) -> list[str]:
    """Return anon_study_uid values whose CT series Playbook set matches ``fingerprint``."""
    return anon_model.find_studies_with_series_fingerprint(fingerprint)


def apply_harmonized_study_description(
    study_root: Path,
    description: str,
    anon_model: AnonymizerModel | None,
    anon_study_uid: str,
    *,
    loinc_number: str | None = None,
) -> bool:
    """Write StudyDescription (+ optional LOINC ProcedureCodeSequence) and update ORM."""
    from anonymizer.controller.series_io import apply_study_description

    description = description.strip()
    if not description:
        return False
    if not apply_study_description(Path(study_root), description, loinc_number=loinc_number):
        return False
    if anon_model is None:
        return True
    return anon_model.set_study_harmonized_description(anon_study_uid, description)


def ct_series_paths_for_study(images_dir: Path, anon_patient_id: str, anon_study_uid: str) -> list[Path]:
    """Return CT series directories under an anonymized study folder."""
    study_root = Path(images_dir) / anon_patient_id / anon_study_uid
    if not study_root.is_dir():
        return []
    return [
        path
        for path in sorted(study_root.iterdir())
        if path.is_dir() and not path.name.startswith(".") and _load_ct_series_dataset(path) is not None
    ]


def tseg_series_paths_for_study(images_dir: Path, anon_patient_id: str, anon_study_uid: str) -> list[Path]:
    """Return CT|MR series directories under an anonymized study folder."""
    study_root = Path(images_dir) / anon_patient_id / anon_study_uid
    if not study_root.is_dir():
        return []
    return [
        path
        for path in sorted(study_root.iterdir())
        if path.is_dir() and not path.name.startswith(".") and _load_tseg_series_dataset(path) is not None
    ]


def planar_series_paths_for_study(images_dir: Path, anon_patient_id: str, anon_study_uid: str) -> list[Path]:
    """Return XR/US/MG series directories under an anonymized study folder."""
    study_root = Path(images_dir) / anon_patient_id / anon_study_uid
    if not study_root.is_dir():
        return []
    return [
        path
        for path in sorted(study_root.iterdir())
        if path.is_dir() and not path.name.startswith(".") and _load_planar_series_dataset(path) is not None
    ]


def maybe_offer_study_description_harmonize(
    anon_model: AnonymizerModel,
    anon_study_uid: str,
    *,
    images_dir: Path | None = None,
    top_n: int = 8,
) -> StudyDescriptionOffer | None:
    """
    Build a Study Description offer when the study just became fully Harmonized.

    CT|MR studies: unchanged TSEG gate + CT/MR LOINC ranking.
    Pure XR/US/MG studies: planar gate + XR/US/MG LOINC ranking.
    Mixed CT|MR + planar: only the CT|MR path (planar series must not block CT LOINC).
    """
    from anonymizer.controller.ai.harmonize.loinc_study import (
        build_study_description_ranking,
        count_planar_study_images,
        fingerprint_for_harmonized_study,
        fingerprint_for_planar_harmonized_study,
        rank_planar_loinc_study_descriptions,
    )
    from anonymizer.utils.modalities import planar_harmonize_cohort

    if anon_model.get_study_harmonized_description(anon_study_uid):
        return None

    composition = getattr(anon_model, "study_composition_for_harmonize", None)
    if callable(composition):
        raw = composition(anon_study_uid)
        try:
            has_tseg, has_planar = bool(raw[0]), bool(raw[1])
        except (TypeError, IndexError, ValueError):
            # Test doubles / unexpected return: fall back to CT|MR-only gate.
            has_tseg, has_planar = True, False
    else:
        has_tseg, has_planar = True, False

    # --- CT/MR path (behavioral freeze) ---
    if has_tseg:
        if not anon_model.study_is_harmonized(anon_study_uid):
            return None

        descriptions = anon_model.get_ct_series_harmonized_descriptions(anon_study_uid)
        fingerprint = fingerprint_for_harmonized_study(anon_model, anon_study_uid)
        if not fingerprint:
            return None

        series_paths: list[Path] = []
        loinc_prefix = "CT "
        if images_dir is not None:
            patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
            if patient_id:
                series_paths = tseg_series_paths_for_study(Path(images_dir), patient_id, anon_study_uid)
                from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series

                profiles = [resolve_profile_for_series(p) for p in series_paths]
                if profiles and all(p is not None and p.modality == "MR" for p in profiles):
                    loinc_prefix = "MR "

        _aggregate, matches, ambiguous = build_study_description_ranking(
            descriptions,
            top_n=top_n,
            series_paths=series_paths or None,
            loinc_prefix=loinc_prefix,
        )
        if not matches:
            return None

        peers = [
            uid
            for uid in find_studies_with_fingerprint(anon_model, fingerprint)
            if uid != anon_study_uid and not anon_model.get_study_harmonized_description(uid)
        ]
        return StudyDescriptionOffer(
            anon_study_uid=anon_study_uid,
            fingerprint=fingerprint,
            matches=tuple(matches),
            peer_study_uids=tuple(peers),
            ambiguous=ambiguous,
        )

    # --- Pure planar path (no CT/MR siblings) ---
    if not has_planar:
        return None
    if not anon_model.study_is_planar_harmonized(anon_study_uid):
        return None

    descriptions = anon_model.get_planar_series_harmonized_descriptions(anon_study_uid)
    if not descriptions:
        return None

    modalities = anon_model.get_planar_series_modalities(anon_study_uid)
    cohorts = {planar_harmonize_cohort(m) for m in modalities}
    cohorts.discard(None)
    if len(cohorts) != 1:
        # Mixed XR+US etc.: skip auto LOINC for v1
        return None
    cohort = next(iter(cohorts))
    assert cohort is not None

    image_count: int | None = None
    if images_dir is not None:
        patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
        if patient_id:
            planar_paths = planar_series_paths_for_study(Path(images_dir), patient_id, anon_study_uid)
            counted = count_planar_study_images(planar_paths)
            if counted > 0:
                image_count = counted

    fingerprint = fingerprint_for_planar_harmonized_study(anon_model, anon_study_uid)
    if not fingerprint:
        return None

    from anonymizer.controller.ai.harmonize.playbook_planar import planar_loinc_prefix_for_series_descriptions

    loinc_prefix = planar_loinc_prefix_for_series_descriptions(cohort, descriptions)
    matches = rank_planar_loinc_study_descriptions(
        descriptions,
        loinc_prefix=loinc_prefix,
        top_n=top_n,
        image_count=image_count,
    )
    if not matches:
        return None
    ambiguous = len(matches) > 1 and (matches[0].score - matches[1].score) < 80.0

    peers = [
        uid
        for uid in anon_model.find_studies_with_planar_series_fingerprint(fingerprint)
        if uid != anon_study_uid and not anon_model.get_study_harmonized_description(uid)
    ]
    return StudyDescriptionOffer(
        anon_study_uid=anon_study_uid,
        fingerprint=fingerprint,
        matches=tuple(matches),
        peer_study_uids=tuple(peers),
        ambiguous=ambiguous,
    )


def _looks_like_loinc_study_description(name: str) -> bool:
    """True when ``name`` looks like a LOINC LongCommonName (modality-prefixed)."""
    return bool(re.match(r"(?i)^(CT|MR|XR|US|MG)\b", (name or "").strip()))


def study_description_edit_offer(
    anon_model: AnonymizerModel,
    anon_study_uid: str,
    *,
    top_n: int = 10,
) -> StudyDescriptionOffer | None:
    """
    Build a LOINC Study Description menu for Dataset edit from ORM signals only.

    Uses stored series harmonized descriptions, composition, and planar instance
    counts — never opens DICOM or walks ``images_dir``. When CT|MR series are not
    yet Harmonized, ranks LOINC from the study description text when present.
    """
    from anonymizer.controller.ai.harmonize.loinc_study import (
        LoincStudyMatch,
        build_study_description_ranking,
        fingerprint_for_harmonized_study,
        fingerprint_for_planar_harmonized_study,
        rank_loinc_study_descriptions_from_hint,
        rank_planar_loinc_study_descriptions,
    )
    from anonymizer.controller.ai.harmonize.playbook_planar import planar_loinc_prefix_for_series_descriptions
    from anonymizer.utils.modalities import is_mr_modality, planar_harmonize_cohort

    composition = getattr(anon_model, "study_composition_for_harmonize", None)
    if callable(composition):
        raw = composition(anon_study_uid)
        try:
            has_tseg, has_planar = bool(raw[0]), bool(raw[1])
        except (TypeError, IndexError, ValueError):
            has_tseg, has_planar = True, False
    else:
        has_tseg, has_planar = True, False

    current = (anon_model.get_study_harmonized_description(anon_study_uid) or "").strip()

    def _with_current(matches: list, fingerprint: tuple[str, ...]) -> StudyDescriptionOffer:
        ranked = list(matches)
        # Keep only Harmonized / LOINC-style currents — never raw PHI study text.
        if (
            current
            and _looks_like_loinc_study_description(current)
            and not any(m.long_common_name == current for m in ranked)
        ):
            ranked.insert(0, LoincStudyMatch(loinc_number="", long_common_name=current, score=0.0))
        return StudyDescriptionOffer(
            anon_study_uid=anon_study_uid,
            fingerprint=fingerprint,
            matches=tuple(ranked),
            peer_study_uids=(),
            ambiguous=len(ranked) > 1 and ranked[0].score > 0 and (
                len(ranked) < 2 or (ranked[0].score - ranked[1].score) < 80.0
            ),
        )

    if has_tseg:
        descriptions = anon_model.get_ct_series_harmonized_descriptions(anon_study_uid)
        fingerprint = fingerprint_for_harmonized_study(anon_model, anon_study_uid)
        loinc_prefix = "CT "
        get_mods = getattr(anon_model, "get_tseg_series_modalities", None)
        if callable(get_mods):
            modalities = get_mods(anon_study_uid)
            if modalities and all(is_mr_modality(m) for m in modalities):
                loinc_prefix = "MR "

        if not descriptions and not current:
            return None
        if not descriptions:
            matches = rank_loinc_study_descriptions_from_hint(
                current,
                loinc_prefix=loinc_prefix,
                top_n=top_n,
            )
            return _with_current(matches, fingerprint or ((current,) if current else ()))

        _aggregate, matches, ambiguous = build_study_description_ranking(
            descriptions,
            top_n=top_n,
            series_paths=None,
            loinc_prefix=loinc_prefix,
        )
        offer = _with_current(matches, fingerprint or tuple(sorted(descriptions)))
        return StudyDescriptionOffer(
            anon_study_uid=offer.anon_study_uid,
            fingerprint=offer.fingerprint,
            matches=offer.matches,
            peer_study_uids=(),
            ambiguous=ambiguous if matches else offer.ambiguous,
        )

    if not has_planar:
        if current:
            return _with_current([], (current,))
        return None

    descriptions = anon_model.get_planar_series_harmonized_descriptions(anon_study_uid)
    fingerprint = fingerprint_for_planar_harmonized_study(anon_model, anon_study_uid)
    if not descriptions and not current:
        return None
    if not descriptions:
        return _with_current([], fingerprint or ((current,) if current else ()))

    modalities = anon_model.get_planar_series_modalities(anon_study_uid)
    cohorts = {planar_harmonize_cohort(m) for m in modalities}
    cohorts.discard(None)
    if len(cohorts) != 1:
        return _with_current([], fingerprint or tuple(sorted(descriptions)))

    cohort = next(iter(cohorts))
    assert cohort is not None
    loinc_prefix = planar_loinc_prefix_for_series_descriptions(cohort, descriptions)

    image_count: int | None = None
    get_count = getattr(anon_model, "get_planar_series_instance_count", None)
    if callable(get_count):
        counted = int(get_count(anon_study_uid) or 0)
        if counted > 0:
            image_count = counted

    matches = rank_planar_loinc_study_descriptions(
        descriptions,
        loinc_prefix=loinc_prefix,
        top_n=top_n,
        image_count=image_count,
    )
    offer = _with_current(matches, fingerprint or tuple(sorted(descriptions)))
    ambiguous = len(matches) > 1 and (matches[0].score - matches[1].score) < 80.0
    return StudyDescriptionOffer(
        anon_study_uid=offer.anon_study_uid,
        fingerprint=offer.fingerprint,
        matches=offer.matches,
        peer_study_uids=(),
        ambiguous=ambiguous if matches else offer.ambiguous,
    )


MIN_DESCRIPTION_CHOICES = 4
NEAREST_DESCRIPTION_CHOICES = 10

# Common RadLex Playbook planes / contrast phases offered as series edit alternatives.
_EDIT_PLANES: tuple[str, ...] = ("Ax", "Sag", "Cor")
_EDIT_CONTRASTS: tuple[str, ...] = ("WO", "W", "Art", "Ven", "Delay")
_EDIT_THICKNESS: tuple[str | None, ...] = (None, "Thin", "Thick")
_EDIT_XR_VIEWS: tuple[str, ...] = ("AP", "PA", "Lat", "Obl", "2V", "3V")
_EDIT_MG_VIEWS: tuple[str, ...] = ("CC", "MLO", "ML", "LM", "XCCL", "XCCM")
_EDIT_US_MODES: tuple[str, ...] = ("", "Doppler")

# LOINC anatomy labels → RadLex Playbook body-part codes for CT|MR series edit.
_LOINC_ANATOMY_TO_PLAYBOOK_BODY: dict[str, str] = {
    "Head": "Head",
    "Brain": "Brain",
    "Neck": "Neck",
    "Chest": "Ch",
    "Abdomen": "Abd",
    "Pelvis": "Pel",
    "Spine": "Spine",
    "Cervical spine": "CSp",
    "Thoracic spine": "TSp",
    "Lumbar spine": "LSp",
    "Breast": "Breast",
}


def ensure_min_description_choices(
    choices: list[str],
    extras: list[str],
    *,
    minimum: int = MIN_DESCRIPTION_CHOICES,
) -> list[str]:
    """Append unique ``extras`` until ``minimum`` choices, preserving order."""
    result: list[str] = []
    seen: set[str] = set()
    for text in choices:
        stripped = (text or "").strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
    if len(result) >= minimum:
        return result
    for text in extras:
        stripped = (text or "").strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            result.append(stripped)
            if len(result) >= minimum:
                break
    return result


def _format_tseg_playbook_description(
    *,
    body_parts: list[str],
    plane: str,
    contrast: str,
    slice_thickness: str,
    series_type: str,
    series_type_modifier: str,
) -> str:
    parts: list[str] = []
    if body_parts:
        parts.append("+".join(body_parts))
    if series_type == "Localizer":
        parts.append("Localizer")
        return " ".join(parts)
    if plane:
        parts.append(plane)
    if contrast:
        parts.append(contrast)
    if slice_thickness in {"Thin", "Thick"}:
        parts.append(slice_thickness)
    if series_type:
        parts.append(series_type)
    if series_type_modifier:
        parts.append(series_type_modifier)
    return " ".join(p for p in parts if p).strip()


def _playbook_body_parts_from_anatomy_hint(anatomy_hint: str) -> list[str]:
    """Map free-text study/series PHI anatomy into Playbook body-part codes."""
    from anonymizer.controller.ai.harmonize.loinc_study import infer_loinc_anatomy_from_text

    codes: list[str] = []
    seen: set[str] = set()
    for anat in infer_loinc_anatomy_from_text(anatomy_hint):
        code = _LOINC_ANATOMY_TO_PLAYBOOK_BODY.get(anat)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
        # MR neuro studies prefer Brain LOINC; keep Head as a sibling option.
        if anat == "Head" and "Brain" not in seen:
            seen.add("Brain")
            codes.append("Brain")
    return codes


def _tseg_radlex_series_edit_choices(
    current: str,
    *,
    minimum: int,
    full_catalog: bool = False,
    anatomy_hint: str = "",
) -> list[str]:
    from anonymizer.controller.ai.harmonize.loinc_study import parse_playbook_series_description
    from anonymizer.controller.ai.harmonize.playbook import BODY_PART_PLAYBOOK_CODES

    parsed = parse_playbook_series_description(current)
    parsed_body_parts = list(parsed.get("body_parts") or [])
    body_parts = list(parsed_body_parts)
    hinted_parts = _playbook_body_parts_from_anatomy_hint(anatomy_hint) if anatomy_hint else []
    if not body_parts:
        body_parts = list(hinted_parts[:1])

    base_plane = str(parsed.get("plane") or "")
    base_contrast = str(parsed.get("contrast") or "WO")
    base_thickness = str(parsed.get("slice_thickness") or "")
    series_type = str(parsed.get("series_type") or "")
    series_type_modifier = str(parsed.get("series_type_modifier") or "")

    choices: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        stripped = (text or "").strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            choices.append(stripped)

    def _emit_for_parts(parts: list[str]) -> None:
        if not parts:
            return
        planes = [base_plane] + [p for p in _EDIT_PLANES if p != base_plane] if base_plane else list(_EDIT_PLANES)
        contrasts = (
            [base_contrast] + [c for c in _EDIT_CONTRASTS if c != base_contrast]
            if base_contrast
            else list(_EDIT_CONTRASTS)
        )
        if full_catalog:
            # Full modality browse: anatomy × core plane × WO/W (filterable in dialog).
            catalog_planes = list(_EDIT_PLANES)
            catalog_contrasts = ("WO", "W")
            for plane in catalog_planes:
                for contrast in catalog_contrasts:
                    _add(
                        _format_tseg_playbook_description(
                            body_parts=parts,
                            plane=plane,
                            contrast=contrast,
                            slice_thickness="",
                            series_type="",
                            series_type_modifier="",
                        )
                    )
            return

        thicknesses: list[str] = []
        if base_thickness:
            thicknesses.append(base_thickness)
        for tok in _EDIT_THICKNESS:
            value = tok or ""
            if value not in thicknesses:
                thicknesses.append(value)

        for plane in planes:
            _add(
                _format_tseg_playbook_description(
                    body_parts=parts,
                    plane=plane,
                    contrast=base_contrast or "WO",
                    slice_thickness=base_thickness,
                    series_type=series_type,
                    series_type_modifier=series_type_modifier,
                )
            )
        for contrast in contrasts:
            _add(
                _format_tseg_playbook_description(
                    body_parts=parts,
                    plane=base_plane or planes[0],
                    contrast=contrast,
                    slice_thickness=base_thickness,
                    series_type=series_type,
                    series_type_modifier=series_type_modifier,
                )
            )
        for thickness in thicknesses:
            _add(
                _format_tseg_playbook_description(
                    body_parts=parts,
                    plane=base_plane or planes[0],
                    contrast=base_contrast or "WO",
                    slice_thickness=thickness,
                    series_type=series_type,
                    series_type_modifier=series_type_modifier,
                )
            )
        if len(choices) < minimum:
            for plane in planes:
                for contrast in contrasts:
                    for thickness in thicknesses:
                        _add(
                            _format_tseg_playbook_description(
                                body_parts=parts,
                                plane=plane,
                                contrast=contrast,
                                slice_thickness=thickness,
                                series_type=series_type,
                                series_type_modifier=series_type_modifier,
                            )
                        )
                        if len(choices) >= max(minimum, NEAREST_DESCRIPTION_CHOICES):
                            return

    if current.strip() and parsed_body_parts:
        # Only keep already-Playbook (harmonized) current values in the menu.
        _add(current)
    if series_type == "Localizer":
        return choices

    if full_catalog:
        preferred = list(dict.fromkeys([*(body_parts or []), *hinted_parts]))
        rest = sorted(code for code in BODY_PART_PLAYBOOK_CODES if code not in preferred)
        for code in [*preferred, *rest]:
            _emit_for_parts([code])
        return choices

    if not body_parts:
        # Unrecognized PHI without a study anatomy hint — do not invent Chest.
        return choices

    _emit_for_parts(body_parts)
    return choices


_EDIT_PLANAR_ANATOMY_LABELS: frozenset[str] = frozenset(
    {
        "Head",
        "Neck",
        "Chest",
        "Abdomen",
        "Pelvis",
        "Abdomen Pelvis",
        "Chest Abdomen Pelvis",
        "Spine",
        "Cervical spine",
        "Thoracic spine",
        "Lumbar spine",
        "Breast",
        "Upper extremity",
        "Lower extremity",
        "Hand",
        "Wrist",
        "Elbow",
        "Shoulder",
        "Hip",
        "Knee",
        "Ankle",
        "Foot",
        "Thyroid",
        "Axilla",
    }
)


def _planar_recognized_anatomy(tokens: Sequence[str]) -> str | None:
    """Return a known Playbook anatomy label from tokens, or None for raw PHI text."""
    import re

    if not tokens:
        return None
    joined = " ".join(tokens)
    for label in sorted(_EDIT_PLANAR_ANATOMY_LABELS, key=len, reverse=True):
        if re.search(rf"(?i)\b{re.escape(label)}\b", joined):
            return label
    for tok in tokens:
        if tok in _EDIT_PLANAR_ANATOMY_LABELS:
            return tok
    return None


def _planar_radlex_series_edit_choices(
    current: str,
    modality: object | None,
    *,
    minimum: int,
    full_catalog: bool = False,
) -> list[str]:
    from anonymizer.utils.modalities import planar_harmonize_cohort

    cohort = planar_harmonize_cohort(modality) or "XR"
    tokens = [tok for tok in current.split() if tok]
    anatomy = _planar_recognized_anatomy(tokens) or "Chest"

    laterality = ""
    for tok in tokens:
        if tok in {"L", "R", "Bilat"}:
            laterality = tok
            break

    view_set = _EDIT_MG_VIEWS if cohort == "MG" else _EDIT_XR_VIEWS
    current_view = next((tok for tok in tokens if tok in view_set), "")

    choices: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        stripped = (text or "").strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            choices.append(stripped)

    def _emit(*, anat: str, mode: str = "", view: str = "", lat: str = "") -> None:
        parts: list[str] = []
        if mode:
            parts.append(mode)
        parts.append(anat)
        if lat and cohort in {"XR", "MG"}:
            parts.append(lat)
        if view:
            parts.append(view)
        _add(" ".join(parts))

    if current.strip() and _planar_recognized_anatomy(tokens) is not None:
        # Only keep already-Playbook (harmonized) current values in the menu.
        _add(current)

    if full_catalog:
        anatomies = [anatomy] + sorted(a for a in _EDIT_PLANAR_ANATOMY_LABELS if a != anatomy)
    else:
        anatomies = [anatomy]

    if cohort == "US":
        us_core = ("Abdomen", "Pelvis", "Chest", "Neck", "Thyroid", "Head", "Liver", "Kidney", "Axilla")
        us_anatomies = [anatomy] + [a for a in us_core if a != anatomy]
        if not full_catalog:
            us_anatomies = [anatomy]
        for anat in us_anatomies:
            for mode in _EDIT_US_MODES:
                _emit(anat=anat, mode=mode)
            if not full_catalog and len(choices) >= minimum:
                return choices
        return choices

    if cohort == "MG":
        if full_catalog:
            lats = [laterality] if laterality else []
            lats = list(dict.fromkeys([*lats, "L", "R", "Bilat"]))
        else:
            lats = [laterality or "L"]
        views = ([current_view] if current_view else []) + [v for v in view_set if v != current_view]
        for lat in lats:
            for view in views:
                _emit(anat="Breast", view=view, lat=lat)
            _emit(anat="Breast", lat=lat)
        return choices

    views = ([current_view] if current_view else []) + [v for v in view_set if v != current_view]
    for anat in anatomies:
        for view in views:
            _emit(anat=anat, view=view, lat=laterality)
        _emit(anat=anat, lat=laterality)
        if not full_catalog and len(choices) >= max(minimum, NEAREST_DESCRIPTION_CHOICES):
            return choices
    return choices


def series_description_edit_choices(
    *,
    modality: object | None,
    current_description: str,
    minimum: int = MIN_DESCRIPTION_CHOICES,
    full_catalog: bool = False,
    anatomy_hint: str | None = None,
) -> list[str]:
    """
    RadLex Playbook series description menu for Dataset edit.

    Current value first, then modality-appropriate Playbook alternatives.
    Unrecognized PHI does not invent anatomy. ``full_catalog`` expands the
    modality-relevant Playbook catalog (filterable scroll dialog). ``anatomy_hint``
    (usually the parent study description) prioritizes matching body parts.
    """
    from anonymizer.utils.modalities import series_is_planar_harmonize_eligible, series_is_tseg_eligible

    current = (current_description or "").strip()
    hint = (anatomy_hint or "").strip()
    if series_is_tseg_eligible(modality):
        if current:
            seed = current
        else:
            parts = _playbook_body_parts_from_anatomy_hint(hint) if hint else []
            seed = f"{parts[0]} Ax WO" if parts else "Ch Ax WO"
        return _tseg_radlex_series_edit_choices(
            seed,
            minimum=minimum,
            full_catalog=full_catalog,
            anatomy_hint=hint or current,
        )
    if series_is_planar_harmonize_eligible(modality):
        from anonymizer.utils.modalities import planar_harmonize_cohort

        cohort = planar_harmonize_cohort(modality) or "XR"
        if current:
            seed = current
        elif cohort == "US":
            seed = "Abdomen"
        elif cohort == "MG":
            seed = "Breast L CC"
        else:
            seed = "Chest AP"
        return _planar_radlex_series_edit_choices(
            seed,
            modality,
            minimum=minimum,
            full_catalog=full_catalog,
        )
    return [current] if current else []



def study_loinc_prefix_for_edit(anon_model: AnonymizerModel, anon_study_uid: str) -> str | None:
    """Return LOINC LongCommonName prefix for a study, or None when unknown/mixed."""
    from anonymizer.controller.ai.harmonize.playbook_planar import planar_loinc_prefix_for_series_descriptions
    from anonymizer.utils.modalities import is_mr_modality, planar_harmonize_cohort

    composition = getattr(anon_model, "study_composition_for_harmonize", None)
    has_tseg, has_planar = False, False
    if callable(composition):
        raw = composition(anon_study_uid)
        try:
            has_tseg, has_planar = bool(raw[0]), bool(raw[1])
        except (TypeError, IndexError, ValueError):
            has_tseg, has_planar = False, False

    if has_tseg:
        get_mods = getattr(anon_model, "get_tseg_series_modalities", None)
        if callable(get_mods):
            modalities = get_mods(anon_study_uid)
            if modalities and all(is_mr_modality(m) for m in modalities):
                return "MR "
        return "CT "
    if has_planar:
        descriptions = anon_model.get_planar_series_harmonized_descriptions(anon_study_uid)
        modalities = anon_model.get_planar_series_modalities(anon_study_uid)
        cohorts = {planar_harmonize_cohort(m) for m in modalities}
        cohorts.discard(None)
        if len(cohorts) != 1:
            return None
        cohort = next(iter(cohorts))
        assert cohort is not None
        return planar_loinc_prefix_for_series_descriptions(cohort, descriptions)
    return None


def study_description_edit_choices(
    anon_model: AnonymizerModel,
    anon_study_uid: str,
    *,
    top_n: int = NEAREST_DESCRIPTION_CHOICES,
    minimum: int = MIN_DESCRIPTION_CHOICES,
    hint_description: str | None = None,
    full_catalog: bool = False,
) -> list[tuple[str, str | None]]:
    """
    LOINC Study Description menu for Dataset edit (modality-filtered CSV only).

    Returns ``(long_common_name, loinc_number)`` with the current harmonized
    description first when present. Harmonized studies: nearest ranked matches.
    Unharmonized / ``full_catalog``: entire modality-prefix LOINC list with
    hint-ranked rows first (filterable scroll dialog).
    """
    from anonymizer.controller.ai.harmonize.loinc_study import (
        load_loinc_study_descriptions_for_prefix,
        rank_loinc_study_descriptions_from_hint,
    )

    results: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    def _add(name: str, code: str | None) -> None:
        text = (name or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        results.append((text, (code or None)))

    current = (anon_model.get_study_harmonized_description(anon_study_uid) or "").strip()
    hint = (hint_description or "").strip() or current
    current_code: str | None = None
    offer = study_description_edit_offer(anon_model, anon_study_uid, top_n=top_n)
    ranked_from_series = False
    if offer is not None:
        for match in offer.matches:
            if match.long_common_name == current:
                current_code = match.loinc_number or None
            if match.score > 0:
                ranked_from_series = True
            # Skip raw PHI rows that offer may have carried with score 0.
            if match.score <= 0 and not _looks_like_loinc_study_description(match.long_common_name):
                continue
            _add(match.long_common_name, match.loinc_number or None)

    if current and _looks_like_loinc_study_description(current):
        rest = [(n, c) for n, c in results if n != current]
        results = [(current, current_code)] + rest
        seen = {n for n, _ in results}

    loinc_prefix = study_loinc_prefix_for_edit(anon_model, anon_study_uid)
    use_full = full_catalog or (not ranked_from_series and not current)

    if not use_full and ranked_from_series and len(results) >= max(minimum, top_n):
        return results[: max(minimum, top_n)]

    if not loinc_prefix:
        return results[: max(minimum, top_n)] if results and not use_full else results

    # Prefer hint-ranked rows, then (for full catalog) the rest of the modality list.
    for match in rank_loinc_study_descriptions_from_hint(
        hint or current,
        loinc_prefix=loinc_prefix,
        top_n=max(minimum, top_n) if not use_full else 80,
    ):
        _add(match.long_common_name, match.loinc_number or None)
        if not use_full and len(results) >= max(minimum, top_n):
            return results

    if use_full:
        for code, name in load_loinc_study_descriptions_for_prefix(loinc_prefix):
            _add(name, code)
        return results

    return results


DescriptionEditSelectionKind = str  # "series" | "study" | "invalid"


@dataclass(frozen=True)
class DescriptionEditSelection:
    """Validated Dataset selection for group description edit."""

    kind: DescriptionEditSelectionKind
    reason: str
    count: int
    cohort_key: str = ""


def series_description_cohort_key(modality: object | None) -> str | None:
    """Return cohort key for series group edit (``tseg`` / ``XR`` / ``US`` / ``MG``)."""
    from anonymizer.utils.modalities import (
        planar_harmonize_cohort,
        series_is_planar_harmonize_eligible,
        series_is_tseg_eligible,
    )

    if series_is_tseg_eligible(modality):
        return "tseg"
    if series_is_planar_harmonize_eligible(modality):
        return planar_harmonize_cohort(modality)
    return None


def classify_description_edit_selection(
    *,
    series_cohort_keys: Sequence[str | None] | None = None,
    study_loinc_prefixes: Sequence[str | None] | None = None,
) -> DescriptionEditSelection:
    """
    Validate a Dataset multi-select for Set description….

    Pass either series cohort keys or study LOINC prefixes — not both.
    """
    has_series = series_cohort_keys is not None and len(series_cohort_keys) > 0
    has_studies = study_loinc_prefixes is not None and len(study_loinc_prefixes) > 0
    if has_series and has_studies:
        return DescriptionEditSelection(
            kind="invalid",
            reason="mixed",
            count=len(series_cohort_keys or ()) + len(study_loinc_prefixes or ()),
        )
    if not has_series and not has_studies:
        return DescriptionEditSelection(kind="invalid", reason="empty", count=0)

    if has_series:
        keys = list(series_cohort_keys or ())
        if any(k is None for k in keys):
            return DescriptionEditSelection(kind="invalid", reason="ineligible", count=len(keys))
        unique = {str(k) for k in keys}
        if len(unique) != 1:
            return DescriptionEditSelection(kind="invalid", reason="mixed_modality", count=len(keys))
        return DescriptionEditSelection(
            kind="series",
            reason="",
            count=len(keys),
            cohort_key=next(iter(unique)),
        )

    prefixes = list(study_loinc_prefixes or ())
    if any(p is None or not str(p).strip() for p in prefixes):
        return DescriptionEditSelection(kind="invalid", reason="ineligible", count=len(prefixes))
    unique_p = {str(p) for p in prefixes}
    if len(unique_p) != 1:
        return DescriptionEditSelection(kind="invalid", reason="mixed_modality", count=len(prefixes))
    return DescriptionEditSelection(
        kind="study",
        reason="",
        count=len(prefixes),
        cohort_key=next(iter(unique_p)),
    )


def series_description_group_choices(
    *,
    modalities: Sequence[object | None],
    current_descriptions: Sequence[str],
    minimum: int = MIN_DESCRIPTION_CHOICES,
    anatomy_hint: str | None = None,
) -> list[str]:
    """
    Shared RadLex menu for a homogeneous series multi-select.

    Harmonized Playbook strings: nearest variants (~10).
    Unharmonized PHI: full modality-relevant Playbook catalog.
    """
    if not modalities:
        return []
    keys = [series_description_cohort_key(m) for m in modalities]
    info = classify_description_edit_selection(series_cohort_keys=keys)
    if info.kind != "series":
        return []

    pairs = list(zip(modalities, current_descriptions, strict=False))
    nonempty = [(m, str(d).strip()) for m, d in pairs if str(d).strip()]
    all_playbook = bool(nonempty) and all(
        _series_description_looks_playbook(modality=m, description=d) for m, d in nonempty
    )

    seed_desc = nonempty[0][1] if nonempty else ""
    return series_description_edit_choices(
        modality=modalities[0],
        current_description=seed_desc,
        minimum=NEAREST_DESCRIPTION_CHOICES if all_playbook else minimum,
        full_catalog=not all_playbook,
        anatomy_hint=anatomy_hint,
    )


def study_description_group_choices(
    anon_model: AnonymizerModel,
    anon_study_uids: Sequence[str],
    *,
    top_n: int = NEAREST_DESCRIPTION_CHOICES,
    minimum: int = MIN_DESCRIPTION_CHOICES,
    hint_descriptions: Sequence[str] | None = None,
) -> list[tuple[str, str | None]]:
    """Shared LOINC menu for a homogeneous study multi-select."""
    if not anon_study_uids:
        return []
    prefixes = [study_loinc_prefix_for_edit(anon_model, uid) for uid in anon_study_uids]
    info = classify_description_edit_selection(study_loinc_prefixes=prefixes)
    if info.kind != "study":
        return []

    hints = list(hint_descriptions or [])
    any_unharmonized = False
    for uid in anon_study_uids:
        harm = (anon_model.get_study_harmonized_description(uid) or "").strip()
        if not harm:
            any_unharmonized = True
            break

    results: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for index, uid in enumerate(anon_study_uids):
        hint = hints[index] if index < len(hints) else None
        for name, code in study_description_edit_choices(
            anon_model,
            uid,
            top_n=top_n,
            minimum=minimum,
            hint_description=hint,
            full_catalog=any_unharmonized,
        ):
            if name in seen:
                continue
            seen.add(name)
            results.append((name, code))
    if any_unharmonized:
        return results
    return results[: max(minimum, top_n) * 2]


def _series_description_looks_playbook(*, modality: object | None, description: str) -> bool:
    """True when ``description`` already looks like a RadLex Playbook series string."""
    from anonymizer.controller.ai.harmonize.loinc_study import parse_playbook_series_description
    from anonymizer.utils.modalities import series_is_planar_harmonize_eligible, series_is_tseg_eligible

    text = (description or "").strip()
    if not text:
        return False
    if series_is_tseg_eligible(modality):
        return bool(parse_playbook_series_description(text).get("body_parts"))
    if series_is_planar_harmonize_eligible(modality):
        return _planar_recognized_anatomy(text.split()) is not None
    return False


def apply_series_descriptions(
    *,
    series_dirs: Sequence[Path],
    description: str,
    anon_model: AnonymizerModel,
) -> list[Path]:
    """Apply one RadLex series description to each series directory; return successes."""
    text = (description or "").strip()
    if not text:
        return []
    updated: list[Path] = []
    for series_dir in series_dirs:
        path = Path(series_dir)
        if apply_harmonized_description(path, text, anon_model):
            updated.append(path)
        else:
            logger.error("Failed to apply series description for %s", path)
    return updated


def apply_study_descriptions(
    *,
    images_dir: Path,
    anon_model: AnonymizerModel,
    anon_study_uids: Sequence[str],
    description: str,
    loinc_number: str | None = None,
) -> list[str]:
    """Apply one LOINC study description to each study; return updated UIDs."""
    text = (description or "").strip()
    if not text:
        return []
    updated: list[str] = []
    for anon_study_uid in anon_study_uids:
        patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
        if not patient_id:
            logger.error("No patient id for study %s; skipping study description apply", anon_study_uid)
            continue
        study_root = Path(images_dir) / patient_id / anon_study_uid
        if apply_harmonized_study_description(
            study_root,
            text,
            anon_model,
            anon_study_uid,
            loinc_number=loinc_number,
        ):
            updated.append(anon_study_uid)
        else:
            logger.error("Failed to apply study description for %s", anon_study_uid)
    return updated


def find_similar_study_uids(
    anon_model: AnonymizerModel,
    anon_study_uid: str,
    *,
    candidates: Sequence[tuple[str, str, str | None]] | None = None,
) -> list[str]:
    """
    Other studies similar to ``anon_study_uid`` (excludes self).

    Prefer the same harmonized series-description fingerprint when available.
    Also match ``candidates`` of ``(uid, study_description, loinc_prefix)`` with the
    same non-empty study description and LOINC prefix — so Dataset Select similar
    works before every series is harmonized (mirrors series description matching).
    """
    from anonymizer.controller.ai.harmonize.loinc_study import (
        fingerprint_for_harmonized_study,
        fingerprint_for_planar_harmonized_study,
    )

    peers: set[str] = set()

    composition = getattr(anon_model, "study_composition_for_harmonize", None)
    has_tseg, has_planar = False, False
    if callable(composition):
        raw = composition(anon_study_uid)
        try:
            has_tseg, has_planar = bool(raw[0]), bool(raw[1])
        except (TypeError, IndexError, ValueError):
            has_tseg, has_planar = False, False

    if has_tseg:
        fingerprint = fingerprint_for_harmonized_study(anon_model, anon_study_uid)
        if fingerprint:
            peers.update(uid for uid in find_studies_with_fingerprint(anon_model, fingerprint) if uid != anon_study_uid)
    elif has_planar:
        fingerprint = fingerprint_for_planar_harmonized_study(anon_model, anon_study_uid)
        if fingerprint:
            peers.update(
                uid
                for uid in anon_model.find_studies_with_planar_series_fingerprint(fingerprint)
                if uid != anon_study_uid
            )

    if candidates is not None:
        seed_desc = (anon_model.get_study_harmonized_description(anon_study_uid) or "").strip()
        seed_prefix = study_loinc_prefix_for_edit(anon_model, anon_study_uid)
        # Prefer explicit candidate row for the seed when ORM study desc is empty.
        for uid, description, prefix in candidates:
            if uid == anon_study_uid:
                text = (description or "").strip()
                if text and not seed_desc:
                    seed_desc = text
                if prefix and seed_prefix is None:
                    seed_prefix = prefix
                break
        if seed_desc:
            for uid, description, prefix in candidates:
                if uid == anon_study_uid:
                    continue
                if (description or "").strip() != seed_desc:
                    continue
                if seed_prefix is not None and prefix is not None and prefix != seed_prefix:
                    continue
                peers.add(uid)

    return sorted(peers)


def find_similar_series_uids(
    candidates: Sequence[tuple[str, object | None, str]],
    *,
    seed_uid: str,
    seed_modality: object | None,
    seed_description: str,
) -> list[str]:
    """
    Other series UIDs with the same cohort and description text.

    ``candidates`` is ``(anon_series_uid, modality, description)`` from the Dataset index.
    """
    seed_key = series_description_cohort_key(seed_modality)
    seed_text = (seed_description or "").strip()
    if not seed_key or not seed_text:
        return []
    peers: list[str] = []
    for uid, modality, description in candidates:
        if uid == seed_uid:
            continue
        if series_description_cohort_key(modality) != seed_key:
            continue
        if (description or "").strip() != seed_text:
            continue
        peers.append(uid)
    return peers



def apply_study_description_offer(
    *,
    images_dir: Path,
    anon_model: AnonymizerModel,
    offer: StudyDescriptionOffer,
    description: str,
    apply_to_peers: bool,
    loinc_number: str | None = None,
) -> list[str]:
    """
    Apply a chosen LOINC LongCommonName (and code) to the offer study and optionally peers.

    Returns the list of anon_study_uid values successfully updated.
    """
    targets = [offer.anon_study_uid]
    if apply_to_peers:
        targets.extend(offer.peer_study_uids)

    updated: list[str] = []
    for anon_study_uid in targets:
        if anon_model.get_study_harmonized_description(anon_study_uid):
            continue
        patient_id = anon_model.get_anon_patient_id_for_study(anon_study_uid)
        if not patient_id:
            logger.error("No patient id for study %s; skipping study description apply", anon_study_uid)
            continue
        study_root = Path(images_dir) / patient_id / anon_study_uid
        if apply_harmonized_study_description(
            study_root,
            description,
            anon_model,
            anon_study_uid,
            loinc_number=loinc_number,
        ):
            updated.append(anon_study_uid)
        else:
            logger.error("Failed to apply study description for %s", anon_study_uid)
    return updated


def auto_apply_study_description_offer(
    *,
    images_dir: Path,
    anon_model: AnonymizerModel,
    offer: StudyDescriptionOffer,
) -> list[str]:
    """Auto-apply the top-ranked match to the offer study and fingerprint peers."""
    if not offer.matches:
        return []
    top = offer.matches[0]
    return apply_study_description_offer(
        images_dir=images_dir,
        anon_model=anon_model,
        offer=offer,
        description=top.long_common_name,
        apply_to_peers=True,
        loinc_number=top.loinc_number,
    )


def group_study_description_offers_by_fingerprint(
    offers: Sequence[StudyDescriptionOffer],
) -> list[StudyDescriptionOffer]:
    """Collapse offers that share a fingerprint into one offer (union of peer UIDs)."""
    by_fp: dict[tuple[str, ...], StudyDescriptionOffer] = {}
    for offer in offers:
        existing = by_fp.get(offer.fingerprint)
        if existing is None:
            by_fp[offer.fingerprint] = offer
            continue
        merged_peers = set(existing.peer_study_uids)
        merged_peers.add(offer.anon_study_uid)
        merged_peers.update(offer.peer_study_uids)
        merged_peers.discard(existing.anon_study_uid)
        by_fp[offer.fingerprint] = StudyDescriptionOffer(
            anon_study_uid=existing.anon_study_uid,
            fingerprint=existing.fingerprint,
            matches=existing.matches,
            peer_study_uids=tuple(sorted(merged_peers)),
            ambiguous=existing.ambiguous or offer.ambiguous,
        )
    return list(by_fp.values())


def auto_apply_best_study_descriptions(
    *,
    images_dir: Path,
    anon_model: AnonymizerModel,
    anon_study_uids: Sequence[str],
) -> list[tuple[StudyDescriptionOffer, list[str]]]:
    """
    Best-guess LOINC Study Description for Harmonize (Series View and AI Batch).

    When a study becomes fully series-harmonized, rank LOINC LongCommonName rows and
    apply the top match to that study and to fingerprint peers that still lack a
    study-level description. Always takes the top-ranked match (no confirmation UI);
    users can change the choice later from Dataset.

    Returns a list of ``(offer, updated_uids)`` for groups that were written.
    """
    offers: list[StudyDescriptionOffer] = []
    for anon_study_uid in anon_study_uids:
        offer = maybe_offer_study_description_harmonize(
            anon_model,
            anon_study_uid,
            images_dir=images_dir,
        )
        if offer is not None:
            offers.append(offer)

    results: list[tuple[StudyDescriptionOffer, list[str]]] = []
    for offer in group_study_description_offers_by_fingerprint(offers):
        if anon_model.get_study_harmonized_description(offer.anon_study_uid):
            continue
        if not offer.matches:
            continue
        updated = auto_apply_study_description_offer(
            images_dir=images_dir,
            anon_model=anon_model,
            offer=offer,
        )
        if updated:
            results.append((offer, updated))
    return results


def harmonize_and_apply_series(
    series_path: Path,
    *,
    anon_model: AnonymizerModel | None = None,
    progress: HarmonizeProgressCallback | None = None,
    include_brain_structures: bool = False,
) -> HarmonizeApplyOutcome:
    """Run harmonize for one CT|MR|XR|US|MG series and auto-apply the merged description."""
    series_path = Path(series_path)
    ds = _load_harmonize_series_dataset(series_path)
    if ds is None:
        return HarmonizeApplyOutcome(
            series_path,
            "failed",
            _("Not a CT/MR/XR/US/MG series or no DICOM files"),
        )

    series_uid = str(ds.SeriesInstanceUID)
    if anon_model is not None and anon_model.series_is_harmonized(series_uid):
        status = anon_model.get_series_processing_status(series_uid)
        expected = (status.harmonized_description or "").strip() if status else ""
        current = str(ds.get("SeriesDescription", "") or "").strip()
        if expected and current != expected:
            apply_harmonized_description(series_path, expected, anon_model)
        return HarmonizeApplyOutcome(series_path, "skipped", _("Already harmonized (model)"))

    if anon_model is None and series_description_is_harmonized(series_path, ds) is True:
        return HarmonizeApplyOutcome(series_path, "skipped", _("Already harmonized"))

    results = harmonize_series(
        [series_path],
        progress=progress,
        include_brain_structures=include_brain_structures,
        anon_model=anon_model,
    )
    if not results:
        return HarmonizeApplyOutcome(series_path, "failed", _("No harmonize result"))

    merged = results[0]
    if merged.error:
        return HarmonizeApplyOutcome(series_path, "failed", merged.error)

    description = (merged.radlex_series_description or "").strip()
    if not description:
        return HarmonizeApplyOutcome(series_path, "failed", _("Empty harmonized description"))

    if not apply_harmonized_description(series_path, description, anon_model):
        return HarmonizeApplyOutcome(series_path, "failed", _("Failed to apply description"))

    return HarmonizeApplyOutcome(series_path, "ok", description, harmonized=merged)


def format_harmonize_batch_contrast_log_lines(result: HarmonizedResult) -> list[str]:
    """IV contrast row (and CT organ HU) for the AI Batch workflow log."""
    from anonymizer.controller.ai.harmonize.playbook import playbook_iv_contrast_row_values
    from anonymizer.controller.ai.tseg.config import (
        CONTRAST_STATS_FILENAME,
        CONTRAST_STATS_HN_FILENAME,
    )
    from anonymizer.controller.ai.tseg.contrast import (
        format_dominant_organ_hu_summary,
        load_contrast_statistics,
        load_contrast_stats_hn,
    )
    from anonymizer.controller.ai.tseg.modality_profile import resolve_profile_for_series

    tseg = result.tseg
    if tseg is None:
        return []

    profile = resolve_profile_for_series(result.series_directory)
    is_mr = profile is not None and not profile.enable_contrast_phase
    if not is_mr and not tseg.contrast_phase:
        return []

    lines: list[str] = []
    try:
        ds = _load_series_dataset(result.series_directory)
    except ValueError:
        ds = None

    element, _code, value, evidence, _source = playbook_iv_contrast_row_values(
        tseg=tseg,
        attributes=result.playbook,
        geometry=result.geometry,
        ds=ds,
    )
    if value != "—":
        line = f"{element}: {value}"
        if evidence and evidence != "—":
            line += f" — {evidence}"
        lines.append(line)

    if is_mr:
        return lines

    cache_dir = series_cache_dir(result.series_directory)
    stats_path = cache_dir / CONTRAST_STATS_FILENAME
    stats_hn_path = cache_dir / CONTRAST_STATS_HN_FILENAME
    if stats_path.is_file() and tseg.dominant_region:
        try:
            stats = load_contrast_statistics(stats_path)
            stats_hn = load_contrast_stats_hn(stats_hn_path) if stats_hn_path.is_file() else None
            hu_summary = format_dominant_organ_hu_summary(
                stats,
                stats_hn,
                dominant_region=tseg.dominant_region,
            )
            if hu_summary:
                lines.append(f"{_('Dominant organ HU')}: {hu_summary}")
        except (OSError, ValueError, KeyError, TypeError):
            logger.debug(
                "Harmonize batch log: contrast statistics unreadable for %s",
                result.series_directory,
            )

    return lines


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
    """Harmonize all CT|MR|XR|US|MG series under selected studies, auto-applying descriptions."""
    series_paths = enumerate_harmonize_series_for_studies(images_dir, studies)
    total = len(series_paths)
    summary = HarmonizeStudiesSummary()

    if progress is not None and total == 0:
        progress(0, 0, _("No CT/MR/XR/US/MG series found for selected studies"), 1.0)

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
                    ds = _load_harmonize_series_dataset(series_path)
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
    callback: HarmonizeProgressCallback | None,
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
            HarmonizeProgress(
                stage=progress.stage,
                message=progress.message or stage_label,
                fraction=frac_start + progress.fraction * span,
                elapsed_sec=time.perf_counter() - started,
                remaining_sec=progress.remaining_sec,
                geometry=progress.geometry,
                tseg=progress.tseg,
                radlex_series_description=None,
            )
        )

    return wrapped



def _harmonize_one_planar_series(
    series_dir: Path,
    *,
    progress: HarmonizeProgressCallback | None,
    started: float,
    cancelled: HarmonizeCancelledCallback | None,
    timing_collector: HarmonizeTimingCollector | None,
) -> HarmonizedResult | None:
    """Planar Harmonize for XR/US/MG. XR may use optional pixel body-part model."""
    from anonymizer.controller.ai.harmonize.planar_profile import planar_profile_from_dataset
    from anonymizer.controller.ai.harmonize.playbook_planar import build_planar_harmonized_series_description
    from anonymizer.controller.ai.tseg.dicom_geometry import sorted_dicom_paths

    series_dir = Path(series_dir)
    timing = HarmonizeStageTimings(series_directory=str(series_dir))
    stage_t0 = time.perf_counter()

    def _report(stage: str, message: str, fraction: float) -> bool:
        if harmonize_cancel_requested(cancelled):
            return False
        if progress is None:
            return True
        progress(
            HarmonizeProgress(
                stage=stage,
                message=message,
                fraction=fraction,
                elapsed_sec=time.perf_counter() - started,
                remaining_sec=None,
            )
        )
        return not harmonize_cancel_requested(cancelled)

    if not _report("merge", "Building harmonized description", 0.2):
        return None

    ds = _load_planar_series_dataset(series_dir)
    if ds is None:
        timing.merge_sec = time.perf_counter() - stage_t0
        if timing_collector is not None:
            timing_collector.add(timing)
        error = _("Not an XR/US/MG series or no DICOM files")
        logger.warning("Harmonize planar merge failed for %s: %s", series_dir, error)
        return HarmonizedResult(
            series_directory=series_dir,
            radlex_series_description="",
            tseg=None,
            error=error,
        )

    pixel_pred = None
    pixel_view_pred = None
    profile = planar_profile_from_dataset(ds)
    if profile is not None and profile.cohort == "XR":
        from anonymizer.controller.ai.harmonize.cxp_view import cxp_view_ready, predict_cxp_view
        from anonymizer.controller.ai.harmonize.xp_bodypart import predict_body_part, xp_bodypart_ready

        need_body = xp_bodypart_ready()
        need_view = cxp_view_ready()
        pixels = None
        if need_body or need_view:
            if not _report("merge", "Loading XR pixels for classification", 0.35):
                return None
            try:
                paths = sorted_dicom_paths(series_dir)
                if paths:
                    pixel_ds = dcmread(paths[0], stop_before_pixels=False)
                    pixels = pixel_ds.pixel_array
            except Exception:
                logger.warning("XR pixel load failed for %s", series_dir, exc_info=True)
                pixels = None

        if need_body and pixels is not None:
            if not _report("merge", "Classifying XR body part from pixels", 0.45):
                return None
            pixel_pred = predict_body_part(pixels)

        # Resolve anatomy first so CXR view runs only for Chest.
        try:
            from anonymizer.controller.ai.harmonize.playbook_planar import build_planar_playbook_attributes

            prelim = build_planar_playbook_attributes(ds, pixel_pred=pixel_pred)
            anatomy_is_chest = prelim.body_part_label == "Chest"
        except ValueError:
            anatomy_is_chest = False

        if need_view and anatomy_is_chest and pixels is not None:
            if not _report("merge", "Classifying CXR projection and rotation", 0.55):
                return None
            pixel_view_pred = predict_cxp_view(pixels)

    try:
        description, planar_attrs = build_planar_harmonized_series_description(
            ds, pixel_pred=pixel_pred, pixel_view_pred=pixel_view_pred
        )
    except ValueError as exc:
        timing.merge_sec = time.perf_counter() - stage_t0
        if timing_collector is not None:
            timing_collector.add(timing)
        logger.warning("Harmonize planar merge failed for %s: %s", series_dir, exc)
        return HarmonizedResult(
            series_directory=series_dir,
            radlex_series_description="",
            tseg=None,
            error=str(exc),
        )

    timing.merge_sec = time.perf_counter() - stage_t0
    if timing_collector is not None:
        timing_collector.add(timing)

    if not _report("done", "Harmonized description ready", 1.0):
        return None

    logger.info("Harmonize planar %s -> %s", series_dir.name, description)
    return HarmonizedResult(
        series_directory=series_dir,
        radlex_series_description=description,
        tseg=None,
        planar=planar_attrs,
    )


def harmonize_series(
    series_directories: list[Path],
    *,
    progress: HarmonizeProgressCallback | None = None,
    include_brain_structures: bool = False,
    anon_model=None,
    cancelled: HarmonizeCancelledCallback | None = None,
    timing_collector: HarmonizeTimingCollector | None = None,
) -> list[HarmonizedResult]:
    """
    Run harmonize per series with an exclusive modality branch:

    - CT|MR → TotalSegmentator path (``_harmonize_series_tseg``).
    - CR|DX|US|MG → metadata Playbook only (never TotalSegmentator).
    - Other modalities (SC/OT/DOC/…) → error result.
    """
    from anonymizer.utils.modalities import is_planar_harmonize_modality, is_tseg_modality

    if not series_directories:
        return []

    tseg_dirs: list[Path] = []
    planar_dirs: list[Path] = []
    other_dirs: list[Path] = []
    for series_dir in series_directories:
        series_dir = Path(series_dir)
        try:
            ds = _load_series_dataset(series_dir)
        except ValueError:
            other_dirs.append(series_dir)
            continue
        modality = getattr(ds, "Modality", None)
        if is_tseg_modality(modality):
            tseg_dirs.append(series_dir)
        elif is_planar_harmonize_modality(modality):
            planar_dirs.append(series_dir)
        else:
            other_dirs.append(series_dir)

    harmonized: list[HarmonizedResult] = []
    started = time.perf_counter()

    for series_dir in other_dirs:
        harmonized.append(
            HarmonizedResult(
                series_directory=Path(series_dir),
                radlex_series_description="",
                tseg=None,
                error=_("Not a CT/MR/XR/US/MG series or no DICOM files"),
            )
        )

    for series_dir in planar_dirs:
        result = _harmonize_one_planar_series(
            series_dir,
            progress=progress,
            started=started,
            cancelled=cancelled,
            timing_collector=timing_collector,
        )
        if result is None:
            break
        harmonized.append(result)

    if tseg_dirs:
        harmonized.extend(
            _harmonize_series_tseg(
                tseg_dirs,
                progress=progress,
                include_brain_structures=include_brain_structures,
                anon_model=anon_model,
                cancelled=cancelled,
                timing_collector=timing_collector,
            )
        )
    return harmonized


def _harmonize_series_tseg(
    series_directories: list[Path],
    *,
    progress: HarmonizeProgressCallback | None = None,
    include_brain_structures: bool = False,
    anon_model=None,
    cancelled: HarmonizeCancelledCallback | None = None,
    timing_collector: HarmonizeTimingCollector | None = None,
) -> list[HarmonizedResult]:
    """
    CT|MR-only Harmonize: geometry → TS segmentation → TS contrast → Playbook merge.

    Extracted from the historical ``harmonize_series`` body — callers must not pass XR/US/MG here.
    """
    if not series_directories:
        return []

    if not ENABLE_TS_CONTRAST:
        logger.warning("Harmonize: ENABLE_TS_CONTRAST=False; contrast phase is required for Playbook merge")

    logger.info(
        "Harmonize starting for %d series (geometry -> TS seg -> TS contrast -> Playbook merge)",
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
    ) -> bool:
        if harmonize_cancel_requested(cancelled):
            return False
        if progress is None:
            return True
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
        return not harmonize_cancel_requested(cancelled)

    harmonized: list[HarmonizedResult] = []
    n_series = len(series_directories)

    for index, series_dir in enumerate(series_directories, start=1):
        if harmonize_cancel_requested(cancelled):
            logger.info("Harmonize: cancelled before series %d/%d", index, n_series)
            break
        series_dir = Path(series_dir)
        logger.info("=== Harmonize [%d/%d] %s ===", index, n_series, series_dir)
        series_started = time.perf_counter()
        timing = HarmonizeStageTimings(series_directory=str(series_dir))

        stage_t0 = time.perf_counter()
        geometry = resolve_series_geometry(series_dir)
        timing.geometry_sec = time.perf_counter() - stage_t0
        if harmonize_cancel_requested(cancelled):
            logger.info("Harmonize: cancelled after geometry for %s", series_dir)
            break
        if not _report(
            "geometry",
            format_geometry_progress_message(geometry),
            _GEOMETRY_FRAC[1],
            geometry=geometry,
        ):
            logger.info("Harmonize: cancelled during geometry report for %s", series_dir)
            break
        logger.debug(
            "Harmonize geometry: plane=%s dimensionality=%s provenance=%s ts_suitable=%s",
            geometry.plane,
            geometry.dimensionality,
            geometry.provenance,
            geometry.ts_suitable,
        )

        _report("tseg", "Segmenting anatomy", _TSEG_SEG_FRAC[0], remaining_sec=60.0)
        if harmonize_cancel_requested(cancelled):
            logger.info("Harmonize: cancelled before TS segmentation for %s", series_dir)
            break

        region_result: TS_result
        nifti_path: Path | None
        used_single_pass = False
        series_profile = resolve_profile_for_series(series_dir)
        use_ct_single_pass = bool(
            tseg_config.ENABLE_CT_HARMONIZE_SINGLE_PASS
            and ts_regions_eligible(geometry)
            and ENABLE_TS_CONTRAST
            and series_profile is not None
            and series_profile.modality == "CT"
            and series_profile.enable_contrast_phase
        )

        stage_t0 = time.perf_counter()
        if use_ct_single_pass:
            logger.debug("Harmonize stage 1/3: CT single-pass total+statistics for %s", series_dir)
            tseg_progress = _scaled_progress(
                progress,
                started=started,
                frac_range=_TSEG_SEG_FRAC,
                stage_label="Segmenting anatomy",
            )
            region_result, nifti_path, used_single_pass = analyze_tseg_ct_single_pass(
                series_dir,
                geometry=geometry,
                progress=tseg_progress,
                include_brain_structures=include_brain_structures,
                cancelled=cancelled,
            )
            if not used_single_pass or region_result.error:
                if harmonize_cancel_requested(cancelled) or region_result.error == HARMONIZE_CANCELLED_MESSAGE:
                    logger.info("Harmonize: cancelled during CT single-pass for %s", series_dir)
                    timing.anatomy_sec = time.perf_counter() - stage_t0
                    timing.single_pass = False
                    break
                logger.info(
                    "Harmonize: CT single-pass unavailable (%s); falling back to ROI anatomy for %s",
                    region_result.error or "not applicable",
                    series_dir,
                )
                region_result, nifti_path = analyze_tseg_regions(
                    series_dir,
                    geometry=geometry,
                    progress=tseg_progress,
                    include_brain_structures=include_brain_structures,
                    cancelled=cancelled,
                )
                used_single_pass = False
            timing.anatomy_sec = time.perf_counter() - stage_t0
            timing.single_pass = used_single_pass
            if harmonize_cancel_requested(cancelled) or region_result.error == HARMONIZE_CANCELLED_MESSAGE:
                logger.info("Harmonize: cancelled during TS regions for %s", series_dir)
                break
            if region_result.body_parts_present.strip() and region_result.error is None:
                _report(
                    "regions",
                    "Anatomy regions summarized",
                    _TSEG_SEG_FRAC[1],
                    geometry=geometry,
                    tseg=region_result,
                )
        elif ts_regions_eligible(geometry):
            logger.debug("Harmonize stage 1/3: TS segmentation for %s", series_dir)
            tseg_progress = _scaled_progress(
                progress,
                started=started,
                frac_range=_TSEG_SEG_FRAC,
                stage_label="Segmenting anatomy",
            )
            region_result, nifti_path = analyze_tseg_regions(
                series_dir,
                geometry=geometry,
                progress=tseg_progress,
                include_brain_structures=include_brain_structures,
                cancelled=cancelled,
            )
            timing.anatomy_sec = time.perf_counter() - stage_t0
            if harmonize_cancel_requested(cancelled) or region_result.error == HARMONIZE_CANCELLED_MESSAGE:
                logger.info("Harmonize: cancelled during TS regions for %s", series_dir)
                break
            if region_result.body_parts_present.strip() and region_result.error is None:
                _report(
                    "regions",
                    "Anatomy regions summarized",
                    _TSEG_SEG_FRAC[1],
                    geometry=geometry,
                    tseg=region_result,
                )
        else:
            timing.anatomy_sec = time.perf_counter() - stage_t0
            logger.debug(
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
                error=geometry.notes or _("TS skipped ({dimensionality})").format(dimensionality=geometry.dimensionality),
            )
            nifti_path = None

        if harmonize_cancel_requested(cancelled):
            logger.info("Harmonize: cancelled before contrast for %s", series_dir)
            break

        tseg: TS_result | None = region_result
        run_contrast = bool(series_profile is None or series_profile.enable_contrast_phase)
        stage_t0 = time.perf_counter()
        if (
            run_contrast
            and ENABLE_TS_CONTRAST
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
            logger.debug("Harmonize stage 2/3: TS contrast for %s (nifti=%s)", series_dir, nifti_path)
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
        elif series_profile is not None and not series_profile.enable_contrast_phase:
            # MR: IV contrast comes from DICOM headers in Playbook merge (not TS phase ML).
            logger.debug("Harmonize: contrast phase skipped for modality %s", series_profile.modality)
            _report(
                "contrast",
                "Reading IV contrast from DICOM",
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
        timing.contrast_sec = time.perf_counter() - stage_t0

        if harmonize_cancel_requested(cancelled):
            logger.info("Harmonize: cancelled before merge for %s", series_dir)
            break

        from anonymizer.controller.ai.tseg.seg_retention import evict_tseg_volume

        evict_tseg_volume(series_dir, anon_model=anon_model)

        release_working_memory(stage="harmonize_after_tseg_contrast")

        _report(
            "merge",
            "Building harmonized description",
            _MERGE_FRAC[0],
            remaining_sec=0.0,
            geometry=geometry,
            tseg=tseg,
        )
        stage_t0 = time.perf_counter()
        merged = _merge_result(series_dir, tseg, geometry=geometry)
        timing.merge_sec = time.perf_counter() - stage_t0
        timing.total_sec = time.perf_counter() - series_started
        timing.body_parts_present = (tseg.body_parts_present if tseg else "") or ""
        timing.contrast_phase = (tseg.contrast_phase if tseg else "") or ""
        timing.radlex_series_description = merged.radlex_series_description or ""
        timing.error = merged.error
        logger.info("Harmonize timings: %s", timing.as_log_dict())
        if timing_collector is not None:
            timing_collector.add(timing)

        harmonized.append(merged)
        if merged.error:
            logger.warning(
                "Harmonize [%d/%d] %s failed: %s",
                index,
                n_series,
                series_dir,
                merged.error,
            )
            _report(
                "failed",
                merged.error,
                1.0,
                geometry=geometry,
                tseg=tseg,
            )
        else:
            logger.info(
                "Harmonize [%d/%d] %s: description=%r body=%s contrast=%s plane=%s thickness=%s series_type=%s modifier=%s",
                index,
                n_series,
                series_dir,
                merged.radlex_series_description,
                merged.playbook.body_part_code if merged.playbook else "",
                merged.playbook.iv_contrast_code if merged.playbook else "",
                merged.playbook.anatomic_plane_code if merged.playbook else "",
                merged.playbook.slice_thickness_code if merged.playbook else "",
                merged.playbook.series_type_code if merged.playbook else "",
                merged.playbook.series_type_modifier_code if merged.playbook else "",
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
    if harmonize_cancel_requested(cancelled):
        logger.info("Harmonize finished (cancelled): %d partial result(s) in %.1fs", len(harmonized), time.perf_counter() - started)
    else:
        logger.info("Harmonize finished: %d result(s) in %.1fs", len(harmonized), time.perf_counter() - started)
    return harmonized
