"""Shared Harmonize Description toolbar action (Series View + Report View)."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox

from pydicom import Dataset

from anonymizer.controller.ai.feature_availability import harmonize_allowed_for_modality
from anonymizer.utils.modalities import Modality, get_modality_catalog
from anonymizer.utils.translate import _
from anonymizer.view.ai.harmonize_results import (
    HarmonizeBatchOutcome,
    HarmonizeResultsView,
    focus_harmonize_view,
    get_any_open_harmonize_view,
    get_open_harmonize_view,
    show_harmonize_results_view,
)
from anonymizer.view.common.fonts import AppFonts

logger = logging.getLogger(__name__)


def harmonize_description_button_label() -> str:
    """Toolbar label for Harmonize Description (single source)."""
    return _("Harmonize Description")


def harmonize_button_visible(
    *,
    harmonize_models_ready: bool,
    modality: str | None,
    already_harmonized: bool,
) -> bool:
    """Show Harmonize when models/path are ready and the series ORM flag is not set."""
    if not harmonize_models_ready:
        return False
    series_mod = Modality.from_code(modality)
    if series_mod is None or not get_modality_catalog()[series_mod].harmonize:
        return False
    return not already_harmonized


def launch_harmonize_description(
    parent: tk.Misc,
    *,
    series_path: Path,
    ds: Dataset | None,
    anon_model,
    fonts: AppFonts | None = None,
    mappings_dir: Path | None = None,
    existing_view: HarmonizeResultsView | None = None,
    on_series_description_updated: Callable[[], None] | None = None,
    on_closed: Callable[[HarmonizeBatchOutcome], None] | None = None,
    on_before_open: Callable[[], None] | None = None,
) -> HarmonizeResultsView | None:
    """
    Open Harmonize Description for one series (same path for Series View and Report View).

    Args:
        parent: Host window.
        series_path: Anonymized series directory.
        ds: Loaded series dataset (first instance).
        anon_model: AnonymizerModel for ORM / PHI header.
        fonts: Optional app fonts.
        mappings_dir: Project ``storage_dir/mappings`` for description override CSVs.
        existing_view: Caller's held Harmonize window, if any.
        on_series_description_updated: Refresh host title/index after Accept.
        on_closed: Host cleanup when Harmonize closes.
        on_before_open: Host UI (hide button / disable controls) before opening.

    Returns:
        The Harmonize window, or ``None`` if the action was blocked / cancelled.
    """
    ds_mod = Modality.from_code(getattr(ds, "Modality", None) if ds is not None else None)
    if ds is None or ds_mod is None or not get_modality_catalog()[ds_mod].harmonize:
        return None
    modality = getattr(ds, "Modality", None)
    if not harmonize_allowed_for_modality(modality):
        messagebox.showinfo(
            title=_("Harmonize"),
            message=_("Harmonize is not ready yet. Click AI Features to download models."),
            parent=parent,
        )
        return None

    if existing_view is not None:
        try:
            if existing_view.winfo_exists():
                focus_harmonize_view(existing_view)
                return existing_view
        except tk.TclError:
            pass

    series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "").strip()
    series_key = series_uid or str(Path(series_path).resolve())
    open_elsewhere = get_open_harmonize_view(series_key) or get_any_open_harmonize_view()
    if open_elsewhere is not None:
        same_series = get_open_harmonize_view(series_key) is open_elsewhere
        messagebox.showinfo(
            title=_("Harmonize"),
            message=(
                _("Harmonize is already open for this series.")
                if same_series
                else _("Harmonize is already running for another series. Finish or cancel it first.")
            ),
            parent=parent,
        )
        focus_harmonize_view(open_elsewhere)
        return open_elsewhere

    logger.info("Harmonize starting for %s", series_path)
    if on_before_open is not None:
        on_before_open()
    return show_harmonize_results_view(
        parent,
        series_path=series_path,
        ds=ds,
        current_description=str(ds.get("SeriesDescription", "") or "").strip(),
        fonts=fonts,
        anon_model=anon_model,
        mappings_dir=mappings_dir,
        on_series_description_updated=on_series_description_updated,
        on_closed=on_closed,
    )
