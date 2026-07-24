"""Harmonize results view: batch-aware analysis progress, Treeview tables, and Playbook proposal."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk

import customtkinter as ctk
from pydicom import Dataset

from anonymizer.controller.create_projections import apply_series_description
from anonymizer.controller.harmonize import HarmonizedResult, HarmonizeProgress, harmonize_series
from anonymizer.controller.tseg.dicom_geometry import geometry_analysis_progress_prefix
from anonymizer.controller.tseg.radlex_playbook import (
    PLAYBOOK_TREE_IIDS,
    build_localizer_playbook_attributes,
    harmonize_analysis_rows,
    harmonize_dicom_rows,
    is_localizer_geometry,
    playbook_body_part_row_values,
    playbook_iv_contrast_row_values,
    playbook_plane_row_values,
    playbook_series_type_row_values,
)
from anonymizer.model.anonymizer import StudyPhiHeader
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HarmonizeSeriesItem:
    """One CT series selected for Playbook harmonization within a study batch."""

    series_path: Path
    ds: Dataset
    study_description: str = ""
    current_description: str = ""
    phi_header: StudyPhiHeader | None = None

    @classmethod
    def from_dataset(
        cls,
        series_path: Path,
        ds: Dataset,
        *,
        phi_header: StudyPhiHeader | None = None,
    ) -> HarmonizeSeriesItem:
        return cls(
            series_path=Path(series_path),
            ds=ds,
            study_description=str(ds.get("StudyDescription", "") or "").strip(),
            current_description=str(ds.get("SeriesDescription", "") or "").strip(),
            phi_header=phi_header,
        )


@dataclass
class HarmonizeSeriesOutcome:
    item: HarmonizeSeriesItem
    accepted: bool | None = None
    result: HarmonizedResult | None = None
    error: str | None = None


@dataclass
class HarmonizeBatchOutcome:
    """Outcomes for each harmonized series; supports single- and multi-series batches."""

    outcomes: list[HarmonizeSeriesOutcome] = field(default_factory=list)
    cancelled: bool = False

    @property
    def accepted(self) -> bool | None:
        return self.outcomes[0].accepted if self.outcomes else None

    @property
    def result(self) -> HarmonizedResult | None:
        return self.outcomes[0].result if self.outcomes else None

    @property
    def error(self) -> str | None:
        return self.outcomes[0].error if self.outcomes else None


class HarmonizeResultsView(tk.Toplevel):
    """
    Modal harmonize view: runs the pipeline per selected series, shows progress, then Playbook results.

    A study-description header at the top updates as the view iterates through a batch of series
    (single-series use passes one ``HarmonizeSeriesItem``).

    Layout follows ``QueryView`` in ``query_retrieve_import.py``:
    batch header, results frames, optional error frame, footer (status + progress + buttons).
    """

    ux_poll_interval_ms = 200

    PAD = 10
    ButtonWidth = 100
    _WIDTH_SCALE = 0.9
    MIN_WIDTH = int(round(1200 * _WIDTH_SCALE))
    _TREE_TRAILING_BLANK_ROWS = 1
    _DICOM_TREE_ROWS = len(harmonize_dicom_rows(Dataset()))
    _PLAYBOOK_TREE_ROWS = len(PLAYBOOK_TREE_IIDS)
    _DICOM_TREE_VISIBLE_ROWS = _DICOM_TREE_ROWS + _TREE_TRAILING_BLANK_ROWS
    _PLAYBOOK_TREE_VISIBLE_ROWS = _PLAYBOOK_TREE_ROWS + _TREE_TRAILING_BLANK_ROWS
    _SECTION_LABEL_HEIGHT_PX = 22
    _PROPOSAL_VALUE_HEIGHT_PX = 34
    _FOOTER_HEIGHT_PX = 44

    _dicom_attr_map: dict[str, tuple[str, int, bool, bool]] = {
        "field": (_("Field"), 30, False, False),
        "tag": (_("Tag"), 13, False, False),
        "value": (_("Value"), 65, False, True),
    }
    _dicom_column_keys = list(_dicom_attr_map.keys())

    _playbook_attr_map: dict[str, tuple[str, int, bool, bool]] = {
        "element": (_("Element"), 20, False, False),
        "code": (_("Code"), 13, False, False),
        "value": (_("Value"), 22, False, False),
        "evidence": (_("Evidence"), 34, False, True),
        "source": (_("Source"), 34, False, True),
    }
    _playbook_column_keys = list(_playbook_attr_map.keys())

    def __init__(
        self,
        parent: tk.Misc,
        *,
        items: Sequence[HarmonizeSeriesItem],
        mono_font: ctk.CTkFont | None = None,
        anon_model=None,
        on_series_description_updated: Callable[[], None] | None = None,
    ):
        super().__init__(master=parent)
        if not items:
            raise ValueError("HarmonizeResultsView requires at least one series item")

        self._items = list(items)
        self._batch_total = len(self._items)
        self._item_index = 0
        self._outcomes: list[HarmonizeSeriesOutcome] = []
        self.cancelled = False
        self._anon_model = anon_model
        self._on_series_description_updated = on_series_description_updated

        self._data_font = mono_font or getattr(parent, "_data_font", None) or ctk.CTkFont(family="Menlo", size=12)
        font_family = self._data_font.cget("family")
        self._study_header_font = ctk.CTkFont(family=font_family, size=14, weight="bold")
        self._radlex_title_font = ctk.CTkFont(family=font_family, size=13, weight="bold")
        self._radlex_value_font = ctk.CTkFont(family=font_family, size=20, weight="bold")

        self.accepted: bool | None = None
        self.result: HarmonizedResult | None = None
        self.error: str | None = None
        self._harmonize_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._save_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._running = True
        self._saving = False
        self._closing = False
        self._poll_after_id: str | None = None
        self._pending_save_description: str | None = None
        self._worker_thread: threading.Thread | None = None

        self._bind_current_item()

        self._min_height = self._compute_min_window_height()
        self.resizable(True, True)
        self.minsize(self.MIN_WIDTH, self._min_height)
        self.geometry(f"{self.MIN_WIDTH}x{self._min_height}")
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=0)
        self.grid_columnconfigure(0, weight=1)

        self._create_widgets()
        self._update_batch_header()
        self._populate_dicom_tree()
        self._clear_playbook_tree()
        self._update_window_title()
        self._show_running_state()
        self._start_current_item_worker()

        self.wait_visibility()
        self.grab_set()
        parent.wait_window(self)

    @property
    def _current_item(self) -> HarmonizeSeriesItem:
        return self._items[self._item_index]

    def _bind_current_item(self) -> None:
        item = self._current_item
        self._series_path = item.series_path
        self._ds = item.ds
        self._current_description = item.current_description.strip()

    def _create_widgets(self) -> None:
        char_width_px = self._data_font.measure("A")

        self._header_frame = ctk.CTkFrame(self)
        self._header_frame.grid(row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="ew")
        self._header_frame.grid_columnconfigure(0, weight=1)

        self._study_description_label = ctk.CTkLabel(
            self._header_frame,
            anchor="w",
            justify="left",
            font=self._study_header_font,
            text="",
        )
        self._study_description_label.grid(row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="ew")

        self._series_description_label = ctk.CTkLabel(
            self._header_frame,
            anchor="w",
            justify="left",
            font=self._data_font,
            text="",
        )
        self._series_description_label.grid(row=1, column=0, padx=self.PAD, pady=(4, 0), sticky="ew")

        self._study_context_label = ctk.CTkLabel(
            self._header_frame,
            anchor="w",
            justify="left",
            font=self._data_font,
            text="",
        )
        self._study_context_label.grid(row=2, column=0, padx=self.PAD, pady=(4, self.PAD), sticky="ew")

        self._results_frame = ctk.CTkFrame(self)
        self._results_frame.grid(row=1, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="nsew")
        self._results_frame.grid_rowconfigure(0, weight=self._DICOM_TREE_VISIBLE_ROWS)
        self._results_frame.grid_rowconfigure(1, weight=self._PLAYBOOK_TREE_VISIBLE_ROWS)
        self._results_frame.grid_rowconfigure(2, weight=0)
        self._results_frame.grid_columnconfigure(0, weight=1)

        self._dicom_frame = ctk.CTkFrame(self._results_frame)
        self._dicom_frame.grid(row=0, column=0, padx=0, pady=(0, 0), sticky="nsew")
        self._dicom_frame.grid_rowconfigure(0, weight=0)
        self._dicom_frame.grid_rowconfigure(1, weight=1)
        self._dicom_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._dicom_frame, text=_("DICOM"), anchor="w").grid(
            row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w"
        )
        self._dicom_tree_frame = ctk.CTkFrame(self._dicom_frame, fg_color="transparent")
        self._dicom_tree_frame.grid(row=1, column=0, padx=self.PAD, pady=(0, self.PAD), sticky="nsew")
        self._dicom_tree = self._build_treeview(
            self._dicom_tree_frame,
            column_keys=self._dicom_column_keys,
            attr_map=self._dicom_attr_map,
            char_width_px=char_width_px,
            visible_rows=self._DICOM_TREE_VISIBLE_ROWS,
        )

        self._playbook_frame = ctk.CTkFrame(self._results_frame)
        self._playbook_frame.grid(row=1, column=0, padx=0, pady=(self.PAD, 0), sticky="nsew")
        self._playbook_frame.grid_rowconfigure(0, weight=0)
        self._playbook_frame.grid_rowconfigure(1, weight=1)
        self._playbook_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._playbook_frame, text=_("Playbook harmonization"), anchor="w").grid(
            row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w"
        )
        self._playbook_tree_frame = ctk.CTkFrame(self._playbook_frame, fg_color="transparent")
        self._playbook_tree_frame.grid(row=1, column=0, padx=self.PAD, pady=(0, self.PAD), sticky="nsew")
        self._playbook_tree = self._build_treeview(
            self._playbook_tree_frame,
            column_keys=self._playbook_column_keys,
            attr_map=self._playbook_attr_map,
            char_width_px=char_width_px,
            visible_rows=self._PLAYBOOK_TREE_VISIBLE_ROWS,
        )

        self._proposal_frame = ctk.CTkFrame(self._results_frame)
        self._proposal_frame.grid(row=2, column=0, padx=0, pady=(self.PAD, 0), sticky="ew")
        self._proposal_frame.grid_columnconfigure(0, weight=1)
        self._radlex_title_label = ctk.CTkLabel(
            self._proposal_frame,
            anchor="w",
            justify="left",
            font=self._radlex_title_font,
            text=_("RadLex Series Description") + ":",
        )
        self._radlex_title_label.grid(row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w")
        self._radlex_value_label = ctk.CTkLabel(
            self._proposal_frame,
            anchor="w",
            justify="left",
            font=self._radlex_value_font,
            text="",
        )
        self._radlex_value_label.grid(row=1, column=0, padx=self.PAD, pady=(4, self.PAD), sticky="w")

        self._error_frame = ctk.CTkFrame(self)
        self._error_frame.grid(row=2, column=0, padx=self.PAD, pady=(0, 0), sticky="ew")
        self._error_frame.grid_columnconfigure(0, weight=1)
        self._error_label = ctk.CTkLabel(self._error_frame, anchor="w", justify="left", text="")
        self._error_label.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="w")
        self._error_frame.grid_remove()

        self._footer_frame = ctk.CTkFrame(self)
        self._footer_frame.grid(row=3, column=0, padx=self.PAD, pady=(0, self.PAD), sticky="ew")
        self._footer_frame.grid_columnconfigure(2, weight=1)

        self._status_label = ctk.CTkLabel(
            self._footer_frame,
            font=self._data_font,
            anchor="w",
            text=_("Analyzing scan geometry") + "… (0%)",
        )
        self._status_label.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="w")

        self._progressbar = ctk.CTkProgressBar(self._footer_frame)
        self._progressbar.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="w")
        self._progressbar.set(0)

        self._no_button = ctk.CTkButton(
            self._footer_frame,
            width=self.ButtonWidth,
            text=_("No"),
            command=self._on_no,
            state="disabled",
        )
        self._yes_button = ctk.CTkButton(
            self._footer_frame,
            width=self.ButtonWidth,
            text=_("Yes"),
            command=self._on_yes,
            state="disabled",
        )
        self._ok_button = ctk.CTkButton(
            self._footer_frame,
            width=self.ButtonWidth,
            text=_("OK"),
            command=self._on_ok,
            state="disabled",
        )

    @staticmethod
    def format_study_header(study_description: str, *, phi_header: StudyPhiHeader | None = None) -> str:
        if phi_header is not None and phi_header.study_description.strip():
            text = phi_header.study_description.strip()
        else:
            text = study_description.strip() or _("(no study description)")
        return _("Study") + f": {text}"

    @staticmethod
    def format_series_description_header(*, ds: Dataset, current_description: str) -> str:
        series_desc = current_description.strip() or _("(no series description)")
        series_no = ds.get("SeriesNumber")
        if series_no not in (None, ""):
            return _("Series Description") + f" (#{series_no}): \"{series_desc}\""
        return _("Series Description") + f": \"{series_desc}\""

    @staticmethod
    def format_study_context_line(
        *,
        ds: Dataset | None = None,
        phi_header: StudyPhiHeader | None = None,
        batch_index: int | None = None,
        batch_total: int | None = None,
    ) -> str:
        parts: list[str] = []

        if phi_header is not None:
            patient = phi_header.patient_name.strip()
            patient_id = phi_header.patient_id.strip()
            study_date = phi_header.study_date.strip()
            accession = phi_header.accession_number.strip()
        elif ds is not None:
            patient = str(ds.get("PatientName", "") or "").strip()
            patient_id = str(ds.get("PatientID", "") or "").strip()
            study_date = str(ds.get("StudyDate", "") or "").strip()
            accession = str(ds.get("AccessionNumber", "") or "").strip()
        else:
            patient = patient_id = study_date = accession = ""

        if patient:
            parts.append(f"{_('Patient')}: {patient}")

        if patient_id:
            parts.append(f"{_('ID')}: {patient_id}")

        if study_date:
            parts.append(f"{_('Date')}: {study_date}")

        if accession:
            parts.append(f"{_('Accession')}: {accession}")

        if batch_index is not None and batch_total is not None and batch_total > 1:
            parts.append(_("Batch") + f" {batch_index + 1}/{batch_total}")

        return " · ".join(parts)

    @staticmethod
    def format_study_distilled_summary(
        *,
        ds: Dataset,
        study_description: str,
        current_description: str,
        phi_header: StudyPhiHeader | None = None,
        batch_index: int | None = None,
        batch_total: int | None = None,
    ) -> str:
        return HarmonizeResultsView.format_study_context_line(
            phi_header=phi_header,
            ds=ds if phi_header is None else None,
            batch_index=batch_index,
            batch_total=batch_total,
        )

    @staticmethod
    def format_study_description_line(study_description: str) -> str:
        return HarmonizeResultsView.format_study_header(study_description)

    @staticmethod
    def format_series_header_line(*, ds: Dataset, current_description: str) -> str:
        return HarmonizeResultsView.format_series_description_header(
            ds=ds,
            current_description=current_description,
        )

    @staticmethod
    def format_batch_position_line(*, index: int, total: int) -> str:
        return _("Batch") + f" {index + 1}/{total}"

    def _update_batch_header(self) -> None:
        item = self._current_item
        self._study_description_label.configure(
            text=self.format_study_header(item.study_description, phi_header=item.phi_header)
        )
        self._series_description_label.configure(
            text=self.format_series_description_header(
                ds=item.ds,
                current_description=item.current_description,
            ),
        )
        self._study_context_label.configure(
            text=self.format_study_context_line(
                phi_header=item.phi_header,
                ds=item.ds if item.phi_header is None else None,
                batch_index=self._item_index if self._batch_total > 1 else None,
                batch_total=self._batch_total if self._batch_total > 1 else None,
            ),
        )

    def _update_window_title(self) -> None:
        title = _("Harmonize Description")
        if self._batch_total > 1:
            title += f" ({self._item_index + 1}/{self._batch_total})"
        self.title(title)

    def _tree_row_height_px(self) -> int:
        return max(20, int(self._data_font.metrics("linespace") * 1.15))

    def _tree_block_height_px(self, *, section_label: bool, visible_rows: int) -> int:
        heading_px = self._tree_row_height_px() + 6
        rows_px = visible_rows * self._tree_row_height_px()
        section_px = self._SECTION_LABEL_HEIGHT_PX + self.PAD if section_label else 0
        return section_px + heading_px + rows_px + self.PAD

    def _compute_min_window_height(self) -> int:
        header_lines_px = 3 * self._tree_row_height_px()
        header_px = header_lines_px + (self.PAD * 2) + 12
        dicom_px = self._tree_block_height_px(section_label=True, visible_rows=self._DICOM_TREE_VISIBLE_ROWS)
        playbook_px = self._tree_block_height_px(section_label=True, visible_rows=self._PLAYBOOK_TREE_VISIBLE_ROWS)
        proposal_px = self._SECTION_LABEL_HEIGHT_PX + self._PROPOSAL_VALUE_HEIGHT_PX + (self.PAD * 2)
        chrome_px = header_px + dicom_px + playbook_px + proposal_px + self._FOOTER_HEIGHT_PX + (self.PAD * 3)
        return max(720, chrome_px)

    def _build_treeview(
        self,
        parent: ctk.CTkFrame,
        *,
        column_keys: list[str],
        attr_map: dict[str, tuple[str, int, bool, bool]],
        char_width_px: float,
        visible_rows: int | None = None,
    ) -> ttk.Treeview:
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            parent,
            show="headings",
            columns=column_keys,
            height=visible_rows or 10,
        )
        tree.grid(row=0, column=0, sticky="nsew")

        for col in column_keys:
            col_name, col_width_chars, center, stretch = attr_map[col]
            tree.heading(col, text=col_name)
            width_px = int(max(col_width_chars, len(col_name)) * char_width_px)
            tree.column(
                col,
                width=width_px,
                minwidth=width_px,
                anchor="center" if center else "w",
                stretch=stretch,
            )

        tree.bind("<Left>", lambda _event: "break")
        tree.bind("<Right>", lambda _event: "break")
        tree.bind("<Up>", lambda _event: "break")
        tree.bind("<Down>", lambda _event: "break")
        return tree

    @staticmethod
    def _format_progress_pct(fraction: float) -> str:
        pct = min(100, max(0, int(round(fraction * 100))))
        return f" ({pct}%)"

    def _batch_overall_fraction(self, item_fraction: float) -> float:
        if self._batch_total <= 1:
            return item_fraction
        return (self._item_index + min(1.0, max(0.0, item_fraction))) / self._batch_total

    @staticmethod
    def _status_text_for_progress(progress: HarmonizeProgress) -> str:
        message = (progress.message or "").strip()
        stage = progress.stage
        geometry_prefix = geometry_analysis_progress_prefix()
        pct = HarmonizeResultsView._format_progress_pct(progress.fraction)

        if stage == "done":
            return _("Harmonize analysis complete")

        if stage == "geometry" and message.startswith(geometry_prefix):
            return _("Scan geometry analyzed") + pct
        if stage == "tseg" and message.startswith(geometry_prefix):
            return _("Anatomy analysis not available for this series") + pct

        stage_labels: dict[str, str] = {
            "geometry": _("Analyzing scan geometry"),
            "prepare": _("Preparing CT volume"),
            "segment": _("Segmenting anatomy"),
            "regions": _("Summarizing anatomy regions"),
            "tseg": _("Analyzing anatomy"),
            "contrast": _("Analyzing contrast phase"),
            "contrast_stats": _("Computing organ HU statistics"),
            "contrast_stats_cached": _("Using cached organ HU statistics"),
            "contrast_stats_hn": _("Computing head/neck vessel statistics"),
            "contrast_stats_hn_cached": _("Using cached head/neck vessel statistics"),
            "contrast_stats_hn_skip": _("Head/neck statistics not required"),
            "contrast_xgboost": _("Classifying contrast phase"),
            "contrast_phase_cache": _("Using cached contrast phase classification"),
            "merge": _("Building series description"),
        }

        if stage in stage_labels:
            return stage_labels[stage] + "…" + pct

        known_messages = {
            "Starting contrast phase analysis": _("Starting contrast phase analysis"),
            "Contrast phase analysis complete": _("Contrast phase analysis complete"),
            "Segmenting anatomy": _("Segmenting anatomy"),
            "Preparing CT volume": _("Preparing CT volume"),
            "Summarizing anatomy regions": _("Summarizing anatomy regions"),
            "Building harmonized description": _("Building series description"),
        }
        if message in known_messages:
            return known_messages[message] + pct

        if message:
            return message + pct

        return _("Processing") + "…" + pct

    def _populate_dicom_tree(self) -> None:
        for item in self._dicom_tree.get_children():
            self._dicom_tree.delete(item)
        for field_name, tag, value in harmonize_dicom_rows(self._ds):
            self._dicom_tree.insert("", "end", values=(field_name, tag, value))

    def _clear_playbook_tree(self) -> None:
        for iid in self._playbook_tree.get_children():
            self._playbook_tree.delete(iid)

    def _upsert_playbook_row(self, iid: str, values: tuple[str, str, str, str, str]) -> None:
        """Insert or refresh one Playbook row as pipeline stages complete."""
        if self._playbook_tree.exists(iid):
            self._playbook_tree.item(iid, values=values)
            return
        self._playbook_tree.insert("", "end", iid=iid, values=values)
        self._playbook_tree.see(iid)

    def _update_playbook_from_progress(self, progress: HarmonizeProgress) -> None:
        if progress.geometry is not None and is_localizer_geometry(progress.geometry):
            try:
                attributes = build_localizer_playbook_attributes(self._ds, progress.geometry)
                for iid, values in zip(
                    PLAYBOOK_TREE_IIDS,
                    harmonize_analysis_rows(attributes, geometry=progress.geometry, ds=self._ds),
                    strict=True,
                ):
                    self._upsert_playbook_row(iid, values)
            except ValueError:
                logger.debug(
                    "Playbook localizer rows not yet available for %s",
                    self._series_path,
                    exc_info=True,
                )
            radlex_description = (progress.radlex_series_description or "").strip()
            if radlex_description:
                self._radlex_value_label.configure(text=radlex_description)
                self._proposal_frame.grid()
            return

        if progress.geometry is not None:
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[1],
                playbook_plane_row_values(progress.geometry),
            )
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[3],
                playbook_series_type_row_values(ds=self._ds, geometry=progress.geometry),
            )

        tseg = progress.tseg
        if tseg is not None and tseg.body_parts_present.strip() and tseg.error is None:
            try:
                self._upsert_playbook_row(
                    PLAYBOOK_TREE_IIDS[0],
                    playbook_body_part_row_values(tseg=tseg),
                )
            except ValueError:
                logger.debug("Playbook body part not yet mappable for %s", self._series_path)

        if tseg is not None and tseg.contrast_phase:
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[2],
                playbook_iv_contrast_row_values(tseg=tseg),
            )

        radlex_description = (progress.radlex_series_description or "").strip()
        if radlex_description:
            self._radlex_value_label.configure(text=radlex_description)
            self._proposal_frame.grid()

    def _populate_playbook_from_result(self, result: HarmonizedResult) -> None:
        if result.playbook is None:
            return
        for iid, values in zip(
            PLAYBOOK_TREE_IIDS,
            harmonize_analysis_rows(result.playbook, geometry=result.geometry, ds=self._ds),
            strict=True,
        ):
            self._upsert_playbook_row(iid, values)

    def _user_harmonize_status(self, progress: HarmonizeProgress) -> str:
        return self._status_text_for_progress(progress)

    def _reset_item_ui(self) -> None:
        self.result = None
        self.error = None
        self.accepted = None
        self._running = True
        self._saving = False
        self._harmonize_queue = queue.Queue()
        self._save_queue = queue.Queue()
        self._error_frame.grid_remove()
        self._radlex_value_label.configure(text="")
        self._status_label.configure(text=_("Analyzing scan geometry") + "… (0%)")
        self._progressbar.set(self._batch_overall_fraction(0.0))
        self._populate_dicom_tree()
        self._clear_playbook_tree()
        self._proposal_frame.grid_remove()

    def _show_running_state(self) -> None:
        self._dicom_frame.grid()
        self._playbook_frame.grid()
        self._proposal_frame.grid_remove()
        self._no_button.grid_remove()
        self._yes_button.grid_remove()
        self._ok_button.grid_remove()
        self._no_button.configure(state="disabled")
        self._yes_button.configure(state="disabled")
        self._ok_button.configure(state="disabled")

    def _show_error(self, message: str) -> None:
        self._running = False
        self.error = message
        self._error_label.configure(text=message)
        self._error_frame.grid()
        self._status_label.configure(text=_("Harmonize failed"))
        self._progressbar.set(self._batch_overall_fraction(0.0))
        self._configure_ok_button()

    def _configure_ok_button(self) -> None:
        if self._item_index + 1 < self._batch_total:
            self._ok_button.configure(text=_("Skip") + " →")
        else:
            self._ok_button.configure(text=_("OK"))
        self._ok_button.configure(state="normal")
        self._ok_button.grid(row=0, column=5, padx=(self.PAD, self.PAD), pady=self.PAD, sticky="e")

    def _configure_review_buttons(self, *, already_matches: bool) -> None:
        if already_matches:
            self._configure_ok_button()
            return

        if self._item_index + 1 < self._batch_total:
            self._no_button.configure(text=_("No") + " →")
            self._yes_button.configure(text=_("Yes") + " →")
        else:
            self._no_button.configure(text=_("No"))
            self._yes_button.configure(text=_("Yes"))
        self._no_button.configure(state="normal")
        self._yes_button.configure(state="normal")
        self._no_button.grid(row=0, column=3, padx=(self.PAD, 0), pady=self.PAD, sticky="e")
        self._yes_button.grid(row=0, column=4, padx=(self.PAD, 0), pady=self.PAD, sticky="e")

    def _show_saving_state(self) -> None:
        self._saving = True
        self._running = True
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self._no_button.configure(state="disabled")
        self._yes_button.configure(state="disabled")
        self._ok_button.grid_remove()
        self._error_frame.grid_remove()
        self._status_label.configure(text=_("Saving series description to DICOM") + "…")
        self._progressbar.set(self._batch_overall_fraction(1.0))
        self.update_idletasks()

    def _finish_saving_state(self) -> None:
        self._saving = False
        self._running = False
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _begin_save_accepted_description(self, description: str) -> None:
        self._pending_save_description = description
        self._show_saving_state()
        threading.Thread(
            target=self._save_description_worker,
            args=(self._series_path, description, str(self._ds.SeriesInstanceUID)),
            name="HarmonizeSaveWorker",
            daemon=True,
        ).start()
        self._schedule_poll(self._poll_save_progress)

    def _commit_saved_description(self) -> None:
        if self._pending_save_description is None:
            return
        self._ds.SeriesDescription = self._pending_save_description
        self._pending_save_description = None
        if self._on_series_description_updated is not None:
            self._on_series_description_updated()

    def _save_description_worker(self, series_path: Path, description: str, series_uid: str) -> None:
        try:
            if not apply_series_description(series_path, description):
                self._save_queue.put(("error", _("Failed to write DICOM files.")))
                return
            if self._anon_model is not None:
                update = getattr(self._anon_model, "update_series_description_by_anon_uid", None)
                if update is not None and not update(series_uid, description):
                    self._save_queue.put(("error", _("Failed to update project database.")))
                    return
            self._save_queue.put(("done", None))
        except Exception as exc:
            logger.exception("Harmonize save failed for %s", series_path)
            self._save_queue.put(("error", str(exc)))

    def _poll_save_progress(self) -> None:
        self._poll_after_id = None
        if not self.winfo_exists() or self._closing:
            return

        try:
            kind, payload = self._save_queue.get_nowait()
        except queue.Empty:
            self._schedule_poll(self._poll_save_progress)
            return

        if kind == "done":
            self._finish_saving_state()
            if self.cancelled:
                return
            self._commit_saved_description()
            self.accepted = True
            self._status_label.configure(text=_("Series description saved"))
            self._record_outcome(accepted=True)
            return

        self._finish_saving_state()
        self._show_save_error(str(payload))

    def _show_save_error(self, message: str) -> None:
        self.error = message
        self._error_label.configure(text=message)
        self._error_frame.grid()
        self._status_label.configure(text=_("Could not save series description"))
        self._configure_review_buttons(already_matches=False)

    def _show_harmonize_progress(self, progress: HarmonizeProgress) -> None:
        self._status_label.configure(text=self._user_harmonize_status(progress))
        self._progressbar.set(self._batch_overall_fraction(progress.fraction))
        self._update_playbook_from_progress(progress)

    def _start_current_item_worker(self) -> None:
        self._schedule_poll(self._poll_harmonize_progress)
        self._worker_thread = threading.Thread(
            target=self._harmonize_worker,
            name=f"HarmonizeWorker-{self._item_index + 1}",
            daemon=True,
        )
        self._worker_thread.start()

    def _advance_to_next_item(self) -> None:
        if self._item_index + 1 >= self._batch_total:
            self._close()
            return

        self._item_index += 1
        self._bind_current_item()
        self._update_batch_header()
        self._update_window_title()
        self._reset_item_ui()
        self._show_running_state()
        self._start_current_item_worker()

    def _record_outcome(self, *, accepted: bool | None) -> None:
        self._outcomes.append(
            HarmonizeSeriesOutcome(
                item=self._current_item,
                accepted=accepted,
                result=self.result,
                error=self.error,
            )
        )
        self._advance_to_next_item()

    def _harmonize_worker(self) -> None:
        series_path = self._series_path

        def on_progress(progress: HarmonizeProgress) -> None:
            self._harmonize_queue.put(("progress", progress))

        try:
            results = harmonize_series([series_path], progress=on_progress)
            self._harmonize_queue.put(("done", results))
        except Exception as exc:
            logger.exception("Harmonize failed for %s: %s", series_path, exc)
            self._harmonize_queue.put(("error", exc))

    def _poll_harmonize_progress(self) -> None:
        self._poll_after_id = None
        if not self.winfo_exists() or self._closing:
            return

        while True:
            try:
                kind, payload = self._harmonize_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                self._show_harmonize_progress(payload)
            elif kind == "done":
                self._finish_harmonize(payload)
                return
            elif kind == "error":
                self._show_error(str(payload))
                return

        self._schedule_poll(self._poll_harmonize_progress)

    def _finish_harmonize(self, results: list[HarmonizedResult]) -> None:
        self._running = False
        if not results:
            self._show_error(_("Harmonize could not analyze this series."))
            return

        result = results[0]
        self.result = result

        if result.error is not None:
            self._show_error(result.error)
            return

        self._populate_playbook_from_result(result)
        self._dicom_frame.grid()
        self._playbook_frame.grid()
        self._proposal_frame.grid()

        proposed = (result.radlex_series_description or "").strip()
        already_matches = proposed == self._current_description
        self._radlex_value_label.configure(text=proposed or _("(empty)"))

        if already_matches:
            self.accepted = None
            self._status_label.configure(text=_("Series description already up to date"))
            self._progressbar.set(self._batch_overall_fraction(1.0))
            self._configure_review_buttons(already_matches=True)
            return

        self._status_label.configure(text=_("Harmonize analysis complete"))
        self._progressbar.set(self._batch_overall_fraction(1.0))
        self._configure_review_buttons(already_matches=False)

    def _on_yes(self) -> None:
        if self.result is None or self.result.error is not None:
            return
        proposed = (self.result.radlex_series_description or "").strip()
        if not proposed:
            self._show_save_error(_("No harmonized description to save."))
            return
        self._begin_save_accepted_description(proposed)

    def _on_no(self) -> None:
        self.accepted = False
        self._record_outcome(accepted=False)

    def _on_ok(self) -> None:
        accepted = False if self.error is not None else None
        self.accepted = accepted
        self._record_outcome(accepted=accepted)

    def _on_cancel(self) -> None:
        if self._saving or self._closing:
            return
        logger.info("_on_cancel")
        if self._running:
            self.cancelled = True
            self.accepted = False
        elif self._batch_total > 1 and len(self._outcomes) < self._batch_total:
            self.cancelled = True
        elif self.accepted is None and self.result is not None:
            pass
        elif self.accepted is None:
            self.accepted = False
        self._close()

    def _escape_keypress(self, _event=None) -> None:
        self._on_cancel()

    def _schedule_poll(self, callback) -> None:
        if self._closing:
            return
        self._poll_after_id = self.after(self.ux_poll_interval_ms, callback)

    def _cancel_scheduled_polls(self) -> None:
        if self._poll_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self._running = False

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self._cancel_scheduled_polls()
        self.destroy()


def show_harmonize_results_view(
    parent: tk.Misc,
    *,
    items: Sequence[HarmonizeSeriesItem] | None = None,
    series_path: Path | None = None,
    ds: Dataset | None = None,
    current_description: str | None = None,
    mono_font: ctk.CTkFont | None = None,
    anon_model=None,
    on_series_description_updated: Callable[[], None] | None = None,
) -> HarmonizeBatchOutcome:
    """
    Open harmonize view modally; runs analysis per item and returns batch outcomes.

    Pass ``items`` for multi-series batches (e.g. from a study-selection view), or the legacy
    ``series_path`` / ``ds`` / ``current_description`` arguments for a single series.
    """
    if items is None:
        if series_path is None or ds is None:
            raise ValueError("show_harmonize_results_view requires items or series_path and ds")
        phi_header = None
        if anon_model is not None:
            resolve = getattr(anon_model, "get_study_phi_header_by_anon_study_uid", None)
            if resolve is not None:
                phi_header = resolve(str(ds.StudyInstanceUID))
        items = [
            HarmonizeSeriesItem(
                series_path=series_path,
                ds=ds,
                study_description=str(ds.get("StudyDescription", "") or "").strip(),
                current_description=(current_description or str(ds.get("SeriesDescription", "") or "")).strip(),
                phi_header=phi_header,
            )
        ]

    view = HarmonizeResultsView(
        parent,
        items=items,
        mono_font=mono_font,
        anon_model=anon_model,
        on_series_description_updated=on_series_description_updated,
    )
    if view.cancelled and not view._outcomes:
        return HarmonizeBatchOutcome(outcomes=[], cancelled=True)
    if view.cancelled:
        return HarmonizeBatchOutcome(outcomes=view._outcomes, cancelled=True)
    if view._outcomes:
        return HarmonizeBatchOutcome(outcomes=view._outcomes, cancelled=False)

    # Window closed before recording (e.g. escape during first run).
    return HarmonizeBatchOutcome(
        outcomes=[
            HarmonizeSeriesOutcome(
                item=view._items[view._item_index],
                accepted=view.accepted,
                result=view.result,
                error=view.error,
            )
        ],
        cancelled=view.cancelled,
    )
