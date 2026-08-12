"""Sequential batch processing for PHI Index study selection.

Canonical module name per unified background-task plan. Implementation lives in
``ai_batch_process`` during migration; import from here for new code.
"""

from __future__ import annotations

from anonymizer.controller.ai_batch_process import (  # noqa: F401
    AI_BATCH_TO_RUNNER,
    CANONICAL_ALGORITHM_ORDER,
    AiBatchAlgorithm,
    AiBatchAlgorithmTotals,
    AiBatchCancelledCallback,
    AiBatchMemoryCallback,
    AiBatchOutcome,
    AiBatchProcessOptions,
    AiBatchProgressCallback,
    AiBatchSummary,
    AiBatchWorkflowLogCallback,
    SeriesItem,
    ai_batch_process,
    count_pending_series,
    enumerate_series_for_studies,
    format_ai_batch_completion_summary,
    format_ai_batch_phase_label,
    format_ai_batch_position,
    format_ai_batch_status_line,
    format_batch_outcome_subline,
    format_batch_phase_banner,
    format_batch_step_subline,
    format_batch_workflow_log_line,
    format_remove_pixel_phi_instance_detail,
    format_remove_pixel_phi_series_message,
    missing_series_description_label,
    normalize_selected_algorithms,
)
from anonymizer.controller.runner import CANONICAL_ALGORITHM_ORDER as RUNNER_ALGORITHM_ORDER
from anonymizer.controller.runner import Algorithm

# Preferred names (plan aliases)
BatchAlgorithm = AiBatchAlgorithm
BatchProcessOptions = AiBatchProcessOptions
BatchOutcome = AiBatchOutcome
BatchSummary = AiBatchSummary
BatchAlgorithmTotals = AiBatchAlgorithmTotals
batch_process = ai_batch_process

__all__ = [
    "AI_BATCH_TO_RUNNER",
    "Algorithm",
    "BatchAlgorithm",
    "BatchAlgorithmTotals",
    "BatchOutcome",
    "BatchProcessOptions",
    "BatchSummary",
    "CANONICAL_ALGORITHM_ORDER",
    "RUNNER_ALGORITHM_ORDER",
    "SeriesItem",
    "ai_batch_process",
    "batch_process",
    "count_pending_series",
    "enumerate_series_for_studies",
    "format_ai_batch_completion_summary",
    "format_ai_batch_phase_label",
    "format_ai_batch_position",
    "format_ai_batch_status_line",
    "format_batch_outcome_subline",
    "format_batch_phase_banner",
    "format_batch_step_subline",
    "format_batch_workflow_log_line",
    "format_remove_pixel_phi_instance_detail",
    "format_remove_pixel_phi_series_message",
    "missing_series_description_label",
    "normalize_selected_algorithms",
]
