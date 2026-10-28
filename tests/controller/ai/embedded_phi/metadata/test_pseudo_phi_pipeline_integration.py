"""Integration: PseudoPHI first-3 patients (script + private KB + NER; no pixels).

Core-stack health gate is ≥99.0% header. The 99.9% target is blocked on known
long-tail clusters (e.g. glued ``Sep1999`` OpenMed miss) — collect those before
adding NER-prep exceptions.

Opt-in (excluded from default suite)::

    uv run pytest -m pseudo_phi_integration \\
      tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \\
      --override-ini='addopts='

Fuller cohort (manual)::

    PSEUDO_PHI_FULL=1 uv run pytest -m pseudo_phi_integration \\
      tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \\
      -k full --override-ini='addopts='
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from prototyping.pseudo_phi_deid.pairs import list_eval_patient_ids, pair_all
from prototyping.pseudo_phi_deid.paths import (
    DEFAULT_DEID_DIR,
    DEFAULT_EVAL_DIR,
    DEFAULT_PATID_CROSSWALK,
    DEFAULT_UID_CROSSWALK,
)
from prototyping.pseudo_phi_deid.pipeline.run import RunConfig, run_pairs
from prototyping.pseudo_phi_deid.pipeline.script_session import ensure_experiment_script_copy
from prototyping.pseudo_phi_deid.score import score_pairs

# Interim core-stack gate (no Sep1999 NER-prep exceptions). Raise to 99.9 when long-tail cleared.
_HEADER_GATE = 99.0
_N_PATIENTS = 3
_FULL_N_PATIENTS = 20
_FULL_HEADER_GATE = 99.0
_TARGET_99_9 = 99.9


def _pseudo_phi_ready() -> bool:
    return (
        DEFAULT_EVAL_DIR.is_dir()
        and DEFAULT_DEID_DIR.is_dir()
        and DEFAULT_PATID_CROSSWALK.is_file()
        and DEFAULT_UID_CROSSWALK.is_file()
    )


def _run_header_gate(
    tmp_path: Path,
    *,
    n_patients: int,
    header_gate: float,
    label: str,
) -> None:
    subjects = list_eval_patient_ids()[:n_patients]
    assert len(subjects) == n_patients, f"need ≥{n_patients} patients, got {subjects!r}"

    pairs, unpaired = pair_all(patient_ids=subjects)
    assert pairs, f"no pairs for {subjects}; unpaired={unpaired[:5]}"

    script = ensure_experiment_script_copy(force=False)
    cfg = RunConfig.from_mode("combined", script_path=script, subject_ids=subjects)
    assert cfg.use_script and cfg.use_openmed
    assert cfg.mode == "combined"

    out = tmp_path / "candidates"
    result = run_pairs(pairs, out, cfg)
    metrics = score_pairs(pairs, result.candidate_dir, histogram=result.histogram)

    buckets = Counter((f.tag_path or "").split(".")[-1] for f in metrics.failures)
    # Align language with MIDI-B adversarial taxonomy buckets where possible.
    long_tail = (
        f"header={metrics.header_accuracy:.4f} (99.9 target={_TARGET_99_9}); "
        f"fails={len(metrics.failures)}; residual_phi_tags={buckets.most_common(8)}"
    )

    assert metrics.header_accuracy >= header_gate, (
        f"header_accuracy={metrics.header_accuracy:.4f} < {header_gate} "
        f"on {len(subjects)} patients / {len(pairs)} pairs; {long_tail}"
    )
    print(f"\nPseudoPHI {label} long-tail: {long_tail}")


@pytest.mark.pseudo_phi_integration
@pytest.mark.prototyping
@pytest.mark.skipif(not _pseudo_phi_ready(), reason="Pseudo-PHI-DICOM-Dataset not at default path")
def test_pseudo_phi_first3_header_core_stack(tmp_path: Path) -> None:
    """Steps 1–6 on first 3 patients; ≥99.0% header; report long-tail vs 99.9%."""
    _run_header_gate(
        tmp_path,
        n_patients=_N_PATIENTS,
        header_gate=_HEADER_GATE,
        label="first-3",
    )


@pytest.mark.pseudo_phi_integration
@pytest.mark.prototyping
@pytest.mark.skipif(not _pseudo_phi_ready(), reason="Pseudo-PHI-DICOM-Dataset not at default path")
def test_pseudo_phi_full_header_core_stack(tmp_path: Path) -> None:
    """Larger cohort gate — enable with PSEUDO_PHI_FULL=1."""
    if os.environ.get("PSEUDO_PHI_FULL", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set PSEUDO_PHI_FULL=1 for fuller PseudoPHI header gate")
    _run_header_gate(
        tmp_path,
        n_patients=_FULL_N_PATIENTS,
        header_gate=_FULL_HEADER_GATE,
        label=f"full-{_FULL_N_PATIENTS}",
    )
