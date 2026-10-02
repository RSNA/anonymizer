"""Dataset toolbar dialog to inspect/delete per-project description mappings.

Series mappings remember RadLex Playbook series descriptions.
Study mappings remember LOINC study descriptions (with LOINC code).

Row management mirrors View Dataset: Select All, Clear Selection, Delete.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from anonymizer.model.anonymizer import AnonymizerModel, DescriptionMappingRecord
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

logger = logging.getLogger(__name__)

# Segmented-button labels — keep stable for gettext and tab→kind mapping.
_TAB_SERIES = "Series (RadLex)"
_TAB_STUDY = "Study (LOINC)"


class DescriptionMappingsDialog(AppToplevel):
    PAD = 10
    BUTTON_WIDTH = 120
    DIALOG_WIDTH = 900
    DIALOG_HEIGHT = 480
    MIN_WIDTH = 720
    MIN_HEIGHT = 360
    # Original and harmonized description columns share the same default width.
    _DESC_COL_WIDTH = 220

    def __init__(self, parent: tk.Misc, *, anon_model: AnonymizerModel) -> None:
        super().__init__(parent)
        self.title(_("Description Mappings"))
        self._anon_model = anon_model
        self.geometry(f"{self.DIALOG_WIDTH}x{self.DIALOG_HEIGHT}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.resizable(True, True)
        self.grab_set()
        self.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._on_close())

        pad = self.PAD
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._tab_series = _(_TAB_SERIES)
        self._tab_study = _(_TAB_STUDY)
        self._tab = ctk.CTkSegmentedButton(
            self,
            values=[self._tab_series, self._tab_study],
            command=self._on_tab_changed,
        )
        self._tab.set(self._tab_series)
        self._tab.grid(row=0, column=0, padx=pad, pady=(pad, 0), sticky="ew")

        self._hint = ctk.CTkLabel(
            self,
            text="",
            wraplength=self.DIALOG_WIDTH - pad * 4,
            justify="left",
            anchor="w",
        )
        self._hint.grid(row=1, column=0, padx=pad, pady=(pad // 2, 0), sticky="ew")

        tree_frame = ctk.CTkFrame(self, fg_color="transparent")
        tree_frame.grid(row=2, column=0, padx=pad, pady=pad, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self._columns_series = ("original", "harmonized", "modality", "origin", "updated")
        self._columns_study = ("original", "harmonized", "modality", "origin", "loinc", "updated")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=self._columns_series,
            show="headings",
            selectmode="extended",
        )
        self._tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._tree.configure(yscrollcommand=scrollbar.set)

        self._empty_label = ctk.CTkLabel(
            self,
            text="",
            wraplength=self.DIALOG_WIDTH - pad * 4,
            justify="left",
        )
        self._empty_label.grid(row=3, column=0, padx=pad, pady=(0, pad), sticky="w")

        # Same management strip as View Dataset (Select All / Clear Selection / Delete).
        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.grid(row=4, column=0, padx=pad, pady=(0, pad), sticky="ew")
        button_row.grid_columnconfigure(0, weight=1)

        self._select_all_button = ctk.CTkButton(
            button_row,
            width=self.BUTTON_WIDTH,
            text=_("Select All"),
            command=self._select_all_button_pressed,
        )
        self._select_all_button.grid(row=0, column=1, padx=(pad, 0), sticky="e")

        self._clear_selection_button = ctk.CTkButton(
            button_row,
            width=self.BUTTON_WIDTH,
            text=_("Clear Selection"),
            command=self._clear_selection_button_pressed,
        )
        self._clear_selection_button.grid(row=0, column=2, padx=(pad, 0), sticky="e")

        self._delete_button = ctk.CTkButton(
            button_row,
            width=self.BUTTON_WIDTH,
            text=_("Delete"),
            command=self._delete_button_pressed,
        )
        self._delete_button.grid(row=0, column=3, padx=(pad, 0), sticky="e")

        self._close_button = ctk.CTkButton(
            button_row,
            width=self.BUTTON_WIDTH,
            text=_("Close"),
            command=self._on_close,
        )
        self._close_button.grid(row=0, column=4, padx=(pad, 0), sticky="e")

        self._rows_by_iid: dict[str, DescriptionMappingRecord] = {}
        self._configure_columns_for_kind(self._kind_for_tab())
        self._refresh()

    def _kind_for_tab(self) -> str:
        return "study" if self._tab.get() == self._tab_study else "series"

    def _on_tab_changed(self, _value: str | None = None) -> None:
        self._configure_columns_for_kind(self._kind_for_tab())
        self._refresh()

    def _configure_columns_for_kind(self, kind: str) -> None:
        """Series = RadLex (no LOINC col); Study = LOINC (show code)."""
        columns = self._columns_study if kind == "study" else self._columns_series
        self._tree.configure(columns=columns)
        headings = {
            "original": _("Original"),
            "harmonized": _("RadLex") if kind == "series" else _("LOINC name"),
            "modality": _("Modality"),
            "origin": _("Origin"),
            "loinc": _("LOINC"),
            "updated": _("Updated"),
        }
        # Equal description widths; no stretch on them (stretch snap-back squashes
        # earlier cols). Only ``updated`` stretches to fill leftover view width.
        desc_cols = {"original", "harmonized"}
        widths = {
            "original": self._DESC_COL_WIDTH,
            "harmonized": self._DESC_COL_WIDTH,
            "modality": 80,
            "origin": 100,
            "loinc": 90,
            "updated": 140,
        }
        for col in columns:
            self._tree.heading(col, text=headings[col])
            self._tree.column(
                col,
                width=widths[col],
                minwidth=60 if col in desc_cols else 40,
                stretch=(col == "updated"),
                anchor="w",
            )
        if kind == "series":
            self._hint.configure(
                text=_(
                    "Series mappings: original series description → RadLex Playbook name "
                    "(saved when you set a series description)."
                )
            )
        else:
            self._hint.configure(
                text=_(
                    "Study mappings: original study description → LOINC study name "
                    "(saved when you set a study description; LOINC code required)."
                )
            )

    def _empty_message(self, kind: str) -> str:
        if kind == "series":
            return _(
                "No RadLex series mappings yet — they appear when you set a series description manually."
            )
        return _(
            "No LOINC study mappings yet — they appear when you set a study description manually."
        )

    def _refresh(self) -> None:
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._rows_by_iid.clear()
        kind = self._kind_for_tab()
        rows = self._anon_model.list_description_mappings(kind=kind)
        if not rows:
            self._empty_label.configure(text=self._empty_message(kind))
            self._empty_label.grid()
            return
        self._empty_label.grid_remove()
        for row in rows:
            iid = str(row.mapping_pk)
            self._rows_by_iid[iid] = row
            if kind == "study":
                values = (
                    row.original_display,
                    row.harmonized_description,
                    row.modality,
                    row.origin,
                    row.loinc or "",
                    row.updated_at,
                )
            else:
                values = (
                    row.original_display,
                    row.harmonized_description,
                    row.modality,
                    row.origin,
                    row.updated_at,
                )
            self._tree.insert("", "end", iid=iid, values=values)

    def _select_all_button_pressed(self) -> None:
        children = self._tree.get_children("")
        if children:
            self._tree.selection_set(*children)

    def _clear_selection_button_pressed(self) -> None:
        self._tree.selection_set([])

    def _delete_button_pressed(self) -> None:
        selected = list(self._tree.selection())
        if not selected:
            messagebox.showerror(
                title=_("Delete mapping"),
                message=_("No mappings selected for deletion.")
                + "\n\n"
                + _("Use SHIFT+Click and/or CMD/CTRL+Click to select multiple rows."),
                parent=self,
            )
            return
        rows = [self._rows_by_iid[iid] for iid in selected if iid in self._rows_by_iid]
        if not rows:
            return
        n = len(rows)
        message = (
            _("Delete this description mapping?")
            if n == 1
            else _("Delete {n} description mappings?").format(n=n)
        )
        if not messagebox.askyesno(title=_("Delete mapping"), message=message, parent=self):
            return
        failed = 0
        for row in rows:
            if not self._anon_model.delete_description_mapping(row.mapping_pk):
                failed += 1
        if failed:
            messagebox.showerror(
                title=_("Delete mapping"),
                message=_("Could not delete {n} mapping(s).").format(n=failed),
                parent=self,
            )
        self._refresh()

    def _on_close(self) -> None:
        teardown_ctk_toplevel(self)


def show_description_mappings_dialog(parent: tk.Misc, *, anon_model: AnonymizerModel) -> None:
    DescriptionMappingsDialog(parent, anon_model=anon_model)
