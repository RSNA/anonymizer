"""Project Dataset analytics: PHI demographics, modality/AI coverage, TS organ volumes.

Simple read-only API for the Dashboard to call when analytics UX needs a refresh.
Does not own threads, caches, or idle gating — that belongs in the view.

Snapshot shape (nested by domain so panels can grow independently)::

    DatasetAnalytics
      .demographics    DemographicsAnalytics  (sex / age / ethnicity Distributions)
      .imaging         ImagingAnalytics       (modality / ai_coverage Distributions)
      .anatomy         AnatomyAnalytics       (regions + main-organ volume histogram)

Population denominators live on each ``Distribution.total`` — this API does not
replace or feed the Dashboard Patients/Studies/Series/Images counters.

Unknown demographic values are excluded from chart ``items`` and tracked on
``Distribution.unknown_count`` (charts report known ``n=`` in titles). AI coverage
is % of series with
only non-zero algorithms included. Organ panel histograms patient-mean organ volumes
(one sample per patient after averaging multi-series volumes for that organ).
"""

from __future__ import annotations

import json
import logging
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir
from anonymizer.controller.ai.tseg.config import PRIMARY_SEGMENT_GROUPS
from anonymizer.controller.ai.tseg.seg_retention import (
    aggregate_primary_segment_voxels,
    read_mask_geometry,
    read_primary_segment_voxels,
    read_structure_voxels,
)
from anonymizer.controller.ai.tseg.segment import dominant_region_from_voxels
from anonymizer.model.anonymizer import AnonymizerModel, Study
from anonymizer.utils.modalities import is_tseg_modality
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

AGE_BANDS_KNOWN: tuple[str, ...] = ("<18", "18–39", "40–59", "60–79", "80+")
AGE_BANDS: tuple[str, ...] = AGE_BANDS_KNOWN + ("Unknown",)
AGE_UNKNOWN = "Unknown"
AGE_HIST_BIN_YEARS = 5.0
AGE_HIST_RANGE_YEARS: tuple[float, float] = (0.0, 100.0)
ETHNICITY_TOP_N = 5
TOP_ORGANS_N = 2  # default checked count in the Volumes picker
MODALITY_FILTER_TOP_N = 6
# Volumes picker / histograms: every Series View primary latch group (TS grouping).
VOLUME_SEGMENT_GROUPS: frozenset[str] = frozenset(PRIMARY_SEGMENT_GROUPS)
BODY_REGIONS: tuple[str, ...] = ("Head", "Chest", "Abdomen")
_DICOM_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
MODALITY_FILTER_ALL = "All"
_ORGAN_VOLUME_RANGES_PATH = (
    Path(__file__).resolve().parents[1] / "assets" / "analytics" / "organ_volume_ranges_ml.json"
)
# Nested JSON sections under assets/analytics/organ_volume_ranges_ml.json.
_ORGAN_VOLUME_RANGE_SECTIONS: tuple[str, ...] = (
    "soft_organs",
    "brain_structures",
    "skeletal",
    "airways_and_cord",
)
_ORGAN_VOLUME_RANGES_CACHE: dict[str, tuple[float, float, float]] | None = None


@dataclass(frozen=True)
class CountBucket:
    """One categorical label and its absolute count."""

    label: str
    count: int


@dataclass(frozen=True)
class Distribution:
    """Categorical counts with a single shared percentage denominator.

    ``total`` is the denominator for ``pct`` (e.g. patient count for sex),
    not necessarily ``sum(item.count for item in items)`` when items can overlap
    or when the chart should show coverage against a population.

    For demographics, ``items`` exclude Unknown; ``unknown_count`` is tracked but
    titles use known ``n=`` only.
    """

    items: tuple[CountBucket, ...]
    total: int
    unknown_count: int = 0

    def pct(self, count: int) -> float:
        if self.total <= 0:
            return 0.0
        return 100.0 * count / self.total

    def unknown_pct(self) -> float:
        return self.pct(self.unknown_count)

    def values(self, *, as_pct: bool) -> tuple[float, ...]:
        if as_pct:
            return tuple(self.pct(item.count) for item in self.items)
        return tuple(float(item.count) for item in self.items)

    @property
    def known_total(self) -> int:
        return max(0, self.total - self.unknown_count)

    @property
    def empty(self) -> bool:
        return not self.items or not any(item.count for item in self.items)


@dataclass(frozen=True)
class OrganVolumeSample:
    """One patient-mean organ volume (ml) after modality filter."""

    anon_patient_id: str
    ml: float


@dataclass(frozen=True)
class OrganVolumeDistribution:
    """Per-patient mean ml samples for one organ (histogram source).

    Each entry in ``samples`` is one patient: the mean volume across that
    patient's segmented series for this organ (after modality filter).
    """

    organ_name: str
    samples: tuple[OrganVolumeSample, ...]

    @property
    def samples_ml(self) -> tuple[float, ...]:
        return tuple(s.ml for s in self.samples)

    @property
    def patient_count(self) -> int:
        return len(self.samples)

    @property
    def empty(self) -> bool:
        return not self.samples


def _parse_organ_volume_range_entry(
    key: str, entry: Mapping[str, Any]
) -> tuple[float, float, float] | None:
    try:
        lo = float(entry["min_ml"])
        hi = float(entry["max_ml"])
        width = float(entry["bin_width_ml"])
    except (KeyError, TypeError, ValueError):
        logger.warning("Skipping invalid organ volume range entry: %s", key)
        return None
    if hi <= lo or width <= 0:
        logger.warning("Skipping non-positive organ volume range: %s", key)
        return None
    return lo, hi, width


def load_organ_volume_ranges() -> dict[str, tuple[float, float, float]]:
    """Load normative (min_ml, max_ml, bin_width_ml) per PRIMARY_SEGMENT_GROUPS key.

    JSON is sectioned (``soft_organs`` / ``brain_structures`` / ``skeletal`` /
    ``airways_and_cord``) to mirror TS latch grouping; the returned map is flat.
    There is no default range — every volume histogram key must be listed.
    """
    global _ORGAN_VOLUME_RANGES_CACHE
    if _ORGAN_VOLUME_RANGES_CACHE is not None:
        return _ORGAN_VOLUME_RANGES_CACHE

    ranges: dict[str, tuple[float, float, float]] = {}
    try:
        raw = json.loads(_ORGAN_VOLUME_RANGES_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load organ volume ranges from %s", _ORGAN_VOLUME_RANGES_PATH)
        _ORGAN_VOLUME_RANGES_CACHE = ranges
        return ranges

    if not isinstance(raw, dict):
        logger.error("Organ volume ranges JSON must be an object: %s", _ORGAN_VOLUME_RANGES_PATH)
        _ORGAN_VOLUME_RANGES_CACHE = ranges
        return ranges

    for section in _ORGAN_VOLUME_RANGE_SECTIONS:
        section_raw = raw.get(section)
        if not isinstance(section_raw, dict):
            logger.error("Organ volume ranges missing section %r in %s", section, _ORGAN_VOLUME_RANGES_PATH)
            continue
        for key, entry in section_raw.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            parsed = _parse_organ_volume_range_entry(key, entry)
            if parsed is None:
                continue
            if key in ranges:
                logger.warning("Duplicate organ volume range key %r (section %r)", key, section)
            ranges[key] = parsed

    missing = sorted(VOLUME_SEGMENT_GROUPS - ranges.keys())
    if missing:
        logger.error(
            "organ_volume_ranges_ml.json missing PRIMARY_SEGMENT_GROUPS keys: %s",
            ", ".join(missing),
        )
    extra = sorted(ranges.keys() - VOLUME_SEGMENT_GROUPS)
    if extra:
        logger.warning(
            "organ_volume_ranges_ml.json has keys outside PRIMARY_SEGMENT_GROUPS: %s",
            ", ".join(extra),
        )

    _ORGAN_VOLUME_RANGES_CACHE = ranges
    return ranges


def organ_volume_range_ml(organ_name: str) -> tuple[float, float, float]:
    """Return normative (min_ml, max_ml, bin_width_ml) for a primary segment group.

    Raises ``KeyError`` when ``organ_name`` has no healthy-adult entry in
    ``organ_volume_ranges_ml.json`` (no catch-all default).
    """
    ranges = load_organ_volume_ranges()
    try:
        return ranges[organ_name]
    except KeyError as exc:
        raise KeyError(
            f"No normative volume range for {organ_name!r}; "
            "add it under the matching TS section in "
            "assets/analytics/organ_volume_ranges_ml.json"
        ) from exc


def organ_volume_axis_span(
    samples: Sequence[float] | None = None,
    *,
    organ_name: str,
) -> tuple[float, float, float, float, float]:
    """Return ``(axis_lo, axis_hi, norm_lo, norm_hi, bin_width_ml)``.

    The axis always covers the normative window from ``organ_volume_ranges_ml.json``,
    plus one bin of headroom on each side so both dotted normative bounds stay
    inset (not glued to the plot spine). If any sample falls outside that padded
    window, extend by whole bin widths so outliers remain visible.
    """
    norm_lo, norm_hi, width = organ_volume_range_ml(organ_name)
    w = float(width)
    # One-bin pad keeps axvline(norm_lo/hi) visually interior when samples sit
    # inside the healthy window (otherwise left bound coincides with the spine).
    axis_lo = max(0.0, float(norm_lo) - w)
    axis_hi = float(norm_hi) + w
    if axis_hi <= axis_lo:
        axis_hi = axis_lo + w
    if samples:
        s_lo = float(min(samples))
        s_hi = float(max(samples))
        if s_lo < axis_lo:
            axis_lo = max(0.0, axis_lo - math.ceil((axis_lo - s_lo) / w) * w)
        if s_hi > axis_hi:
            axis_hi += math.ceil((s_hi - axis_hi) / w) * w
    return axis_lo, axis_hi, float(norm_lo), float(norm_hi), w


def organ_volume_bin_edges(
    samples: Sequence[float] | None = None,
    *,
    organ_name: str,
) -> list[float]:
    """Fixed-width histogram edges covering normative range plus any sample outliers."""
    axis_lo, axis_hi, _norm_lo, _norm_hi, w = organ_volume_axis_span(
        samples, organ_name=organ_name
    )
    n_bins = max(1, int(math.ceil((axis_hi - axis_lo) / w)))
    edges = [axis_lo + i * w for i in range(n_bins)]
    edges.append(axis_lo + n_bins * w)
    return edges


def organ_volume_bin_patient_ids(
    samples: Sequence[OrganVolumeSample],
    edges: Sequence[float],
) -> list[tuple[str, ...]]:
    """Group patient ids into bins matching matplotlib ``hist`` edge semantics.

    Intervals are left-closed / right-open except the last bin, which is closed
    on the right (same as ``numpy.histogram`` / ``Axes.hist``).
    """
    if len(edges) < 2:
        return []
    buckets: list[list[str]] = [[] for _ in range(len(edges) - 1)]
    last = len(buckets) - 1
    for sample in samples:
        ml = float(sample.ml)
        placed = False
        for i in range(last):
            if edges[i] <= ml < edges[i + 1]:
                buckets[i].append(sample.anon_patient_id)
                placed = True
                break
        if not placed and edges[last] <= ml <= edges[last + 1]:
            buckets[last].append(sample.anon_patient_id)
    return [tuple(ids) for ids in buckets]


def _nice_ml_tick_step(raw_step: float) -> float:
    """Round ``raw_step`` up to 1/2/5 × 10^k for readable ml axis labels."""
    step = max(float(raw_step), 1e-6)
    exp = math.floor(math.log10(step))
    base = 10.0**exp
    mantissa = step / base
    if mantissa <= 1.0:
        nice = 1.0
    elif mantissa <= 2.0:
        nice = 2.0
    elif mantissa <= 5.0:
        nice = 5.0
    else:
        nice = 10.0
    return nice * base


def organ_volume_ml_tick_values(
    axis_lo: float,
    axis_hi: float,
    bin_width: float,
    *,
    max_ticks: int = 6,
) -> list[float]:
    """Sparse ml-axis tick positions — always labels the left origin.

    Tick step is at least ``bin_width`` and grows (1/2/5×10^k) until there are at
    most ``max_ticks`` labels across ``[axis_lo, axis_hi]``. ``axis_lo`` is always
    included so the left spine is never mistaken for an unlabeled 0. The next
    sparse label above the origin is omitted so it cannot overwrite the origin
    text. Normative bounds are not force-injected (avoids clutter).
    """
    lo = float(axis_lo)
    hi = float(axis_hi)
    if hi <= lo:
        return [lo]
    span = hi - lo
    cap = max(2, int(max_ticks))
    min_step = float(bin_width) if bin_width > 0 else span / (cap - 1)
    step = _nice_ml_tick_step(max(min_step, span / (cap - 1)))
    origin = float(round(lo, 10))

    def _with_origin(ticks: list[float]) -> list[float]:
        # Drop any sparse tick that collides with the forced origin label.
        rest = [t for t in ticks if abs(t - origin) > max(step, 1.0) * 1e-6]
        # Omit the next label up from min — prevents origin/next overwrite.
        if rest:
            rest = rest[1:]
        out = [origin] + rest
        if len(out) > cap:
            out = out[:cap]
        return out

    # Grow until the inclusive tick count fits (origin may add one slot).
    for _attempt in range(8):
        first = math.ceil(lo / step - 1e-12) * step
        ticks: list[float] = []
        t = first
        # Guard float drift at the end.
        while t <= hi + step * 1e-9:
            ticks.append(float(round(t, 10)))
            t += step
        merged = _with_origin(ticks) if ticks else [origin, float(round(hi, 10))]
        # Fit check against pre-origin sparse count so we don't over-grow solely
        # because of the mandatory origin label.
        if len(ticks) <= cap and len(merged) <= cap:
            return merged
        if len(ticks) <= max(1, cap - 1) and len(merged) <= cap:
            return merged
        step = _nice_ml_tick_step(step * 2.0)
    return _with_origin([lo, hi])


def age_histogram_bin_edges(
    samples: Sequence[float] | None = None,
    *,
    width: float = AGE_HIST_BIN_YEARS,
    lo: float = AGE_HIST_RANGE_YEARS[0],
    hi: float = AGE_HIST_RANGE_YEARS[1],
) -> list[float]:
    """Static fixed-width age histogram edges (default 0–100 in 5-year bins).

    Edges do not shrink to the sample span — a single patient still shows the
    full age axis. ``samples`` is ignored (kept for call-site compatibility).
    """
    _ = samples
    w = float(width) if width > 0 else AGE_HIST_BIN_YEARS
    start = float(lo)
    stop = float(hi)
    if stop <= start:
        stop = start + w
    n_bins = max(1, int(math.ceil((stop - start) / w)))
    edges = [start + i * w for i in range(n_bins)]
    edges.append(start + n_bins * w)
    return edges


@dataclass(frozen=True)
class AgeHistogram:
    """Known patient ages in years for a 5-year histogram; Unknown excluded from samples."""

    samples_years: tuple[float, ...]
    total: int
    unknown_count: int = 0

    @property
    def known_total(self) -> int:
        return len(self.samples_years)

    def unknown_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return 100.0 * self.unknown_count / self.total

    @property
    def empty(self) -> bool:
        return not self.samples_years


@dataclass(frozen=True)
class DemographicsAnalytics:
    sex: Distribution
    age: AgeHistogram
    ethnicity: Distribution


@dataclass(frozen=True)
class ImagingAnalytics:
    modality: Distribution
    ai_coverage: Distribution


@dataclass(frozen=True)
class AnatomyAnalytics:
    """TS-derived anatomy; ``available`` is False when no series cache was found.

    ``applicable`` is False when the active modality filter cannot have Harmonize
    CT/MR segmentation (e.g. CR-only filter).
    ``organ_volumes`` lists every ``PRIMARY_SEGMENT_GROUPS`` latch with samples
    (soft organs, brain structures, skeletal, airways/cord), ranked for default
    picker selection (first ``TOP_ORGANS_N`` are pre-checked in the UI).
    """

    available: bool
    applicable: bool
    regions: Distribution
    organ_volumes: tuple[OrganVolumeDistribution, ...]
    segmented_series: int
    ct_mr_series: int

    @property
    def organ_volume(self) -> OrganVolumeDistribution | None:
        """Primary (first) organ — back-compat for callers expecting a single organ."""
        return self.organ_volumes[0] if self.organ_volumes else None


@dataclass(frozen=True)
class _PatientRow:
    sex: str
    age_years: float | None
    ethnicity: str
    modalities: frozenset[str]


@dataclass(frozen=True)
class _SeriesRow:
    modality: str
    anon_series_uid: str
    harmonized: bool
    face_blur: bool
    pixel_phi: bool


@dataclass(frozen=True)
class _RegionHit:
    region: str
    modality: str


@dataclass(frozen=True)
class _OrganSample:
    organ: str
    modality: str
    ml: float
    anon_patient_id: str


@dataclass(frozen=True)
class AnalyticsFilterIndex:
    """Compact facts for modality re-bucketing without a PHI reload."""

    patients: tuple[_PatientRow, ...]
    series: tuple[_SeriesRow, ...]
    region_hits: tuple[_RegionHit, ...]
    organ_samples: tuple[_OrganSample, ...]
    segmented_modalities: tuple[str, ...]


@dataclass(frozen=True)
class DatasetAnalytics:
    """Immutable project analytics snapshot for Dashboard charts.

    Independent of Dashboard inventory counters (``Totals`` / databoard labels).
    """

    generated_at: datetime
    demographics: DemographicsAnalytics
    imaging: ImagingAnalytics
    anatomy: AnatomyAnalytics
    modality_options: tuple[str, ...]
    filter_index: AnalyticsFilterIndex
    modality_filter: str = MODALITY_FILTER_ALL

    @property
    def is_all_modalities(self) -> bool:
        key = (self.modality_filter or "").strip()
        return not key or key == MODALITY_FILTER_ALL

    def for_modality(self, modality: str | None) -> DatasetAnalytics:
        """Return a view restricted to ``modality``, or self when All/None."""
        key = (modality or "").strip()
        if not key or key == MODALITY_FILTER_ALL:
            if self.is_all_modalities:
                return self
            return _assemble_from_index(self.filter_index, self.generated_at, modality=None)
        return _assemble_from_index(self.filter_index, self.generated_at, modality=key)


def _parse_dicom_date(raw: str | None) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    match = _DICOM_DATE_RE.match(text[:8])
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def normalize_sex_label(raw: str | None) -> str:
    key = (raw or "").strip().upper()
    if key in {"M", "MALE"}:
        return _("Male")
    if key in {"F", "FEMALE"}:
        return _("Female")
    if key in {"O", "OTHER"}:
        return _("Other")
    return _("Unknown")


def age_years_for_dob(dob: date | None, study_date: date | None) -> float | None:
    """Age in whole years at study date, or None when Unknown."""
    if dob is None or study_date is None:
        return None
    years = study_date.year - dob.year - ((study_date.month, study_date.day) < (dob.month, dob.day))
    if years < 0:
        return None
    return float(years)


def age_band_for_dob(dob: date | None, study_date: date | None) -> str:
    years = age_years_for_dob(dob, study_date)
    if years is None:
        return AGE_UNKNOWN
    if years < 18:
        return "<18"
    if years < 40:
        return "18–39"
    if years < 60:
        return "40–59"
    if years < 80:
        return "60–79"
    return "80+"


def normalize_ethnicity_label(raw: str | None) -> str:
    text = (raw or "").strip()
    return text if text else _("Unknown")


def _distribution_from_counter(
    counter: Counter[str],
    *,
    total: int,
    order: Iterable[str] | None = None,
    unknown_count: int = 0,
) -> Distribution:
    if order is not None:
        labels = list(order)
        seen = set(labels)
        for label in counter:
            if label not in seen:
                labels.append(label)
                seen.add(label)
    else:
        labels = [label for label, _ in counter.most_common()]
    items = tuple(CountBucket(label=label, count=int(counter.get(label, 0))) for label in labels)
    return Distribution(items=items, total=max(0, total), unknown_count=max(0, unknown_count))


def _distribution_excluding_unknown(
    counter: Counter[str],
    *,
    total: int,
    unknown_label: str,
    order: Iterable[str] | None = None,
) -> Distribution:
    unknown_count = int(counter.get(unknown_label, 0))
    known = Counter({label: count for label, count in counter.items() if label != unknown_label})
    known_order = None if order is None else [label for label in order if label != unknown_label]
    return _distribution_from_counter(known, total=total, order=known_order, unknown_count=unknown_count)


def _ethnicity_distribution(counter: Counter[str], *, top_n: int = ETHNICITY_TOP_N) -> Distribution:
    unknown = _("Unknown")
    grand = sum(counter.values())
    unknown_count = int(counter.get(unknown, 0))
    known = [(label, count) for label, count in counter.most_common() if label != unknown]
    top = known[:top_n]
    other = sum(count for _, count in known[top_n:])
    buckets: list[CountBucket] = [CountBucket(label=label, count=count) for label, count in top]
    if other:
        buckets.append(CountBucket(label=_("Other"), count=other))
    return Distribution(items=tuple(buckets), total=grand, unknown_count=unknown_count)


def _ai_coverage_distribution(
    *,
    series_total: int,
    series_harmonized: int,
    series_face_blur: int,
    series_pixel_phi: int,
) -> Distribution:
    """Series-level AI coverage; omit algorithms that round to 0%."""
    total = max(0, series_total)

    def keep(count: int) -> bool:
        if count <= 0 or total <= 0:
            return False
        return round(100.0 * count / total) > 0

    candidates = (
        (_("Harmonize"), series_harmonized),
        (_("Face blur"), series_face_blur),
        (_("Pixel PHI"), series_pixel_phi),
    )
    items = tuple(CountBucket(label=label, count=count) for label, count in candidates if keep(count))
    return Distribution(items=items, total=total)


def _ranked_organ_volumes(
    samples_by_organ: dict[str, list[OrganVolumeSample]],
) -> tuple[OrganVolumeDistribution, ...]:
    """All nonempty organs, ranked by patient count then median volume."""
    nonempty = {name: samples for name, samples in samples_by_organ.items() if samples}
    if not nonempty:
        return ()

    def sort_key(name: str) -> tuple[int, float, str]:
        samples = nonempty[name]
        return (-len(samples), -statistics.median(s.ml for s in samples), name)

    ranked = sorted(nonempty.keys(), key=sort_key)
    return tuple(
        OrganVolumeDistribution(
            organ_name=name,
            samples=tuple(
                OrganVolumeSample(anon_patient_id=s.anon_patient_id, ml=round(s.ml, 1))
                for s in nonempty[name]
            ),
        )
        for name in ranked
    )


def _warn_organ_volume_outside_normative(
    *,
    organ: str,
    anon_patient_id: str,
    mean_ml: float,
    series_entries: Sequence[tuple[float, str]],
) -> None:
    """Log WARNING when patient mean or any series ml falls outside the normative axis.

    Out-of-range volumes are still kept in the histogram sample list (``n=`` unchanged);
    they simply fall outside the fixed axis bins. Causes may be segmentation error,
    a true clinical outlier, or an incorrect entry in ``organ_volume_ranges_ml.json``.
    """
    lo, hi, _width = organ_volume_range_ml(organ)
    series_oor = [(ml, mod) for ml, mod in series_entries if ml < lo or ml > hi]
    mean_oor = mean_ml < lo or mean_ml > hi
    if not mean_oor and not series_oor:
        return

    if mean_ml < lo:
        mean_side = "below"
    elif mean_ml > hi:
        mean_side = "above"
    else:
        mean_side = "inside"

    series_detail = ", ".join(f"{ml:.1f}ml/{mod}" for ml, mod in series_entries)
    oor_detail = (
        ", ".join(f"{ml:.1f}ml/{mod}" for ml, mod in series_oor) if series_oor else "none"
    )
    logger.warning(
        "Organ volume outside normative range: organ=%s patient=%s mean_ml=%.1f "
        "mean_vs_range=%s normative=[%.1f, %.1f] ml series_n=%d series=[%s] "
        "series_outside=[%s] — check TotalSegmentator mask, true outlier, or "
        "update assets/analytics/organ_volume_ranges_ml.json",
        organ,
        anon_patient_id,
        mean_ml,
        mean_side,
        lo,
        hi,
        len(series_entries),
        series_detail,
        oor_detail,
    )


def _patient_mean_samples_by_organ(
    organ_samples: Sequence[_OrganSample],
    *,
    modality: str | None,
) -> dict[str, list[OrganVolumeSample]]:
    """Collapse series samples to one mean-ml value per patient per organ.

    Modality filter is applied before averaging so a CT+MR patient only
    contributes CT series when the filter is CT. Patient means (and any
    contributing series) outside the normative JSON range are logged at WARNING
    but still included in the returned samples.
    """
    by_organ_patient: dict[str, dict[str, list[tuple[float, str]]]] = {
        name: {} for name in VOLUME_SEGMENT_GROUPS
    }
    for sample in organ_samples:
        if modality is not None and sample.modality != modality:
            continue
        patients = by_organ_patient.get(sample.organ)
        if patients is None:
            continue
        patients.setdefault(sample.anon_patient_id, []).append(
            (sample.ml, sample.modality)
        )

    samples_by_organ: dict[str, list[OrganVolumeSample]] = {
        name: [] for name in VOLUME_SEGMENT_GROUPS
    }
    for organ, patients in by_organ_patient.items():
        for patient_id, entries in patients.items():
            mean_ml = statistics.fmean(ml for ml, _mod in entries)
            _warn_organ_volume_outside_normative(
                organ=organ,
                anon_patient_id=patient_id,
                mean_ml=mean_ml,
                series_entries=entries,
            )
            samples_by_organ[organ].append(
                OrganVolumeSample(anon_patient_id=patient_id, ml=mean_ml)
            )
    return samples_by_organ


def _select_top_organs(
    samples_by_organ: dict[str, list[OrganVolumeSample]],
    *,
    top_n: int = TOP_ORGANS_N,
) -> tuple[OrganVolumeDistribution, ...]:
    return _ranked_organ_volumes(samples_by_organ)[: max(0, top_n)]


def default_selected_organ_names(
    organ_volumes: Sequence[OrganVolumeDistribution],
    *,
    top_n: int = TOP_ORGANS_N,
) -> tuple[str, ...]:
    """Default Volumes-picker checks: first ``top_n`` ranked organs."""
    return tuple(organ.organ_name for organ in organ_volumes[: max(0, top_n)])


def organ_display_name(organ_name: str) -> str:
    """UI label for a volume segment key (``frontal_lobe`` → ``Frontal lobe``)."""
    return organ_name.replace("_", " ").capitalize()


def _select_main_organ(
    samples_by_organ: dict[str, list[OrganVolumeSample]],
) -> OrganVolumeDistribution | None:
    top = _select_top_organs(samples_by_organ, top_n=1)
    return top[0] if top else None


def _earliest_study_date(studies: list[Study] | None) -> date | None:
    dates = [_parse_dicom_date(s.study_date) for s in (studies or [])]
    valid = [d for d in dates if d is not None]
    return min(valid) if valid else None


def voxels_to_ml(voxels: int, spacing: list[float] | tuple[float, ...] | None) -> float | None:
    if voxels <= 0 or not spacing or len(spacing) < 3:
        return None
    try:
        mm3 = float(spacing[0]) * float(spacing[1]) * float(spacing[2])
    except (TypeError, ValueError):
        return None
    if mm3 <= 0:
        return None
    return voxels * mm3 / 1000.0


def _organ_counts_for_cache(cache_dir: Path) -> dict[str, int]:
    primary = read_primary_segment_voxels(cache_dir)
    if primary:
        return {
            name: count
            for name, count in primary.items()
            if name in VOLUME_SEGMENT_GROUPS and count > 0
        }
    structures = read_structure_voxels(cache_dir)
    if not structures:
        return {}
    seg_dir = cache_dir / "seg"
    aggregated = aggregate_primary_segment_voxels(
        structures,
        seg_dir,
        require_masks=False,
        min_voxels=1,
    )
    return {
        name: count
        for name, count in aggregated.items()
        if name in VOLUME_SEGMENT_GROUPS and count > 0
    }


def _iter_series_dirs(images_dir: Path) -> list[Path]:
    """Leaf series directories under ``images_dir/patient/study/series``."""
    series: list[Path] = []
    root = Path(images_dir)
    if not root.is_dir():
        return series
    for patient in sorted(root.iterdir()):
        if not patient.is_dir() or patient.name.startswith("."):
            continue
        for study in sorted(patient.iterdir()):
            if not study.is_dir() or study.name.startswith("."):
                continue
            for ser in sorted(study.iterdir()):
                if ser.is_dir() and not ser.name.startswith("."):
                    series.append(ser)
    return series


def _collect_tseg_raw(
    images_dir: Path,
    modality_by_anon_uid: dict[str, str],
    *,
    should_abort: Callable[[], bool] | None = None,
) -> tuple[tuple[_RegionHit, ...], tuple[_OrganSample, ...], tuple[str, ...]]:
    region_hits: list[_RegionHit] = []
    organ_samples: list[_OrganSample] = []
    segmented_modalities: list[str] = []
    series_dirs = _iter_series_dirs(images_dir)
    logger.info("Analytics tseg scan: %d series dirs under %s", len(series_dirs), images_dir)

    for idx, series_path in enumerate(series_dirs, start=1):
        if should_abort is not None and should_abort():
            logger.info("Analytics tseg scan aborted after %d/%d series", idx - 1, len(series_dirs))
            break
        cache_dir = resolve_series_cache_dir(series_path)
        if not cache_dir.is_dir():
            continue
        structures = read_structure_voxels(cache_dir)
        if not structures and not read_primary_segment_voxels(cache_dir):
            continue
        modality = modality_by_anon_uid.get(series_path.name, "").strip().upper() or _("Unknown")
        segmented_modalities.append(modality)
        if structures:
            region = dominant_region_from_voxels(structures)
            for body_part, voxels in region.region_voxels.items():
                if voxels > 0:
                    region_hits.append(_RegionHit(region=body_part, modality=modality))

        geometry = read_mask_geometry(cache_dir)
        spacing = geometry.get("spacing") if geometry else None
        if spacing:
            for organ, voxels in _organ_counts_for_cache(cache_dir).items():
                ml = voxels_to_ml(voxels, spacing)
                if ml is None:
                    continue
                organ_samples.append(
                    _OrganSample(
                        organ=organ,
                        modality=modality,
                        ml=ml,
                        anon_patient_id=series_path.parent.parent.name,
                    )
                )
        if idx % 50 == 0:
            logger.info("Analytics tseg scan progress %d/%d", idx, len(series_dirs))

    return tuple(region_hits), tuple(organ_samples), tuple(segmented_modalities)


def _modality_options(modality_counter: Counter[str], *, top_n: int = MODALITY_FILTER_TOP_N) -> tuple[str, ...]:
    ranked = [label for label, _ in modality_counter.most_common(top_n) if label]
    return (MODALITY_FILTER_ALL, *ranked)


def _patient_matches(row: _PatientRow, modality: str | None) -> bool:
    if modality is None:
        return True
    return modality in row.modalities


def _series_matches(row: _SeriesRow, modality: str | None) -> bool:
    if modality is None:
        return True
    return row.modality == modality


def _assemble_demographics(patients: Iterable[_PatientRow]) -> DemographicsAnalytics:
    sex_counter: Counter[str] = Counter()
    ethnicity_counter: Counter[str] = Counter()
    age_samples: list[float] = []
    unknown_age = 0
    n = 0
    for row in patients:
        n += 1
        sex_counter[row.sex] += 1
        ethnicity_counter[row.ethnicity] += 1
        if row.age_years is None:
            unknown_age += 1
        else:
            age_samples.append(float(row.age_years))
    return DemographicsAnalytics(
        sex=_distribution_excluding_unknown(sex_counter, total=n, unknown_label=_("Unknown")),
        age=AgeHistogram(
            samples_years=tuple(age_samples),
            total=n,
            unknown_count=unknown_age,
        ),
        ethnicity=_ethnicity_distribution(ethnicity_counter),
    )


def _assemble_imaging(series_rows: Iterable[_SeriesRow]) -> ImagingAnalytics:
    rows = list(series_rows)
    modality_counter: Counter[str] = Counter(row.modality for row in rows)
    series_total = len(rows)
    return ImagingAnalytics(
        modality=_distribution_from_counter(modality_counter, total=series_total),
        ai_coverage=_ai_coverage_distribution(
            series_total=series_total,
            series_harmonized=sum(1 for row in rows if row.harmonized),
            series_face_blur=sum(1 for row in rows if row.face_blur),
            series_pixel_phi=sum(1 for row in rows if row.pixel_phi),
        ),
    )


def _assemble_anatomy(
    index: AnalyticsFilterIndex,
    *,
    modality: str | None,
) -> AnatomyAnalytics:
    if modality is not None and not is_tseg_modality(modality):
        empty_regions = _distribution_from_counter(Counter(), total=0, order=BODY_REGIONS)
        return AnatomyAnalytics(
            available=False,
            applicable=False,
            regions=empty_regions,
            organ_volumes=(),
            segmented_series=0,
            ct_mr_series=0,
        )

    series_pool = [row for row in index.series if _series_matches(row, modality)]
    ct_mr_series = sum(1 for row in series_pool if is_tseg_modality(row.modality))
    segmented = [mod for mod in index.segmented_modalities if modality is None or mod == modality]
    segmented_series = len(segmented)

    region_counter: Counter[str] = Counter()
    for hit in index.region_hits:
        if modality is None or hit.modality == modality:
            region_counter[hit.region] += 1
    regions = _distribution_from_counter(region_counter, total=segmented_series, order=BODY_REGIONS)

    samples_by_organ = _patient_mean_samples_by_organ(index.organ_samples, modality=modality)
    organ_volumes = _ranked_organ_volumes(samples_by_organ)
    available = segmented_series > 0

    return AnatomyAnalytics(
        available=available,
        applicable=True,
        regions=regions,
        organ_volumes=organ_volumes,
        segmented_series=segmented_series,
        ct_mr_series=ct_mr_series,
    )


def _assemble_from_index(
    index: AnalyticsFilterIndex,
    generated_at: datetime,
    *,
    modality: str | None = None,
) -> DatasetAnalytics:
    patients = tuple(row for row in index.patients if _patient_matches(row, modality))
    series_rows = tuple(row for row in index.series if _series_matches(row, modality))
    # Modality mix stays project-global; AI coverage follows the active filter.
    global_imaging = _assemble_imaging(index.series)
    filtered_ai = _assemble_imaging(series_rows).ai_coverage
    modality_counter = Counter(row.modality for row in index.series)
    filter_key = modality if modality else MODALITY_FILTER_ALL
    return DatasetAnalytics(
        generated_at=generated_at,
        demographics=_assemble_demographics(patients),
        imaging=ImagingAnalytics(modality=global_imaging.modality, ai_coverage=filtered_ai),
        anatomy=_assemble_anatomy(index, modality=modality),
        modality_options=_modality_options(modality_counter),
        filter_index=index,
        modality_filter=filter_key,
    )


def build_dataset_analytics(
    anon_model: AnonymizerModel,
    images_dir: Path,
    *,
    should_abort: Callable[[], bool] | None = None,
) -> DatasetAnalytics:
    """Build a read-only Dataset analytics snapshot from PHI + TS cache files."""
    t0 = time.monotonic()
    logger.info("Analytics build: loading PHI tree (no instances)")
    phi_rows = anon_model.load_phi_with_studies_series_no_instances()
    logger.info("Analytics build: PHI loaded in %.2fs (%d rows)", time.monotonic() - t0, len(phi_rows))
    if should_abort is not None and should_abort():
        raise RuntimeError("analytics aborted")

    t_phi = time.monotonic()
    pixel_phi_series_uids = anon_model.anon_series_uids_with_pixel_phi()
    logger.info(
        "Analytics build: pixel_phi series set (%d) in %.2fs",
        len(pixel_phi_series_uids),
        time.monotonic() - t_phi,
    )

    patients: list[_PatientRow] = []
    series_rows: list[_SeriesRow] = []
    modality_by_anon_uid: dict[str, str] = {}
    default_pk = getattr(anon_model, "DEFAULT_PHI_PATIENT_ID_PK_VALUE", None)

    for phi in phi_rows:
        if default_pk is not None and phi.patient_id == default_pk:
            continue
        patient_modalities: set[str] = set()
        dob = _parse_dicom_date(phi.dob)
        study_day = _earliest_study_date(phi.studies)

        for study in phi.studies or []:
            for ser in study.series or []:
                modality = (ser.modality or "").strip().upper() or _("Unknown")
                anon_uid = (ser.anon_series_uid or "").strip()
                patient_modalities.add(modality)
                if anon_uid:
                    modality_by_anon_uid[anon_uid] = modality
                series_rows.append(
                    _SeriesRow(
                        modality=modality,
                        anon_series_uid=anon_uid,
                        harmonized=bool((ser.harmonized_description or "").strip()),
                        face_blur=bool((ser.face_blur_algorithm_applied or "").strip()),
                        pixel_phi=bool(anon_uid and anon_uid in pixel_phi_series_uids),
                    )
                )

        patients.append(
            _PatientRow(
                sex=normalize_sex_label(phi.sex),
                age_years=age_years_for_dob(dob, study_day),
                ethnicity=normalize_ethnicity_label(phi.ethnic_group),
                modalities=frozenset(patient_modalities),
            )
        )

    if should_abort is not None and should_abort():
        raise RuntimeError("analytics aborted")

    logger.info(
        "Analytics build: demographics done (patients=%d series=%d)",
        len(patients),
        len(series_rows),
    )
    t_tseg = time.monotonic()
    region_hits, organ_samples, segmented_modalities = _collect_tseg_raw(
        images_dir,
        modality_by_anon_uid,
        should_abort=should_abort,
    )
    logger.info(
        "Analytics build: tseg metrics in %.2fs (segmented=%d organ_samples=%d)",
        time.monotonic() - t_tseg,
        len(segmented_modalities),
        len(organ_samples),
    )

    index = AnalyticsFilterIndex(
        patients=tuple(patients),
        series=tuple(series_rows),
        region_hits=region_hits,
        organ_samples=organ_samples,
        segmented_modalities=segmented_modalities,
    )
    snapshot = _assemble_from_index(index, datetime.now().astimezone())
    logger.info("Analytics build: complete in %.2fs", time.monotonic() - t0)
    return snapshot


# Back-compat helper used by older tests / callers that only need tseg assembly.
def _collect_tseg_metrics(
    images_dir: Path,
    *,
    should_abort: Callable[[], bool] | None = None,
    modality_by_anon_uid: dict[str, str] | None = None,
) -> AnatomyAnalytics:
    region_hits, organ_samples, segmented_modalities = _collect_tseg_raw(
        images_dir,
        modality_by_anon_uid or {},
        should_abort=should_abort,
    )
    index = AnalyticsFilterIndex(
        patients=(),
        series=(),
        region_hits=region_hits,
        organ_samples=organ_samples,
        segmented_modalities=segmented_modalities,
    )
    # Without PHI series rows, ct_mr_series stays 0; still report segmented anatomy.
    anatomy = _assemble_anatomy(index, modality=None)
    return replace(anatomy, ct_mr_series=max(anatomy.ct_mr_series, anatomy.segmented_series))
