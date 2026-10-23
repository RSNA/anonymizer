"""Route a series to the right Embedded PHI workspace (Series View or Report Text Review)."""

import logging
import tkinter as tk
from pathlib import Path

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.controller.project import ProjectController
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.reports.report_text_review import show_report_text_review
from anonymizer.view.series.series import show_series_view

logger = logging.getLogger(__name__)

# Native text reports only — pixel/SC “text reports” use Series View + OCR.
_TEXT_WORKSPACE_KINDS = frozenset({SeriesKind.NATIVE_SR, SeriesKind.NATIVE_PDF})


def workspace_kind_for_series(series_path: Path, *, modality: str | None = None) -> SeriesKind:
    """Classification used by open_series_workspace (exposed for tests / callers)."""
    return classify_series(series_path, modality=modality)


def open_series_workspace(
    parent: tk.Misc,
    *,
    controller: ProjectController,
    series_path: Path,
    fonts: AppFonts | None = None,
    modality: str | None = None,
):
    """
    Open the workspace for series_path.

    * Imaging / other pixel / SC text-like series → Series View (OCR + NER).
    * Native SR / Encapsulated PDF → Report Text Review (text-layer NER only).
    """
    kind = classify_series(series_path, modality=modality)
    logger.info("open_series_workspace kind=%s path=%s", kind.value, series_path)
    if kind in _TEXT_WORKSPACE_KINDS:

        document_kind = "sr" if kind is SeriesKind.NATIVE_SR else "pdf"
        return show_report_text_review(
            parent,
            controller=controller,
            series_path=series_path,
            document_kind=document_kind,
            fonts=fonts,
        )
    return show_series_view(parent, controller=controller, series_path=series_path, fonts=fonts)
