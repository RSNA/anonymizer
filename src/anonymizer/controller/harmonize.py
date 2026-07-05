"""Combine TotalSegmentator anatomy analysis with FALCON for harmonized series descriptions."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anonymizer.controller.falcon.predict import FalconPrediction, predict_falcon_series
from anonymizer.controller.tseg.config import ENABLE_TS_CONTRAST
from anonymizer.controller.tseg.contrast import log_memory_usage, release_working_memory
from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    format_geometry_progress_message,
    resolve_series_geometry,
    ts_regions_eligible,
)
from anonymizer.controller.tseg.radlex import falcon_body_part_to_region_token, format_radlex_ct_series_description
from anonymizer.controller.tseg.runtime import log_active_threads, sequential_ml_context
from anonymizer.controller.tseg.segment import (
    AnalysisProgress,
    ProgressCallback,
    TS_result,
    analyze_tseg_contrast,
    analyze_tseg_regions,
)

logger = logging.getLogger(__name__)

HarmonizeProgress = AnalysisProgress

# Progress fractions for sequential harmonize stages (single-threaded worker).
_GEOMETRY_FRAC = (0.0, 0.05)
_FALCON_FRAC = (0.05, 0.22)
_TSEG_SEG_FRAC = (0.22, 0.62)
_TSEG_CONTRAST_FRAC = (0.62, 0.90)
_MERGE_FRAC = (0.90, 1.0)


@dataclass(frozen=True)
class HarmonizedResult:
    series_directory: Path
    radlex_series_description: str
    tseg: TS_result | None
    falcon: FalconPrediction | None
    regions_source: Literal["tseg", "falcon", "none"]
    contrast_source: Literal["tseg", "falcon", "none"]
    geometry: SeriesGeometryResult | None = None
    error: str | None = None


def _falcon_regions_label(falcon: FalconPrediction) -> str:
    return falcon_body_part_to_region_token(falcon.body_part)


def _merge_result(
    series_directory: Path,
    tseg: TS_result | None,
    falcon: FalconPrediction | None,
    *,
    geometry: SeriesGeometryResult | None = None,
) -> HarmonizedResult:
    regions_source: Literal["tseg", "falcon", "none"] = "none"
    contrast_source: Literal["tseg", "falcon", "none"] = "none"
    body_parts_present = ""
    iv_contrast = False

    tseg_ok = tseg is not None and tseg.body_parts_present.strip()
    tseg_regions_ok = tseg_ok and (tseg.error is None or not tseg.contrast_phase)
    tseg_contrast_ok = (
        tseg is not None
        and tseg.error is None
        and bool(tseg.contrast_phase)
    )
    falcon_ok = falcon is not None and falcon.error is None and falcon.body_part

    if tseg_regions_ok and tseg is not None:
        body_parts_present = tseg.body_parts_present
        regions_source = "tseg"
    elif falcon_ok and falcon is not None:
        body_parts_present = _falcon_regions_label(falcon)
        regions_source = "falcon"

    if tseg_contrast_ok and tseg is not None:
        iv_contrast = tseg.iv_contrast
        contrast_source = "tseg"
    elif falcon_ok and falcon is not None:
        iv_contrast = falcon.iv_contrast
        contrast_source = "falcon"

    if not body_parts_present:
        return HarmonizedResult(
            series_directory=series_directory,
            radlex_series_description="",
            tseg=tseg,
            falcon=falcon,
            regions_source="none",
            contrast_source="none",
            geometry=geometry,
            error="Could not determine anatomy regions from TotalSegmentator or FALCON",
        )

    radlex_description = format_radlex_ct_series_description(body_parts_present, iv_contrast)
    return HarmonizedResult(
        series_directory=series_directory,
        radlex_series_description=radlex_description,
        tseg=tseg,
        falcon=falcon,
        regions_source=regions_source,
        contrast_source=contrast_source,
        geometry=geometry,
    )


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
            )
        )

    return wrapped


def harmonize_series(
    series_directories: list[Path],
    *,
    progress: ProgressCallback | None = None,
) -> list[HarmonizedResult]:
    """
    Run harmonize sequentially per series: geometry → FALCON → TS segmentation → (optional) TS contrast → merge.

    Geometry is cached under ``<series>/.tseg_cache/geometry.json``. TotalSegmentator is skipped when
    ``geometry.ts_suitable`` is false (localizers, single-slice 2D, derived 3D renders, etc.).

    When ``ENABLE_TS_CONTRAST`` is False, regions come from TS and contrast from FALCON.
    """
    if not series_directories:
        return []

    logger.info(
        "Harmonize starting for %d series (geometry → FALCON → TS seg%s)",
        len(series_directories),
        " → TS contrast" if ENABLE_TS_CONTRAST else "; TS contrast off → FALCON contrast",
    )
    started = time.perf_counter()
    log_memory_usage("harmonize_start")
    log_active_threads("harmonize_start")

    def _report(stage: str, message: str, fraction: float, remaining_sec: float | None = None) -> None:
        if progress is None:
            return
        progress(
            HarmonizeProgress(
                stage=stage,
                message=message,
                fraction=fraction,
                elapsed_sec=time.perf_counter() - started,
                remaining_sec=remaining_sec,
            )
        )

    harmonized: list[HarmonizedResult] = []
    n_series = len(series_directories)

    for index, series_dir in enumerate(series_directories, start=1):
        series_dir = Path(series_dir)
        logger.info("=== Harmonize [%d/%d] %s ===", index, n_series, series_dir)

        geometry = resolve_series_geometry(series_dir)
        _report("geometry", format_geometry_progress_message(geometry), _GEOMETRY_FRAC[1])
        logger.info(
            "Harmonize geometry: plane=%s dimensionality=%s provenance=%s ts_suitable=%s",
            geometry.plane,
            geometry.dimensionality,
            geometry.provenance,
            geometry.ts_suitable,
        )

        # Stage 1: FALCON (lightweight; runs before TS to avoid peak RAM with both loaded)
        _report("falcon", "Running FALCON analysis", _FALCON_FRAC[0], remaining_sec=12.0)
        logger.info("Harmonize stage 1/4: FALCON for %s", series_dir)
        log_memory_usage("harmonize_before_falcon")
        with sequential_ml_context("harmonize_falcon"):
            falcon_results = predict_falcon_series([series_dir])
        falcon = falcon_results[0] if falcon_results else None
        if falcon is not None and falcon.error is None:
            logger.info(
                "Harmonize FALCON: body_part=%s iv_contrast=%s confidence=%.3f",
                falcon.body_part,
                falcon.iv_contrast,
                falcon.body_part_confidence,
            )
        elif falcon is not None and falcon.error:
            logger.warning("Harmonize FALCON failed: %s", falcon.error)
        release_working_memory(stage="harmonize_after_falcon")

        # Stage 2: TS segmentation + regions (volume released before contrast)
        _report("tseg", "Segmenting anatomy", _TSEG_SEG_FRAC[0], remaining_sec=60.0)
        if ts_regions_eligible(geometry):
            logger.info("Harmonize stage 2/4: TS segmentation for %s", series_dir)
            tseg_progress = _scaled_progress(
                progress,
                started=started,
                frac_range=_TSEG_SEG_FRAC,
                stage_label="Segmenting anatomy",
            )
            region_result, nifti_path = analyze_tseg_regions(series_dir, progress=tseg_progress)
        else:
            logger.info(
                "Harmonize stage 2/4: TS segmentation skipped for %s (%s)",
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

        # Stage 3: TS contrast (organ HU statistics + XGBoost)
        tseg: TS_result | None = region_result
        if (
            ENABLE_TS_CONTRAST
            and nifti_path is not None
            and region_result.body_parts_present.strip()
            and region_result.error is None
        ):
            _report("contrast", "Analyzing contrast phase", _TSEG_CONTRAST_FRAC[0], remaining_sec=35.0)
            logger.info("Harmonize stage 3/4: TS contrast for %s (nifti=%s)", series_dir, nifti_path)
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
        elif not ENABLE_TS_CONTRAST and region_result.body_parts_present.strip():
            logger.info(
                "Harmonize: TS contrast disabled (ENABLE_TS_CONTRAST=False); "
                "using FALCON for contrast on %s",
                series_dir,
            )
        elif region_result.error:
            logger.warning("Harmonize skipping TS contrast (regions error): %s", region_result.error)
        else:
            logger.warning("Harmonize skipping TS contrast (no regions detected)")

        release_working_memory(stage="harmonize_after_tseg_contrast")

        _report("merge", "Building harmonized description", _MERGE_FRAC[0], remaining_sec=0.0)
        merged = _merge_result(series_dir, tseg, falcon, geometry=geometry)
        harmonized.append(merged)
        logger.info(
            "Harmonize [%d/%d] %s: regions=%s contrast=%s description=%r",
            index,
            n_series,
            series_dir,
            merged.regions_source,
            merged.contrast_source,
            merged.radlex_series_description,
        )

    _report("done", "Harmonize complete", 1.0, remaining_sec=0.0)
    log_memory_usage("harmonize_end")
    logger.info("Harmonize finished: %d result(s) in %.1fs", len(harmonized), time.perf_counter() - started)
    return harmonized
