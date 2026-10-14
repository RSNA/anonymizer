"""CLI: characterize / run / score / final-report / phase1-baselines."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from prototyping.pseudo_phi_deid.characterize import characterize
from prototyping.pseudo_phi_deid.pairs import pair_all
from prototyping.pseudo_phi_deid.paths import RESULTS_DIR, phase_dir
from prototyping.pseudo_phi_deid.pipeline.clinical import ensure_experiment_script_copy
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig, run_pairs
from prototyping.pseudo_phi_deid.report import (
    upsert_section_12,
    write_final_report,
    write_ner_sample,
    write_scorecard,
)
from prototyping.pseudo_phi_deid.score import score_pairs, write_failures_csv, write_metrics_json

logger = logging.getLogger("pseudo_phi_deid")


def _setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Keep product anonymizer / pydicom noise out of the terminal unless -v.
    if not verbose:
        for name in (
            "anonymizer",
            "anonymizer.controller.anonymizer",
            "anonymizer.model.anonymizer",
            "anonymizer.controller.ai.embedded_phi.ner.engine",
            "pydicom",
        ):
            logging.getLogger(name).setLevel(logging.WARNING)
        logging.getLogger("pydicom").setLevel(logging.ERROR)


def _load_pixel_same() -> dict[str, bool]:
    p = phase_dir(0, "characterize") / "pixel_same_by_sop.json"
    if p.is_file():
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: bool(v) for k, v in raw.items()}
    return {}


def _load_burnin_sops() -> set[str]:
    p = phase_dir(0, "characterize") / "inventory.json"
    if not p.is_file():
        return set()
    inv = json.loads(p.read_text(encoding="utf-8"))
    return set(inv.get("burnin_sops") or [])


def _write_run(
    *,
    phase: int,
    slug: str,
    goal: str,
    changed: str,
    next_step: str,
    config: RunConfig,
    result,
    metrics,
    out: Path | None = None,
) -> Path:
    out = out or phase_dir(phase, slug)
    out.mkdir(parents=True, exist_ok=True)
    cfg = {
        "mode": config.mode,
        "use_script": config.use_script,
        "use_openmed": config.use_openmed,
        "field_wrap": config.field_wrap,
        "caret_space": config.caret_space,
        "subject_ids": config.subject_ids,
        "candidate_dir": str(result.candidate_dir),
        "pixel_modified": result.pixel_modified,
    }
    (out / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    write_metrics_json(out / "metrics.json", metrics)
    write_failures_csv(out / "failures.csv", metrics.failures)
    write_ner_sample(out / "ner_sample.md", result.ner_samples)
    write_scorecard(
        out / "SCORECARD.md",
        title=f"SCORECARD — {out.name}",
        goal=goal,
        changed=changed,
        config=cfg,
        metrics=metrics,
        next_step=next_step,
    )
    # Move candidates under phase dir if not already
    return out


def cmd_characterize(args: argparse.Namespace) -> int:
    ensure_experiment_script_copy()
    inv = characterize(ner_limit=args.ner_limit, patient_ids=args.subjects or None)
    print(json.dumps({k: inv[k] for k in (
        "pairs", "unpaired", "pixel_same", "pixel_diff", "burnin_sop_count",
        "overlay_eval", "overlay_gold_cleared", "ner_files",
    )}, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    pairs, _un = pair_all(patient_ids=args.subjects or None)
    if not pairs:
        logger.error("no pairs")
        return 1
    pixel_same = _load_pixel_same()
    if args.mode == "pixels":
        logger.error("pixels mode removed; plan path is steps 1–6 only (combined)")
        return 1
    cfg = RunConfig.from_mode(
        args.mode,
        subject_ids=args.subjects or ["ALL"],
    )
    out = phase_dir(args.phase, args.slug or args.mode)
    cand = out / "candidates"
    result = run_pairs(pairs, cand, cfg)
    metrics = score_pairs(
        pairs,
        result.candidate_dir,
        pixel_same_by_sop=pixel_same or None,
        histogram=result.histogram,
    )
    _write_run(
        phase=args.phase,
        slug=args.slug or args.mode,
        goal=args.goal or f"mode={args.mode}",
        changed=args.changed or "(see config)",
        next_step=args.next_step or "Review SCORECARD; iterate toward >95%.",
        config=cfg,
        result=result,
        metrics=metrics,
    )
    print(json.dumps({
        "cohort_accuracy": metrics.cohort_accuracy,
        "header_accuracy": metrics.header_accuracy,
        "pixel_accuracy": metrics.pixel_accuracy,
        "overlay_accuracy": metrics.overlay_accuracy,
        "passed_gate": metrics.passed_gate,
        "pairs": metrics.pairs,
    }, indent=2))
    return 0


def cmd_phase1(args: argparse.Namespace) -> int:
    """Run script / openmed / combined baselines on full cohort."""
    ensure_experiment_script_copy()
    pairs, _ = pair_all(patient_ids=args.subjects or None)
    if not pairs:
        logger.error("no pairs")
        return 1
    pixel_same = _load_pixel_same()
    variants = [
        ("1a_script", "script", "Step 1 Clinical script only", "Baseline without NER"),
        ("1b_openmed", "openmed", "Steps 2–6 private KB + NER (no Clinical script)", "NER without script"),
        ("1c_combined", "combined", "Steps 1–6 script + private KB + bulk NER", "Plan path"),
    ]
    summary = []
    for slug, mode, goal, changed in variants:
        logger.info("=== phase1 %s ===", slug)
        cfg = RunConfig.from_mode(
            mode,
            subject_ids=args.subjects or ["ALL"],
        )
        out = phase_dir(1, slug)
        result = run_pairs(pairs, out / "candidates", cfg)
        metrics = score_pairs(
            pairs,
            result.candidate_dir,
            pixel_same_by_sop=pixel_same or None,
            histogram=result.histogram,
        )
        _write_run(
            phase=1,
            slug=slug,
            goal=goal,
            changed=changed,
            next_step="Compare accuracies; adapt taxonomy/script toward >95%.",
            config=cfg,
            result=result,
            metrics=metrics,
        )
        summary.append({
            "slug": slug,
            "mode": mode,
            "cohort_accuracy": metrics.cohort_accuracy,
            "header_accuracy": metrics.header_accuracy,
            "pixel_accuracy": metrics.pixel_accuracy,
            "overlay_accuracy": metrics.overlay_accuracy,
            "passed_gate": metrics.passed_gate,
        })
    rollup = phase_dir(1, "baselines")
    rollup.mkdir(parents=True, exist_ok=True)
    (rollup / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (rollup / "config.json").write_text(json.dumps({"variants": [s["slug"] for s in summary]}, indent=2), encoding="utf-8")
    lines = [
        "# SCORECARD — phase_1_baselines",
        "",
        "**Goal:** Full-cohort baselines for script / OpenMed / combined.",
        "",
        "| slug | mode | cohort % | header % | pixel % | overlay % | gate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in summary:
        lines.append(
            f"| {s['slug']} | {s['mode']} | {s['cohort_accuracy']} | {s['header_accuracy']} | "
            f"{s['pixel_accuracy']} | {s['overlay_accuracy']} | "
            f"{'PASS' if s['passed_gate'] else 'FAIL'} |"
        )
    lines += ["", "## Next step", "", "Phase 2: lock taxonomy + adapt clinical script from failure clusters.", ""]
    (rollup / "SCORECARD.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def cmd_phase2(args: argparse.Namespace) -> int:
    """Re-run combined with locked taxonomy; optionally note script path."""
    from prototyping.pseudo_phi_deid.taxonomy import ACTIONS, lock_taxonomy_from_histogram

    inv = phase_dir(0, "characterize") / "inventory.json"
    if inv.is_file():
        hist = json.loads(inv.read_text(encoding="utf-8")).get("ner_histogram") or {}
        lock_taxonomy_from_histogram(hist)
        logger.info("locked taxonomy %d labels", len(ACTIONS))
    # Re-run combined as phase 2
    args.mode = "combined"
    args.phase = 2
    args.slug = "taxonomy_combined"
    args.goal = "Combined with taxonomy locked from Phase 0"
    args.changed = "ACTIONS locked; clinical script experiment copy in use"
    args.next_step = "If header failures cluster on script tags, patch scripts/clinical-anonymizer.script"
    args.pixels_all = False
    return cmd_run(args)


def cmd_phase3(args: argparse.Namespace) -> int:
    """Pixel-focused combined run (burn-in SOPs + overlay awareness)."""
    args.mode = "combined"
    args.phase = 3
    args.slug = "pixels_integrated"
    args.goal = "EasyOCR+OpenMed pixels on burn-in SOPs + script + metadata NER"
    args.changed = "Pixel path integrated for Phase-0 burn-in set"
    args.next_step = "Freeze if ≥95%; else iterate script/taxonomy"
    args.pixels_all = False
    return cmd_run(args)


def cmd_phase4(_args: argparse.Namespace) -> int:
    """Freeze: re-run best combined + FINAL_REPORT."""
    ns = argparse.Namespace(
        mode="combined",
        phase=4,
        slug="full_cohort",
        goal="Frozen generalizable pipeline — full Evaluation cohort",
        changed="Final freeze of core + OpenMed + EasyOCR",
        next_step="Promote successful script/taxonomy into product if gates pass",
        subjects=None,
        pixels_all=False,
    )
    rc = cmd_run(ns)
    path = write_final_report()
    print(path)
    return rc


def cmd_final_report(_args: argparse.Namespace) -> int:
    path = write_final_report()
    upsert_section_12()
    print(path)
    return 0


def _sync_tcia_clinical_script() -> Path:
    """Copy packaged clinical-anonymizer.script into the experiment scripts dir."""
    return ensure_experiment_script_copy(force=True)


PSEUDO_PHI_EVAL = "PseudoPHI-eval"
PSEUDO_PHI_NER = "PseudoPHI-ner"


def cmd_pseudo_phi_ner(args: argparse.Namespace) -> int:
    """Legacy: steps 2–6 only (no Clinical script). Prefer PseudoPHI-eval."""
    pairs, _ = pair_all(patient_ids=args.subjects or None)
    if not pairs:
        logger.error("no pairs")
        return 1
    pixel_same = _load_pixel_same()
    out = RESULTS_DIR / PSEUDO_PHI_NER
    cfg = RunConfig.from_mode(
        "ner_only",
        subject_ids=args.subjects or ["ALL"],
    )
    logger.info("=== %s (steps 2–6 only; no Clinical script) ===", PSEUDO_PHI_NER)
    cand = out / "candidates"
    result = run_pairs(pairs, cand, cfg)
    metrics = score_pairs(
        pairs,
        result.candidate_dir,
        pixel_same_by_sop=pixel_same or None,
        histogram=result.histogram,
    )
    _write_run(
        phase=0,
        slug=PSEUDO_PHI_NER,
        goal="Steps 2–6: private KB + bulk NER (no Clinical script)",
        changed="PseudoPHI-ner: no step 1 script",
        next_step="Use PseudoPHI-eval for plan path (steps 1–6).",
        config=cfg,
        result=result,
        metrics=metrics,
        out=out,
    )
    if cand.is_dir():
        import shutil

        shutil.rmtree(cand, ignore_errors=True)
    summary = [
        {
            "slug": PSEUDO_PHI_NER,
            "cohort_accuracy": metrics.cohort_accuracy,
            "header_accuracy": metrics.header_accuracy,
            "pixel_accuracy": metrics.pixel_accuracy,
            "overlay_accuracy": metrics.overlay_accuracy,
            "failure_count": len(metrics.failures),
            "passed_gate": metrics.passed_gate,
        }
    ]
    logger.info(
        "%s cohort=%.4f fails=%d gate=%s",
        PSEUDO_PHI_NER,
        metrics.cohort_accuracy,
        len(metrics.failures),
        metrics.passed_gate,
    )
    (out / "rollup.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_final_report()
    _append_tcia_report_section(summary, section_title=f"11. {PSEUDO_PHI_NER}")
    upsert_section_12()
    print(json.dumps({"summary": summary}, indent=2))
    return 0


def cmd_pseudo_phi_eval(args: argparse.Namespace) -> int:
    """Score combined (clinical script + private KB + bulk NER)."""
    script = _sync_tcia_clinical_script()
    logger.info("Clinical script: %s (%d bytes)", script, script.stat().st_size)

    pairs, _ = pair_all(patient_ids=args.subjects or None)
    if not pairs:
        logger.error("no pairs")
        return 1
    pixel_same = _load_pixel_same()

    out = RESULTS_DIR / PSEUDO_PHI_EVAL
    cfg = RunConfig.from_mode(
        "combined",
        script_path=script,
        subject_ids=args.subjects or ["ALL"],
    )
    goal = "TCIA Clinical script + private KB + bulk NER (no pixels/regex)"
    changed = "PseudoPHI-eval: script + process_private_tags_tcia + OpenMed bulk NER"

    logger.info("=== %s ===", PSEUDO_PHI_EVAL)
    cand = out / "candidates"
    result = run_pairs(pairs, cand, cfg)
    metrics = score_pairs(
        pairs,
        result.candidate_dir,
        pixel_same_by_sop=pixel_same or None,
        histogram=result.histogram,
    )
    _write_run(
        phase=0,
        slug=PSEUDO_PHI_EVAL,
        goal=goal,
        changed=changed,
        next_step="Compare failure clusters vs phase_4; update FINAL_REPORT.",
        config=cfg,
        result=result,
        metrics=metrics,
        out=out,
    )
    if cand.is_dir():
        import shutil

        shutil.rmtree(cand, ignore_errors=True)
    summary = [
        {
            "slug": PSEUDO_PHI_EVAL,
            "cohort_accuracy": metrics.cohort_accuracy,
            "header_accuracy": metrics.header_accuracy,
            "pixel_accuracy": metrics.pixel_accuracy,
            "overlay_accuracy": metrics.overlay_accuracy,
            "failure_count": len(metrics.failures),
            "passed_gate": metrics.passed_gate,
        }
    ]
    logger.info(
        "%s cohort=%.4f fails=%d gate=%s",
        PSEUDO_PHI_EVAL,
        metrics.cohort_accuracy,
        len(metrics.failures),
        metrics.passed_gate,
    )

    (out / "rollup.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report = write_final_report()
    _append_tcia_report_section(summary)
    upsert_section_12()
    print(json.dumps({"summary": summary, "report": str(report)}, indent=2))
    return 0


def _append_tcia_report_section(
    summary: list[dict],
    *,
    section_title: str | None = None,
) -> None:
    """Extend FINAL_REPORT with eval results + concrete failure values."""
    import csv
    import re
    from collections import defaultdict

    report_path = RESULTS_DIR / "FINAL_REPORT.md"
    if not report_path.is_file():
        return

    slug = (summary[0].get("slug") if summary else "") or PSEUDO_PHI_EVAL
    title = section_title or f"10. {PSEUDO_PHI_EVAL}"
    fail_csv = RESULTS_DIR / slug / "failures.csv"
    if not fail_csv.is_file() and slug == PSEUDO_PHI_EVAL:
        fail_csv = phase_dir(5, "tcia_combined") / "failures.csv"
    if not fail_csv.is_file() and slug == PSEUDO_PHI_EVAL:
        fail_csv = phase_dir(5, "tcia_script") / "failures.csv"

    blurb = (
        "Identity + DATEINC + OpenMed NER + EasyOCR; no clinical @remove / keyword wipe."
        if slug == PSEUDO_PHI_NER
        else (
            "TCIA clinical script + OpenMed blank + EasyOCR on burn-in SOPs "
            "(recompiled from Table 1 / Private Tag KB)."
        )
    )
    lines = [
        "",
        f"## {title}",
        "",
        blurb,
        "",
        "| slug | cohort % | header % | pixel % | overlay % | failure rows | gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for s in summary:
        lines.append(
            f"| {s['slug']} | {s['cohort_accuracy']} | {s['header_accuracy']} | "
            f"{s['pixel_accuracy']} | {s['overlay_accuracy']} | {s['failure_count']} | "
            f"{'PASS' if s['passed_gate'] else 'FAIL'} |"
        )

    for s in summary:
        gate_note = (
            "meets the experiment pass rule (cohort accuracy > 95%)"
            if s["passed_gate"]
            else "does not meet the experiment pass rule (cohort accuracy must exceed 95%)"
        )
        lines += [
            "",
            f"**Accuracy gate:** {s['cohort_accuracy']}% {gate_note}. "
            "The gate is a single yes/no on overall cohort accuracy vs DeIdentified gold "
            "(UIDs excluded); it is not a count of failure rows.",
        ]

    if fail_csv.is_file():
        rows = list(csv.DictReader(fail_csv.open(encoding="utf-8")))
        lines += [
            "",
            f"### Where the {len(rows)} failure rows go",
            "",
            "Each row is one comparable field (or pixel check) that differs from gold. "
            "The table below accounts for **all** rows. Example snippets afterward "
            "only illustrate the largest clusters.",
            "",
            "| Cluster | Rows | Share |",
            "| --- | ---: | ---: |",
        ]

        def leaf(tp: str) -> str:
            return re.sub(r"\[\d+\]", "", tp)

        by: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            if r["kind"] == "pixel_mismatch":
                by["pixel"].append(r)
                continue
            tp = leaf(r["tag_path"])
            name = tp.split(".")[-1]
            if tp.startswith("("):
                by["private"].append(r)
            elif "Date" in name or "DateTime" in name or name.endswith("Time"):
                by["public_dates"].append(r)
            else:
                by[name].append(r)

        # Named buckets first, then remaining tags by size; always sum to len(rows).
        preferred = [
            ("private", "Private tags"),
            ("public_dates", "Public dates"),
            ("CodeMeaning", "CodeMeaning (coded sequences removed by Table 1)"),
            ("CodeValue", "CodeValue (same coded sequences)"),
            ("CodingSchemeDesignator", "CodingSchemeDesignator (same)"),
            ("Occupation", "Occupation"),
            ("StudyDescription", "StudyDescription"),
            ("SeriesDescription", "SeriesDescription"),
            ("DeviceSerialNumber", "DeviceSerialNumber"),
            ("StudyID", "StudyID"),
            ("pixel", "Pixel / OCR"),
        ]
        preferred_keys = {k for k, _ in preferred}
        # Collapse PET isotope / reconstruction public tags into one rollup.
        pet_like = {
            k
            for k in by
            if k
            not in preferred_keys
            and (
                k
                in {
                    "AxialMash",
                    "CoincidenceWindowWidth",
                    "CountsSource",
                    "DecayCorrection",
                    "DecayFactor",
                    "DoseCalibrationFactor",
                    "EnergyWindowLowerLimit",
                    "EnergyWindowUpperLimit",
                    "ImageIndex",
                    "NumberOfSlices",
                    "RadionuclideHalfLife",
                    "RadionuclidePositronFraction",
                    "RadionuclideTotalDose",
                    "Radiopharmaceutical",
                    "RadiopharmaceuticalVolume",
                    "RandomsCorrectionMethod",
                    "ReconstructionMethod",
                    "ScatterCorrectionMethod",
                    "SeriesType",
                    "SliceSensitivityFactor",
                    "TransverseMash",
                    "TypeOfDetectorMotion",
                    "Units",
                    "AttenuationCorrectionMethod",
                    "ScatterFractionFactor",
                    "NumberOfTimeSlices",
                    "PrimaryPromptsCountsAccumulated",
                    "DeadTimeFactor",
                    "DetectorLinesOfResponseUsed",
                    "SecondaryCountsAccumulated",
                }
            )
        }
        pet_rows: list[dict] = []
        for k in pet_like:
            pet_rows.extend(by.pop(k))
        if pet_rows:
            by["pet_public"] = pet_rows

        inventory: list[tuple[str, str, list[dict]]] = []
        for key, title in preferred:
            if key in by:
                inventory.append((key, title, by.pop(key)))
        if "pet_public" in by:
            inventory.append(
                (
                    "pet_public",
                    "PET / NM public attributes (gold keeps; Clinical removes)",
                    by.pop("pet_public"),
                )
            )
        for key, group in sorted(by.items(), key=lambda kv: -len(kv[1])):
            inventory.append((key, key, group))

        accounted = 0
        for _key, title, group in inventory:
            n = len(group)
            accounted += n
            pct = 100.0 * n / len(rows) if rows else 0.0
            lines.append(f"| {title} | {n} | {pct:.1f}% |")
        lines += [
            f"| **Total** | **{accounted}** | **100%** |",
            "",
            "### Example mismatches (largest clusters only)",
            "",
        ]

        # Detailed examples for top clusters by row count.
        for key, title, group in sorted(inventory, key=lambda x: -len(x[2]))[:8]:
            if not group:
                continue
            lines += [
                f"#### {title} — {len(group)}",
                "",
                "| Tag | Candidate | Gold | Patient |",
                "| --- | --- | --- | --- |",
            ]
            seen: set[tuple[str, str, str]] = set()
            shown = 0
            for r in group:
                key3 = (r["tag_path"], r["candidate_value"][:60], r["gold_value"][:60])
                if key3 in seen:
                    continue
                seen.add(key3)
                cand = r["candidate_value"] or "*(empty)*"
                gold = r["gold_value"] or "*(empty)*"
                if len(cand) > 48:
                    cand = cand[:45] + "…"
                if len(gold) > 48:
                    gold = gold[:45] + "…"
                lines.append(
                    f"| `{r['tag_path']}` | `{cand}` | `{gold}` | `{r['eval_patient_id']}` |"
                )
                shown += 1
                if shown >= 3:
                    break
            lines.append("")

    text = report_path.read_text(encoding="utf-8")
    marker = f"## {title}"
    # Also replace legacy headings for the same eval slug.
    candidates = [marker]
    if slug == PSEUDO_PHI_EVAL:
        candidates.extend(
            (f"## 10. {PSEUDO_PHI_EVAL}", "## 10. TCIA-2024 clinical policy re-eval")
        )
    if slug == PSEUDO_PHI_NER:
        candidates.append(f"## 11. {PSEUDO_PHI_NER}")

    def _drop_section(body: str, heading: str) -> str:
        if heading not in body:
            return body
        before, _, after = body.partition(heading)
        nxt = after.find("\n## ")
        if nxt >= 0:
            return before.rstrip() + "\n" + after[nxt + 1 :]
        return before.rstrip() + "\n"

    for heading in candidates:
        text = _drop_section(text, heading)
    report_path.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def cmd_score(args: argparse.Namespace) -> int:
    pairs, _ = pair_all(patient_ids=args.subjects or None)
    metrics = score_pairs(
        pairs,
        Path(args.candidate_dir),
        pixel_same_by_sop=_load_pixel_same() or None,
    )
    out = Path(args.out) if args.out else RESULTS_DIR / "score_adhoc"
    out.mkdir(parents=True, exist_ok=True)
    write_metrics_json(out / "metrics.json", metrics)
    write_failures_csv(out / "failures.csv", metrics.failures)
    print(json.dumps({"cohort_accuracy": metrics.cohort_accuracy, "passed_gate": metrics.passed_gate}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pseudo_phi_deid")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("characterize", help="Phase 0 full Evaluation inventory")
    c.add_argument("--ner-limit", type=int, default=None, help="Cap OpenMed files (default all)")
    c.add_argument("--subjects", nargs="*", default=None)
    c.set_defaults(func=cmd_characterize)

    r = sub.add_parser("run", help="Run one mode and score")
    r.add_argument(
        "--mode",
        choices=["script", "openmed", "pixels", "combined", "ner_only"],
        required=True,
    )
    r.add_argument("--phase", type=int, default=1)
    r.add_argument("--slug", default="")
    r.add_argument("--subjects", nargs="*", default=None)
    r.add_argument("--pixels-all", action="store_true")
    r.add_argument("--goal", default="")
    r.add_argument("--changed", default="")
    r.add_argument("--next-step", default="")
    r.set_defaults(func=cmd_run)

    p1 = sub.add_parser("phase1-baselines", help="Script / OpenMed / combined baselines")
    p1.add_argument("--subjects", nargs="*", default=None)
    p1.set_defaults(func=cmd_phase1)

    p2 = sub.add_parser("phase2-taxonomy", help="Lock taxonomy and re-run combined")
    p2.add_argument("--subjects", nargs="*", default=None)
    p2.set_defaults(func=cmd_phase2)

    p3 = sub.add_parser("phase3-pixels", help="Pixel-integrated combined run")
    p3.add_argument("--subjects", nargs="*", default=None)
    p3.set_defaults(func=cmd_phase3)

    p4 = sub.add_parser("phase4-freeze", help="Full cohort freeze + FINAL_REPORT")
    p4.set_defaults(func=cmd_phase4)

    p5 = sub.add_parser(
        PSEUDO_PHI_EVAL,
        help="Compile TCIA clinical script; score script+private KB+bulk NER (no pixels)",
    )
    p5.add_argument("--subjects", nargs="*", default=None)
    p5.set_defaults(func=cmd_pseudo_phi_eval)

    ner = sub.add_parser(
        "PseudoPHI-ner",
        help="No clinical @remove: identity+DATEINC + OpenMed NER + EasyOCR (no keyword wipe)",
    )
    ner.add_argument("--subjects", nargs="*", default=None)
    ner.set_defaults(func=cmd_pseudo_phi_ner)

    fr = sub.add_parser("final-report", help="Assemble FINAL_REPORT.md")
    fr.set_defaults(func=cmd_final_report)

    sc = sub.add_parser("score", help="Score existing candidates")
    sc.add_argument("--candidate-dir", required=True)
    sc.add_argument("--subjects", nargs="*", default=None)
    sc.add_argument("--out", default="")
    sc.set_defaults(func=cmd_score)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
