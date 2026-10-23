"""First-20 MIDI-B Synthetic Validation: PseudoPHI pipeline + pairwise score vs curated.

No official MIDI scorer. Digest-pairs Synthetic → Curated, runs shared de-id stack,
writes ``results/<HHMM>/report.md`` (same shape as PseudoPHI ``1301/report.md``).
"""

import csv
import hashlib
import json
import logging
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pydicom

from prototyping.midi_b.inventory import list_instances
from prototyping.midi_b.paths import (
    DEFAULT_CURATED_VALIDATION,
    DEFAULT_SYNTHETIC_VALIDATION,
    PACKAGE_DIR,
)
from prototyping.midi_b.pipeline import run_instances
from prototyping.pseudo_phi_deid.pairs import InstancePair
from prototyping.pseudo_phi_deid.pipeline.script_session import ensure_experiment_script_copy
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig
from prototyping.pseudo_phi_deid.score import score_pairs

logger = logging.getLogger("midi_b.first20")
RESULTS = PACKAGE_DIR / "results"
GATE = 99.9
N_PATIENTS = 20


def _digests(path: Path) -> set[str]:
    """Raw PixelData MD5 and/or decoded array MD5 (TS may differ syn vs curated)."""
    out: set[str] = set()
    try:
        ds = pydicom.dcmread(str(path), force=True)
    except Exception:
        return out
    raw = getattr(ds, "PixelData", None)
    if raw:
        try:
            out.add(hashlib.md5(bytes(raw)).hexdigest())
        except Exception:
            pass
    try:
        arr = np.ascontiguousarray(ds.pixel_array)
        out.add(hashlib.md5(arr.tobytes()).hexdigest())
    except Exception:
        pass
    return out


def _index_curated(curated_root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    paths = list(curated_root.rglob("*.dcm"))
    logger.info("indexing curated digests n=%d", len(paths))
    for i, path in enumerate(paths, 1):
        if i == 1 or i % 2000 == 0 or i == len(paths):
            logger.info("curated digest %d/%d", i, len(paths))
        for d in _digests(path):
            index.setdefault(d, path)
    return index


def _pair_first_n(
    syn_root: Path,
    curated_index: dict[str, Path],
    *,
    n_patients: int,
) -> tuple[list[InstancePair], list[dict]]:
    patient_dirs = sorted(p for p in syn_root.iterdir() if p.is_dir())[:n_patients]
    pairs: list[InstancePair] = []
    unpaired: list[dict] = []
    for pdir in patient_dirs:
        for path in sorted(pdir.rglob("*.dcm")):
            try:
                ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
            except Exception as exc:
                unpaired.append({"path": str(path), "reason": f"unreadable:{exc}"})
                continue
            sop = str(getattr(ds, "SOPInstanceUID", "") or "").strip()
            pid = str(getattr(ds, "PatientID", "") or pdir.name).strip()
            mod = str(getattr(ds, "Modality", "") or "").strip()
            digs = _digests(path)
            gold = None
            for d in digs:
                gold = curated_index.get(d)
                if gold is not None:
                    break
            if gold is None:
                unpaired.append(
                    {"path": str(path), "patient": pid, "sop": sop, "reason": "no_digest_match"}
                )
                continue
            try:
                gds = pydicom.dcmread(str(gold), stop_before_pixels=True, force=True)
                gold_sop = str(getattr(gds, "SOPInstanceUID", "") or "").strip()
                gold_pid = str(getattr(gds, "PatientID", "") or "").strip()
            except Exception:
                gold_sop, gold_pid = "", ""
            pairs.append(
                InstancePair(
                    eval_path=path,
                    gold_path=gold,
                    eval_patient_id=pid,
                    gold_patient_id=gold_pid,
                    eval_sop_uid=sop,
                    gold_sop_uid=gold_sop,
                    modality=mod,
                )
            )
    return pairs, unpaired


def _classify(f: dict) -> tuple[str, str]:
    kind = f.get("kind") or ""
    tag = (f.get("tag_path") or "").strip()
    leaf = "pixel" if tag == "PixelData" else tag.split(".")[-1]
    ev = f.get("eval_value") or ""
    cv = f.get("candidate_value") or ""
    gv = f.get("gold_value") or ""

    if kind == "pixel_mismatch" or leaf == "pixel":
        return "n/a (pixel score; OCR not run)", "burn-in / pixel (out of phase)"
    if leaf.startswith("(") and len(leaf) >= 9 and leaf[1:5].isalnum():
        if cv and gv and cv != gv and ev and cv != ev:
            return "1 anonymizer script (DATEINC/private path) or 2 Private KB", "private value mismatch"
        if (ev or cv) and not gv:
            return "2 Private KB", "KB keep vs gold remove"
        if not cv and gv:
            return "2 Private KB", "KB removed vs gold keep"
        return "2 Private KB", "private value mismatch"
    script_leaves = {
        "DateOfLastCalibration",
        "DateOfLastDetectorCalibration",
        "SecondaryCaptureDeviceID",
        "TimeOfLastCalibration",
        "RescaleType",
        "CodingSchemeDesignator",
        "PlanarConfiguration",
        "PixelAspectRatio",
    }
    if leaf in script_leaves:
        if (ev or cv) and not gv:
            return "1 anonymizer script", "script keep vs gold empty"
        if not cv and gv:
            return "1 anonymizer script", "script blank vs gold keep"
        return "1 anonymizer script", "script vs gold mismatch"
    if leaf.endswith("Sequence") or leaf == "AcquisitionContextSequence":
        if not ev and not cv and gv:
            return "1 anonymizer script", "blanked vs gold keep"
        return "1 anonymizer script", "sequence mismatch"
    textish = {
        "StudyDescription",
        "SeriesDescription",
        "ImageComments",
        "CodeMeaning",
        "ProtocolName",
        "RequestedProcedureDescription",
    }
    if leaf in textish:
        if cv != ev:
            return "5 NER scrub or 6 residual", "NER residue / partial scrub"
        return "5 NER detect/scrub (miss) or 6 residual", "NER under-scrub / residue"
    if (ev or cv) and not gv:
        return "1 anonymizer script", "kept vs gold empty"
    if not ev and not cv and gv:
        return "1 anonymizer script", "blanked vs gold keep"
    if not cv and gv:
        return "5 NER scrub", "removed vs gold keep"
    return "unknown", "value mismatch"


def _short(v: str, n: int = 36) -> str:
    s = (v or "").replace("\n", " ")
    if not s:
        return "∅"
    return s if len(s) <= n else s[: n - 1]


def write_report(
    *,
    hhmm: str,
    metrics,
    fails: list[dict],
    patients: list[str],
    unpaired_n: int,
) -> Path:
    out_dir = RESULTS / hhmm
    out_dir.mkdir(parents=True, exist_ok=True)
    by_step: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    by_step_class: Counter[tuple[str, str]] = Counter()
    by_leaf: Counter[str] = Counter()
    examples: dict[str, tuple[str, str, dict]] = {}

    for f in fails:
        step, cls = _classify(f)
        tag = (f.get("tag_path") or "").strip()
        leaf = "pixel" if tag == "PixelData" else tag.split(".")[-1]
        by_step[step] += 1
        by_class[cls] += 1
        by_step_class[(step, cls)] += 1
        by_leaf[leaf] += 1
        examples.setdefault(leaf, (step, cls, f))

    hc, hm = metrics.header_comparable, metrics.header_matches
    header_acc = metrics.header_accuracy
    gate_pass = header_acc >= GATE

    lines = [
        f"# MIDI-B Synthetic Validation first-{N_PATIENTS} — PseudoPHI stack report `{hhmm}`",
        "",
        "**Stack:** 1 anonymizer script → 2 Private KB → 3–5 OpenMed NER → 6 residual cleanup. No OCR.",
        "**Score:** PseudoPHI pairwise cand vs curated gold (digest-paired). No official MIDI scorer.",
        "",
        "| | |",
        "| --- | --- |",
        f"| Patients | {len(patients)} |",
        f"| Files paired | {metrics.pairs} |",
        f"| Unpaired (no digest match) | {unpaired_n} |",
        f"| Header fields comparable | {hc} |",
        f"| Header fields match | {hm} |",
        f"| Header fields fail | {hc - hm} |",
        f"| Header accuracy | {header_acc:.4f}% |",
        f"| Cohort accuracy | {metrics.cohort_accuracy:.4f}% |",
        f"| Failure rows | {len(fails)} |",
        f"| Gate (≥{GATE}%) | {'PASS' if gate_pass else 'FAIL'} |",
        "",
        "## Failures by pipeline step",
        "",
        "| Step | fields affected (rows) |",
        "| --- | ---: |",
    ]
    for step, n in by_step.most_common():
        lines.append(f"| {step} | {n} |")
    lines += [
        f"| **Total** | **{sum(by_step.values())}** |",
        "",
        "## Failures by error class",
        "",
        "| Class | fields affected (rows) |",
        "| --- | ---: |",
    ]
    for cls, n in by_class.most_common():
        lines.append(f"| {cls} | {n} |")
    lines += [
        "",
        "## Step × class",
        "",
        "| Step | Class | n |",
        "| --- | --- | ---: |",
    ]
    for (step, cls), n in sorted(
        by_step_class.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1])
    ):
        lines.append(f"| {step} | {cls} | {n} |")
    lines += [
        "",
        "## By field (leaf)",
        "",
        "| leaf | n | step | class | sample (eval → cand → gold) |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for leaf, n in by_leaf.most_common():
        step, cls, f = examples[leaf]
        samp = (
            f"`{_short(f.get('eval_value'))}` → "
            f"`{_short(f.get('candidate_value'))}` → "
            f"`{_short(f.get('gold_value'))}`"
        )
        lines.append(f"| `{leaf}` | {n} | {step} | {cls} | {samp} |")
    lines.append("")

    report = out_dir / "report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    RESULTS.mkdir(parents=True, exist_ok=True)
    hhmm = datetime.now().strftime("%H%M")
    work = RESULTS / f"_work_{hhmm}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    syn = DEFAULT_SYNTHETIC_VALIDATION
    curated = DEFAULT_CURATED_VALIDATION
    patients = sorted(p.name for p in syn.iterdir() if p.is_dir())[:N_PATIENTS]
    logger.info("patients=%s", patients)

    cache = RESULTS / "_curated_digest_index.json"
    if cache.is_file():
        logger.info("loading curated digest cache %s", cache)
        raw = json.loads(cache.read_text(encoding="utf-8"))
        curated_index = {k: Path(v) for k, v in raw.items()}
    else:
        curated_index = _index_curated(curated)
        cache.write_text(
            json.dumps({k: str(v) for k, v in curated_index.items()}),
            encoding="utf-8",
        )

    pairs, unpaired = _pair_first_n(syn, curated_index, n_patients=N_PATIENTS)
    logger.info("paired=%d unpaired=%d", len(pairs), len(unpaired))
    (work / "unpaired.json").write_text(json.dumps(unpaired, indent=2), encoding="utf-8")
    if not pairs:
        logger.error("no pairs")
        return 1

    script = ensure_experiment_script_copy()
    cfg = RunConfig.from_mode("combined", script_path=script, subject_ids=patients)
    instances = list_instances(syn, patient_ids=patients)
    # Only process paired SOPs
    paired_sops = {p.eval_sop_uid for p in pairs}
    instances = [i for i in instances if i.sop_uid in paired_sops or not i.sop_uid]
    # Prefer path-based filter: re-list with headers
    instances = list_instances(syn, patient_ids=patients, read_headers=True)
    instances = [i for i in instances if i.sop_uid in paired_sops]
    logger.info("run instances=%d", len(instances))
    result = run_instances(instances, work, cfg)

    metrics = score_pairs(pairs, result.candidate_dir, histogram=result.histogram)
    fails = [
        {
            "kind": f.kind,
            "eval_patient_id": f.eval_patient_id,
            "tag_path": f.tag_path,
            "eval_value": f.eval_value,
            "candidate_value": f.candidate_value,
            "gold_value": f.gold_value,
            "note": f.note,
        }
        for f in metrics.failures
    ]
    report = write_report(
        hhmm=hhmm,
        metrics=metrics,
        fails=fails,
        patients=patients,
        unpaired_n=len(unpaired),
    )
    # Keep only HHMM/report.md (+ digest cache for reuse)
    shutil.rmtree(work, ignore_errors=True)
    for p in list(RESULTS.iterdir()):
        if p.name in {hhmm, "_curated_digest_index.json"}:
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file() and p.name != ".gitkeep":
            p.unlink(missing_ok=True)
    keep = RESULTS / hhmm
    for p in keep.iterdir():
        if p.name != "report.md":
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    logger.info(
        "report=%s header=%.4f fails=%d gate=%s",
        report,
        metrics.header_accuracy,
        len(fails),
        metrics.header_accuracy >= GATE,
    )
    print(str(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
