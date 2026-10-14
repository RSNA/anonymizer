"""CLI: inventory / run / score MIDI-B Validation (and Test)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from prototyping.midi_b.inventory import list_instances, write_inventory
from prototyping.midi_b.mappings import filter_answer_db
from prototyping.midi_b.paths import RESULTS_DIR, run_dir, split_paths
from prototyping.midi_b.pipeline import run_instances
from prototyping.midi_b.report import write_score_report
from prototyping.midi_b.score_official import (
    copy_score_summary,
    run_validation,
    write_config,
)
from prototyping.pseudo_phi_deid.pipeline.clinical import ensure_experiment_script_copy
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig

logger = logging.getLogger("midi_b")


def _setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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


def _parse_patients(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def cmd_inventory(args: argparse.Namespace) -> int:
    synthetic, _, _ = split_paths(args.split)
    if args.synthetic_root:
        synthetic = Path(args.synthetic_root)
    patients = _parse_patients(args.patients)
    instances = list_instances(
        synthetic, patient_ids=patients, limit=args.limit
    )
    out = Path(args.out) if args.out else RESULTS_DIR / f"{args.split}_inventory.json"
    summary = write_inventory(instances, out)
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


def _resolve_run_out(args: argparse.Namespace) -> Path:
    if args.out:
        return Path(args.out)
    runs_root = Path(args.runs_root) if getattr(args, "runs_root", None) else None
    out = run_dir(args.split, getattr(args, "slug", None), runs_root=runs_root)
    # Convenience symlink under package results/ → external run dir.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    link = RESULTS_DIR / out.name
    try:
        if link.is_symlink() or not link.exists():
            link.unlink(missing_ok=True)
            link.symlink_to(out)
    except OSError:
        logger.debug("could not symlink %s → %s", link, out, exc_info=True)
    return out


def cmd_run(args: argparse.Namespace) -> int:
    synthetic, answer_db, _ = split_paths(args.split)
    if args.synthetic_root:
        synthetic = Path(args.synthetic_root)
    patients = _parse_patients(args.patients)
    ensure_experiment_script_copy()

    instances = list_instances(
        synthetic, patient_ids=patients, limit=args.limit
    )
    if not instances:
        logger.error("no instances found under %s", synthetic)
        return 1

    out = _resolve_run_out(args)
    out.mkdir(parents=True, exist_ok=True)
    write_inventory(instances, out / "inventory.json")

    config = RunConfig.from_mode(
        args.mode,
        script_path=Path(args.script) if args.script else None,
    )
    result = run_instances(instances, out, config)
    logger.info(
        "candidates=%s uids=%s patids=%s n=%d",
        result.candidate_dir,
        result.uid_mapping,
        result.patid_mapping,
        result.n_instances,
    )

    # Filtered answer key when scoring a patient subset (avoids mass missing-file fails).
    if answer_db and answer_db.is_file() and patients:
        filter_answer_db(
            answer_db,
            out / "answer_key_filtered.db",
            patient_ids=patients,
        )

    args.run_dir = str(out)
    print(str(out))
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    run_path = Path(args.run_dir)
    cfg_path = run_path / "config.json"
    if not cfg_path.is_file():
        logger.error("missing %s — run first", cfg_path)
        return 1
    run_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    candidate_dir = Path(run_cfg["candidate_dir"])
    uid_mapping = Path(run_cfg["uid_mapping"])
    patid_mapping = Path(run_cfg["patid_mapping"])

    _, default_answer, _ = split_paths(args.split)
    answer_db = Path(args.answer_db) if args.answer_db else None
    if answer_db is None:
        filtered = run_path / "answer_key_filtered.db"
        if filtered.is_file():
            answer_db = filtered
        elif default_answer is not None:
            answer_db = default_answer
    if answer_db is None or not answer_db.is_file():
        logger.error("no answer key DB (Validation only); pass --answer-db")
        return 1

    official_out = run_path / "official_score"
    config_path = write_config(
        run_name="midi_b",
        input_data_path=candidate_dir,
        output_data_path=official_out,
        answer_db_file=answer_db,
        uid_mapping_file=uid_mapping,
        patid_mapping_file=patid_mapping,
        config_path=run_path / "official_config.json",
        multiprocessing=args.multiprocessing,
        multiprocessing_cpus=args.cpus,
    )
    score_dir = run_validation(config_path, reports=not args.no_reports)
    summary_path = copy_score_summary(score_dir, run_path / "official_summary.json")
    try:
        report_path = write_score_report(run_path, title=f"SCORECARD — {run_path.name}")
        logger.info("scorecard → %s", report_path)
        print(str(report_path))
    except Exception:
        logger.exception("scorecard generation failed")
        print(str(summary_path))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Run + official score in one shot (Validation split)."""
    # Fix output path before run so score uses the same directory.
    args.out = str(_resolve_run_out(args))
    rc = cmd_run(args)
    if rc != 0:
        return rc
    if not getattr(args, "run_dir", None):
        args.run_dir = args.out
    return cmd_score(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m prototyping.midi_b",
        description="MIDI-B harness (Clinical + private KB + NER → official scorer)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_split(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--split",
            default="validation",
            choices=("validation", "test"),
            help="dataset split (default: validation)",
        )
        sp.add_argument("--synthetic-root", type=str, default=None)
        sp.add_argument(
            "--patients",
            type=str,
            default=None,
            help="comma-separated Synthetic PatientIDs (smoke / subset)",
        )
        sp.add_argument("--limit", type=int, default=None, help="max instances")
        sp.add_argument(
            "--runs-root",
            type=str,
            default=None,
            help="root for timestamped runs (default: …/TCIA/MIDI-B/harness-runs)",
        )

    inv = sub.add_parser("inventory", help="list Synthetic instances")
    add_split(inv)
    inv.add_argument("--out", type=str, default=None)
    inv.set_defaults(func=cmd_inventory)

    run_p = sub.add_parser("run", help="de-id Synthetic → candidates + mappings")
    add_split(run_p)
    run_p.add_argument(
        "--mode",
        default="combined",
        choices=("combined", "script", "openmed", "ner_only"),
    )
    run_p.add_argument("--script", type=str, default=None)
    run_p.add_argument(
        "--slug",
        type=str,
        default=None,
        help="optional label appended after UTC stamp (e.g. ner_v2)",
    )
    run_p.add_argument("--out", type=str, default=None, help="override full run path")
    run_p.set_defaults(func=cmd_run)

    score_p = sub.add_parser("score", help="official MIDI_validation_script")
    score_p.add_argument("run_dir", type=str, help="path from `run`")
    score_p.add_argument("--split", default="validation", choices=("validation", "test"))
    score_p.add_argument("--answer-db", type=str, default=None)
    score_p.add_argument("--multiprocessing", action="store_true")
    score_p.add_argument("--cpus", type=int, default=4)
    score_p.add_argument("--no-reports", action="store_true")
    score_p.set_defaults(func=cmd_score)

    val = sub.add_parser("validate", help="run + official score (Validation)")
    add_split(val)
    val.add_argument("--mode", default="combined", choices=("combined", "script", "openmed"))
    val.add_argument("--script", type=str, default=None)
    val.add_argument(
        "--slug",
        type=str,
        default=None,
        help="optional label appended after UTC stamp (e.g. ner_v2)",
    )
    val.add_argument("--out", type=str, default=None, help="override full run path")
    val.add_argument("--answer-db", type=str, default=None)
    val.add_argument("--multiprocessing", action="store_true")
    val.add_argument("--cpus", type=int, default=4)
    val.add_argument("--no-reports", action="store_true")
    val.set_defaults(func=cmd_validate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup(args.verbose)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
