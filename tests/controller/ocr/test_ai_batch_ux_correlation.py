"""AI batch removal must match UX workflow logs for the three standard fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from anonymizer.controller.ai.remove_pixel_phi import (
    PixelPhiRemovalMode,
    remove_pixel_phi,
)
from anonymizer.controller.ai_batch_process import (
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
)
from anonymizer.controller.runner import RemovePixelPhiRunner
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.ai_batch_ux_fixtures import BATCH_UX_EXPECTATIONS, BatchUxExpectation

pytestmark = pytest.mark.ocr_integration


@pytest.fixture(autouse=True)
def _require_ocr_and_assets(require_ocr) -> None:
    for case in BATCH_UX_EXPECTATIONS:
        assert_dcm(Path(case.dcm_path))


def _format_ux_instance_log(case: BatchUxExpectation) -> str:
    return format_remove_pixel_phi_instance_detail(
        instance_index=1,
        instance_total=1,
        modified=True,
        texts=list(case.removed_texts),
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
        pixels_changed=case.pixels_changed,
    )


def _format_ux_series_log(case: BatchUxExpectation) -> str:
    return format_remove_pixel_phi_series_message(
        modified_count=1,
        total=1,
        texts_removed=list(case.removed_texts),
        pixels_changed=case.pixels_changed,
        removal_mode=PixelPhiRemovalMode.BLACKOUT,
    )


@pytest.mark.parametrize("case", BATCH_UX_EXPECTATIONS, ids=lambda case: case.label)
def test_batch_removal_matches_ux_logs(
    case: BatchUxExpectation,
    tmp_path: Path,
) -> None:
    """Mirror UX: default modality whitelist, no explicit whitelist=[]."""
    dcm_path = tmp_path / "instance.dcm"
    shutil.copy(case.dcm_path, dcm_path)

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        modified, texts, pixels_changed = remove_pixel_phi(
            dcm_path,
            handle.reader,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
            modality=case.modality,
        )
    finally:
        runner.exit_models(handle)

    assert modified is True
    assert texts == list(case.removed_texts)
    assert pixels_changed == case.pixels_changed

    instance_log = _format_ux_instance_log(case)
    series_log = _format_ux_series_log(case)

    for token in case.instance_log_tokens:
        assert token in instance_log
    for token in case.series_log_tokens:
        assert token in series_log

    if case.instance_log_more_count is not None:
        assert f"(+{case.instance_log_more_count} more)" in instance_log
    if case.series_log_more_count is not None:
        assert f"(+{case.series_log_more_count} more)" in series_log

    assert f"{case.pixels_changed:,} px" in instance_log
    assert f"{case.pixels_changed:,} pixels blacked out" in series_log
