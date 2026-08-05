"""Tests for AI batch process options dialog."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anonymizer.controller.ai_batch_process import AiBatchAlgorithm
from anonymizer.controller.blur_face import FaceBlurMode
from anonymizer.controller.remove_pixel_phi import PixelPhiRemovalMode
from anonymizer.view.ai_batch_process_options_dialog import (
    AiBatchProcessOptionsDialog,
    pixel_phi_removal_mode_from_menu_label,
    show_ai_batch_process_options_dialog,
)


def test_show_options_dialog_returns_none_when_no_features_ready() -> None:
    with patch(
        "anonymizer.view.ai_batch_process_options_dialog.pixel_phi_allowed",
        return_value=False,
    ):
        with patch(
            "anonymizer.view.ai_batch_process_options_dialog.harmonize_allowed",
            return_value=False,
        ):
            with patch(
                "anonymizer.view.ai_batch_process_options_dialog.face_blur_allowed",
                return_value=False,
            ):
                result = show_ai_batch_process_options_dialog(MagicMock())
    assert result.confirmed is False
    assert result.options is None


def test_selected_algorithms_respects_canonical_order() -> None:
    dialog = AiBatchProcessOptionsDialog.__new__(AiBatchProcessOptionsDialog)
    dialog._vars = {
        AiBatchAlgorithm.FACE_BLUR: MagicMock(get=MagicMock(return_value=1)),
        AiBatchAlgorithm.REMOVE_PIXEL_PHI: MagicMock(get=MagicMock(return_value=1)),
        AiBatchAlgorithm.HARMONIZE: MagicMock(get=MagicMock(return_value=0)),
    }
    assert dialog._selected_algorithms() == (
        AiBatchAlgorithm.REMOVE_PIXEL_PHI,
        AiBatchAlgorithm.FACE_BLUR,
    )


def test_on_ok_returns_options_with_blur_mode() -> None:
    dialog = AiBatchProcessOptionsDialog.__new__(AiBatchProcessOptionsDialog)
    dialog._result = None
    dialog._blur_mode_var = MagicMock(get=MagicMock(return_value="Gaussian blur"))
    dialog._pixel_phi_mode_var = MagicMock(get=MagicMock(return_value="Black out text"))
    dialog._vars = {
        AiBatchAlgorithm.HARMONIZE: MagicMock(get=MagicMock(return_value=1)),
    }
    dialog._close = MagicMock()

    AiBatchProcessOptionsDialog._on_ok(dialog)

    assert dialog._result.confirmed is True
    assert dialog._result.options is not None
    assert dialog._result.options.algorithms == (AiBatchAlgorithm.HARMONIZE,)
    assert dialog._result.options.blur_mode is FaceBlurMode.GAUSSIAN
    assert dialog._result.options.pixel_phi_removal_mode is PixelPhiRemovalMode.BLACKOUT


def test_algorithm_limitation_notes() -> None:
    rows = {
        algorithm: limitation for algorithm, _label, limitation, _allowed in AiBatchProcessOptionsDialog._ALGORITHM_ROWS
    }
    assert rows[AiBatchAlgorithm.HARMONIZE] == "CT only. Updates SeriesDescription only."
    assert "CT head" in rows[AiBatchAlgorithm.FACE_BLUR]
    assert "OCR" in rows[AiBatchAlgorithm.REMOVE_PIXEL_PHI]


def test_pixel_phi_removal_mode_from_menu_label() -> None:
    assert pixel_phi_removal_mode_from_menu_label("Black out text") is PixelPhiRemovalMode.BLACKOUT
    assert pixel_phi_removal_mode_from_menu_label("Blend into background") is PixelPhiRemovalMode.INPAINT
