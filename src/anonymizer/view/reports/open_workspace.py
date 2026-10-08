"""Route a series to the right Embedded PHI workspace (Series View or Report Text Review)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from anonymizer.controller.ai.embedded_phi.classify_series import SeriesKind, classify_series
from anonymizer.view.series.series import show_series_view

if TYPE_CHECKING:
    import tkinter as tk

    from anonymizer.controller.project import ProjectController
    from anonymizer.view.common.fonts import AppFonts

logger = logging.getLogger(__name__)

_TEXT_WORKSPACE_KINDS = frozenset(
    {SeriesKind.NATIVE_SR, SeriesKind.NATIVE_PDF, SeriesKind.PIXEL_TEXT_REPORT}
)


def workspace_kind_for_series(series_path: Path, *, modality: str | None = None) -> SeriesKind:
    """Classification used by ``open_series_workspace`` (exposed for tests / callers)."""
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
    Open the workspace for ``series_path``.

    * Imaging / other pixel → Series View.
    * Native SR / Encapsulated PDF / SC pixel text reports → Report Text Review.
    """
    kind = classify_series(series_path, modality=modality)
    logger.info("open_series_workspace kind=%s path=%s", kind.value, series_path)
    if kind in _TEXT_WORKSPACE_KINDS:
        from anonymizer.view.reports.report_text_review import show_report_text_review

        if kind is SeriesKind.NATIVE_SR:
            document_kind = "sr"
        elif kind is SeriesKind.NATIVE_PDF:
            document_kind = "pdf"
        else:
            document_kind = "pixel_report"
        return show_report_text_review(
            parent,
            controller=controller,
            series_path=series_path,
            document_kind=document_kind,
            fonts=fonts,
        )
    return show_series_view(parent, controller=controller, series_path=series_path, fonts=fonts)
