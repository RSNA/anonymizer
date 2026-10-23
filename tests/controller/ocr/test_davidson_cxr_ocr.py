"""OCR integration tests on real burnt-in PHI CXR fixture (Davidson)."""

from pathlib import Path

import pytest

from anonymizer.controller.ai.embedded_phi.pixel.detect_text import (
    filter_ocr_whitelist_only,
    load_modality_whitelist,
    load_modality_whitelist_match_settings,
)
from anonymizer.controller.jobs.runner import OcrEditContext, RemovePixelPhiRunner, RunOptions
from anonymizer.controller.jobs.work_state import WorkState
from anonymizer.controller.series.series_io import load_series_frames
from tests.controller.ocr.conftest import assert_dcm
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

DAVIDSON_CXR_SERIES_DIR = CONTROLLER_TEST_DCM_FILES_DIR / "davidson_cxr"
DAVIDSON_CXR_DCM = DAVIDSON_CXR_SERIES_DIR / "davidson_cxr_monochrome1_uncompressed.dcm"


@pytest.fixture(scope="module")
def davidson_loaded():
    assert_dcm(DAVIDSON_CXR_DCM)
    return load_series_frames(DAVIDSON_CXR_SERIES_DIR)


def test_davidson_cxr_loads_single_frame(davidson_loaded) -> None:
    assert davidson_loaded.is_single_frame
    assert davidson_loaded.frames.shape[0] == 1
    assert davidson_loaded.frames.ndim == 3


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_davidson_cxr_ocr_finds_burned_in_text(davidson_loaded) -> None:
    """Regression: MONOCHROME1 CXR must yield OCR boxes with an empty whitelist."""
    from anonymizer.controller.ai.embedded_phi.ner.cache import ner_ready

    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(edit_context=OcrEditContext.FRAME, whitelist=[]),
        )
    finally:
        runner.exit_models(handle)

    assert isinstance(ws.result, dict)
    assert 0 in ws.result
    assert len(ws.result[0]) > 0, "Expected burned-in text on Davidson CXR"
    texts = [t.text for t in ws.result[0]]
    assert any("portable" in t.lower() for t in texts), f"Expected Portable in OCR results, got {texts}"
    # Series View annotate path: overlay kept; PHI strings labeled when NER is ready.
    portable = next(t for t in ws.result[0] if "portable" in t.text.lower())
    assert portable.phi_label is None, f"Portable must not be classified as PHI, got {portable.phi_label}"
    if ner_ready():
        assert any(t.phi_label in {"NAME", "DATE"} for t in ws.result[0]), (
            f"Expected pixel NAME or DATE labels on Davidson PHI, got "
            f"{[(t.text, t.phi_label) for t in ws.result[0]]}"
        )
        # Frame-context gate: name and DOB boxes labelled from one contextual
        # call; hover entities recorded per box (entity only, no "DOB:" prefix).
        dob_box = next(t for t in ws.result[0] if "DOB" in t.text)
        assert dob_box.phi_label == "DATE", (
            f"DOB box must be DATE-labelled, got {[(t.text, t.phi_label) for t in ws.result[0]]}"
        )
        assert dob_box.phi_entities, "DOB box must record its detected entities for hover"
        assert all(label == "DATE" for label, _text in dob_box.phi_entities)
        # The model may fragment this date (e.g. '.' + '.1976'); the box is
        # still DATE-labelled/removed whole, and the date must be among them.
        assert any("1976" in text or "06" in text for _label, text in dob_box.phi_entities)
        name_boxes = [t for t in ws.result[0] if "DAVIDSON" in t.text or "DOUGLAS" in t.text]
        assert name_boxes and all(
            t.phi_label == "NAME" for t in name_boxes
        ), f"Name boxes mislabelled: {[(t.text, t.phi_label) for t in name_boxes]}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_davidson_cxr_ocr_hides_portable_with_whitelist(davidson_loaded) -> None:
    """Whitelist containing PORTABLE should filter burned-in Portable overlay text."""
    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(
                edit_context=OcrEditContext.FRAME,
                whitelist=["PORTABLE"],
            ),
        )
    finally:
        runner.exit_models(handle)

    texts = [t.text for t in ws.result[0]]
    assert not any("portable" in t.lower() for t in texts), f"Portable should be whitelisted, got {texts}"


@pytest.mark.ocr_integration
@pytest.mark.usefixtures("require_ocr")
def test_davidson_cleared_whitelist_with_project_dir_finds_portable(davidson_loaded) -> None:
    """Cleared Series View whitelist must not reload modality defaults from project_dir."""
    loaded = davidson_loaded
    ws = WorkState()
    ws.bind(
        loaded.metadata,
        loaded.frames,
        loaded.slice_paths,
        loaded.default_window,
        single_frame=True,
    )
    ws.frame_index = 0
    runner = RemovePixelPhiRunner()
    handle = runner.enter_models()
    try:
        runner.process_series(
            ws,
            handle,
            options=RunOptions(
                edit_context=OcrEditContext.FRAME,
                whitelist=[],
                project_dir=Path("/tmp/fake-project"),
            ),
        )
    finally:
        runner.exit_models(handle)

    texts = [t.text for t in ws.result[0]]
    assert any("portable" in t.lower() for t in texts), f"Expected Portable after cleared whitelist, got {texts}"


def test_davidson_overlay_draw_includes_portable_when_project_whitelist_omits_it(
    tmp_path: Path,
) -> None:
    """Detect-all + draw-filter: project cr.txt without PORTABLE must still draw Portable."""
    from anonymizer.controller.series.series_overlay import OCRText

    project_dir = tmp_path / "project"
    project_whitelist = project_dir / "whitelists" / "cr.txt"
    project_whitelist.parent.mkdir(parents=True)
    project_whitelist.write_text("AXIAL\nCHEST\n", encoding="utf-8")

    detections = [
        OCRText(text="DAVIDSON", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="DOUGLAS [M]", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="01.09.2012", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Semi-Upright", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="DOB: 06.16.1976", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Portable", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]
    effective_whitelist = load_modality_whitelist(project_dir, "CR")
    match_settings = load_modality_whitelist_match_settings(project_dir, "CR")
    drawn = filter_ocr_whitelist_only(
        detections,
        whitelist=effective_whitelist,
        whitelist_match_settings=match_settings,
    )
    drawn_texts = [item.text for item in drawn]

    assert "Portable" in drawn_texts
    assert "Semi-Upright" in drawn_texts
    assert "DAVIDSON" in drawn_texts


def test_davidson_default_cr_whitelist_hides_portable_and_semi_upright() -> None:
    """Packaged CR/DX defaults must hide common Davidson overlay markers."""
    from anonymizer.controller.ai.embedded_phi.pixel.whitelist_io import load_default_whitelist
    from anonymizer.controller.series.series_overlay import OCRText

    detections = [
        OCRText(text="DAVIDSON DOUGLAS [M]", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="01.09.2012", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Semi-Upright", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
        OCRText(text="Portable", top_left=(0, 0), bottom_right=(10, 10), prob=0.9),
    ]
    cr_wl = load_default_whitelist("CR")
    assert "PORTABLE" in cr_wl
    assert "SEMI-UPRIGHT" in cr_wl
    drawn = filter_ocr_whitelist_only(detections, whitelist=cr_wl)
    texts = [t.text for t in drawn]
    assert "Portable" not in texts
    assert "Semi-Upright" not in texts
    assert "DAVIDSON DOUGLAS [M]" in texts
