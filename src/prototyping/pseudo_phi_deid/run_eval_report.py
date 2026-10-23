"""Full PseudoPHI-eval → ``results/<HHMM>/report.md`` (1301-style, gate 99.9%).

Stack: anonymizer script → Private KB → OpenMed NER → residual. No OCR.
"""

import logging
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from prototyping.pseudo_phi_deid.pairs import pair_all
from prototyping.pseudo_phi_deid.paths import RESULTS_DIR
from prototyping.pseudo_phi_deid.pipeline.script_session import ensure_experiment_script_copy
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig, run_pairs
from prototyping.pseudo_phi_deid.score import score_pairs

logger = logging.getLogger("pseudo_phi_deid.eval_report")
GATE = 99.9


def _classify(f) -> tuple[str, str]:
    kind = f.kind or ""
    tag = (f.tag_path or "").strip()
    leaf = "pixel" if tag == "PixelData" else tag.split(".")[-1]
    ev, cv, gv = f.eval_value or "", f.candidate_value or "", f.gold_value or ""

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
        "AcquisitionDateTime",
        "AcquisitionContextSequence",
    }
    if leaf in script_leaves:
        if (ev or cv) and not gv:
            return "1 anonymizer script", "script keep vs gold empty"
        if not cv and gv:
            return "1 anonymizer script", "script blank vs gold keep"
        return "1 anonymizer script", "script vs gold mismatch"
    if leaf.endswith("Sequence"):
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
            return "5 NER scrub or 6 residual", "NER over-scrub / residue"
        return "5 NER detect/scrub (miss) or 6 residual", "NER under-scrub / residue"
    if (ev or cv) and not gv:
        return "1 anonymizer script", "script keep vs gold empty"
    if not ev and not cv and gv:
        return "1 anonymizer script", "blanked vs gold keep"
    if not cv and gv:
        return "1 anonymizer script", "script blank vs gold keep"
    return "unknown", "value mismatch"


def _short(v: str, n: int = 36) -> str:
    s = (v or "").replace("\n", " ")
    if not s:
        return "∅"
    return s if len(s) <= n else s[: n - 1]


def write_report(*, hhmm: str, metrics) -> Path:
    out_dir = RESULTS_DIR / hhmm
    out_dir.mkdir(parents=True, exist_ok=True)
    fails = metrics.failures
    by_step: Counter[str] = Counter()
    by_class: Counter[str] = Counter()
    by_step_class: Counter[tuple[str, str]] = Counter()
    by_leaf: Counter[str] = Counter()
    examples: dict[str, tuple[str, str, object]] = {}

    for f in fails:
        step, cls = _classify(f)
        tag = (f.tag_path or "").strip()
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
        f"# PseudoPHI-eval report `{hhmm}`",
        "",
        "**Stack:** 1 anonymizer script → 2 Private KB → 3–5 OpenMed NER → 6 residual cleanup. No OCR.",
        "",
        "| | |",
        "| --- | --- |",
        f"| Files (pairs) | {metrics.pairs} |",
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
        f"| **Total** | **{len(fails)}** |",
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
            f"`{_short(f.eval_value)}` → "
            f"`{_short(f.candidate_value)}` → "
            f"`{_short(f.gold_value)}`"
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
    for name in (
        "anonymizer",
        "anonymizer.controller.anonymizer",
        "anonymizer.model.anonymizer",
        "anonymizer.controller.ai.embedded_phi.ner.engine",
        "pydicom",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("pydicom").setLevel(logging.ERROR)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    hhmm = datetime.now().strftime("%H%M")
    work = RESULTS_DIR / f"_work_{hhmm}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    script = ensure_experiment_script_copy(force=True)
    pairs, unpaired = pair_all()
    logger.info("paired=%d unpaired=%d script=%s", len(pairs), len(unpaired), script)
    if not pairs:
        logger.error("no pairs")
        return 1

    cfg = RunConfig.from_mode("combined", script_path=script, subject_ids=["ALL"])
    cand = work / "candidates"
    result = run_pairs(pairs, cand, cfg)
    metrics = score_pairs(pairs, result.candidate_dir, histogram=result.histogram)
    report = write_report(hhmm=hhmm, metrics=metrics)
    shutil.rmtree(work, ignore_errors=True)
    keep = RESULTS_DIR / hhmm
    for p in keep.iterdir():
        if p.name != "report.md":
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)

    logger.info(
        "report=%s header=%.4f%% fails=%d gate=%s",
        report,
        metrics.header_accuracy,
        len(metrics.failures),
        "PASS" if metrics.header_accuracy >= GATE else "FAIL",
    )
    print(str(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
