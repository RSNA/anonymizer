"""Taxonomy builder against an existing scored harness run (fast path)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from prototyping.midi_b.taxonomy import build_adversarial_taxonomy, write_adversarial_taxonomy
from tests.prototyping.midi_b.support import midi_b_ready

pytestmark = [
    pytest.mark.midi_b_integration,
    pytest.mark.prototyping,
]

_DEFAULT_EXISTING = Path(
    "/Volumes/MBOD.DX.LIFE/TCIA/MIDI-B/harness-runs/validation_20261014T023428Z_smoke20pct"
)


def test_build_taxonomy_from_existing_scored_run() -> None:
    if not midi_b_ready():
        pytest.skip("MIDI-B volume not mounted")
    run_dir = Path(os.environ.get("MIDI_B_RUN_DIR", "").strip() or _DEFAULT_EXISTING)
    db = run_dir / "official_score" / "midi_b" / "validation_results.db"
    if not db.is_file():
        pytest.skip(f"no scored run at {run_dir}")
    tax = build_adversarial_taxonomy(run_dir)
    assert tax["totals"]["checks"] > 0
    assert "residual_phi" in tax["counts"]
    path = write_adversarial_taxonomy(run_dir)
    assert path.is_file()
    assert (run_dir / "ADVERSARIAL.md").is_file()
    assert (run_dir / "ner_harvest_candidates.jsonl").is_file()
    # Thorough characterization: residual or over-scrub buckets should be informative.
    assert (
        tax["counts"]["residual_phi"] + tax["counts"]["over_scrub"] + tax["counts"]["private_tag"]
        > 0
    )
