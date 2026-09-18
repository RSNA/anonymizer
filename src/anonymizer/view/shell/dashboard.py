import contextlib
import logging
import os
import threading
from queue import Queue
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from anonymizer.controller.analytics import default_selected_organ_names, organ_display_name
from anonymizer.controller.project import EchoRequest, EchoResponse, ProjectController
from anonymizer.model.anonymizer import Totals
from anonymizer.utils.memory import schedule_collect_garbage_on_tk
from anonymizer.utils.storage import count_quarantine_images, count_studies_series_images
from anonymizer.utils.translate import _
from anonymizer.view.common.ctk_safe import release_mpl_frame_images
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.shell.analytics_charts import (
    ANALYTICS_SCROLL_MIN_HEIGHT,
    analytics_scroll_height,
    analytics_scrollbar_needed,
    configure_granular_scroll,
)

logger = logging.getLogger(__name__)


class Dashboard(ctk.CTkFrame):
    """
    A class representing the dashboard view of the anonymizer application.

    Args:
        parent: The parent widget.
        query_callback: The callback function for the query button.
        export_callback: The callback function for the export button.
        controller: The project controller.

    Attributes:
        AWS_AUTH_TIMEOUT_SECONDS (int): The timeout duration for AWS authentication.
        PAD (int): The padding value.
        BUTTON_WIDTH (int): The width of buttons.
        _label_font (ctk.CTkFont): The font for labels.
        _data_font (ctk.CTkFont): The font for data.
        _last_qsize (int): The previous size of the queue.
        _latch_max_qsize (int): The maximum size of the queue.
        _query_callback (Any): The callback function for the query button.
        _export_callback (Any): The callback function for the export button.
        _controller (ProjectController): The project controller.
        _timer (int): The timer for AWS authentication.
        _query_ux_Q (Queue[EchoResponse]): The queue for query responses.
        _export_ux_Q (Queue[EchoResponse]): The queue for export responses.
        _patients (int): The number of patients.
        _studies (int): The number of studies.
        _series (int): The number of series.
        _images (int): The number of images.
    """

    AWS_AUTH_TIMEOUT_SECONDS = 15  # must be > 2 secs
    PAD = 20
    BUTTON_WIDTH = 100
    # Volumes organ picker: cap height (~10–12 rows); scroll when the list is longer.
    _VOLUMES_DROPDOWN_MAX_HEIGHT_PX = 300

    def __init__(self, parent, query_callback, export_callback, view_callback, controller: ProjectController, *, fonts: AppFonts):
        super().__init__(master=parent)
        self._fonts = fonts
        self._data_font = fonts.mono_large
        self._last_qsize = 0
        self._latch_max_qsize = 1
        self._query_callback = query_callback
        self._export_callback = export_callback
        self._view_callback = view_callback
        self._controller: ProjectController = controller
        self._timer = 0
        self._query_ux_Q: Queue[EchoResponse] = Queue()
        self._export_ux_Q: Queue[EchoResponse] = Queue()
        self._patients = 0
        self._studies = 0
        self._series = 0
        self._images = 0
        self._create_widgets()
        self.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)

    def _create_widgets(self):
        logger.debug("_create_widgets")

        row = 0

        self._query_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Search"),
            command=self._query_button_click,
        )
        self._query_button.grid(row=row, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="w")

        self._view_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("View"),
            command=self._view_button_click,
        )
        self._view_button.grid(row=row, column=1, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        self._send_button = ctk.CTkButton(
            self,
            width=self.BUTTON_WIDTH,
            text=_("Send"),
            command=self._send_button_click,
        )
        self._send_button.grid(row=row, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        row += 1

        self._databoard = ctk.CTkFrame(self)
        db_row = 0

        self._label_patients = ctk.CTkLabel(self._databoard, font=self._fonts.label_large, text=_("Patients"))
        self._label_studies = ctk.CTkLabel(self._databoard, font=self._fonts.label_large, text=_("Studies"))
        self._label_series = ctk.CTkLabel(self._databoard, font=self._fonts.label_large, text=_("Series"))
        self._label_images = ctk.CTkLabel(self._databoard, font=self._fonts.label_large, text=_("Images"))
        self._label_quarantine = ctk.CTkLabel(self._databoard, font=self._fonts.label_large, text=_("Quarantine"))

        self._label_patients.grid(row=db_row, column=0, padx=self.PAD, pady=(self.PAD, 0))
        self._label_studies.grid(row=db_row, column=1, padx=self.PAD, pady=(self.PAD, 0))
        self._label_series.grid(row=db_row, column=2, padx=self.PAD, pady=(self.PAD, 0))
        self._label_images.grid(row=db_row, column=3, padx=self.PAD, pady=(self.PAD, 0))
        self._label_quarantine.grid(row=db_row, column=4, padx=self.PAD, pady=(self.PAD, 0))

        db_row += 1

        self._patients_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._studies_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._series_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._images_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")
        self._quarantined_label = ctk.CTkLabel(self._databoard, font=self._data_font, text="0")

        self._patients_label.grid(row=db_row, column=0, padx=self.PAD, pady=(0, self.PAD))
        self._studies_label.grid(row=db_row, column=1, padx=self.PAD, pady=(0, self.PAD))
        self._series_label.grid(row=db_row, column=2, padx=self.PAD, pady=(0, self.PAD))
        self._images_label.grid(row=db_row, column=3, padx=self.PAD, pady=(0, self.PAD))
        self._quarantined_label.grid(row=db_row, column=4, padx=self.PAD, pady=(0, self.PAD))

        db_row += 1

        self._databoard.grid(
            row=row,
            column=0,
            columnspan=4,
            padx=self.PAD,
            pady=(self.PAD, 0),
            sticky="n",
        )

        row += 1

        self._status_frame = ctk.CTkFrame(self)
        self._status_frame.columnconfigure(2, weight=1)
        self._status_frame.grid(
            row=row,
            column=0,
            columnspan=4,
            sticky="nsew",
            padx=self.PAD,
            pady=(self.PAD, 0),
        )

        self.label_metadata_queue = ctk.CTkLabel(self._status_frame, text=_("Metadata Queue") + ":")
        self.label_metadata_queue.grid(row=0, column=0, padx=self.PAD, sticky="w")

        self._meta_qsize = ctk.CTkLabel(self._status_frame, text="0")
        self._meta_qsize.grid(row=0, column=1, sticky="w")

        self._status = ctk.CTkLabel(self._status_frame, text="")
        self._status.grid(row=0, column=2, padx=self.PAD, sticky="e")

        row += 1
        self._analytics_expanded = False
        self._analytics_header = ctk.CTkFrame(self, fg_color="transparent")
        self._analytics_header.grid(row=row, column=0, columnspan=4, sticky="ew", padx=self.PAD, pady=(self.PAD, 0))
        self._analytics_header.grid_columnconfigure(3, weight=1)
        # Hidden until the project has at least one study.
        self._analytics_header.grid_remove()

        self._analytics_expand_btn = ctk.CTkButton(
            self._analytics_header,
            width=self.BUTTON_WIDTH,
            text=self._analytics_expand_btn_label(False),
            command=self._analytics_toggle_expand,
        )
        self._analytics_expand_btn.grid(row=0, column=0, sticky="w")

        # Volumes control lives in the header chrome (not the board layout).
        self._volumes_label = ctk.CTkLabel(self._analytics_header, text=_("Volumes"), anchor="w")
        self._volumes_label.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self._volumes_label.bind("<Button-1>", lambda _e: self._toggle_volumes_picker())
        self._volumes_label.grid_remove()

        self._volumes_expand_btn = ctk.CTkButton(
            self._analytics_header,
            width=28,
            text="▸",
            command=self._toggle_volumes_picker,
        )
        self._volumes_expand_btn.grid(row=0, column=2, sticky="w", padx=(6, 0))
        self._volumes_expand_btn.grid_remove()

        self._analytics_updated = ctk.CTkLabel(self._analytics_header, text="", text_color="gray")
        self._analytics_updated.grid(row=0, column=3, sticky="e", padx=(8, 8))

        self._analytics_refresh_btn = ctk.CTkButton(
            self._analytics_header,
            width=80,
            text=_("Refresh"),
            command=self._request_analytics_refresh,
        )
        # Create + grid once, then hide (same pattern as QueryView._error_frame).
        self._analytics_refresh_btn.grid(row=0, column=4, sticky="e")
        self._analytics_refresh_btn.grid_remove()

        row += 1
        # Scrollable analytics viewport: grows with content up to a screen-height
        # fraction, then scrolls — keeps the project window from ballooning.
        self._analytics_scroll = ctk.CTkScrollableFrame(
            self,
            height=ANALYTICS_SCROLL_MIN_HEIGHT,
            fg_color="transparent",
        )
        configure_granular_scroll(self._analytics_scroll)
        self._analytics_scroll.grid(
            row=row,
            column=0,
            columnspan=4,
            sticky="nsew",
            padx=self.PAD,
            pady=(6, self.PAD),
        )
        self._analytics_scroll.grid_remove()
        # Hidden until content overflows (CTk always creates the bar).
        self._set_analytics_scrollbar_visible(False)
        # Content host inside the scrollable frame (safe to clear on refresh).
        self._analytics_board = ctk.CTkFrame(self._analytics_scroll, fg_color="transparent")
        self._analytics_board.pack(fill="both", expand=True)

        self._analytics_cache = None
        self._analytics_busy = False
        self._analytics_ux_Q: Queue[tuple[str, object]] = Queue()
        self._analytics_poll_after_id: str | None = None
        self._analytics_poll_ms = 200
        # None until first snapshot; then the user's Volumes-picker checks.
        self._analytics_selected_organs: set[str] | None = None
        self._volumes_picker_expanded = False
        self._organ_picker_vars: dict[str, ctk.BooleanVar] = {}
        self._analytics_flow_host: ctk.CTkFrame | None = None
        self._volumes_dropdown: ctk.CTkFrame | None = None
        self._volumes_dropdown_dismiss_after_id: str | None = None
        self._volumes_outside_bind_id: str | None = None
        self._project_size_sync_after_id: str | None = None
        self._project_size_sync_grow_only = False

    def _sync_project_window_size(self, *, grow_only: bool = False) -> None:
        """Fit the fixed project window to the dashboard — coalesced to one idle pass."""
        if self._project_size_sync_after_id is not None:
            # Full sync wins over a pending grow-only pass.
            if not grow_only:
                self._project_size_sync_grow_only = False
            return
        self._project_size_sync_grow_only = grow_only
        self._project_size_sync_after_id = self.after_idle(self._run_project_window_size_sync)

    def _run_project_window_size_sync(self) -> None:
        self._project_size_sync_after_id = None
        grow_only = self._project_size_sync_grow_only
        self._project_size_sync_grow_only = False
        if not self.winfo_exists():
            return
        root = self.winfo_toplevel()
        apply = getattr(root, "_apply_project_window_size", None)
        if callable(apply):
            self.update_idletasks()
            apply(log=False, grow_only=grow_only)

    def _analytics_expand_btn_label(self, expanded: bool) -> str:
        return f"{_('Analytics')} {'▾' if expanded else '▸'}"

    def _sync_analytics_chrome(self, studies: int) -> None:
        """Show Analytics chrome only when the project has at least one study."""
        was_mapped = bool(self._analytics_header.winfo_ismapped())
        if studies > 0:
            if not was_mapped:
                self._analytics_header.grid()
                self._sync_project_window_size()
            return
        changed = False
        if self._analytics_expanded:
            self._analytics_collapse(sync_window=False)
            changed = True
        self._analytics_header.grid_remove()
        if was_mapped or changed:
            self._sync_project_window_size()

    def _analytics_toggle_expand(self) -> None:
        if self._analytics_expanded:
            self._analytics_collapse()
            return
        self._analytics_expand()

    def _analytics_collapse(self, *, sync_window: bool = True) -> None:
        """Hide with grid_remove — keeps board widgets; restores on next grid()."""
        self._analytics_expanded = False
        self._analytics_expand_btn.configure(text=self._analytics_expand_btn_label(False))
        self._analytics_refresh_btn.grid_remove()
        self._set_volumes_header_visible(False)
        self._close_volumes_dropdown()
        self._analytics_scroll.grid_remove()
        if sync_window:
            self._sync_project_window_size()

    def _analytics_expand(self) -> None:
        """Show the scroll viewport; reuse existing board widgets when possible."""
        self._analytics_expanded = True
        self._analytics_expand_btn.configure(text=self._analytics_expand_btn_label(True))
        self._analytics_refresh_btn.grid()
        self._analytics_scroll.grid()
        if self._analytics_cache is not None:
            # Collapse only hid the scroll frame — do not destroy/rebuild charts
            # (that flickered then left a blank canvas after PhotoImage churn).
            if self._analytics_board_is_empty():
                logger.info("Analytics expand: applying cached snapshot (empty board)")
                self._apply_analytics_snapshot(self._analytics_cache, None)
                return
            logger.info("Analytics expand: restoring cached board without re-render")
            self._set_volumes_header_visible(bool(self._analytics_cache.anatomy.organ_volumes))
            self.update_idletasks()
            self._fit_analytics_scroll_viewport()
            self._sync_project_window_size()
            # Second pass after geometry settles (scrollbar + scrollregion).
            self.after_idle(self._fit_analytics_scroll_viewport)
            return
        logger.info("Analytics expand: no cache, requesting refresh")
        self._request_analytics_refresh()

    def _set_volumes_header_visible(self, visible: bool) -> None:
        if visible and self._analytics_expanded:
            self._volumes_label.grid()
            self._volumes_expand_btn.grid()
        else:
            self._volumes_label.grid_remove()
            self._volumes_expand_btn.grid_remove()

    def _sync_organ_selection_with_snapshot(self, snapshot) -> None:
        """Keep selection ⊆ available organs; seed defaults on first load only."""
        available_set = {o.organ_name for o in snapshot.anatomy.organ_volumes}
        if not available_set:
            self._analytics_selected_organs = set()
            self._set_volumes_header_visible(False)
            self._close_volumes_dropdown()
            return
        if self._analytics_selected_organs is None:
            self._analytics_selected_organs = set(
                default_selected_organ_names(snapshot.anatomy.organ_volumes)
            )
        else:
            # Preserve intentional empty selection; only drop organs that vanished.
            self._analytics_selected_organs &= available_set
        self._set_volumes_header_visible(True)

    def _selected_organs_for_render(self) -> tuple[str, ...]:
        if self._analytics_selected_organs is None:
            return ()
        return tuple(self._analytics_selected_organs)

    def _toggle_volumes_picker(self) -> None:
        if self._volumes_picker_expanded:
            self._close_volumes_dropdown()
            return
        self._open_volumes_dropdown()

    def _cancel_volumes_dropdown_dismiss(self) -> None:
        after_id = self._volumes_dropdown_dismiss_after_id
        if after_id is None:
            return
        with contextlib.suppress(Exception):
            self.after_cancel(after_id)
        self._volumes_dropdown_dismiss_after_id = None

    def _close_volumes_dropdown(self) -> None:
        self._cancel_volumes_dropdown_dismiss()
        self._unbind_volumes_dropdown_outside()
        self._volumes_picker_expanded = False
        if self._volumes_expand_btn.winfo_exists():
            with contextlib.suppress(Exception):
                self._volumes_expand_btn.configure(text="▸")
        dropdown = self._volumes_dropdown
        self._volumes_dropdown = None
        # Keep BooleanVar refs until deferred destroy finishes on the main thread
        # (dropping them here lets worker-thread GC call Variable.__del__ → bus error).
        pending_vars = self._organ_picker_vars
        self._organ_picker_vars = {}
        if dropdown is None:
            return
        with contextlib.suppress(Exception):
            if dropdown.winfo_exists():
                dropdown.place_forget()
        # Defer past Leave/Enter handlers racing destroy + Tcl GC.
        self.after(1, lambda: self._destroy_volumes_dropdown_later(dropdown, pending_vars))

    def _destroy_volumes_dropdown_later(self, dropdown, pending_vars) -> None:
        with contextlib.suppress(Exception):
            if dropdown.winfo_exists():
                dropdown.destroy()
        pending_vars.clear()

    def _open_volumes_dropdown(self) -> None:
        """Floating checkbox menu under header Volumes ▸ — place() overlay, not layout."""
        snapshot = self._analytics_cache
        if snapshot is None or not snapshot.anatomy.organ_volumes:
            return
        if not self._volumes_expand_btn.winfo_ismapped():
            return

        self._close_volumes_dropdown()
        self._volumes_picker_expanded = True
        self._volumes_expand_btn.configure(text="▾")

        self.update_idletasks()
        anchor = self._volumes_label
        width = max(
            self._volumes_label.winfo_width() + self._volumes_expand_btn.winfo_width() + 24,
            180,
        )
        x = anchor.winfo_rootx() - self.winfo_rootx()
        y = (
            self._volumes_expand_btn.winfo_rooty()
            - self.winfo_rooty()
            + self._volumes_expand_btn.winfo_height()
            + 2
        )
        space_below = max(80, int(self.winfo_height()) - y - 8)

        dropdown = ctk.CTkFrame(self, width=width, corner_radius=6, border_width=1)
        self._volumes_dropdown = dropdown
        self._organ_picker_vars = {}
        selected = self._analytics_selected_organs or set()

        # Inner scroll host: height clamped after packing so short lists stay compact.
        list_frame = ctk.CTkScrollableFrame(
            dropdown,
            width=max(width - 16, 160),
            height=min(self._VOLUMES_DROPDOWN_MAX_HEIGHT_PX, space_below),
        )
        list_frame.pack(fill="both", expand=True, padx=4, pady=4)

        checkboxes: list[ctk.CTkCheckBox] = []
        for organ in snapshot.anatomy.organ_volumes:
            var = ctk.BooleanVar(value=organ.organ_name in selected)
            self._organ_picker_vars[organ.organ_name] = var
            cb = ctk.CTkCheckBox(
                list_frame,
                text=f"{organ_display_name(organ.organ_name)} (n={organ.patient_count})",
                variable=var,
                command=self._on_organ_volume_checks_changed,
            )
            cb.pack(anchor="w", padx=6, pady=4)
            checkboxes.append(cb)

        self.update_idletasks()
        width = max(width, dropdown.winfo_reqwidth() + 8, list_frame.winfo_reqwidth() + 24)
        dropdown.configure(width=width)
        list_frame.configure(width=max(width - 16, 160))

        content_h = sum(int(cb.winfo_reqheight()) + 8 for cb in checkboxes) + 8
        list_h = min(content_h, self._VOLUMES_DROPDOWN_MAX_HEIGHT_PX, space_below)
        list_frame.configure(height=max(list_h, 40))

        dropdown.place(x=x, y=y)
        dropdown.lift()
        dropdown.bind("<Escape>", lambda _e: self._close_volumes_dropdown())
        self._volumes_dropdown_dismiss_after_id = self.after(
            50, self._arm_volumes_dropdown_outside_dismiss
        )

    def _arm_volumes_dropdown_outside_dismiss(self) -> None:
        self._volumes_dropdown_dismiss_after_id = None
        dropdown = self._volumes_dropdown
        if dropdown is None or not dropdown.winfo_exists():
            return
        root = self.winfo_toplevel()
        self._volumes_outside_bind_id = root.bind(
            "<ButtonPress-1>", self._on_volumes_dropdown_outside_click, add="+"
        )

    def _on_volumes_dropdown_outside_click(self, event) -> None:
        dropdown = self._volumes_dropdown
        if dropdown is None or not dropdown.winfo_exists():
            self._unbind_volumes_dropdown_outside()
            return
        widget = event.widget
        with contextlib.suppress(Exception):
            wpath = str(widget)
            if wpath.startswith(str(dropdown)):
                return
            if wpath.startswith(str(self._volumes_expand_btn)):
                return
            if wpath.startswith(str(self._volumes_label)):
                return
        self._close_volumes_dropdown()

    def _unbind_volumes_dropdown_outside(self) -> None:
        bind_id = self._volumes_outside_bind_id
        self._volumes_outside_bind_id = None
        if bind_id is None:
            return
        root = self.winfo_toplevel()
        with contextlib.suppress(Exception):
            root.unbind("<ButtonPress-1>", bind_id)

    def _on_organ_volume_checks_changed(self) -> None:
        if self._organ_picker_vars:
            self._analytics_selected_organs = {
                name for name, var in self._organ_picker_vars.items() if bool(var.get())
            }
        self._rerender_analytics_flow()
        dropdown = self._volumes_dropdown
        if dropdown is not None and dropdown.winfo_exists():
            dropdown.lift()

    def _rerender_analytics_flow(self) -> None:
        """Sync the analytics board in place — only add/remove/move cells (no window flash)."""
        from anonymizer.view.shell.analytics_charts import (
            resolve_board_theme,
            select_board_sections,
            sync_widget_section,
        )

        snapshot = self._analytics_cache
        host = self._analytics_flow_host
        if snapshot is None:
            return
        if host is None or not host.winfo_exists():
            # First paint path — full render builds the host.
            self._render_analytics_view(snapshot)
            return

        sections = select_board_sections(
            snapshot,
            selected_organs=self._selected_organs_for_render(),
            on_organ_bar_activate=self._on_organ_bar_activate,
        )
        theme = resolve_board_theme(self._analytics_board)
        sync_widget_section(host, sections.ordered, snapshot, theme)
        if sections.ordered and not host.winfo_ismapped():
            host.pack(fill="x")
        elif not sections.ordered:
            host.pack_forget()

        # Grow the project window with new organ charts; never shrink here
        # (shrink-on-deselect flickered the whole dashboard).
        self.update_idletasks()
        self._fit_analytics_scroll_viewport()
        self._sync_project_window_size(grow_only=True)

    def _on_organ_bar_activate(self, organ_name: str, patient_ids: tuple[str, ...]) -> None:
        """Open Dataset View (if needed) and select studies for patients in a hist bar."""
        if not patient_ids:
            return
        logger.info(
            "Analytics organ bar activate: organ=%s patients=%d",
            organ_name,
            len(patient_ids),
        )
        self._view_callback()
        app = self.master
        dataset = getattr(app, "dataset_view", None)
        if dataset is None:
            return
        with contextlib.suppress(Exception):
            if not dataset.winfo_exists():
                return
            dataset.select_studies_for_patients(patient_ids)

    def _fit_analytics_scroll_viewport(self) -> None:
        """Grow the scroll viewport with content, then cap; show scrollbar only if needed."""
        self.update_idletasks()
        # CTkScrollableFrame shrink-wraps its inner host — pin board width to the
        # viewport so the 2-col grid actually fills left→right.
        scroll_w = max(int(self._analytics_scroll.winfo_width()), 1)
        canvas = getattr(self._analytics_scroll, "_parent_canvas", None)
        win_id = getattr(self._analytics_scroll, "_create_window_id", None)
        if scroll_w > 1:
            self._analytics_board.configure(width=scroll_w)
            if canvas is not None and win_id is not None:
                with contextlib.suppress(Exception):
                    canvas.itemconfigure(win_id, width=scroll_w)
            self.update_idletasks()

        content_h = max(int(self._analytics_board.winfo_reqheight()), 1)
        screen_h = int(self.winfo_screenheight() or 900)
        height = analytics_scroll_height(screen_h, content_h)
        self._analytics_scroll.configure(height=height)
        need_bar = analytics_scrollbar_needed(content_h, height)
        self._set_analytics_scrollbar_visible(need_bar)
        # CTk only updates scrollregion on Configure; force it so overflow scrolls
        # after collapse/expand or when the scrollbar is re-gridded.
        if canvas is not None:
            with contextlib.suppress(Exception):
                self.update_idletasks()
                bbox = canvas.bbox("all")
                if bbox is not None:
                    canvas.configure(scrollregion=bbox)
        logger.debug(
            "Analytics scroll fit: content_h=%s viewport_h=%s scrollbar=%s",
            content_h,
            height,
            need_bar,
        )

    def _set_analytics_scrollbar_visible(self, visible: bool) -> None:
        """Show/hide the CTkScrollableFrame vertical scrollbar (always created)."""
        bar = getattr(self._analytics_scroll, "_scrollbar", None)
        if bar is None:
            return
        if visible:
            # Match CTkScrollableFrame._create_grid vertical layout exactly —
            # bare grid() after grid_remove can leave the bar unmapped.
            with contextlib.suppress(Exception):
                bar.grid(row=1, column=1, sticky="nsew")
        else:
            with contextlib.suppress(Exception):
                bar.grid_remove()

    def _render_analytics_view(self, snapshot) -> None:
        from anonymizer.view.shell.analytics_charts import (
            render_widget_section,
            resolve_board_theme,
            select_board_sections,
        )

        self._sync_organ_selection_with_snapshot(snapshot)
        self._close_volumes_dropdown()
        # Clear board hosts; volumes menu is a place() overlay on the dashboard.
        # ImageViewer pattern: dispose PhotoImages on the main thread, then destroy.
        for child in list(self._analytics_board.winfo_children()):
            with contextlib.suppress(Exception):
                release_mpl_frame_images(child)
                child.destroy()
        self._organ_picker_vars = {}
        self._analytics_flow_host = None
        theme = resolve_board_theme(self._analytics_board)
        sections = select_board_sections(
            snapshot,
            selected_organs=self._selected_organs_for_render(),
            on_organ_bar_activate=self._on_organ_bar_activate,
        )
        logger.info(
            "Analytics charts: render sections charts=%s organs=%s texts=%s",
            [w.key for w in sections.charts],
            [w.key for w in sections.organs],
            [w.key for w in sections.texts],
        )

        if not sections.all and not snapshot.anatomy.organ_volumes:
            ctk.CTkLabel(
                self._analytics_board,
                text=_("No analytics available"),
                wraplength=520,
                justify="center",
            ).pack(expand=True, padx=12, pady=24)
            self._analytics_flow_host = None
        else:
            # One 2-col flow for charts + volumes + AI so both columns fill
            # before wrapping (e.g. AI beside modality when no volumes selected).
            flow_host = ctk.CTkFrame(self._analytics_board, fg_color="transparent")
            self._analytics_flow_host = flow_host
            render_widget_section(flow_host, sections.ordered, snapshot, theme)
            if sections.all:
                flow_host.pack(fill="x")

        self._fit_analytics_scroll_viewport()
        self._sync_project_window_size()
        self._fit_analytics_scroll_viewport()
        # After labels/images request size, re-fit so the scrollbar enables when needed.
        self.after_idle(self._fit_analytics_scroll_viewport)

    def _analytics_board_is_empty(self) -> bool:
        return not self._analytics_board.winfo_children()

    def _request_analytics_refresh(self) -> None:
        from anonymizer.view.shell.analytics_charts import render_analytics_placeholder

        if self._analytics_busy:
            logger.info("Analytics refresh: already busy, ignore")
            return
        if not self._controller.anonymizer.idle():
            self._analytics_updated.configure(text=_("Waiting for idle…"))
            # Keep existing charts; only show a placeholder if the board is empty.
            if self._analytics_expanded and self._analytics_board_is_empty():
                render_analytics_placeholder(
                    self._analytics_board,
                    _("Waiting until import/anonymize is idle…"),
                )
            logger.info("Analytics refresh: deferred until idle")
            return

        logger.info("Analytics refresh: starting")
        self._analytics_updated.configure(text=_("Updating…"))
        self._analytics_refresh_btn.configure(state="disabled")
        self._analytics_busy = True
        # Do not clear widgets here — leave the previous board until redraw.

        def worker() -> None:
            snapshot = None
            error: str | None = None
            try:
                logger.info("Analytics worker: calling build_dataset_analytics")
                snapshot = self._controller.build_dataset_analytics()
                self._analytics_cache = snapshot
                logger.info(
                    "Analytics worker: ok demo_n=%s modality_n=%s",
                    snapshot.demographics.sex.total if snapshot is not None else None,
                    snapshot.imaging.modality.total if snapshot is not None else None,
                )
            except Exception as exc:
                logger.exception("Analytics worker failed")
                error = str(exc)
            finally:
                self._analytics_ux_Q.put(("done", (snapshot, error)))

        threading.Thread(target=worker, name="DashboardAnalytics", daemon=True).start()
        self._schedule_analytics_poll()

    def _schedule_analytics_poll(self) -> None:
        if self._analytics_poll_after_id is not None:
            return
        self._analytics_poll_after_id = self.after(self._analytics_poll_ms, self._poll_analytics_ux_Q)

    def _poll_analytics_ux_Q(self) -> None:
        self._analytics_poll_after_id = None
        while not self._analytics_ux_Q.empty():
            try:
                kind, payload = self._analytics_ux_Q.get_nowait()
            except Exception:
                break
            if kind == "done":
                self._analytics_busy = False
                snapshot, error = payload  # type: ignore[misc]
                self._apply_analytics_snapshot(snapshot, error)
        if self._analytics_busy or not self._analytics_ux_Q.empty():
            self._schedule_analytics_poll()

    def _apply_analytics_snapshot(self, snapshot, error: str | None) -> None:
        from anonymizer.view.shell.analytics_charts import render_analytics_placeholder

        logger.info(
            "Analytics apply: snapshot=%s error=%s expanded=%s",
            snapshot is not None,
            error,
            self._analytics_expanded,
        )
        self._analytics_refresh_btn.configure(state="normal")
        if not self._analytics_expanded:
            if snapshot is not None:
                stamp = snapshot.generated_at.strftime("%H:%M")
                self._analytics_updated.configure(text=_("Updated {time}").format(time=stamp))
            return
        try:
            if snapshot is None:
                message = error or _("Analytics unavailable")
                render_analytics_placeholder(self._analytics_board, message)
                self._analytics_updated.configure(text=message)
                self._sync_project_window_size()
                return
            self._render_analytics_view(snapshot)
            stamp = snapshot.generated_at.strftime("%H:%M")
            self._analytics_updated.configure(text=_("Updated {time}").format(time=stamp))
            logger.info("Analytics apply: UI updated at %s", stamp)
            self._sync_project_window_size()
            # After images are disposed+replaced, GC on idle like SeriesView close.
            schedule_collect_garbage_on_tk(self, generations=2)
        except Exception:
            logger.exception("Analytics apply failed")
            render_analytics_placeholder(self._analytics_board, _("Chart render failed — see log"))
            self._analytics_updated.configure(text=_("Render failed"))
            self._sync_project_window_size()
            schedule_collect_garbage_on_tk(self, generations=2)

    def _wait_for_scp_echo(
        self,
        scp_name: str,
        button: ctk.CTkButton,
        ux_Q: Queue[EchoResponse],
        callback: Any,
    ):
        if ux_Q.empty():
            self.after(500, self._wait_for_scp_echo, scp_name, button, ux_Q, callback)
            return

        er: EchoResponse = ux_Q.get()
        logger.info(er)
        if er.success:
            button.configure(state="normal", text_color="light green")
            self._status.configure(text=f"{scp_name} " + _("online"))
            callback()
        else:
            messagebox.showerror(
                title=_("Connection Error"),
                message=f"{scp_name} "
                + _("Server Failed DICOM ECHO")
                + "\n\n"
                + _("Check Project Settings")
                + f"/{scp_name} "
                + _("Server")
                + "\n\n"
                + _("Ensure the remote server is setup to allow the local server for echo and storage services."),
                parent=self,
            )
            self._status.configure(text=f"{scp_name} " + _("offline"))
            button.configure(state="normal", text_color="red")

    def set_status(self, text: str):
        self._status.configure(text=text)

    def _query_button_click(self):
        logger.info("_query_button_click")
        self._query_button.configure(state="disabled")
        self._controller.echo_ex(EchoRequest(scp=_("QUERY"), ux_Q=self._query_ux_Q))
        self.after(
            500,
            self._wait_for_scp_echo,
            _("Query Server"),
            self._query_button,
            self._query_ux_Q,
            self._query_callback,
        )
        self._status.configure(text=_("Checking Query DICOM Server is online") + "...")

    def _send_button_click(self):
        logger.info("_export_button_click")
        self._send_button.configure(state="disabled")

        if self._controller.model.export_to_AWS:
            self._controller.AWS_authenticate_ex()  # Authenticate to AWS in background
            self._timer = self.AWS_AUTH_TIMEOUT_SECONDS
            self.after(1000, self._wait_for_aws)
            self._status.configure(text=_("Waiting for AWS Authentication") + "...")
        else:
            self._controller.echo_ex(EchoRequest(scp="EXPORT", ux_Q=self._export_ux_Q))
            self.after(
                1000,
                self._wait_for_scp_echo,
                _("Export Server"),
                self._send_button,
                self._export_ux_Q,
                self._export_callback,
            )
            self._status.configure(text=_("Checking Export DICOM Server is online") + "...")

    def _view_button_click(self):
        logger.info("_view_button_click")
        self._view_callback()

    def _wait_for_aws(self):
        self._timer -= 1
        if self._timer <= 0 or self._controller._aws_last_error:  # Error or TIMEOUT
            if self._controller._aws_last_error is None:
                self._controller._aws_last_error = "AWS Response Timeout"
            messagebox.showerror(
                title=_("Connection Error"),
                message=_("AWS Authentication Failed")
                + ":"
                + f"\n\n{self._controller._aws_last_error}"
                + "\n\n"
                + _("Check Project Settings/AWS Cognito and ensure all parameters are correct."),
                parent=self,
            )
            self._status.configure(text="")
            self._send_button.configure(state="normal", text_color="red")
            return

        if self._controller.AWS_credentials_valid():
            self._send_button.configure(state="normal", text_color="light green")
            self._export_callback()
            self._status.configure(text=_("AWS Authenticated"))
            return

        self.after(1000, self._wait_for_aws)

    def update_anonymizer_queues(self, ds_Q_size: int) -> None:
        self._meta_qsize.configure(text=f"{ds_Q_size}")

    def update_totals(self, totals: Totals):
        self._patients = totals.patients
        self._studies = totals.studies
        self._series = totals.series
        self._images = totals.instances
        self._patients_label.configure(text=f"{totals.patients}")
        self._studies_label.configure(text=f"{totals.studies}")
        self._series_label.configure(text=f"{totals.series}")
        self._images_label.configure(text=f"{totals.instances}")
        self._quarantined_label.configure(
            text=f"{count_quarantine_images(self._controller.anonymizer.get_quarantine_path())}"
        )
        self._sync_analytics_chrome(totals.studies)

    def _update_dashboard_from_file_system(self):
        if not self._controller:
            return

        dir = self._controller.model.images_dir()
        pts = os.listdir(dir)
        pts = [item for item in pts if dir.joinpath(item).is_dir()]

        self._patients = len(pts)
        self._studies = 0
        self._series = 0
        self._images = 0

        for pt in pts:
            study_count, series_count, file_count = count_studies_series_images(os.path.join(dir, pt))
            self._studies += study_count
            self._series += series_count
            self._images += file_count

        self._patients_label.configure(text=f"{self._patients}")
        self._studies_label.configure(text=f"{self._studies}")
        self._series_label.configure(text=f"{self._series}")
        self._images_label.configure(text=f"{self._images}")
        self._sync_analytics_chrome(self._studies)
