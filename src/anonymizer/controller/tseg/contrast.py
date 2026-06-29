"""IV contrast phase analysis via TotalSegmentator organ HU statistics and XGBoost."""

from __future__ import annotations

import gc
import importlib.resources
import json
import logging
import pickle
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import nibabel as nib
import numpy as np

from anonymizer.controller.tseg.runtime import sequential_ml_context

logger = logging.getLogger(__name__)

PHASES_WITH_CONTRAST: frozenset[str] = frozenset(
    {"arterial_early", "arterial_late", "portal_venous"}
)

_TSEG_INSTALL_HINT = 'pip install "rsna-anonymizer[tseg]"'

# Same feature order as totalsegmentator.bin.totalseg_get_phase
CONTRAST_ORGANS: tuple[str, ...] = (
    "liver",
    "pancreas",
    "urinary_bladder",
    "gallbladder",
    "heart",
    "aorta",
    "inferior_vena_cava",
    "portal_vein_and_splenic_vein",
    "iliac_vena_left",
    "iliac_vena_right",
    "iliac_artery_left",
    "iliac_artery_right",
    "pulmonary_vein",
    "brain",
    "colon",
    "small_bowel",
)
CONTRAST_ORGANS_HN: tuple[str, ...] = (
    "internal_carotid_artery_right",
    "internal_carotid_artery_left",
    "internal_jugular_vein_right",
    "internal_jugular_vein_left",
)
_LOG_HU_ORGANS: tuple[str, ...] = (
    "aorta",
    "heart",
    "pulmonary_vein",
    "portal_vein_and_splenic_vein",
    "liver",
    "inferior_vena_cava",
    "brain",
    "internal_carotid_artery_right",
    "internal_carotid_artery_left",
)

# Minimum segmented volume (mm³) to treat a truncal organ as in-FOV.
_MIN_ORGAN_VOLUME_MM3 = 10.0
_TRUNCAL_FOV_ORGANS: tuple[str, ...] = (
    "aorta",
    "liver",
    "heart",
    "portal_vein_and_splenic_vein",
)
_HU_NATIVE_VESSEL_MAX = 70.0
_HU_NATIVE_LIVER_MAX = 80.0
_HU_ENHANCED_VESSEL_MIN = 90.0
_HU_ENHANCED_LIVER_MIN = 90.0


@dataclass(frozen=True)
class ContrastResult:
    phase: str
    pi_time: float
    probability: float
    iv_contrast: bool


def phase_to_iv_contrast(phase: str) -> bool:
    """Map TS phase label to binary iv_contrast (native=False, else True)."""
    normalized = phase.strip().lower()
    if normalized == "native":
        return False
    if normalized in PHASES_WITH_CONTRAST:
        return True
    raise ValueError(
        f"Unknown contrast phase {phase!r}. Expected native or one of {sorted(PHASES_WITH_CONTRAST)}."
    )


def verify_xgboost_runtime() -> None:
    """
    Raise RuntimeError when XGBoost (or its platform OpenMP runtime) cannot load.

    TotalSegmentator ships the contrast classifier pickles but does not declare xgboost
    as a dependency; the ``tseg`` extra adds it. On macOS, XGBoost may still require
    the system OpenMP library (libomp) that pip cannot install.
    """
    try:
        import xgboost

        version = xgboost.__version__
        logger.debug("XGBoost version %s import OK", version)
    except Exception as exc:
        platform_hint = ""
        if sys.platform == "darwin":
            platform_hint = (
                " On macOS, XGBoost also needs the OpenMP runtime (libomp), e.g. "
                "`brew install libomp`, which is outside pip."
            )
        elif sys.platform.startswith("win"):
            platform_hint = (
                " On Windows, install the Microsoft Visual C++ Redistributable if "
                "OpenMP (vcomp140.dll) is missing."
            )
        raise RuntimeError(
            f"XGBoost is required for TotalSegmentator contrast analysis. "
            f"Install with: {_TSEG_INSTALL_HINT}.{platform_hint}"
        ) from exc


def release_accelerator_memory() -> None:
    """Release PyTorch accelerator memory after a heavy inference step."""
    try:
        import torch
    except ImportError:
        gc.collect()
        return

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    elif torch.backends.mps.is_available():
        torch.mps.empty_cache()
        if hasattr(torch.mps, "synchronize"):
            torch.mps.synchronize()
    gc.collect()


def log_memory_usage(stage: str) -> None:
    """Log process RSS at a pipeline stage (best-effort)."""
    try:
        import psutil

        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        logger.info("Memory [%s]: RSS %.0f MB", stage, rss_mb)
    except Exception:
        logger.debug("Memory [%s]: psutil unavailable", stage)


def release_working_memory(*, stage: str = "") -> None:
    """Release accelerator caches and run GC between harmonize pipeline stages."""
    release_accelerator_memory()
    gc.collect()
    if stage:
        log_memory_usage(stage)


def release_before_contrast(*, stage: str = "before_contrast") -> None:
    """
    Release anatomy-segmentation RAM and nnU-Net/PyTorch caches before contrast inference.

    Contrast loads a separate TotalSegmentator statistics pass; clearing anatomy allocations
    first reduces peak memory. Two ``gc.collect()`` passes help drop MPS/CUDA tensor cycles.
    """
    release_accelerator_memory()
    gc.collect()
    gc.collect()
    log_memory_usage(stage)


def _require_totalsegmentator():
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError as exc:
        raise ImportError(
            f"TotalSegmentator is required for contrast analysis. Install with: {_TSEG_INSTALL_HINT}"
        ) from exc
    return totalsegmentator


def resolve_device(device: str | None = None) -> str:
    import torch

    if device:
        return device
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "gpu"
    return "cpu"


def resolve_contrast_device(device: str | None = None) -> str:
    """Device for contrast statistics inference (defaults to same as ``resolve_device``)."""
    return resolve_device(device)


def _require_pi_time_to_phase():
    try:
        from totalsegmentator.bin.totalseg_get_phase import pi_time_to_phase
    except ImportError as exc:
        raise ImportError(
            f"TotalSegmentator contrast phase requires totalsegmentator and xgboost. "
            f"Install with: {_TSEG_INSTALL_HINT}"
        ) from exc
    return pi_time_to_phase


def load_contrast_statistics(stats_path: Path) -> dict:
    """Load per-series organ statistics JSON written during segmentation."""
    stats_path = Path(stats_path)
    if not stats_path.is_file():
        raise FileNotFoundError(f"Statistics file not found: {stats_path}")
    return json.loads(stats_path.read_text(encoding="utf-8"))


def save_contrast_statistics(stats: dict, stats_path: Path) -> None:
    """Persist TotalSegmentator organ statistics JSON for reuse on later runs."""
    stats_path = Path(stats_path)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats), encoding="utf-8")


def _hu_medians_from_stats(stats: dict, organs: tuple[str, ...]) -> dict[str, float]:
    return {organ: float(stats[organ]["intensity"]) for organ in organs}


def _format_hu_medians(hu_medians: dict[str, float], organs: tuple[str, ...]) -> str:
    parts = [f"{organ}={hu_medians[organ]:.0f}" for organ in organs if organ in hu_medians]
    return ", ".join(parts)


def _organ_stat(stats: dict, organ: str, field: str) -> float:
    return float(stats.get(organ, {}).get(field, 0.0))


def truncal_fov_present(stats: dict) -> bool:
    """True when chest/abdomen contrast organs are segmented with non-trivial volume."""
    return any(
        _organ_stat(stats, organ, "volume") > _MIN_ORGAN_VOLUME_MM3 for organ in _TRUNCAL_FOV_ORGANS
    )


def head_dominant_limited_fov(stats: dict) -> bool:
    """Head CT without truncal organs in FOV — XGBoost contrast features are mostly zero."""
    return _organ_stat(stats, "brain", "volume") > 100 and not truncal_fov_present(stats)


def hu_gate_iv_contrast(stats: dict, stats_hn: dict) -> bool | None:
    """
    Organ-HU gate for binary IV contrast.

    Truncal FOV: aorta/IVC/liver medians. Head-only FOV: head/neck vessel medians
    (XGBoost features are mostly zero without truncal organs).
    Returns ``None`` when inconclusive (defer to XGBoost).
    """
    aorta = _organ_stat(stats, "aorta", "intensity")
    ivc = _organ_stat(stats, "inferior_vena_cava", "intensity")
    liver = _organ_stat(stats, "liver", "intensity")

    if truncal_fov_present(stats):
        max_vessel = max(aorta, ivc)
        if max_vessel < _HU_NATIVE_VESSEL_MAX and liver < _HU_NATIVE_LIVER_MAX:
            return False
        if max_vessel >= _HU_ENHANCED_VESSEL_MIN or liver >= _HU_ENHANCED_LIVER_MIN:
            return True
        return None

    if _organ_stat(stats, "brain", "volume") > 100:
        head_intensities = [
            _organ_stat(stats_hn, organ, "intensity")
            for organ in CONTRAST_ORGANS_HN
            if _organ_stat(stats_hn, organ, "volume") > 0 or _organ_stat(stats_hn, organ, "intensity") > 0
        ]
        if not head_intensities:
            return None
        max_hn_vessel = max(head_intensities)
        if max_hn_vessel < _HU_NATIVE_VESSEL_MAX:
            return False
        return True

    return None


def _apply_hu_gate(result: dict, stats: dict, stats_hn: dict) -> dict:
    """Override XGBoost when organ HU gate disagrees (common on head-only CECT)."""
    gate = hu_gate_iv_contrast(stats, stats_hn)
    if gate is None:
        return result

    xgb_iv = phase_to_iv_contrast(str(result["phase"]))
    if gate == xgb_iv:
        return result

    updated = dict(result)
    limited_fov = head_dominant_limited_fov(stats)
    logger.info(
        "TS contrast: HU gate iv_contrast=%s overrides XGBoost=%s (head_limited_fov=%s)",
        gate,
        xgb_iv,
        limited_fov,
    )
    if gate:
        if updated["phase"] == "native":
            updated["phase"] = "arterial_early"
            updated["pi_time"] = max(float(updated["pi_time"]), 35.0)
    else:
        updated["phase"] = "native"
        updated["pi_time"] = min(float(updated["pi_time"]), 5.0)
    return updated


def _run_contrast_classifier(hu_features: list[float]) -> dict:
    with sequential_ml_context("ts_contrast_xgboost"):
        verify_xgboost_runtime()
        pi_time_to_phase = _require_pi_time_to_phase()
        classifier_path = str(
            importlib.resources.files("totalsegmentator")
            / "resources/contrast_phase_classifiers_2024_07_19.pkl"
        )
        with open(classifier_path, "rb") as classifier_file:
            clfs = pickle.load(classifier_file)
        preds = np.array([clf.predict([hu_features])[0] for clf in clfs.values()])
        pi_time = round(float(np.mean(preds)), 2)
        phase, probability = pi_time_to_phase(pi_time)
        return {
            "pi_time": pi_time,
            "phase": phase,
            "probability": probability,
            "pi_time_min": round(float(preds.min()), 2),
            "pi_time_max": round(float(preds.max()), 2),
            "stddev": round(float(np.std(preds)), 4),
        }


def predict_contrast_phase(
    nifti_path: Path,
    *,
    device: str | None = None,
    existing_stats: dict | None = None,
    stats_output_path: Path | None = None,
) -> tuple[dict, float, dict[str, float]]:
    """
    Run TotalSegmentator contrast-phase (organ median HU + XGBoost).

    When ``existing_stats`` is provided, the main organ-statistics TotalSegmentator run is
    skipped. Cached stats must come from a prior ``ml=True, fast=True, statistics=True``
    pass (full ``total`` task, not the ROI anatomy subset).

    Returns ``(result dict, inference_sec, hu_medians for all classifier organs)``.
    """
    totalsegmentator = _require_totalsegmentator()
    ts_device = resolve_device(device)
    nifti_path = Path(nifti_path)
    started = time.perf_counter()
    ct_img = nib.load(nifti_path)

    logger.info(
        "TS contrast: statistics from %s (device=%s, existing_stats=%s)",
        nifti_path,
        ts_device,
        existing_stats is not None,
    )
    log_memory_usage("ts_contrast_start")

    with sequential_ml_context("ts_contrast_statistics"):
        try:
            if existing_stats is None:
                logger.info(
                    "TS contrast: running TotalSegmentator organ statistics "
                    "(total task, fast=3mm, statistics=True)"
                )
                _, stats = totalsegmentator(
                    ct_img,
                    None,
                    ml=True,
                    fast=True,
                    statistics=True,
                    roi_subset=None,
                    statistics_exclude_masks_at_border=False,
                    quiet=True,
                    stats_aggregation="median",
                    nr_thr_resamp=1,
                    device=ts_device,
                )
            else:
                logger.info("TS contrast: reusing cached organ statistics")
                stats = existing_stats

            if existing_stats is None and stats_output_path is not None:
                save_contrast_statistics(stats, stats_output_path)
                logger.info("TS contrast: wrote cached contrast statistics to %s", stats_output_path)

            if stats["brain"]["volume"] > 100:
                logger.info("TS contrast: running head/neck vessel statistics")
                _, stats_hn = totalsegmentator(
                    ct_img,
                    None,
                    ml=True,
                    fast=False,
                    statistics=True,
                    task="headneck_bones_vessels",
                    roi_subset=None,
                    statistics_exclude_masks_at_border=False,
                    quiet=True,
                    stats_aggregation="median",
                    nr_thr_resamp=1,
                    device=ts_device,
                )
            else:
                stats_hn = {organ: {"intensity": 0.0} for organ in CONTRAST_ORGANS_HN}

            hu_features = [stats[organ]["intensity"] for organ in CONTRAST_ORGANS]
            hu_features.extend(stats_hn[organ]["intensity"] for organ in CONTRAST_ORGANS_HN)
            hu_medians = _hu_medians_from_stats(stats, CONTRAST_ORGANS)
            hu_medians.update(_hu_medians_from_stats(stats_hn, CONTRAST_ORGANS_HN))
            logger.info("TS contrast: HU median: %s", _format_hu_medians(hu_medians, _LOG_HU_ORGANS))
            logger.info("TS contrast: HU features ready; running XGBoost ensemble")
            result = _run_contrast_classifier(hu_features)
            result = _apply_hu_gate(result, stats, stats_hn)
            phase = str(result["phase"])
            logger.info(
                "TS contrast: phase=%s pi_time=%s probability=%.3f iv_contrast=%s",
                phase,
                result["pi_time"],
                result["probability"],
                phase_to_iv_contrast(phase),
            )

            inference_sec = time.perf_counter() - started
            return result, inference_sec, hu_medians
        finally:
            release_working_memory(stage="ts_contrast_end")


def analyze_contrast_phase(
    nifti_path: Path,
    *,
    device: str | None = None,
    existing_stats: dict | None = None,
    stats_output_path: Path | None = None,
) -> ContrastResult:
    """Derive IV contrast phase; thin wrapper around ``predict_contrast_phase``."""
    classified, _, _ = predict_contrast_phase(
        nifti_path,
        device=device,
        existing_stats=existing_stats,
        stats_output_path=stats_output_path,
    )
    phase = str(classified["phase"])
    return ContrastResult(
        phase=phase,
        pi_time=float(classified["pi_time"]),
        probability=float(classified["probability"]),
        iv_contrast=phase_to_iv_contrast(phase),
    )
