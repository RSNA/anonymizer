"""De-id pipeline steps: clinical script, OpenMed metadata scrub, EasyOCR pixels."""

from __future__ import annotations

from prototyping.pseudo_phi_deid.pipeline.run import RunConfig, run_pairs

__all__ = ["RunConfig", "run_pairs"]
