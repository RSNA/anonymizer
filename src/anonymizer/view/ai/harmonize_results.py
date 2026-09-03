"""Harmonize results view: batch-aware analysis progress, Treeview tables, and Playbook proposal."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk
from pydicom import Dataset

from anonymizer.controller.ai.harmonize import (
    HarmonizedResult,
    HarmonizeProgress,
    apply_harmonized_description,
    format_harmonize_progress_message,
    harmonize_series,
    maybe_offer_study_description_harmonize,
)
from anonymizer.controller.ai.harmonize.playbook import (
    PLAYBOOK_TREE_IIDS,
    build_localizer_playbook_attributes,
    harmonize_analysis_rows,
    harmonize_dicom_rows,
    is_localizer_geometry,
    playbook_body_part_row_values,
    playbook_iv_contrast_row_values,
    playbook_plane_row_values,
    playbook_series_type_modifier_row_values,
    playbook_series_type_row_values,
    playbook_slice_thickness_row_values,
)
from anonymizer.controller.runner import Algorithm
from anonymizer.controller.work_state import WorkState
from anonymizer.model.anonymizer import StudyPhiHeader
from anonymizer.utils.modalities import is_mr_modality
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.availability import brain_structures_allowed
from anonymizer.view.ai.features.catalog import AiFeatureId, feature_description
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.common.job_poller import STAGE_POLL_MS, start_background_job

logger = logging.getLogger(__name__)

# In-flight Harmonize windows keyed by anon SeriesInstanceUID (or resolved series path).
# At most one Harmonize dialog may be open app-wide (TotalSegmentator is not process-safe concurrently).
_open_harmonize_by_series_key: dict[str, HarmonizeResultsView] = {}


def _series_key_for_items(items: Sequence[HarmonizeSeriesItem]) -> str:
    first = items[0]
    uid = str(getattr(first.ds, "SeriesInstanceUID", "") or "").strip()
    if uid:
        return uid
    return str(Path(first.series_path).resolve())


def focus_harmonize_view(view: HarmonizeResultsView) -> None:
    """Bring an existing Harmonize window forward."""
    with contextlib.suppress(tk.TclError):
        if not view.winfo_exists():
            return
        view.deiconify()
        view.lift()
        view.focus_force()


def get_open_harmonize_view(series_key: str) -> HarmonizeResultsView | None:
    view = _open_harmonize_by_series_key.get(series_key)
    if view is None:
        return None
    try:
        if view.winfo_exists():
            return view
    except tk.TclError:
        pass
    _open_harmonize_by_series_key.pop(series_key, None)
    return None


def get_any_open_harmonize_view() -> HarmonizeResultsView | None:
    """Return any live Harmonize window (at most one should exist app-wide)."""
    for key, view in list(_open_harmonize_by_series_key.items()):
        try:
            if view.winfo_exists():
                return view
        except tk.TclError:
            pass
        _open_harmonize_by_series_key.pop(key, None)
    return None


def brain_structures_option_available_for_series(ds: Dataset | None) -> bool:
    """True when manual Harmonize can offer the brain-structures option (CT series only)."""
    if ds is None:
        return False
    modality = getattr(ds, "Modality", None)
    if is_mr_modality(modality):
        return False
    return str(modality or "").strip().upper() == "CT"


def series_is_ct_head_candidate(series_path: Path, ds: Dataset | None) -> bool:
    """True when cached anatomy or DICOM metadata indicates a head-dominant CT study."""
    if not brain_structures_option_available_for_series(ds):
        return False
    from anonymizer.controller.ai.blur_face.pipeline import (
        CachedRegionSignal,
        MetadataSignal,
        cached_region_signal,
        metadata_signal,
    )

    region_signal = cached_region_signal(series_path)
    if region_signal == CachedRegionSignal.HEAD:
        return True
    if region_signal in (CachedRegionSignal.NON_HEAD, CachedRegionSignal.MULTI_REGION):
        return False
    return metadata_signal(ds) == MetadataSignal.HEAD


def should_prompt_brain_structures_for_series(series_path: Path, ds: Dataset | None) -> bool:
    """True when Harmonize should ask whether to run detailed brain structure segmentation."""
    return series_is_ct_head_candidate(series_path, ds) and brain_structures_allowed()


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


class HarmonizeResultsView(AppToplevel):
    """
    Series View–scoped dialog (blocks launching Series View only): runs the pipeline per
    selected series, shows progress, then Playbook results.

    Does not use application-wide ``grab_set`` / ``wait_window`` so Dataset and other
    windows remain usable. The launching Series View disables its own controls while open.

    A study-description header at the top updates as the view iterates through a batch of series
    (single-series use passes one ``HarmonizeSeriesItem``).

    Layout follows ``QueryView`` in ``query_retrieve_import.py``:
    batch header, results frames, optional error frame, footer (status + progress + buttons).
    """

    ux_poll_interval_ms = STAGE_POLL_MS

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
        "field": ("Field", 30, False, False),
        "tag": ("Tag", 13, False, False),
        "value": ("Value", 65, False, True),
    }
    _dicom_column_keys = list(_dicom_attr_map.keys())

    _playbook_attr_map: dict[str, tuple[str, int, bool, bool]] = {
        "element": ("Element", 20, False, False),
        "code": ("Code", 13, False, False),
        "value": ("Value", 22, False, False),
        "evidence": ("Evidence", 34, False, True),
        "source": ("Source", 34, False, True),
    }
    _playbook_column_keys = list(_playbook_attr_map.keys())

    def __init__(
        self,
        parent: tk.Misc,
        *,
        items: Sequence[HarmonizeSeriesItem],
        fonts: AppFonts | None = None,
        anon_model=None,
        on_series_description_updated: Callable[[], None] | None = None,
        on_closed: Callable[[HarmonizeBatchOutcome], None] | None = None,
        include_brain_structures: bool = False,
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
        self._on_closed = on_closed
        self._series_key = _series_key_for_items(self._items)
        self._include_brain_structures_for_current_run = False
        self._closed_notified = False

        self._data_font = fonts.mono if fonts else ctk.CTkFont(family="Menlo", size=12)
        self._study_header_font = fonts.bold if fonts else ctk.CTkFont(size=14, weight="bold")
        self._radlex_title_font = fonts.bold if fonts else ctk.CTkFont(size=13, weight="bold")
        self._radlex_value_font = fonts.heading if fonts else ctk.CTkFont(size=20, weight="bold")

        self.accepted: bool | None = None
        self.result: HarmonizedResult | None = None
        self.error: str | None = None
        self._harmonize_work_state = WorkState()
        self._save_work_state = WorkState()
        self._running = True
        self._saving = False
        self._closing = False
        self._pending_save_description: str | None = None

        self._bind_current_item()

        self._min_height = self._compute_min_window_height()
        self.resizable(True, True)
        self.minsize(self.MIN_WIDTH, self._min_height)
        self.geometry(f"{self.MIN_WIDTH}x{self._min_height}")
        with contextlib.suppress(tk.TclError):
            self.transient(parent)
        self.lift()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)
        self.bind("<Destroy>", self._on_destroy, add="+")

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
        _open_harmonize_by_series_key[self._series_key] = self
        self._start_current_item_worker()

    def batch_outcome(self) -> HarmonizeBatchOutcome:
        """Snapshot of recorded outcomes for ``on_closed`` / tests."""
        if self.cancelled and not self._outcomes:
            return HarmonizeBatchOutcome(outcomes=[], cancelled=True)
        if self.cancelled:
            return HarmonizeBatchOutcome(outcomes=list(self._outcomes), cancelled=True)
        if self._outcomes:
            return HarmonizeBatchOutcome(outcomes=list(self._outcomes), cancelled=False)
        return HarmonizeBatchOutcome(
            outcomes=[
                HarmonizeSeriesOutcome(
                    item=self._items[self._item_index],
                    accepted=self.accepted,
                    result=self.result,
                    error=self.error,
                )
            ],
            cancelled=self.cancelled,
        )

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

        self._cancel_button = ctk.CTkButton(
            self._footer_frame,
            width=self.ButtonWidth,
            text=_("Cancel"),
            command=self._on_cancel,
        )

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
            return _("Series Description") + f' (#{series_no}): "{series_desc}"'
        return _("Series Description") + f': "{series_desc}"'

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

    @staticmethod
    def _column_heading(msgid: str) -> str:
        headings = {
            "Field": _("Field"),
            "Tag": _("Tag"),
            "Value": _("Value"),
            "Element": _("Element"),
            "Code": _("Code"),
            "Evidence": _("Evidence"),
            "Source": _("Source"),
        }
        return headings.get(msgid, _(msgid))

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
            tree.heading(col, text=HarmonizeResultsView._column_heading(col_name))
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
        return format_harmonize_progress_message(progress)

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
                playbook_slice_thickness_row_values(geometry=progress.geometry, ds=self._ds),
            )
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[4],
                playbook_series_type_row_values(ds=self._ds, geometry=progress.geometry),
            )
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[5],
                playbook_series_type_modifier_row_values(geometry=progress.geometry, ds=self._ds),
            )

        tseg = progress.tseg
        if tseg is not None and tseg.body_parts_present.strip() and tseg.error is None:
            try:
                self._upsert_playbook_row(
                    PLAYBOOK_TREE_IIDS[0],
                    playbook_body_part_row_values(tseg=tseg, ds=self._ds),
                )
            except ValueError:
                logger.debug("Playbook body part not yet mappable for %s", self._series_path)

        if is_mr_modality(getattr(self._ds, "Modality", None)):
            self._upsert_playbook_row(
                PLAYBOOK_TREE_IIDS[2],
                playbook_iv_contrast_row_values(ds=self._ds),
            )
        elif tseg is not None and tseg.contrast_phase:
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
            harmonize_analysis_rows(
                result.playbook,
                geometry=result.geometry,
                ds=self._ds,
                tseg=result.tseg,
            ),
            strict=True,
        ):
            self._upsert_playbook_row(iid, values)

    def _prompt_brain_structures_for_current_series(self) -> bool:
        if not should_prompt_brain_structures_for_series(self._series_path, self._ds):
            return False
        description = feature_description(AiFeatureId.BRAIN_STRUCTURES.value)
        return messagebox.askyesno(
            title=_("Brain structures"),
            message=_("This appears to be a CT head study. Run detailed brain structure segmentation?")
            + "\n\n"
            + description,
            default="no",
            parent=self,
        )

    def _user_harmonize_status(self, progress: HarmonizeProgress) -> str:
        from anonymizer.controller.ai.tseg.config import segmentation_mode_for_modality

        return format_harmonize_progress_message(
            progress,
            segmentation_mode=segmentation_mode_for_modality(getattr(self._ds, "Modality", None)),
        )

    def _reset_item_ui(self) -> None:
        self.result = None
        self.error = None
        self.accepted = None
        self._running = True
        self._saving = False
        self._harmonize_work_state.prepare_job()
        self._save_work_state.prepare_job()
        self._error_frame.grid_remove()
        self._radlex_value_label.configure(text="")
        self._status_label.configure(text=_("Analyzing scan geometry") + "… (0%)")
        self._progressbar.set(self._batch_overall_fraction(0.0))
        self._populate_dicom_tree()
        self._clear_playbook_tree()
        self._include_brain_structures_for_current_run = False
        self._proposal_frame.grid_remove()

    def _show_cancel_button(self, *, enabled: bool = True) -> None:
        self._cancel_button.configure(state="normal" if enabled else "disabled")
        self._cancel_button.grid(row=0, column=2, padx=(self.PAD, self.PAD), pady=self.PAD, sticky="e")

    def _hide_cancel_button(self) -> None:
        self._cancel_button.grid_remove()

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
        self._show_cancel_button()

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
        self._show_cancel_button()

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
        self._show_cancel_button()

    def _show_saving_state(self) -> None:
        self._saving = True
        self._running = True
        self.protocol("WM_DELETE_WINDOW", lambda: None)
        self._no_button.configure(state="disabled")
        self._yes_button.configure(state="disabled")
        self._ok_button.grid_remove()
        self._show_cancel_button(enabled=False)
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
        self._save_work_state.prepare_job()
        series_path = self._series_path
        series_uid = str(self._ds.SeriesInstanceUID)

        def _worker() -> None:
            self._save_description_job(series_path, description, series_uid)

        start_background_job(
            self,
            work_state=self._save_work_state,
            algorithm=Algorithm.HARMONIZE,
            worker_target=_worker,
            on_done=self._on_save_job_done,
            poll_ms=self.ux_poll_interval_ms,
        )

    def _commit_saved_description(self) -> None:
        if self._pending_save_description is None:
            return
        self._ds.SeriesDescription = self._pending_save_description
        self._pending_save_description = None
        self._notify_series_description_updated()

    def _apply_current_harmonized_description_if_unchanged(self) -> None:
        """Record harmonized metadata when DICOM already matches the Playbook proposal."""
        if self.result is None or self.result.error is not None:
            return
        proposed = (self.result.radlex_series_description or "").strip()
        if not proposed or proposed != self._current_description:
            return
        # DICOM already matches; persist ORM flag on the UI thread.
        if self._persist_harmonized_metadata(proposed):
            self._maybe_offer_study_description()

    def _notify_series_description_updated(self) -> None:
        if self._on_series_description_updated is not None:
            self._on_series_description_updated()

    def _save_description_job(self, series_path: Path, description: str, series_uid: str) -> None:
        """Write SeriesDescription to DICOM on a worker thread (ORM update is main-thread)."""
        try:
            # anon_model=None: avoid SQLite/scoped-session writes off the UI thread.
            if not apply_harmonized_description(series_path, description, None):
                self._save_work_state.fail(_("Failed to write DICOM files."))
                return
            self._save_work_state.finish(series_uid)
        except Exception as exc:
            logger.exception("Harmonize save failed for %s", series_path)
            self._save_work_state.fail(str(exc))

    def _persist_harmonized_metadata(self, description: str) -> bool:
        """Record series harmonized_description in the project DB (must run on UI thread)."""
        if self._anon_model is None:
            return True
        series_uid = str(self._ds.SeriesInstanceUID)
        ok = self._anon_model.set_series_harmonized_description(series_uid, description.strip())
        if not ok:
            logger.error(
                "Failed to set harmonized_description for series_uid=%s description=%r",
                series_uid,
                description,
            )
        return ok

    def _maybe_offer_study_description(self) -> None:
        """Auto-apply or offer LOINC StudyDescription when this apply completes the study."""
        if self._anon_model is None or self._closing or not self.winfo_exists():
            return
        anon_study_uid = str(self._ds.StudyInstanceUID)
        images_dir = Path(self._series_path).resolve().parent.parent.parent
        offer = maybe_offer_study_description_harmonize(
            self._anon_model,
            anon_study_uid,
            images_dir=images_dir,
        )
        if offer is None:
            return
        from anonymizer.view.ai.study_description_dialog import resolve_and_show_study_description_offers

        resolve_and_show_study_description_offers(
            self,
            offers=[offer],
            images_dir=images_dir,
            anon_model=self._anon_model,
            on_auto_applied=lambda _offer, updated: logger.info(
                "Auto-applied LOINC study description to %d study(ies)",
                len(updated),
            ),
        )

    def _on_save_job_done(self, _algorithm: Algorithm | None, work_state: WorkState) -> None:
        if self._closing or not self.winfo_exists():
            return
        if work_state.error:
            self._finish_saving_state()
            self._show_save_error(work_state.error)
            return
        description = (self._pending_save_description or "").strip()
        if description and not self._persist_harmonized_metadata(description):
            self._finish_saving_state()
            self._show_save_error(_("Failed to update project database."))
            # DICOM already matches the proposal; keep in-memory UI in sync with disk.
            self._commit_saved_description()
            return
        self._finish_saving_state()
        if self.cancelled:
            return
        self._commit_saved_description()
        self.accepted = True
        self._status_label.configure(text=_("Series description saved"))
        self._maybe_offer_study_description()
        self._record_outcome(accepted=True)

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
        self._include_brain_structures_for_current_run = self._prompt_brain_structures_for_current_series()
        self._harmonize_work_state.prepare_job()

        def _worker() -> None:
            self._run_harmonize_job()

        start_background_job(
            self,
            work_state=self._harmonize_work_state,
            algorithm=Algorithm.HARMONIZE,
            worker_target=_worker,
            on_tick=self._on_harmonize_job_tick,
            on_done=self._on_harmonize_job_done,
            poll_ms=self.ux_poll_interval_ms,
        )

    def _on_harmonize_job_tick(self, work_state: WorkState) -> None:
        if self._closing or not self.winfo_exists():
            return
        _status, _done, _fraction, _error, _result, detail = work_state.read_job_ui()
        if isinstance(detail, HarmonizeProgress):
            self._show_harmonize_progress(detail)
        elif work_state.status:
            self._status_label.configure(text=work_state.status)
            self._progressbar.set(self._batch_overall_fraction(_fraction))

    def _on_harmonize_job_done(self, _algorithm: Algorithm | None, work_state: WorkState) -> None:
        if self._closing or not self.winfo_exists():
            return
        if self.cancelled or work_state.should_cancel() or work_state.result is None:
            return
        if work_state.error:
            self._show_error(work_state.error)
            return
        results = work_state.result
        if not isinstance(results, list):
            self._show_error(_("Harmonize could not analyze this series."))
            return
        self._finish_harmonize(results)

    def _run_harmonize_job(self) -> None:
        series_path = self._series_path
        work_state = self._harmonize_work_state

        def _is_cancelled() -> bool:
            return self.cancelled or work_state.should_cancel()

        def on_progress(progress: HarmonizeProgress) -> None:
            if _is_cancelled():
                return
            work_state.update_job_progress(
                status=self._user_harmonize_status(progress),
                fraction=progress.fraction,
                detail=progress,
            )

        try:
            results = harmonize_series(
                [series_path],
                progress=on_progress,
                include_brain_structures=self._include_brain_structures_for_current_run,
                anon_model=self._anon_model,
                cancelled=_is_cancelled,
            )
        except Exception as exc:
            if not _is_cancelled():
                logger.exception("Harmonize failed for %s: %s", series_path, exc)
                work_state.fail(str(exc))
            return

        if _is_cancelled():
            logger.info("Harmonize worker finished after cancel for %s", series_path)
            work_state.finish(None)
        else:
            work_state.finish(results)

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
        if self.error is None and self.result is not None and not self.result.error:
            self._apply_current_harmonized_description_if_unchanged()
            self._notify_series_description_updated()

    def _on_cancel(self) -> None:
        if self._saving or self._closing:
            return
        logger.info("_on_cancel")
        if self._running:
            self.cancelled = True
            self.accepted = False
            self._harmonize_work_state.request_cancel()
            self._save_work_state.request_cancel()
        elif self._batch_total > 1 and len(self._outcomes) < self._batch_total:
            self.cancelled = True
        elif self.accepted is None:
            self.cancelled = True
            self.accepted = False
        self._close()

    def _escape_keypress(self, _event=None) -> None:
        self._on_cancel()

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        if self._closing:
            if _open_harmonize_by_series_key.get(self._series_key) is self:
                _open_harmonize_by_series_key.pop(self._series_key, None)
            return
        # Parent Series View destroy cascades without WM_DELETE_WINDOW.
        self._harmonize_work_state.request_cancel()
        self._save_work_state.request_cancel()
        if _open_harmonize_by_series_key.get(self._series_key) is self:
            _open_harmonize_by_series_key.pop(self._series_key, None)
        if self._on_closed is not None and not self._closed_notified:
            self._closed_notified = True
            self._closing = True
            self._running = False
            self._on_closed(self.batch_outcome())

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._harmonize_work_state.request_cancel()
        self._save_work_state.request_cancel()
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self._running = False
        if _open_harmonize_by_series_key.get(self._series_key) is self:
            _open_harmonize_by_series_key.pop(self._series_key, None)
        outcome = self.batch_outcome()
        on_closed = self._on_closed
        parent = self.master
        teardown_ctk_toplevel(self, parent=parent)
        if on_closed is not None and not self._closed_notified:
            self._closed_notified = True
            on_closed(outcome)


def show_harmonize_results_view(
    parent: tk.Misc,
    *,
    items: Sequence[HarmonizeSeriesItem] | None = None,
    series_path: Path | None = None,
    ds: Dataset | None = None,
    current_description: str | None = None,
    fonts: AppFonts | None = None,
    anon_model=None,
    on_series_description_updated: Callable[[], None] | None = None,
    on_closed: Callable[[HarmonizeBatchOutcome], None] | None = None,
    include_brain_structures: bool = False,
) -> HarmonizeResultsView:
    """
    Open Harmonize as a Series View–scoped dialog (non-blocking for the rest of the app).

    Pass ``items`` for multi-series batches (e.g. from a study-selection view), or the legacy
    ``series_path`` / ``ds`` / ``current_description`` arguments for a single series.

    If a Harmonize window is already open for any series, focuses it and returns that view
    without starting a second job. Callers should pass ``on_closed`` for post-close UI refresh.
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

    series_key = _series_key_for_items(items)
    existing = get_open_harmonize_view(series_key) or get_any_open_harmonize_view()
    if existing is not None:
        focus_harmonize_view(existing)
        return existing

    return HarmonizeResultsView(
        parent,
        items=items,
        fonts=fonts,
        anon_model=anon_model,
        on_series_description_updated=on_series_description_updated,
        on_closed=on_closed,
        include_brain_structures=include_brain_structures,
    )
