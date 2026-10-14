"""UID-excluded accuracy scoring vs Pseudo-PHI DeIdentified gold."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset

from prototyping.pseudo_phi_deid import ACCURACY_GATE
from prototyping.pseudo_phi_deid.pairs import InstancePair

_STAMP_KEYWORDS = frozenset(
    {
        "PatientIdentityRemoved",
        "DeidentificationMethod",
        "DeIdentificationMethod",
        "DeidentificationMethodCodeSequence",
        "DeIdentificationMethodCodeSequence",
    }
)
# Gold replaces these with research IDs; any remapping away from Evaluation counts
# as a match when gold also changed (exact gold string not required — avoids
# overfitting to Pseudo-PHI-00N labels while still requiring de-id).
_IDENTITY_REMAP_TAGS = frozenset(
    {
        "PatientID",
        "PatientName",
        "OtherPatientIDs",
        "OtherPatientNames",
        "AccessionNumber",
    }
)
# Date shift algorithms differ across systems; require remapping away from
# Evaluation when gold also changed (exact gold calendar day not required).
_DATE_REMAP_TAGS = frozenset(
    {
        "StudyDate",
        "SeriesDate",
        "AcquisitionDate",
        "ContentDate",
        "InstanceCreationDate",
        "PatientBirthDate",
        "StudyTime",
        "SeriesTime",
        "AcquisitionTime",
        "ContentTime",
        "InstanceCreationTime",
        # Do not end with "Date" / "DateTime" (…Calibration); still date-shifted PHI.
        "DateOfLastCalibration",
        "DateOfLastDetectorCalibration",
        "DateTimeOfLastCalibration",
    }
)


def _is_date_remap_leaf(leaf: str) -> bool:
    """True for top-level date tags and nested *Date / *DateTime / *Time leaves."""
    if leaf in _DATE_REMAP_TAGS:
        return True
    return bool(
        leaf.endswith("Date")
        or leaf.endswith("DateTime")
        or (leaf.endswith("Time") and not leaf.endswith("Timezone"))
    )


@dataclass
class FailRow:
    kind: str
    eval_patient_id: str
    tag_path: str
    eval_value: str
    candidate_value: str
    gold_value: str
    note: str = ""


@dataclass
class ScoreMetrics:
    pairs: int = 0
    header_comparable: int = 0
    header_matches: int = 0
    pixel_comparable: int = 0
    pixel_matches: int = 0
    overlay_comparable: int = 0
    overlay_matches: int = 0
    header_accuracy: float = 0.0
    pixel_accuracy: float = 0.0
    overlay_accuracy: float = 0.0
    cohort_accuracy: float = 0.0
    passed_gate: bool = False
    accuracy_gate: float = ACCURACY_GATE
    modality_accuracy: dict[str, float] = field(default_factory=dict)
    failures: list[FailRow] = field(default_factory=list)
    histogram: dict[str, int] = field(default_factory=dict)

    def to_json_dict(self) -> dict:
        d = asdict(self)
        d["failures"] = [asdict(f) for f in self.failures[:200]]
        d["failure_count"] = len(self.failures)
        return d


def _norm(s: str) -> str:
    return " ".join(str(s or "").replace("^", " ").split()).casefold()


def _is_uid_elem(keyword: str, vr: str) -> bool:
    if vr == "UI":
        return True
    k = keyword or ""
    return k.endswith("UID") or k.endswith("UIDs")


def _elem_map(ds: Dataset) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(current: Dataset, prefix: str = "") -> None:
        for elem in current:
            kw = elem.keyword or str(elem.tag)
            if kw in _STAMP_KEYWORDS:
                continue
            if elem.tag.group == 0x0013:
                continue
            if elem.tag.group == 0x0002:
                continue
            if elem.VR == "SQ" and elem.value:
                for i, item in enumerate(elem.value):
                    if isinstance(item, Dataset):
                        walk(item, f"{prefix}{kw}[{i}].")
                continue
            if elem.tag == (0x7FE0, 0x0010) or elem.VR in {"OB", "OW", "OF", "OD"}:
                continue
            if _is_uid_elem(kw, elem.VR or ""):
                continue
            try:
                val = "" if elem.value is None else str(elem.value)
            except Exception:
                continue
            out[f"{prefix}{kw}"] = val

    walk(ds)
    return out


def _has_overlay(ds: Dataset) -> bool:
    for elem in ds:
        g = int(elem.tag.group)
        if 0x6000 <= g <= 0x601E and g % 2 == 0:
            return True
    return False


def _pixel_digest(path: Path) -> tuple[str | None, tuple[int, ...] | None]:
    try:
        ds = pydicom.dcmread(str(path), force=True)
        arr = ds.pixel_array
        digest = hashlib.sha1(np.ascontiguousarray(arr).tobytes()).hexdigest()
        return digest, tuple(int(x) for x in arr.shape)
    except Exception:
        return None, None


def _pixels_agree_with_gold(
    *,
    eval_path: Path,
    gold_path: Path,
    cand_path: Path,
    eval_gold_same: bool,
) -> tuple[bool, str]:
    """Return (match, note) for pixel stratum."""
    try:
        ev = pydicom.dcmread(str(eval_path), force=True).pixel_array
        gold = pydicom.dcmread(str(gold_path), force=True).pixel_array
        cand = pydicom.dcmread(str(cand_path), force=True).pixel_array
    except Exception as exc:
        return False, f"pixel_read_error:{exc}"
    if ev.shape != gold.shape or cand.shape != gold.shape:
        return False, "shape_mismatch"
    if eval_gold_same:
        # Must not invent redaction: candidate should match eval (== gold).
        ok = bool(np.array_equal(cand, gold))
        return ok, "keep_identical" if ok else "false_redaction"
    # Burn-in case: candidate should be closer to gold than to eval.
    mad_cg = float(np.mean(np.abs(cand.astype(np.float64) - gold.astype(np.float64))))
    mad_ce = float(np.mean(np.abs(cand.astype(np.float64) - ev.astype(np.float64))))
    mad_eg = float(np.mean(np.abs(ev.astype(np.float64) - gold.astype(np.float64))))
    # Pass if cand≈gold OR cand moved away from eval toward gold.
    if mad_cg <= max(1.0, 0.25 * mad_eg):
        return True, f"burnin_cleaned mad_cg={mad_cg:.2f}"
    if mad_ce > 0.5 * mad_eg and mad_cg < mad_eg:
        return True, f"burnin_improved mad_cg={mad_cg:.2f}"
    return False, f"burnin_residual mad_cg={mad_cg:.2f} mad_ce={mad_ce:.2f}"


def score_pair(
    pair: InstancePair,
    candidate_path: Path,
    *,
    eval_gold_pixel_same: bool | None = None,
) -> tuple[dict[str, int], list[FailRow]]:
    eval_ds = pydicom.dcmread(str(pair.eval_path), stop_before_pixels=True, force=True)
    gold_ds = pydicom.dcmread(str(pair.gold_path), stop_before_pixels=True, force=True)
    cand_ds = pydicom.dcmread(str(candidate_path), stop_before_pixels=True, force=True)
    ev = _elem_map(eval_ds)
    gold = _elem_map(gold_ds)
    cand = _elem_map(cand_ds)
    fails: list[FailRow] = []
    stats = {
        "header_comparable": 0,
        "header_matches": 0,
        "pixel_comparable": 0,
        "pixel_matches": 0,
        "overlay_comparable": 0,
        "overlay_matches": 0,
    }

    keys = sorted(set(ev) | set(gold) | set(cand))
    for key in keys:
        g_val = gold.get(key, "")
        c_val = cand.get(key, "")
        e_val = ev.get(key, "")
        # Only score tags that appear on gold or eval (skip pure candidate stamps already filtered).
        if key not in gold and key not in ev:
            continue
        stats["header_comparable"] += 1
        leaf = key.split(".")[-1]
        matched = _norm(c_val) == _norm(g_val)
        if not matched and _norm(g_val) != _norm(e_val):
            # Gold changed this field: accept any successful remapping / blanking.
            if leaf in _IDENTITY_REMAP_TAGS and _norm(c_val) != _norm(e_val):
                matched = True
            elif _is_date_remap_leaf(leaf) and _norm(c_val) != _norm(e_val):
                matched = True
            elif not _norm(g_val) and not _norm(c_val):
                # Gold emptied PHI; candidate also empty.
                matched = True
        if matched:
            stats["header_matches"] += 1
        else:
            fails.append(
                FailRow(
                    kind="header_mismatch",
                    eval_patient_id=pair.eval_patient_id,
                    tag_path=key,
                    eval_value=e_val,
                    candidate_value=c_val,
                    gold_value=g_val,
                )
            )

    # Overlay stratum
    gold_ov = _has_overlay(gold_ds)
    cand_ov = _has_overlay(cand_ds)
    eval_ov = _has_overlay(eval_ds)
    if eval_ov or gold_ov or cand_ov:
        stats["overlay_comparable"] += 1
        if cand_ov == gold_ov:
            stats["overlay_matches"] += 1
        else:
            fails.append(
                FailRow(
                    kind="overlay_mismatch",
                    eval_patient_id=pair.eval_patient_id,
                    tag_path="Overlay(60xx)",
                    eval_value=str(eval_ov),
                    candidate_value=str(cand_ov),
                    gold_value=str(gold_ov),
                )
            )

    # Pixel stratum
    if eval_gold_pixel_same is None:
        ed, _ = _pixel_digest(pair.eval_path)
        gd, _ = _pixel_digest(pair.gold_path)
        eval_gold_pixel_same = bool(ed and gd and ed == gd)
    stats["pixel_comparable"] += 1
    ok, note = _pixels_agree_with_gold(
        eval_path=pair.eval_path,
        gold_path=pair.gold_path,
        cand_path=candidate_path,
        eval_gold_same=bool(eval_gold_pixel_same),
    )
    if ok:
        stats["pixel_matches"] += 1
    else:
        fails.append(
            FailRow(
                kind="pixel_mismatch",
                eval_patient_id=pair.eval_patient_id,
                tag_path="PixelData",
                eval_value="",
                candidate_value="",
                gold_value="",
                note=note,
            )
        )
    return stats, fails


def score_pairs(
    pairs: Sequence[InstancePair],
    candidate_dir: Path,
    *,
    pixel_same_by_sop: dict[str, bool] | None = None,
    histogram: dict[str, int] | None = None,
) -> ScoreMetrics:
    metrics = ScoreMetrics(histogram=dict(histogram or {}))
    by_mod_comp: dict[str, list[int]] = {}
    by_mod_match: dict[str, list[int]] = {}

    for pair in pairs:
        cand = candidate_dir / pair.eval_patient_id / f"{pair.eval_sop_uid.replace('.', '_')}.dcm"
        if not cand.is_file():
            # also try flat
            cand = candidate_dir / f"{pair.eval_sop_uid.replace('.', '_')}.dcm"
        if not cand.is_file():
            metrics.failures.append(
                FailRow(
                    kind="missing_candidate",
                    eval_patient_id=pair.eval_patient_id,
                    tag_path="(file)",
                    eval_value=str(pair.eval_path),
                    candidate_value="",
                    gold_value=str(pair.gold_path),
                )
            )
            continue
        metrics.pairs += 1
        same = None
        if pixel_same_by_sop is not None:
            same = pixel_same_by_sop.get(pair.eval_sop_uid)
        stats, fails = score_pair(pair, cand, eval_gold_pixel_same=same)
        metrics.failures.extend(fails)
        metrics.header_comparable += stats["header_comparable"]
        metrics.header_matches += stats["header_matches"]
        metrics.pixel_comparable += stats["pixel_comparable"]
        metrics.pixel_matches += stats["pixel_matches"]
        metrics.overlay_comparable += stats["overlay_comparable"]
        metrics.overlay_matches += stats["overlay_matches"]
        total_c = (
            stats["header_comparable"]
            + stats["pixel_comparable"]
            + stats["overlay_comparable"]
        )
        total_m = (
            stats["header_matches"] + stats["pixel_matches"] + stats["overlay_matches"]
        )
        mod = pair.modality or "?"
        by_mod_comp.setdefault(mod, []).append(total_c)
        by_mod_match.setdefault(mod, []).append(total_m)

    def _pct(n: int, d: int) -> float:
        return round(100.0 * n / d, 4) if d else 0.0

    metrics.header_accuracy = _pct(metrics.header_matches, metrics.header_comparable)
    metrics.pixel_accuracy = _pct(metrics.pixel_matches, metrics.pixel_comparable)
    metrics.overlay_accuracy = _pct(metrics.overlay_matches, metrics.overlay_comparable)
    tot_c = (
        metrics.header_comparable
        + metrics.pixel_comparable
        + metrics.overlay_comparable
    )
    tot_m = (
        metrics.header_matches + metrics.pixel_matches + metrics.overlay_matches
    )
    metrics.cohort_accuracy = _pct(tot_m, tot_c)
    metrics.passed_gate = (metrics.cohort_accuracy / 100.0) > metrics.accuracy_gate
    for mod, comps in by_mod_comp.items():
        matches = by_mod_match[mod]
        c = sum(comps)
        m = sum(matches)
        metrics.modality_accuracy[mod] = _pct(m, c)
    return metrics


def write_metrics_json(path: Path, metrics: ScoreMetrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics.to_json_dict(), indent=2), encoding="utf-8")


def write_failures_csv(path: Path, failures: Sequence[FailRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "kind",
                "eval_patient_id",
                "tag_path",
                "eval_value",
                "candidate_value",
                "gold_value",
                "note",
            ],
        )
        w.writeheader()
        for f in failures:
            w.writerow(asdict(f))
