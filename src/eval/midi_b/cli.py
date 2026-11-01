"""CLI: validate / test / score MIDI-B via product headless subprocesses."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from eval.midi_b.answer_filter import filter_answer_db
from eval.midi_b.inventory import stage_import_subset
from eval.midi_b.paths import DEFAULT_HARNESS_RUNS, new_run_dir, split_paths
from eval.midi_b.project_prep import prepare_project_dir
from eval.midi_b.report import write_score_report
from eval.midi_b.score_official import (
    copy_score_summary,
    run_validation,
    write_config,
)

logger = logging.getLogger("eval.midi_b")


def _setup(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _parse_patients(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def _rsna_anonymizer_cmd() -> list[str]:
    """Prefer installed console script; fall back to python -m."""
    exe = shutil.which("rsna-anonymizer")
    if exe:
        return [exe]
    return [sys.executable, "-m", "anonymizer.anonymizer"]


def _run(cmd: list[str]) -> None:
    logger.info("exec: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _resolve_images_dir(project_dir: Path, mappings_dir: Path) -> Path:
    manifest = mappings_dir / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        images = Path(data["images_dir"])
        if images.is_dir():
            return images
    public = project_dir / "public"
    if public.is_dir():
        return public
    raise FileNotFoundError(f"anonymized images not found under {project_dir}")


def cmd_score(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    write_score_report(run_dir)
    print(f"wrote {run_dir / 'SCORECARD.md'}", file=sys.stderr)
    return 0


def _dump_batch_errors(project_dir: Path) -> list[str]:
    """Return per-series failure lines from private/batch_runs logs (empty if none).

    Matches workflow "Failed:" sublines and any logger-style ERROR / Clean
    Descriptors failure text copied into the batch run log. Callers always log
    these; with a non-zero batch exit they allow scoring to continue.
    """
    runs = project_dir / "private" / "batch_runs"
    if not runs.is_dir():
        return []
    out: list[str] = []
    for path in sorted(runs.glob("*.log")):
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            out.append(f"{path.name}: could not read ({exc})")
            continue
        for line in body.splitlines():
            if (
                "Failed:" in line
                or " ERROR " in line
                or "Clean Descriptors failed" in line
            ):
                out.append(f"{path.name}: {line}")
    return out


def _abort_after_ai_batch(*, batch_rc: int, series_error_lines: list[str]) -> bool:
    """
    True when the harness must stop before official scoring.

    Per-series outliers (Planar Configuration missing, SR slot mismatch, …)
    leave Failed: lines in the batch log and a non-zero batch exit. Those must
    not abort the full validate/test run. Abort only when the process failed
    with no series-level error lines (config error, cancel, hard crash).

    Args:
        batch_rc: Exit code from rsna-anonymizer --ai-batch-run.
        series_error_lines: Lines from _dump_batch_errors.

    Returns:
        True to abort; False to continue to scoring.
    """
    if batch_rc == 0:
        return False
    return not series_error_lines


def _run_split(args: argparse.Namespace, *, split: str) -> int:
    """Run one MIDI-B split; on any exception dump traceback and return 1."""
    try:
        return _run_split_body(args, split=split)
    except Exception as exc:
        logger.error("MIDI-B eval aborted: %s", exc)
        logger.exception("MIDI-B eval traceback")
        return 1


def _run_split_body(args: argparse.Namespace, *, split: str) -> int:
    synthetic, answer_db = split_paths(split)
    if args.synthetic_root:
        synthetic = Path(args.synthetic_root)
    if args.answer_key:
        answer_db = Path(args.answer_key)

    patients = _parse_patients(args.patients)
    run_dir = new_run_dir(
        split=split,
        slug=args.slug,
        root=Path(args.harness_root) if args.harness_root else DEFAULT_HARNESS_RUNS,
    )
    logger.info("run_dir=%s", run_dir)

    project_json, project_dir = prepare_project_dir(run_dir)
    import_root = synthetic
    if patients:
        staged = run_dir / "import_subset"
        import_root = stage_import_subset(
            synthetic,
            staged,
            patient_ids=patients,
        )

    anon = _rsna_anonymizer_cmd()
    mappings_dir = run_dir / "mappings"
    mappings_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1 — ingest
    _run(
        [
            *anon,
            "-c",
            str(project_json),
            "--import-dir",
            str(import_root),
            "--export-mappings",
            str(mappings_dir),
        ]
    )

    # Phase 2 — AI batch (optional skip). Series-level Failed:/ERROR lines are
    # always logged. Non-zero exit with those lines (partial series failure)
    # continues to scoring. Non-zero exit with no series log lines aborts
    # (config error, cancel, crash before/without per-series outcomes).
    batch_cfg = run_dir / "AiBatchConfig.json"
    if not args.skip_ai_batch and batch_cfg.is_file():
        batch_cmd = [
            *anon,
            "-c",
            str(project_json),
            "--ai-batch",
            str(batch_cfg),
            "--ai-batch-run",
            "--export-mappings",
            str(mappings_dir),
        ]
        logger.info("exec: %s", " ".join(batch_cmd))
        batch_rc = subprocess.run(batch_cmd, check=False).returncode
        error_lines = _dump_batch_errors(project_dir)
        for line in error_lines:
            logger.error("%s", line)
            print(line, file=sys.stderr)
        if _abort_after_ai_batch(
            batch_rc=batch_rc, series_error_lines=error_lines
        ):
            raise RuntimeError(f"AI batch process failed (exit={batch_rc})")
        if batch_rc != 0 and error_lines:
            logger.warning(
                "AI batch exit=%s with %d series-level error line(s); continuing to score",
                batch_rc,
                len(error_lines),
            )
    elif not batch_cfg.is_file():
        logger.warning("AiBatchConfig.json missing; skipping AI batch phase")

    images_dir = _resolve_images_dir(project_dir, mappings_dir)
    uid_csv = mappings_dir / "uid_mapping.csv"
    patid_csv = mappings_dir / "patid_mapping.csv"

    if answer_db is None:
        logger.info("test split: no answer key; import + AI batch complete at %s", run_dir)
        (run_dir / "config.json").write_text(
            json.dumps(
                {
                    "split": split,
                    "images_dir": str(images_dir),
                    "mappings": str(mappings_dir),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0

    score_answer = answer_db
    if patients:
        filtered = run_dir / "answer_key_filtered.db"
        n = filter_answer_db(answer_db, filtered, patient_ids=patients)
        logger.info("filtered answer key rows=%d → %s", n, filtered)
        score_answer = filtered

    official_out = run_dir / "official_score"
    config_path = run_dir / "official_config.json"
    # Stable CBIIT subfolder name (same as prototyping) so SCORECARD finds the DB.
    write_config(
        run_name="midi_b",
        input_data_path=images_dir,
        output_data_path=official_out,
        answer_db_file=score_answer,
        uid_mapping_file=uid_csv,
        patid_mapping_file=patid_csv,
        config_path=config_path,
        multiprocessing=bool(args.multiprocessing),
    )
    run_validation(config_path, reports=not args.no_reports)
    copy_score_summary(run_dir, official_out / "midi_b")
    scorecard = write_score_report(run_dir)
    print(f"wrote {scorecard}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MIDI-B eval via product headless import + AI batch + CBIIT score",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def add_run_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--patients", help="Comma-separated patient folder IDs for smoke")
        sp.add_argument("--slug", default=None, help="Label appended to run directory name")
        sp.add_argument("--synthetic-root", default=None, help="Override synthetic DICOM root")
        sp.add_argument("--answer-key", default=None, help="Override answer-key DB (validation)")
        sp.add_argument("--harness-root", default=None, help="Override harness-runs parent")
        sp.add_argument("--skip-ai-batch", action="store_true")
        sp.add_argument("--multiprocessing", action="store_true")
        sp.add_argument("--no-reports", action="store_true")

    val = sub.add_parser("validate", help="Synthetic Validation import + score")
    add_run_flags(val)
    val.set_defaults(func=lambda a: _run_split(a, split="validation"))

    test = sub.add_parser("test", help="Synthetic Test import (+ AI batch)")
    add_run_flags(test)
    test.set_defaults(func=lambda a: _run_split(a, split="test"))

    score = sub.add_parser("score", help="Rebuild SCORECARD.md for an existing run dir")
    score.add_argument("run_dir", type=str)
    score.set_defaults(func=cmd_score)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup(bool(args.verbose))
    return int(args.func(args))
