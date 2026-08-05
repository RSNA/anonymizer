"""Backward-compatible import shim for harmonize-only batch progress dialog."""

from anonymizer.controller.ai_batch_process import AiBatchAlgorithm, AiBatchProcessOptions
from anonymizer.view.ai_batch_process_dialog import AiBatchProcessDialog

__all__ = ["HarmonizeStudiesDialog"]


class HarmonizeStudiesDialog(AiBatchProcessDialog):
    """Run harmonize-only batch processing (legacy entry point)."""

    def __init__(self, parent, controller, studies) -> None:
        options = AiBatchProcessOptions(algorithms=(AiBatchAlgorithm.HARMONIZE,))
        super().__init__(parent, controller, studies, options)
