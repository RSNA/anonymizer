"""Helpers to drive MIDI-B validate/score from pytest."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from prototyping.midi_b.cli import cmd_validate
from prototyping.midi_b.taxonomy import build_adversarial_taxonomy, write_adversarial_taxonomy
from tests.prototyping.midi_b.support import SMOKE5_PATIENT_IDS


def env_run_dir() -> Path | None:
    """Optional existing scored run from MIDI_B_RUN_DIR."""
    raw = os.environ.get("MIDI_B_RUN_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_dir() else None


def run_smoke5_validate(*, slug: str = "pytest_smoke5") -> Path:
    """
    Run validate (de-id + official score) for SMOKE5 patients.

    Returns:
        Harness run directory path.
    """
    patients = ",".join(SMOKE5_PATIENT_IDS)
    args = argparse.Namespace(
        split="validation",
        synthetic_root=None,
        patients=patients,
        limit=None,
        runs_root=None,
        mode="combined",
        script=None,
        slug=slug,
        out=None,
        answer_db=None,
        multiprocessing=False,
        cpus=4,
        no_reports=False,
        verbose=False,
        run_dir=None,
    )
    rc = cmd_validate(args)
    if rc != 0:
        raise RuntimeError(f"midi_b validate failed with rc={rc}")
    run_dir = Path(args.run_dir or args.out)
    if not run_dir.is_dir():
        raise RuntimeError(f"validate did not set run_dir: {run_dir}")
    # Ensure taxonomy exists even if score hook failed soft.
    write_adversarial_taxonomy(run_dir)
    return run_dir


def resolve_scored_run(*, prefer_smoke: bool = True) -> Path:
    """
    Prefer MIDI_B_RUN_DIR; otherwise run smoke5 validate.

    Args:
        prefer_smoke: Unused placeholder for future inventory of harness-runs.

    Returns:
        Path to a scored harness run directory.
    """
    del prefer_smoke
    existing = env_run_dir()
    if existing is not None:
        db = existing / "official_score" / "midi_b" / "validation_results.db"
        if db.is_file():
            tax = existing / "adversarial_taxonomy.json"
            if not tax.is_file():
                write_adversarial_taxonomy(existing)
            return existing
    return run_smoke5_validate()


def taxonomy_for(run_dir: Path) -> dict:
    """Load or build adversarial taxonomy for run_dir."""
    return build_adversarial_taxonomy(run_dir)
