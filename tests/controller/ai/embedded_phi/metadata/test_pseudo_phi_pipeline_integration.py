"""Integration: PseudoPHI first-3 patients (script + private KB + NER; no pixels).

Core-stack health gate is ≥99.0% header. The 99.9% target is blocked on known
long-tail clusters (e.g. glued ``Sep1999`` OpenMed miss) — collect those before
adding NER-prep exceptions.

Opt-in (excluded from default suite)::

    uv run pytest -m pseudo_phi_integration \\
      tests/controller/ai/embedded_phi/metadata/test_pseudo_phi_pipeline_integration.py \\
      --override-ini='addopts='
"""

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
_TARGET_99_9 = 99.9


def _pseudo_phi_ready() -> bool:
    return (
        DEFAULT_EVAL_DIR.is_dir()
        and DEFAULT_DEID_DIR.is_dir()
        and DEFAULT_PATID_CROSSWALK.is_file()
        and DEFAULT_UID_CROSSWALK.is_file()
    )


@pytest.mark.pseudo_phi_integration
@pytest.mark.prototyping
@pytest.mark.skipif(not _pseudo_phi_ready(), reason="Pseudo-PHI-DICOM-Dataset not at default path")
def test_pseudo_phi_first3_header_core_stack(tmp_path: Path) -> None:
    """Steps 1–6 on first 3 patients; ≥99.0% header; report long-tail vs 99.9%."""
    subjects = list_eval_patient_ids()[:_N_PATIENTS]
    assert len(subjects) == _N_PATIENTS, f"need ≥{_N_PATIENTS} patients, got {subjects!r}"

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
    long_tail = (
        f"header={metrics.header_accuracy:.4f} (99.9 target={_TARGET_99_9}); "
        f"fails={len(metrics.failures)}; buckets={buckets.most_common(8)}"
    )

    assert metrics.header_accuracy >= _HEADER_GATE, (
        f"header_accuracy={metrics.header_accuracy:.4f} < {_HEADER_GATE} "
        f"on {len(subjects)} patients / {len(pairs)} pairs; {long_tail}"
    )
    # Visible in -vv: known gap to 99.9 without exception patches.
    print(f"\nPseudoPHI first-3 long-tail (collect before NER-prep exceptions): {long_tail}")
