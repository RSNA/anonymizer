"""Characterization: batch UX expectations still remove known PHI tokens.

Opt-in with the rest of ``ocr_integration`` (not CI). Fails when golden
removed-texts stop listing residual name/ID tokens for the three fixtures.
"""

from __future__ import annotations

import pytest

from tests.controller.support.ai_batch_ux_fixtures import BATCH_UX_EXPECTATIONS

pytestmark = pytest.mark.ocr_integration

# Tokens that must remain in at least one fixture's removed_texts (residual PHI).
_REQUIRED_PHI_NEEDLES = (
    "DAVIDSON",
    "DOUGLAS",
    "Christopher",
    "Robinson",
)


def test_batch_ux_expectations_still_list_known_phi_tokens() -> None:
    all_removed = " ".join(
        " ".join(case.removed_texts) for case in BATCH_UX_EXPECTATIONS
    ).upper()
    missing = [n for n in _REQUIRED_PHI_NEEDLES if n.upper() not in all_removed]
    assert not missing, (
        "BATCH_UX_EXPECTATIONS no longer list known PHI tokens "
        f"{missing}; fixtures or removal expectations may have regressed"
    )
    assert BATCH_UX_EXPECTATIONS, "expected at least one batch UX fixture"
