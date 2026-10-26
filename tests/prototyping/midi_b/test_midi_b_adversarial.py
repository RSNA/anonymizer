"""Opt-in MIDI-B official-score adversarial gates (not CI)."""

from __future__ import annotations

import pytest

from tests.prototyping.midi_b.run_helpers import resolve_scored_run, taxonomy_for
from tests.prototyping.midi_b.support import (
    SMOKE_FLOORS_PATH,
    TAXONOMY_BASELINE_PATH,
    full_validation_enabled,
    load_json,
    midi_b_python_deps_ready,
    midi_b_ready,
    validator_ready,
    write_baseline_enabled,
    write_json,
)

pytestmark = [
    pytest.mark.midi_b_integration,
    pytest.mark.prototyping,
]


def _require_midi() -> None:
    if not midi_b_ready():
        pytest.skip("MIDI-B Synthetic Validation / answer key not at default path")
    if not validator_ready():
        pytest.skip("official MIDI_validation_script not under midi_b/vendor")
    if not midi_b_python_deps_ready():
        pytest.fail(
            "nltk missing — install MIDI scorer deps with: uv sync --group midi-b "
            "(then re-run with: uv run --group midi-b pytest …)"
        )


def test_midi_b_smoke5_official_score() -> None:
    """Smoke5 pass rate must meet committed floors (or write them when requested)."""
    _require_midi()
    run_dir = resolve_scored_run()
    tax = taxonomy_for(run_dir)
    pass_pct = float(tax["totals"]["pass_pct"])
    floors = load_json(SMOKE_FLOORS_PATH)
    min_pass = floors.get("min_pass_pct")
    if min_pass is None:
        if write_baseline_enabled():
            # Small slack below observed so trivial noise does not fail immediately.
            floors["min_pass_pct"] = round(max(0.0, pass_pct - 1.0), 4)
            floors["last_run_dir"] = str(run_dir)
            floors["last_pass_pct"] = pass_pct
            write_json(SMOKE_FLOORS_PATH, floors)
            return
        pytest.fail(
            f"smoke_floors.json has no min_pass_pct; re-run with "
            f"MIDI_B_WRITE_BASELINE=1 (observed pass_pct={pass_pct:.4f} at {run_dir})"
        )
    assert pass_pct >= float(min_pass), (
        f"pass_pct={pass_pct:.4f} < floor {min_pass} (run={run_dir})"
    )


def test_midi_b_failure_taxonomy_nonempty_report() -> None:
    """Taxonomy must classify most failures into known buckets."""
    _require_midi()
    run_dir = resolve_scored_run()
    tax = taxonomy_for(run_dir)
    assert "counts" in tax
    assert set(tax["counts"]) >= {
        "residual_phi",
        "over_scrub",
        "uid_action",
        "private_tag",
        "other",
    }
    failed = int(tax["totals"]["failed"])
    if failed == 0:
        return
    ratio = float(tax["classified_ratio"])
    min_ratio = float(tax["min_classified_ratio"])
    assert ratio >= min_ratio, (
        f"classified_ratio={ratio:.3f} < {min_ratio} "
        f"(other={tax['counts'].get('other')}; run={run_dir})"
    )
    from prototyping.midi_b.taxonomy import write_adversarial_taxonomy

    tax_path = write_adversarial_taxonomy(run_dir)
    assert tax_path.is_file()


def test_midi_b_no_category_regression() -> None:
    """residual_phi / over_scrub counts must not exceed taxonomy baseline."""
    _require_midi()
    run_dir = resolve_scored_run()
    tax = taxonomy_for(run_dir)
    counts = tax["counts"]
    baseline = load_json(TAXONOMY_BASELINE_PATH)
    if baseline.get("max_residual_phi") is None:
        if write_baseline_enabled():
            baseline["max_residual_phi"] = int(counts.get("residual_phi", 0))
            baseline["max_over_scrub"] = int(counts.get("over_scrub", 0))
            baseline["max_private_tag"] = int(counts.get("private_tag", 0))
            baseline["last_run_dir"] = str(run_dir)
            write_json(TAXONOMY_BASELINE_PATH, baseline)
            return
        pytest.fail(
            "taxonomy_baseline.json has null max_*; re-run with MIDI_B_WRITE_BASELINE=1 "
            f"(residual={counts.get('residual_phi')} over_scrub={counts.get('over_scrub')})"
        )
    assert int(counts.get("residual_phi", 0)) <= int(baseline["max_residual_phi"])
    assert int(counts.get("over_scrub", 0)) <= int(baseline["max_over_scrub"])
    if baseline.get("max_private_tag") is not None:
        assert int(counts.get("private_tag", 0)) <= int(baseline["max_private_tag"])


def test_midi_b_full_validation_gate() -> None:
    """Full Validation — only when MIDI_B_FULL=1 (overnight)."""
    if not full_validation_enabled():
        pytest.skip("set MIDI_B_FULL=1 to run full Validation gate")
    _require_midi()
    # Reuse CLI path with no patient filter via empty patients → all instances.
    import argparse

    from prototyping.midi_b.cli import cmd_validate

    args = argparse.Namespace(
        split="validation",
        synthetic_root=None,
        patients=None,
        limit=None,
        runs_root=None,
        mode="combined",
        script=None,
        slug="pytest_full",
        out=None,
        answer_db=None,
        multiprocessing=False,
        cpus=4,
        no_reports=False,
        verbose=False,
        run_dir=None,
    )
    rc = cmd_validate(args)
    assert rc == 0
    run_dir = args.run_dir or args.out
    tax = taxonomy_for(run_dir)
    floors = load_json(SMOKE_FLOORS_PATH)
    min_pass = floors.get("min_pass_pct")
    if min_pass is not None:
        assert float(tax["totals"]["pass_pct"]) >= float(min_pass)
