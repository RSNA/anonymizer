"""IV contrast phase analysis via TotalSegmentator organ HU statistics and XGBoost."""

from __future__ import annotations

import importlib.resources
import json
import logging
import pickle
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from anonymizer.controller.ai.tseg.ml_env import sequential_ml_context
from anonymizer.utils.memory import collect_garbage_safe, release_accelerator_caches

logger = logging.getLogger(__name__)

ContrastProgressCallback = Callable[[str, str, float], None]


def _emit_contrast_progress(
    callback: ContrastProgressCallback | None,
    *,
    stage: str,
    message: str,
    fraction: float,
) -> None:
    if callback is None:
        return
    callback(stage, message, min(1.0, max(0.0, fraction)))


PHASES_WITH_CONTRAST: frozenset[str] = frozenset({"arterial_early", "arterial_late", "portal_venous"})

_TSEG_INSTALL_HINT = "pip install rsna-anonymizer"

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

_CONTRAST_ORGAN_LABELS: dict[str, str] = {
    "aorta": "aorta",
    "heart": "heart",
    "pulmonary_vein": "pulmonary vein",
    "portal_vein_and_splenic_vein": "portal vein",
    "liver": "liver",
    "inferior_vena_cava": "IVC",
    "brain": "brain",
}

_VESSEL_LABELS: dict[str, str] = {
    "internal_carotid_artery_right": "ICA-R",
    "internal_carotid_artery_left": "ICA-L",
    "internal_jugular_vein_right": "IJV-R",
    "internal_jugular_vein_left": "IJV-L",
}

# Minimum segmented volume (mm³) to treat a truncal organ as in-FOV.
_MIN_ORGAN_VOLUME_MM3 = 10.0
_TRUNCAL_FOV_ORGANS: tuple[str, ...] = (
    "aorta",
    "liver",
    "heart",
    "portal_vein_and_splenic_vein",
)
_DOMINANT_REGION_CONTRAST_ORGANS: dict[str, tuple[str, ...]] = {
    "Head": ("brain", *CONTRAST_ORGANS_HN),
    "Chest": ("heart", "aorta", "pulmonary_vein"),
    "Abdomen": (
        "liver",
        "aorta",
        "inferior_vena_cava",
        "portal_vein_and_splenic_vein",
    ),
}
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
    raise ValueError(f"Unknown contrast phase {phase!r}. Expected native or one of {sorted(PHASES_WITH_CONTRAST)}.")


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
                " On Windows, install the Microsoft Visual C++ Redistributable if OpenMP (vcomp140.dll) is missing."
            )
        raise RuntimeError(
            f"XGBoost is required for TotalSegmentator contrast analysis. "
            f"Install with: {_TSEG_INSTALL_HINT}.{platform_hint}"
        ) from exc


def release_accelerator_memory() -> None:
    """Release PyTorch accelerator memory after a heavy inference step."""
    release_accelerator_caches()
    collect_garbage_safe()


def log_memory_usage(stage: str) -> None:
    """Log process RSS at a pipeline stage (best-effort)."""
    try:
        import psutil

        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        logger.debug("Memory [%s]: RSS %.0f MB", stage, rss_mb)
    except Exception:
        logger.debug("Memory [%s]: psutil unavailable", stage)


def release_working_memory(*, stage: str = "", preserve_accelerator: bool = False) -> None:
    """Release accelerator caches and run GC between harmonize pipeline stages."""
    from anonymizer.controller.ai.tseg.model_cache import preserve_accelerator_memory

    release_accelerator_caches()
    if not preserve_accelerator and not preserve_accelerator_memory():
        collect_garbage_safe()
    if stage:
        log_memory_usage(stage)


def release_before_contrast(*, stage: str = "before_contrast") -> None:
    """
    Release anatomy-segmentation RAM and nnU-Net/PyTorch caches before contrast inference.

    Contrast loads a separate TotalSegmentator statistics pass; clearing anatomy allocations
    first reduces peak memory. Two GC passes help drop MPS/CUDA tensor cycles on the main thread.
    """
    release_accelerator_caches()
    collect_garbage_safe(generations=2)
    log_memory_usage(stage)


def _require_nibabel():
    try:
        import nibabel as nib
    except ImportError as exc:
        raise ImportError(f"nibabel is required for contrast analysis. Install with: {_TSEG_INSTALL_HINT}") from exc
    return nib


def _require_totalsegmentator():
    try:
        from totalsegmentator.python_api import totalsegmentator
    except ImportError as exc:
        raise ImportError(
            f"TotalSegmentator is required for contrast analysis. Install with: {_TSEG_INSTALL_HINT}"
        ) from exc
    return totalsegmentator


def _contrast_classifier_pickle_path() -> str:
    try:
        resource_root = importlib.resources.files("totalsegmentator")
    except ModuleNotFoundError as exc:
        raise ImportError(
            f"TotalSegmentator is required for contrast classification. Install with: {_TSEG_INSTALL_HINT}"
        ) from exc
    return str(resource_root / "resources/contrast_phase_classifiers_2024_07_19.pkl")


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
            f"TotalSegmentator contrast phase requires totalsegmentator and xgboost. Install with: {_TSEG_INSTALL_HINT}"
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


def load_contrast_stats_hn(stats_hn_path: Path) -> dict:
    stats_hn_path = Path(stats_hn_path)
    if not stats_hn_path.is_file():
        raise FileNotFoundError(f"Head/neck statistics file not found: {stats_hn_path}")
    return json.loads(stats_hn_path.read_text(encoding="utf-8"))


def save_contrast_stats_hn(stats_hn: dict, stats_hn_path: Path) -> None:
    stats_hn_path = Path(stats_hn_path)
    stats_hn_path.parent.mkdir(parents=True, exist_ok=True)
    stats_hn_path.write_text(json.dumps(stats_hn), encoding="utf-8")


def contrast_phase_cache_is_valid(
    phase_cache_path: Path,
    stats_path: Path,
    *,
    stats_hn_path: Path | None = None,
    require_stats_hn: bool = False,
) -> bool:
    """Return True when cached XGBoost output is at least as new as its statistics inputs."""
    phase_cache_path = Path(phase_cache_path)
    stats_path = Path(stats_path)
    if not phase_cache_path.is_file() or not stats_path.is_file():
        return False

    phase_mtime = phase_cache_path.stat().st_mtime
    if phase_mtime < stats_path.stat().st_mtime:
        return False

    if require_stats_hn:
        if stats_hn_path is None or not Path(stats_hn_path).is_file():
            return False
        if phase_mtime < Path(stats_hn_path).stat().st_mtime:
            return False

    return True


def load_contrast_phase_cache(phase_cache_path: Path) -> dict:
    phase_cache_path = Path(phase_cache_path)
    if not phase_cache_path.is_file():
        raise FileNotFoundError(f"Contrast phase cache not found: {phase_cache_path}")
    return json.loads(phase_cache_path.read_text(encoding="utf-8"))


def save_contrast_phase_cache(
    result: dict,
    *,
    hu_medians: dict[str, float],
    phase_cache_path: Path,
) -> None:
    phase_cache_path = Path(phase_cache_path)
    phase_cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase": str(result["phase"]),
        "pi_time": float(result["pi_time"]),
        "probability": float(result["probability"]),
        "pi_time_min": float(result.get("pi_time_min", result["pi_time"])),
        "pi_time_max": float(result.get("pi_time_max", result["pi_time"])),
        "stddev": float(result.get("stddev", 0.0)),
        "hu_medians": {key: float(value) for key, value in hu_medians.items()},
    }
    phase_cache_path.write_text(json.dumps(payload), encoding="utf-8")


def estimate_contrast_remaining_sec(
    *,
    stats_cached: bool,
    stats_hn_cached: bool,
    phase_cached: bool,
    needs_head_neck: bool,
) -> float | None:
    """Rough ETA for UI progress based on which contrast cache layers are already present."""
    if phase_cached:
        return 0.0
    if stats_cached and (not needs_head_neck or stats_hn_cached):
        return 2.0
    if stats_cached and needs_head_neck:
        return 22.0
    return 60.0


def _hu_medians_from_stats(stats: dict, organs: tuple[str, ...]) -> dict[str, float]:
    return {organ: float(stats[organ]["intensity"]) for organ in organs}


def _format_hu_medians(hu_medians: dict[str, float], organs: tuple[str, ...]) -> str:
    parts = [f"{organ}={hu_medians[organ]:.0f}" for organ in organs if organ in hu_medians]
    return ", ".join(parts)


def format_contrast_hu_summary(
    stats: dict,
    *,
    organs: tuple[str, ...],
    labels: dict[str, str] | None = None,
) -> str:
    """Compact ``organ=NN HU`` list for organs with non-trivial segmented volume."""
    parts: list[str] = []
    for organ in organs:
        entry = stats.get(organ)
        if not entry:
            continue
        if float(entry.get("volume", 0)) <= _MIN_ORGAN_VOLUME_MM3:
            continue
        label = (labels or {}).get(organ, organ.replace("_", " "))
        parts.append(f"{label}={float(entry['intensity']):.0f} HU")
    return ", ".join(parts)


def format_contrast_organ_hu_summary(stats: dict) -> str:
    truncal_organs = (
        "aorta",
        "heart",
        "pulmonary_vein",
        "portal_vein_and_splenic_vein",
        "liver",
        "inferior_vena_cava",
        "brain",
    )
    return format_contrast_hu_summary(
        stats,
        organs=truncal_organs,
        labels=_CONTRAST_ORGAN_LABELS,
    )


def format_contrast_vessel_hu_summary(stats_hn: dict) -> str:
    return format_contrast_hu_summary(
        stats_hn,
        organs=CONTRAST_ORGANS_HN,
        labels=_VESSEL_LABELS,
    )


def _contrast_organ_labels() -> dict[str, str]:
    return {**_CONTRAST_ORGAN_LABELS, **_VESSEL_LABELS}


def format_dominant_organ_hu_summary(
    stats: dict,
    stats_hn: dict | None,
    *,
    dominant_region: str,
) -> str:
    """HU range and per-organ medians for contrast organs in the dominant anatomy region."""
    organs = _DOMINANT_REGION_CONTRAST_ORGANS.get(dominant_region, ())
    if not organs:
        return ""
    combined = dict(stats)
    if stats_hn:
        combined.update(stats_hn)
    labels = _contrast_organ_labels()
    hu_values: list[float] = []
    parts: list[str] = []
    for organ in organs:
        entry = combined.get(organ)
        if not entry:
            continue
        if float(entry.get("volume", 0)) <= _MIN_ORGAN_VOLUME_MM3:
            continue
        hu = float(entry.get("intensity", 0))
        hu_values.append(hu)
        label = labels.get(organ, organ.replace("_", " "))
        parts.append(f"{label}={hu:.0f} HU")
    if not hu_values:
        return ""
    if len(hu_values) == 1:
        return parts[0]
    hu_min, hu_max = min(hu_values), max(hu_values)
    range_label = f"{hu_min:.0f}–{hu_max:.0f} HU" if hu_max > hu_min else f"{hu_min:.0f} HU"
    return f"{range_label} ({', '.join(parts)})"


def format_cached_organ_hu_message(stats: dict) -> str:
    summary = format_contrast_organ_hu_summary(stats)
    if summary:
        return f"Using cached organ HU statistics: {summary}"
    return "Using cached organ HU statistics"


def format_cached_vessel_hu_message(stats_hn: dict) -> str:
    summary = format_contrast_vessel_hu_summary(stats_hn)
    if summary:
        return f"Using cached head/neck vessel statistics: {summary}"
    return "Using cached head/neck vessel statistics"


def format_cached_contrast_phase_message(cached: dict) -> str:
    phase = str(cached.get("phase", "")).replace("_", " ")
    hu_medians = {key: float(value) for key, value in cached.get("hu_medians", {}).items()}
    labels = {**_CONTRAST_ORGAN_LABELS, **_VESSEL_LABELS}
    parts = [
        f"{labels.get(organ, organ.replace('_', ' '))}={hu_medians[organ]:.0f} HU"
        for organ in _LOG_HU_ORGANS
        if organ in hu_medians
    ]
    hu_summary = ", ".join(parts)
    if hu_summary:
        return f"Using cached contrast phase: {phase} ({hu_summary})"
    return f"Using cached contrast phase: {phase}"


def _organ_stat(stats: dict, organ: str, field: str) -> float:
    return float(stats.get(organ, {}).get(field, 0.0))


def truncal_fov_present(stats: dict) -> bool:
    """True when chest/abdomen contrast organs are segmented with non-trivial volume."""
    return any(_organ_stat(stats, organ, "volume") > _MIN_ORGAN_VOLUME_MM3 for organ in _TRUNCAL_FOV_ORGANS)


def truncal_anatomy_present(body_parts_present: str) -> bool:
    """True when ROI anatomy includes chest or abdomen (not a head-only FOV)."""
    if not body_parts_present.strip():
        return False
    truncal_regions = frozenset({"Chest", "Abdomen"})
    return any(part in truncal_regions for part in body_parts_present.split("+"))


def head_dominant_limited_fov(stats: dict) -> bool:
    """Head CT without truncal organs in FOV — XGBoost contrast features are mostly zero."""
    return _organ_stat(stats, "brain", "volume") > 100 and not truncal_fov_present(stats)


def needs_head_neck_vessel_stats(
    stats: dict,
    *,
    body_parts_present: str | None = None,
) -> bool:
    """Whether the head/neck TotalSegmentator statistics pass is required."""
    if body_parts_present and truncal_anatomy_present(body_parts_present):
        return False
    return head_dominant_limited_fov(stats)


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
        return max_hn_vessel >= _HU_NATIVE_VESSEL_MAX

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
    logger.debug(
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
        classifier_path = _contrast_classifier_pickle_path()
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
    stats_hn_output_path: Path | None = None,
    phase_cache_path: Path | None = None,
    body_parts_present: str | None = None,
    progress: ContrastProgressCallback | None = None,
) -> tuple[dict, float, dict[str, float]]:
    """
    Run TotalSegmentator contrast-phase (organ median HU + XGBoost).

    When ``existing_stats`` is provided, the main organ-statistics TotalSegmentator run is
    skipped. Cached stats must come from a prior ``ml=True, fast=True, statistics=True``
    pass (full ``total`` task, not the ROI anatomy subset).

    When ``phase_cache_path`` is valid relative to the statistics cache files, the
    head/neck statistics pass, XGBoost ensemble, and NIfTI reload are skipped.

    Returns ``(result dict, inference_sec, hu_medians for all classifier organs)``.
    """
    started = time.perf_counter()
    stats_path = Path(stats_output_path) if stats_output_path is not None else None
    stats_hn_path = Path(stats_hn_output_path) if stats_hn_output_path is not None else None
    phase_cache = Path(phase_cache_path) if phase_cache_path is not None else None

    if phase_cache is not None and stats_path is not None and existing_stats is not None:
        needs_head_neck = needs_head_neck_vessel_stats(
            existing_stats,
            body_parts_present=body_parts_present,
        )
        if contrast_phase_cache_is_valid(
            phase_cache,
            stats_path,
            stats_hn_path=stats_hn_path,
            require_stats_hn=needs_head_neck,
        ):
            cached = load_contrast_phase_cache(phase_cache)
            hu_medians = {key: float(value) for key, value in cached.get("hu_medians", {}).items()}
            result = {
                "phase": cached["phase"],
                "pi_time": cached["pi_time"],
                "probability": cached["probability"],
                "pi_time_min": cached.get("pi_time_min", cached["pi_time"]),
                "pi_time_max": cached.get("pi_time_max", cached["pi_time"]),
                "stddev": cached.get("stddev", 0.0),
            }
            logger.debug(
                "TS contrast: reusing cached XGBoost result from %s (phase=%s pi_time=%s)",
                phase_cache,
                result["phase"],
                result["pi_time"],
            )
            _emit_contrast_progress(
                progress,
                stage="contrast_phase_cache",
                message=format_cached_contrast_phase_message(cached),
                fraction=1.0,
            )
            return result, time.perf_counter() - started, hu_medians

    totalsegmentator = _require_totalsegmentator()
    ts_device = resolve_device(device)
    nifti_path = Path(nifti_path)

    logger.debug(
        "TS contrast: statistics from %s (device=%s, existing_stats=%s)",
        nifti_path,
        ts_device,
        existing_stats is not None,
    )
    log_memory_usage("ts_contrast_start")
    ct_img = None
    stats: dict | None = None
    stats_hn: dict | None = None

    try:
        ct_img = _require_nibabel().load(nifti_path)

        with sequential_ml_context("ts_contrast_statistics"):
            try:
                if existing_stats is None:
                    _emit_contrast_progress(
                        progress,
                        stage="contrast_stats",
                        message="Computing organ HU statistics",
                        fraction=0.05,
                    )
                    logger.debug(
                        "TS contrast: running TotalSegmentator organ statistics (total task, fast=3mm, statistics=True)"
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
                    _emit_contrast_progress(
                        progress,
                        stage="contrast_stats",
                        message="Organ HU statistics complete",
                        fraction=0.30,
                    )
                else:
                    logger.debug("TS contrast: reusing cached organ statistics")
                    stats = existing_stats
                    _emit_contrast_progress(
                        progress,
                        stage="contrast_stats_cached",
                        message=format_cached_organ_hu_message(stats),
                        fraction=0.30,
                    )

                if existing_stats is None and stats_output_path is not None:
                    save_contrast_statistics(stats, stats_output_path)
                    logger.debug("TS contrast: wrote cached contrast statistics to %s", stats_output_path)

                needs_head_neck = needs_head_neck_vessel_stats(
                    stats,
                    body_parts_present=body_parts_present,
                )
                if needs_head_neck:
                    _emit_contrast_progress(
                        progress,
                        stage="contrast_stats_hn",
                        message="Computing head/neck vessel statistics",
                        fraction=0.35,
                    )
                    if (
                        stats_hn_path is not None
                        and stats_hn_path.is_file()
                        and (
                            existing_stats is not None
                            or stats_path is None
                            or stats_hn_path.stat().st_mtime >= stats_path.stat().st_mtime
                        )
                    ):
                        logger.debug("TS contrast: reusing cached head/neck vessel statistics")
                        stats_hn = load_contrast_stats_hn(stats_hn_path)
                        _emit_contrast_progress(
                            progress,
                            stage="contrast_stats_hn_cached",
                            message=format_cached_vessel_hu_message(stats_hn),
                            fraction=0.65,
                        )
                    else:
                        logger.debug(
                            "TS contrast: running head/neck vessel statistics "
                            "(headneck_bones_vessels task; full resolution)"
                        )
                        _, stats_hn = totalsegmentator(
                            ct_img,
                            None,
                            ml=True,
                            statistics=True,
                            task="headneck_bones_vessels",
                            roi_subset=None,
                            statistics_exclude_masks_at_border=False,
                            quiet=True,
                            stats_aggregation="median",
                            nr_thr_resamp=1,
                            device=ts_device,
                        )
                        if stats_hn_path is not None:
                            save_contrast_stats_hn(stats_hn, stats_hn_path)
                            logger.debug(
                                "TS contrast: wrote cached head/neck statistics to %s",
                                stats_hn_path,
                            )
                        _emit_contrast_progress(
                            progress,
                            stage="contrast_stats_hn",
                            message="Head/neck vessel statistics complete",
                            fraction=0.65,
                        )
                else:
                    stats_hn = {organ: {"intensity": 0.0} for organ in CONTRAST_ORGANS_HN}
                    _emit_contrast_progress(
                        progress,
                        stage="contrast_stats_hn_skip",
                        message="Head/neck statistics not required",
                        fraction=0.65,
                    )

                hu_features = [stats[organ]["intensity"] for organ in CONTRAST_ORGANS]
                hu_features.extend(stats_hn[organ]["intensity"] for organ in CONTRAST_ORGANS_HN)
                hu_medians = _hu_medians_from_stats(stats, CONTRAST_ORGANS)
                hu_medians.update(_hu_medians_from_stats(stats_hn, CONTRAST_ORGANS_HN))
                logger.debug("TS contrast: HU median: %s", _format_hu_medians(hu_medians, _LOG_HU_ORGANS))
                logger.debug("TS contrast: HU features ready; running XGBoost ensemble")
                _emit_contrast_progress(
                    progress,
                    stage="contrast_xgboost",
                    message="Classifying contrast phase (XGBoost)",
                    fraction=0.75,
                )
                result = _run_contrast_classifier(hu_features)
                result = _apply_hu_gate(result, stats, stats_hn)
                _emit_contrast_progress(
                    progress,
                    stage="contrast_xgboost",
                    message="Contrast phase classification complete",
                    fraction=0.95,
                )
                phase = str(result["phase"])
                logger.debug(
                    "TS contrast: phase=%s pi_time=%s probability=%.3f iv_contrast=%s",
                    phase,
                    result["pi_time"],
                    result["probability"],
                    phase_to_iv_contrast(phase),
                )

                if phase_cache is not None:
                    save_contrast_phase_cache(result, hu_medians=hu_medians, phase_cache_path=phase_cache)
                    logger.debug("TS contrast: wrote cached XGBoost result to %s", phase_cache)

                inference_sec = time.perf_counter() - started
                return result, inference_sec, hu_medians
            finally:
                stats = None
                stats_hn = None
    finally:
        if ct_img is not None:
            del ct_img
        release_working_memory(stage="ts_contrast_end")


def analyze_contrast_phase(
    nifti_path: Path,
    *,
    device: str | None = None,
    existing_stats: dict | None = None,
    stats_output_path: Path | None = None,
    stats_hn_output_path: Path | None = None,
    phase_cache_path: Path | None = None,
    body_parts_present: str | None = None,
    progress: ContrastProgressCallback | None = None,
) -> ContrastResult:
    """Derive IV contrast phase; thin wrapper around ``predict_contrast_phase``."""
    classified, _, _ = predict_contrast_phase(
        nifti_path,
        device=device,
        existing_stats=existing_stats,
        stats_output_path=stats_output_path,
        stats_hn_output_path=stats_hn_output_path,
        phase_cache_path=phase_cache_path,
        body_parts_present=body_parts_present,
        progress=progress,
    )
    phase = str(classified["phase"])
    return ContrastResult(
        phase=phase,
        pi_time=float(classified["pi_time"]),
        probability=float(classified["probability"]),
        iv_contrast=phase_to_iv_contrast(phase),
    )
