"""Series View survivors after AI batch Remove Text on RGB US single-frame."""

import shutil
from pathlib import Path

import pytest

from anonymizer.controller.ai.embedded_phi.pixel.detect_text import ocr_image_for_frame
from anonymizer.controller.ai.embedded_phi.pixel.ocr_pipeline import (
    PhiMatchMode,
    detect_text,
    filter_ocr_noise,
    make_annotate_whitelist,
)
from anonymizer.controller.ai.embedded_phi.pixel.remove_pixel_phi import PixelPhiRemovalMode, remove_pixel_phi
from anonymizer.controller.ai.embedded_phi.pixel.remove_scope import OcrRemoveMode, texts_for_remove_mode
from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist
from anonymizer.controller.jobs.runner import RemovePixelPhiRunner
from anonymizer.controller.series.series_io import load_series_frames
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.support.us_rgb_fixtures import (
    US_RGB_DCM,
    US_RGB_SERIES_VIEW_SURVIVORS_AFTER_BATCH,
)


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_us_rgb_series_view_after_batch_shows_no_whitelist_display_survivors(
    tmp_path: Path,
) -> None:
    assert_dcm(US_RGB_DCM)
    dcm_path = tmp_path / "us_rgb.dcm"
    shutil.copy(US_RGB_DCM, dcm_path)
    loaded = load_series_frames(US_RGB_DCM.parent)

    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        remove_pixel_phi(
            dcm_path,
            handle.reader,
            removal_mode=PixelPhiRemovalMode.BLACKOUT,
            modality="US",
        )
        import pydicom

        ds = pydicom.dcmread(dcm_path)
        bgr_after = ocr_image_for_frame(loaded.metadata, ds.pixel_array)
        after_all = filter_ocr_noise(
            detect_text(bgr_after, handle.reader, modality="US") or [],
            modality="US",
        )
        us_wl = [item.upper() for item in load_default_whitelist("US")]
        annotated = make_annotate_whitelist(us_wl)(after_all)
        after_display = texts_for_remove_mode(
            annotated,
            OcrRemoveMode.NON_WHITELISTED,
            PhiMatchMode.STANDARD,
        )
        display_texts = [item.text for item in after_display]
    finally:
        runner.exit_models(handle)

    assert display_texts == list(US_RGB_SERIES_VIEW_SURVIVORS_AFTER_BATCH)
