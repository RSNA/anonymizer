"""Structured editor for the project anonymizer script (Active-first)."""

from __future__ import annotations

import contextlib
import logging
import re
import string
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import customtkinter as ctk

from anonymizer.controller.anonymizer_script import (
    OPERANDS,
    OperandSpec,
    ScriptDocument,
    ScriptRule,
    ScriptViewMode,
    add_rule_from_dictionary,
    always_literal_text,
    apply_incrementdate_to_rules,
    commit_script_edit,
    dicom_applicable_standard_text,
    display_operation,
    display_tag_vr,
    filter_rules,
    format_dicom_tag,
    format_incrementdate_affected_lines,
    format_operand,
    format_tag_description_line,
    has_missing_dictionary_tags,
    incrementdate_days,
    is_remove_operation,
    load_script_rules,
    operand_id_for_operation,
    operand_id_from_syntax,
    operand_spec_by_id,
    operand_syntax,
    operand_tag_incompatibility,
    operands_for_tag,
    rebasedate_origin,
    rules_for_incrementdate_bulk,
    search_missing_dictionary_tags,
    stage_script_edit,
    tag_dictionary_meta,
    validate_operation,
)
from anonymizer.controller.process_ctp_lookup import (
    CtpLookupPreview,
    lookup_table_context,
    private_anonymizer_script_path,
)
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel, install_modal_dismiss, place_toplevel_centered_on_parent
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import default_char_width_px
from anonymizer.view.common.ux_fields import dicom_date_chars, int_entry, str_entry
from anonymizer.view.settings.lookup_table_dialog import LookupTableDialog

logger = logging.getLogger(__name__)

_SEARCH_DEBOUNCE_MS = 200
_ROUND_WIDTH_RE = re.compile(r"^@round\(\s*this\s*,\s*(\d+)\s*\)$", re.IGNORECASE)
_HELP_WRAP = 320
_HELP_BODY_INDENT = 12
_NAME_COL_SLACK_CHARS = 2 - 18  # fit longest name, then shrink by 18 characters
# Operands that need a CTP patient lookup table (load/replace via LookupTableDialog).
_LOOKUP_TABLE_OPERANDS = frozenset({"lookup_ptid", "lookup_dateoffset", "rebasedate"})
_OPERAND_DROPDOWN_PAD_CHARS = 3  # wider than longest catalog syntax
# Shared by AnonymizerScriptDialog child dialogs (OperandParam, AddFromDictionary, etc.).
_CHILD_DIALOG_PAD = 10


class AnonymizerScriptDialog(AppToplevel):
    def __init__(
        self,
        parent,
        *,
        script_path: Path,
        project_model: ProjectModel,
        project_controller: ProjectController | None = None,
        on_script_path_changed: Callable[[Path], None] | None = None,
        on_pending_lookup_preview: Callable[[CtpLookupPreview], None] | None = None,
        pending_lookup_preview: CtpLookupPreview | None = None,
    ):
        super().__init__(master=parent)
        self.project_controller = project_controller
        self.project_model = project_model
        self._on_script_path_changed = on_script_path_changed
        self._on_pending_lookup_preview = on_pending_lookup_preview
        self._pending_lookup_preview = pending_lookup_preview
        self._script_path = Path(script_path)
        self._document = load_script_rules(self._script_path)
        self._filtered: list[ScriptRule] = []
        self._view_mode = ScriptViewMode.ACTIVE
        self._search_after_id: str | None = None
        self._selected_tag: str | None = None
        self._custom_operation: str | None = None
        self._detail_updating = False
        self._committed = False
        self._lookup_ctx = lookup_table_context(self.project_model, self._pending_lookup_preview)
        self._char_width_px = max(7, default_char_width_px())
        self._dict_dialog: AddFromDictionaryDialog | None = None

        self.title(_("Edit Anonymizer Script"))
        self.resizable(True, True)
        self._create_widgets()
        self._refresh_list()
        self._apply_dialog_geometry()
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, self._on_cancel)
        self.grab_set()
        self.bind("<Escape>", self._on_cancel)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _available_operands(self) -> tuple[OperandSpec, ...]:
        return OPERANDS

    def _operands_for_selected_rule(self) -> tuple[OperandSpec, ...]:
        if self._selected_tag is None:
            return self._available_operands()
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return self._available_operands()
        return operands_for_tag(tag=rule.tag, name=rule.name or "")

    def _operand_syntax_values(self, *, for_selected_rule: bool = False) -> list[str]:
        specs = self._operands_for_selected_rule() if for_selected_rule else self._available_operands()
        return [operand_syntax(spec) for spec in specs]

    def _rule_row_values(self, rule: ScriptRule) -> tuple[str, str, str, str]:
        return (
            format_dicom_tag(rule.tag),
            display_tag_vr(rule.tag),
            rule.name,
            display_operation(rule.operation),
        )

    def _refresh_lookup_context(self) -> None:
        self._lookup_ctx = lookup_table_context(self.project_model, self._pending_lookup_preview)
        values = self._operand_syntax_values()
        filter_values = [_("All")] + values
        current_filter = self._operand_filter_var.get()
        self._set_operand_combo_values(filter_values, combo=self._operand_filter)
        if current_filter not in filter_values:
            self._operand_filter_var.set(_("All"))
        if self._selected_tag is not None:
            self._configure_operand_combo_for_selection()
        else:
            self._set_operand_combo_values(self._operand_syntax_values())
        self._refresh_operand_action_buttons()

    def _project_script_path_text(self) -> str:
        """Abridged path when editing the project-private script; empty for the packaged default."""
        private = private_anonymizer_script_path(self.project_model)
        try:
            is_project = self._script_path.resolve() == private.resolve()
        except OSError:
            is_project = self._script_path == private
        if not is_project:
            return ""
        return self.project_model.abridged_path(self._script_path, include_filename=True)

    def _refresh_path_label(self) -> None:
        text = self._project_script_path_text()
        self._path_label.configure(text=text)
        if text:
            self._path_label.grid()
        else:
            self._path_label.grid_remove()

    def _create_widgets(self) -> None:
        pad = _CHILD_DIALOG_PAD
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Header controls (path / view / search) ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 0))
        header.grid_columnconfigure(0, weight=1)

        path_row = ctk.CTkFrame(header, fg_color="transparent")
        path_row.grid(row=0, column=0, sticky="ew", pady=(0, pad))
        path_row.grid_columnconfigure(0, weight=1)
        self._path_label = ctk.CTkLabel(path_row, text="", anchor="w", justify="left")
        self._path_label.grid(row=0, column=0, sticky="ew")
        dicom_ver = dicom_applicable_standard_text()
        self._dicom_version_label = ctk.CTkLabel(
            path_row,
            text=_("Applicable Standard: {standard}").format(standard=dicom_ver) if dicom_ver else "",
            font=ctk.CTkFont(weight="bold"),
            anchor="e",
            justify="right",
        )
        self._dicom_version_label.grid(row=0, column=1, sticky="e", padx=(pad, 0))
        if not dicom_ver:
            self._dicom_version_label.grid_remove()
        self._refresh_path_label()

        mode_row = ctk.CTkFrame(header, fg_color="transparent")
        mode_row.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(mode_row, text=_("View") + ":").pack(side="left", padx=(0, pad))
        self._view_var = tk.StringVar(value="active")
        for value, label in (
            ("active", _("Active")),
            ("removed", _("Removed")),
            ("all", _("All")),
        ):
            ctk.CTkRadioButton(
                mode_row,
                text=label,
                variable=self._view_var,
                value=value,
                command=self._on_view_changed,
            ).pack(side="left", padx=(0, pad))

        tool = ctk.CTkFrame(header, fg_color="transparent")
        tool.grid(row=2, column=0, sticky="ew", pady=(pad, pad))
        ctk.CTkLabel(tool, text=_("Search") + ":").pack(side="left")
        self._search_var = tk.StringVar(value="")
        self._search_var.trace_add("write", self._on_search_trace)
        self._search_entry = ctk.CTkEntry(
            tool, textvariable=self._search_var, width=self._search_entry_width_px()
        )
        self._search_entry.pack(side="left", padx=(pad, pad))
        ctk.CTkLabel(tool, text=_("Operand") + ":").pack(side="left")
        self._operand_filter_var = tk.StringVar(value=_("All"))
        self._operand_filter = ctk.CTkComboBox(
            tool,
            values=[_("All")] + self._operand_syntax_values(),
            variable=self._operand_filter_var,
            width=self._operand_dropdown_width_px(),
            command=self._on_operand_filter,
            state="readonly",
        )
        self._operand_filter.pack(side="left", padx=(pad, 0))

        # --- Index chrome (Dataset-style framed tree + help) ---
        index_frame = ctk.CTkFrame(self)
        index_frame.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, pad))
        index_frame.grid_columnconfigure(0, weight=3)
        index_frame.grid_columnconfigure(1, weight=2)
        index_frame.grid_rowconfigure(0, weight=1)

        list_frame = ctk.CTkFrame(index_frame, fg_color="transparent")
        list_frame.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            list_frame,
            columns=("tag", "vr", "name", "operand"),
            show="headings",
            style="Treeview",
            selectmode="browse",
        )
        self._tree.heading("tag", text=_("Tag"), anchor="w")
        self._tree.heading("vr", text=_("VR"), anchor="center")
        self._tree.heading("name", text=_("Name"), anchor="w")
        self._tree.heading("operand", text=_("Operand"), anchor="center")
        self._tree.column("tag", width=self._char_width_px * 10, stretch=False, anchor="w")
        self._tree.column("vr", width=self._char_width_px * 5, stretch=False, anchor="center")
        self._tree.column("name", width=self._search_entry_width_px(), stretch=False, anchor="w")
        self._tree.column(
            "operand",
            width=self._operand_column_width_px(),
            stretch=True,
            anchor="center",
        )
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=yscroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        help_panel = ctk.CTkFrame(index_frame, fg_color="transparent")
        help_panel.grid(row=0, column=1, sticky="nsew", padx=(0, pad), pady=pad)
        help_panel.grid_columnconfigure(0, weight=1)
        # Content stays top-packed; only the spacer row absorbs extra height.
        help_panel.grid_rowconfigure(1, weight=1)
        self._help_panel = help_panel
        self._help_fit_after_id: str | None = None
        self._help_visible = False

        help_content = ctk.CTkFrame(help_panel, fg_color="transparent")
        help_content.grid(row=0, column=0, sticky="new")
        help_content.grid_columnconfigure(0, weight=1)

        self._selection_label = ctk.CTkLabel(
            help_content,
            text=_("Select a rule to change its operand."),
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._selection_label.grid(row=0, column=0, sticky="ew")

        self._tag_description_label = ctk.CTkLabel(
            help_content,
            text="",
            anchor="w",
            justify="left",
            wraplength=_HELP_WRAP,
        )
        self._tag_description_label.grid(row=1, column=0, sticky="ew", pady=(4, pad))
        self._tag_description_label.grid_remove()

        op_block = ctk.CTkFrame(help_content, fg_color="transparent")
        op_block.grid(row=2, column=0, sticky="ew")

        op_row = ctk.CTkFrame(op_block, fg_color="transparent")
        op_row.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(op_row, text=_("Operand") + ":").grid(row=0, column=0, sticky="w")
        self._operand_var = tk.StringVar(value="@keep")
        self._operand_combo = ctk.CTkComboBox(
            op_row,
            values=self._operand_syntax_values(),
            variable=self._operand_var,
            command=self._on_operand_combo,
            width=self._operand_dropdown_width_px(),
            state="disabled",
        )
        self._operand_combo.grid(row=0, column=1, sticky="w", padx=(pad, 0))

        self._action_row = ctk.CTkFrame(op_block, fg_color="transparent")
        # Shown only when Apply / Change parameter / Lookup buttons are visible.
        self._apply_operand_button = ctk.CTkButton(
            self._action_row,
            text=_("Apply"),
            width=90,
            command=self._on_apply_operand,
        )
        self._param_button = ctk.CTkButton(
            self._action_row,
            text=_("Change parameter"),
            width=140,
            command=self._on_change_param,
        )
        self._lookup_table_button = ctk.CTkButton(
            self._action_row,
            text=_("Load Lookup Table"),
            width=160,
            command=self._on_lookup_table_button,
        )

        help_block = ctk.CTkFrame(help_content, fg_color="transparent")
        help_block.grid_columnconfigure(0, weight=1)
        self._help_block = help_block
        ctk.CTkLabel(
            help_block,
            text=_("How this operand works"),
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._help_label = ctk.CTkLabel(
            help_block,
            text="",
            anchor="nw",
            justify="left",
            wraplength=_HELP_WRAP - _HELP_BODY_INDENT,
        )
        self._help_label.grid(row=1, column=0, sticky="ew", padx=(_HELP_BODY_INDENT, 0))
        # Hidden until an operand help text is shown.

        self._error_label = ctk.CTkLabel(
            help_content, text="", text_color="#c44", justify="left", wraplength=_HELP_WRAP, anchor="w"
        )
        self._error_label.grid(row=4, column=0, sticky="ew", pady=(pad, 0))

        ctk.CTkFrame(help_panel, fg_color="transparent", height=1).grid(
            row=1, column=0, sticky="nsew"
        )

        # --- Button bar (Dataset-style framed footer) ---
        button_frame = ctk.CTkFrame(self)
        button_frame.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, pad))
        button_frame.grid_columnconfigure(1, weight=1)
        btn_w = 120

        self._add_dictionary_button = ctk.CTkButton(
            button_frame,
            text=_("Add from Dictionary"),
            width=150,
            command=self._open_add_dictionary,
        )
        self._add_dictionary_button.grid(row=0, column=0, sticky="w", padx=pad, pady=pad)

        ctk.CTkButton(button_frame, text=_("Revert"), width=btn_w, command=self._on_revert).grid(
            row=0, column=2, sticky="e", padx=pad, pady=pad
        )
        ctk.CTkButton(button_frame, text=_("Cancel"), width=btn_w, command=self._on_cancel).grid(
            row=0, column=3, sticky="e", padx=(0, pad), pady=pad
        )
        ctk.CTkButton(button_frame, text=_("Accept"), width=btn_w, command=self._on_accept).grid(
            row=0, column=4, sticky="e", padx=(0, pad), pady=pad
        )

        self._refresh_add_dictionary_visibility()

    def _longest_name_chars(self) -> int:
        max_chars = len(_("Name"))
        for rule in self._document.rules:
            max_chars = max(max_chars, len(rule.name or ""))
        return max_chars

    def _search_entry_width_px(self) -> int:
        return max(12, self._longest_name_chars() + _NAME_COL_SLACK_CHARS) * self._char_width_px

    def _operand_column_width_px(self) -> int:
        max_chars = len(_("Operand"))
        for rule in self._document.rules:
            max_chars = max(max_chars, len(display_operation(rule.operation)))
        for spec in self._available_operands():
            max_chars = max(max_chars, len(operand_syntax(spec)))
        return max(12, max_chars + 2) * self._char_width_px

    def _operand_dropdown_width_px(self) -> int:
        """Width for toolbar + detail Operand combos: longest catalog syntax + 3 chars."""
        max_chars = len(_("All"))
        for spec in OPERANDS:
            max_chars = max(max_chars, len(operand_syntax(spec)))
        return max(12, max_chars + _OPERAND_DROPDOWN_PAD_CHARS) * self._char_width_px

    def _set_operand_combo_values(self, values: list[str], *, combo: ctk.CTkComboBox | None = None) -> None:
        target = combo if combo is not None else self._operand_combo
        target.configure(values=values, width=self._operand_dropdown_width_px())

    def _tree_preferred_width_px(self) -> int:
        tag_w = self._char_width_px * 10
        vr_w = self._char_width_px * 5
        name_w = self._search_entry_width_px()
        operand_w = self._operand_column_width_px()
        scrollbar_w = 18
        return tag_w + vr_w + name_w + operand_w + scrollbar_w

    def _apply_dialog_geometry(self) -> None:
        """Size dialog to the Name column and expand vertically to fit help text."""
        pad = _CHILD_DIALOG_PAD
        tree_w = self._tree_preferred_width_px()
        help_w = _HELP_WRAP + pad * 2
        width = pad * 2 + pad * 2 + tree_w + pad + help_w + pad
        self.update_idletasks()
        help_h = int(self._help_panel.winfo_reqheight() or 0)
        # Reserve room for "How this operand works" so the first rule select
        # does not grow the window (that resize was the visible flicker).
        index_h = max(320, help_h + pad * 2 + 220)
        height = pad + 120 + index_h + 70 + pad  # header + index + button bar approx
        height = max(560, height)
        self.minsize(width, min(560, height))
        self.geometry(f"{width}x{height}")

    def _refresh_add_dictionary_visibility(self) -> None:
        if has_missing_dictionary_tags(self._document):
            self._add_dictionary_button.grid()
        else:
            self._add_dictionary_button.grid_remove()

    def _autosize_name_column(self) -> None:
        """Keep Name column sized to longest script name (shrunk by slack); centre Operand."""
        self._tree.column("name", width=self._search_entry_width_px(), stretch=False, anchor="w")
        self._tree.column(
            "operand",
            width=self._operand_column_width_px(),
            stretch=True,
            anchor="center",
        )

    def _schedule_fit_dialog_height(self) -> None:
        if self._help_fit_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._help_fit_after_id)
        self._help_fit_after_id = self.after_idle(self._fit_dialog_height_to_help)

    def _set_help_text(self, text: str) -> None:
        self._help_label.configure(text=text)
        self._schedule_fit_dialog_height()

    def _show_operand_help(self, text: str) -> None:
        pad = _CHILD_DIALOG_PAD
        if not self._help_visible:
            self._help_block.grid(row=3, column=0, sticky="ew", pady=(pad, 0))
            self._help_visible = True
        self._set_help_text(text)

    def _hide_operand_help(self) -> None:
        if not self._help_visible and not self._help_label.cget("text"):
            return
        self._help_label.configure(text="")
        if self._help_visible:
            self._help_block.grid_remove()
            self._help_visible = False
            self._schedule_fit_dialog_height()

    def _fit_dialog_height_to_help(self) -> None:
        """Grow the dialog if the right-panel text needs more vertical room."""
        self._help_fit_after_id = None
        with contextlib.suppress(tk.TclError):
            self.update_idletasks()
            help_h = int(self._help_panel.winfo_reqheight() or 0)
            index_h = max(320, help_h + 20)
            needed = 10 + 120 + index_h + 70 + 10
            cur_w = max(self.winfo_width(), 1)
            cur_h = max(self.winfo_height(), 1)
            if needed > cur_h + 8:
                self.geometry(f"{cur_w}x{needed}")
                self.minsize(self.winfo_reqwidth() or cur_w, min(560, needed))

    def _update_help_for_operand(self, operand_id: str | None) -> None:
        spec = operand_spec_by_id(operand_id) if operand_id else None
        if spec is None:
            self._hide_operand_help()
            return
        self._show_operand_help(_(spec.help_key))

    def _pending_operand_id(self) -> str | None:
        return operand_id_from_syntax(self._operand_var.get())

    def _rule_operand_id(self, tag: str | None = None) -> str | None:
        key = tag if tag is not None else self._selected_tag
        if key is None:
            return None
        rule = self._document.get_rule(key)
        if rule is None:
            return None
        return operand_id_for_operation(rule.operation)

    def _pending_operand_differs(self) -> bool:
        if self._selected_tag is None:
            return False
        pending = self._pending_operand_id() or "keep"
        current = self._rule_operand_id()
        if current is None:
            # Unrecognized script value is shown as @keep until replaced.
            return pending != "keep"
        return pending != current

    def _refresh_operand_action_buttons(self) -> None:
        pad = _CHILD_DIALOG_PAD
        self._apply_operand_button.pack_forget()
        self._param_button.pack_forget()
        self._lookup_table_button.pack_forget()
        if self._selected_tag is None:
            self._action_row.grid_remove()
            return

        show_apply = self._pending_operand_differs()
        pending = self._pending_operand_id() or "keep"
        spec = operand_spec_by_id(pending)
        show_param = (
            not show_apply
            and spec is not None
            and spec.needs_param
            and self._custom_operation is None
        )
        show_lookup = not show_apply and pending in _LOOKUP_TABLE_OPERANDS

        if not (show_apply or show_param or show_lookup):
            self._action_row.grid_remove()
            return

        self._action_row.grid(row=1, column=0, sticky="w", pady=(pad, 0))
        if show_apply:
            self._apply_operand_button.pack(side="left")
            return
        if show_param:
            self._param_button.pack(side="left")
        if show_lookup:
            if self._lookup_ctx.present:
                self._lookup_table_button.configure(text=_("Replace Lookup Table"))
            else:
                self._lookup_table_button.configure(text=_("Load Lookup Table"))
            self._lookup_table_button.pack(side="left", padx=((pad, 0) if show_param else (0, 0)))

    def _on_operand_filter(self, _value: str | None = None) -> None:
        self._refresh_list()
        filt = self._operand_filter_id()
        if filt is not None:
            # Browse catalog help without assigning an operand to a rule.
            self._update_help_for_operand(filt)
            if self._selected_tag is None:
                self._refresh_operand_action_buttons()
            elif not self._pending_operand_differs():
                # Keep action buttons for the selected rule; help shows the filtered operand.
                self._refresh_operand_action_buttons()
            return
        if self._selected_tag is not None:
            self._load_selection(self._selected_tag)
        else:
            self._update_help_for_operand(None)
            self._refresh_operand_action_buttons()

    def _on_view_changed(self) -> None:
        value = self._view_var.get()
        self._view_mode = ScriptViewMode(value)
        self._refresh_list()

    def _on_search_trace(self, *_args) -> None:
        if self._search_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(_SEARCH_DEBOUNCE_MS, self._refresh_list)

    def _operand_filter_id(self) -> str | None:
        label = self._operand_filter_var.get()
        if label == _("All") or label == "All":
            return None
        return operand_id_from_syntax(label)

    def _refresh_list(self, *, focus_tag: str | None = None) -> None:
        self._filtered = filter_rules(
            self._document,
            view=self._view_mode,
            query=self._search_var.get(),
            operand_id=self._operand_filter_id(),
        )

        for item in self._tree.get_children():
            self._tree.delete(item)
        for rule in self._filtered:
            self._tree.insert(
                "",
                "end",
                iid=rule.tag,
                values=self._rule_row_values(rule),
            )

        self._autosize_name_column()
        search_w = self._search_entry_width_px()
        self._search_entry.configure(width=search_w)

        tag = focus_tag or self._selected_tag
        if tag and self._tree.exists(tag):
            self._tree.selection_set(tag)
            self._tree.see(tag)
            self._load_selection(tag)
        elif self._selected_tag and not self._tree.exists(self._selected_tag):
            if focus_tag is None:
                self._clear_selection()

    def _on_tree_select(self, _event=None) -> None:
        selection = self._tree.selection()
        if not selection:
            return
        self._load_selection(selection[0])

    def _set_tag_description(self, tag: str | None) -> None:
        if not tag:
            self._tag_description_label.configure(text="")
            self._tag_description_label.grid_remove()
            return
        meta = tag_dictionary_meta(tag)
        if meta is None:
            self._tag_description_label.configure(text="")
            self._tag_description_label.grid_remove()
            return
        line = format_tag_description_line(meta, retired_label=_("Retired"))
        if not line:
            self._tag_description_label.configure(text="")
            self._tag_description_label.grid_remove()
            return
        self._tag_description_label.configure(text=line)
        self._tag_description_label.grid()

    def _clear_selection(self) -> None:
        self._selected_tag = None
        self._custom_operation = None
        self._detail_updating = True
        try:
            self._selection_label.configure(text=_("Select a rule to change its operand."))
            self._set_tag_description(None)
            self._operand_var.set("@keep")
            self._operand_combo.configure(state="disabled")
            self._error_label.configure(text="")
            filt = self._operand_filter_id()
            if filt is not None:
                self._update_help_for_operand(filt)
            else:
                self._update_help_for_operand(None)
            self._refresh_operand_action_buttons()
        finally:
            self._detail_updating = False

    def _configure_operand_combo_for_selection(self) -> None:
        """Limit the detail Operand dropdown to VR-compatible catalog entries."""
        if self._selected_tag is None:
            self._set_operand_combo_values(self._operand_syntax_values())
            return
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            self._set_operand_combo_values(self._operand_syntax_values())
            return
        values = self._operand_syntax_values(for_selected_rule=True)
        op_id = operand_id_for_operation(rule.operation) or "keep"
        spec = operand_spec_by_id(op_id) or operand_spec_by_id("keep")
        assert spec is not None
        syntax = operand_syntax(spec)
        if syntax not in values:
            # Keep current (possibly orphan/custom-mapped) choice visible.
            values = [syntax] + values
        self._set_operand_combo_values(values)

    def _load_selection(self, tag: str) -> None:
        rule = self._document.get_rule(tag)
        if rule is None:
            self._clear_selection()
            return
        self._selected_tag = tag
        self._detail_updating = True
        try:
            vr = display_tag_vr(rule.tag)
            tag_label = format_dicom_tag(rule.tag)
            header = f"{rule.name}  ({tag_label}"
            if vr:
                header = f"{header}  {vr}"
            self._selection_label.configure(text=f"{header})")
            self._set_tag_description(rule.tag)
            op_id = operand_id_for_operation(rule.operation)
            help_text: str | None = None
            if op_id is None:
                # Unknown @… forms (not catalog / not fixed-value).
                self._custom_operation = rule.operation
                op_id = "keep"
                help_text = _(
                    "This rule uses a custom script value: {value}. "
                    "Choose a catalog operand to replace it."
                ).format(value=rule.operation or "@keep")
            elif op_id in ("lookup_ptid", "lookup_dateoffset") and not self._lookup_ctx.present:
                self._custom_operation = None
                help_text = _(
                    "This rule uses {value}, but no Patient Lookup Table is loaded. "
                    "Use Load Lookup Table next to the Operand control, or choose a "
                    "different operand."
                ).format(value=display_operation(rule.operation))
            elif op_id == "lookup_dateoffset" and not self._lookup_ctx.has_dateoffset:
                self._custom_operation = None
                help_text = _(
                    "This rule uses {value}, but the loaded lookup table has no "
                    "dateoffset entries. Use Replace Lookup Table, or choose a "
                    "different operand."
                ).format(value=display_operation(rule.operation))
            elif op_id == "rebasedate" and not (
                self._lookup_ctx.present and self._lookup_ctx.has_basedate
            ):
                self._custom_operation = None
                help_text = _(
                    "This rule uses {value}, but no basedate entries are loaded. "
                    "Use Load Lookup Table / Replace Lookup Table next to the "
                    "Operand control, or choose a different operand."
                ).format(value=display_operation(rule.operation))
            else:
                self._custom_operation = None

            spec = operand_spec_by_id(op_id) or operand_spec_by_id("keep")
            assert spec is not None
            # Combo + action row first so help lays out below their final height.
            self._configure_operand_combo_for_selection()
            self._operand_var.set(operand_syntax(spec))
            self._operand_combo.configure(state="readonly")
            self._error_label.configure(text="")
            self._refresh_operand_action_buttons()
            if help_text is not None:
                self._show_operand_help(help_text)
            else:
                self._update_help_for_operand(op_id)
        finally:
            self._detail_updating = False

    def _current_round_width(self) -> int:
        if self._selected_tag is None:
            return 5
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return 5
        match = _ROUND_WIDTH_RE.match(rule.operation or "")
        if match:
            return int(match.group(1))
        return 5

    def _current_increment_days(self) -> int:
        if self._selected_tag is not None:
            rule = self._document.get_rule(self._selected_tag)
            if rule is not None:
                days = incrementdate_days(rule.operation)
                if days is not None:
                    return days
        return 365

    def _current_rebase_origin(self) -> str:
        if self._selected_tag is not None:
            rule = self._document.get_rule(self._selected_tag)
            if rule is not None:
                origin = rebasedate_origin(rule.operation)
                if origin is not None:
                    return origin
        return "19600101"

    def _current_always_text(self) -> str:
        if self._selected_tag is None:
            return "YES"
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return "YES"
        text = always_literal_text(rule.operation)
        return text if text else "YES"

    def _prompt_operand_param(
        self,
        spec: OperandSpec,
        *,
        initial: int | str,
        kind: str = "int",
        message: str | None = None,
        detail: str | None = None,
        detail_title: str | None = None,
    ) -> int | str | None:
        title = _(spec.param_title_key) if spec.param_title_key else _("Operand parameter")
        return OperandParamDialog(
            self,
            title=title,
            message=message if message is not None else _(spec.param_help_key),
            detail=detail,
            detail_title=detail_title,
            initial=initial,
            kind=kind,
        ).result

    def _incrementdate_prompt_parts(self, spec: OperandSpec) -> tuple[str, str | None]:
        intro = _(spec.param_help_key)
        affected = rules_for_incrementdate_bulk(self._document, selected_tag=self._selected_tag)
        field_list = format_incrementdate_affected_lines(affected)
        return intro, field_list or None

    def _prompt_incrementdate_days(self, spec: OperandSpec) -> int | None:
        intro, detail = self._incrementdate_prompt_parts(spec)
        days = self._prompt_operand_param(
            spec,
            initial=self._current_increment_days(),
            kind="int_signed",
            message=intro,
            detail=detail,
            detail_title=_("Fields that will be set to @incrementdate(this,n):"),
        )
        return None if days is None else int(days)

    def _apply_incrementdate(self, days: int) -> None:
        """Apply shared DATEINC to every date-shift field (and the selection)."""
        if self._selected_tag is None or self._detail_updating:
            return
        tags = apply_incrementdate_to_rules(
            self._document, days, selected_tag=self._selected_tag
        )
        self._error_label.configure(text="")
        self._custom_operation = None
        for tag in tags:
            if self._tree.exists(tag):
                rule = self._document.get_rule(tag)
                if rule is not None:
                    self._tree.item(
                        tag,
                        values=self._rule_row_values(rule),
                    )
        self._autosize_name_column()
        self._update_help_for_operand("incrementdate")
        self._sync_operand_combo_from_rule()
        self._refresh_operand_action_buttons()

    def _operation_for_operand(
        self,
        op_id: str,
        *,
        round_width: int | None = None,
        always_text: str | None = None,
        increment_days: int | None = None,
        rebase_origin: str | None = None,
    ) -> tuple[str, str | None]:
        if self._custom_operation is not None and op_id == "keep":
            return self._custom_operation, None
        try:
            if op_id == "round":
                width = int(round_width if round_width is not None else self._current_round_width())
                return format_operand(op_id, round_width=width), None
            if op_id == "incrementdate":
                days = int(increment_days if increment_days is not None else self._current_increment_days())
                return format_operand(op_id, increment_days=days), None
            if op_id == "rebasedate":
                origin = rebase_origin if rebase_origin is not None else self._current_rebase_origin()
                return format_operand(op_id, rebase_origin=str(origin)), None
            if op_id == "always":
                text = always_text if always_text is not None else self._current_always_text()
                return format_operand(op_id, always_text=text), None
            return format_operand(op_id), None
        except ValueError as exc:
            return "", str(exc)

    def _apply_operand(
        self,
        op_id: str,
        *,
        round_width: int | None = None,
        always_text: str | None = None,
        increment_days: int | None = None,
        rebase_origin: str | None = None,
    ) -> None:
        if self._selected_tag is None or self._detail_updating:
            return
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return
        operation, err = self._operation_for_operand(
            op_id,
            round_width=round_width,
            always_text=always_text,
            increment_days=increment_days,
            rebase_origin=rebase_origin,
        )
        if err is not None:
            self._error_label.configure(text=err)
            return
        v_err = validate_operation(operation)
        if v_err is not None:
            self._error_label.configure(text=v_err)
            return

        was_removed = is_remove_operation(rule.operation)
        will_remove = is_remove_operation(operation)
        rule.operation = operation
        self._error_label.configure(text="")

        if was_removed != will_remove and self._view_mode is ScriptViewMode.ACTIVE:
            tag = rule.tag
            self._refresh_list()
            if will_remove:
                self._clear_selection()
            else:
                self._focus_tag_in_active(tag)
            return

        if self._tree.exists(rule.tag):
            self._tree.item(rule.tag, values=self._rule_row_values(rule))
            self._autosize_name_column()
        self._update_help_for_operand(op_id)
        self._refresh_operand_action_buttons()

    def _sync_operand_combo_from_rule(self) -> None:
        if self._selected_tag is None:
            return
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return
        op_id = operand_id_for_operation(rule.operation) or "keep"
        spec = operand_spec_by_id(op_id) or operand_spec_by_id("keep")
        assert spec is not None
        self._detail_updating = True
        try:
            self._operand_var.set(operand_syntax(spec))
        finally:
            self._detail_updating = False

    def _warn_if_incompatible(self, op_id: str) -> bool:
        """Show a warning and return True when the operand is a clear tag mismatch."""
        if self._selected_tag is None:
            return True
        rule = self._document.get_rule(self._selected_tag)
        if rule is None:
            return True
        msg = operand_tag_incompatibility(op_id, tag=rule.tag, name=rule.name or "")
        if msg is None:
            return False
        messagebox.showwarning(_("Incompatible operand"), _(msg), parent=self)
        return True

    def _on_operand_combo(self, value: str | None = None) -> None:
        """Preview operand help only; assignment requires Apply."""
        if self._detail_updating or self._selected_tag is None:
            return
        syntax = value or self._operand_var.get()
        op_id = operand_id_from_syntax(syntax) or "keep"
        self._update_help_for_operand(op_id)
        self._refresh_operand_action_buttons()
        rule = self._document.get_rule(self._selected_tag)
        warn = (
            operand_tag_incompatibility(op_id, tag=rule.tag, name=rule.name or "")
            if rule is not None
            else None
        )
        self._error_label.configure(text=_(warn) if warn else "")

    def _on_apply_operand(self) -> None:
        if self._detail_updating or self._selected_tag is None:
            return
        if not self._pending_operand_differs():
            self._refresh_operand_action_buttons()
            return
        op_id = self._pending_operand_id() or "keep"
        if self._warn_if_incompatible(op_id):
            self._sync_operand_combo_from_rule()
            rule = self._document.get_rule(self._selected_tag)
            if rule is not None:
                self._update_help_for_operand(operand_id_for_operation(rule.operation) or "keep")
            self._refresh_operand_action_buttons()
            self._error_label.configure(text="")
            return
        if op_id in _LOOKUP_TABLE_OPERANDS:
            if not self._ensure_lookup_for_operand(op_id):
                self._sync_operand_combo_from_rule()
                self._refresh_operand_action_buttons()
                return
            # Accepting a lookup table may already rewrite this rule.
            if not self._pending_operand_differs():
                self._refresh_operand_action_buttons()
                return
        spec = operand_spec_by_id(op_id)
        if spec is not None and spec.needs_param:
            if op_id == "always":
                always_text = self._prompt_operand_param(
                    spec, initial=self._current_always_text(), kind="str"
                )
                if always_text is None:
                    self._sync_operand_combo_from_rule()
                    self._refresh_operand_action_buttons()
                    return
                self._custom_operation = None
                self._apply_operand(op_id, always_text=str(always_text))
                self._refresh_operand_action_buttons()
                return
            if op_id == "incrementdate":
                days = self._prompt_incrementdate_days(spec)
                if days is None:
                    self._sync_operand_combo_from_rule()
                    self._refresh_operand_action_buttons()
                    return
                self._apply_incrementdate(days)
                self._refresh_operand_action_buttons()
                return
            if op_id == "rebasedate":
                origin = self._prompt_operand_param(
                    spec, initial=self._current_rebase_origin(), kind="da"
                )
                if origin is None:
                    self._sync_operand_combo_from_rule()
                    self._refresh_operand_action_buttons()
                    return
                self._custom_operation = None
                self._apply_operand(op_id, rebase_origin=str(origin))
                self._refresh_operand_action_buttons()
                return
            round_width = self._prompt_operand_param(
                spec, initial=self._current_round_width(), kind="int"
            )
            if round_width is None:
                self._sync_operand_combo_from_rule()
                self._refresh_operand_action_buttons()
                return
            self._custom_operation = None
            self._apply_operand(op_id, round_width=int(round_width))
            self._refresh_operand_action_buttons()
            return
        self._custom_operation = None
        self._apply_operand(op_id)
        self._refresh_operand_action_buttons()

    def _on_change_param(self) -> None:
        if self._selected_tag is None:
            return
        op_id = operand_id_from_syntax(self._operand_var.get()) or "keep"
        spec = operand_spec_by_id(op_id)
        if spec is None or not spec.needs_param:
            return
        if op_id == "always":
            always_text = self._prompt_operand_param(
                spec, initial=self._current_always_text(), kind="str"
            )
            if always_text is None:
                return
            self._custom_operation = None
            self._apply_operand(op_id, always_text=str(always_text))
            return
        if op_id == "incrementdate":
            days = self._prompt_incrementdate_days(spec)
            if days is None:
                return
            self._apply_incrementdate(days)
            return
        if op_id == "rebasedate":
            if not self._ensure_lookup_for_operand(op_id):
                return
            origin = self._prompt_operand_param(
                spec, initial=self._current_rebase_origin(), kind="da"
            )
            if origin is None:
                return
            self._custom_operation = None
            self._apply_operand(op_id, rebase_origin=str(origin))
            return
        width = self._prompt_operand_param(spec, initial=self._current_round_width(), kind="int")
        if width is None:
            return
        self._custom_operation = None
        self._apply_operand(op_id, round_width=int(width))

    def _focus_tag_in_active(self, tag: str) -> None:
        self._view_var.set("active")
        self._view_mode = ScriptViewMode.ACTIVE
        self._search_var.set("")
        self._operand_filter_var.set(_("All"))
        self._refresh_list(focus_tag=tag)

    def _open_add_dictionary(self) -> None:
        if self._dict_dialog is not None:
            try:
                if self._dict_dialog.winfo_exists():
                    self._dict_dialog.lift()
                    self._dict_dialog.focus_force()
                    return
            except tk.TclError:
                self._dict_dialog = None
        # Parent grab blocks sibling/child toplevel events on macOS; release while open.
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self._dict_dialog = AddFromDictionaryDialog(
            self,
            document=self._document,
            on_added=self._after_dictionary_add,
            on_closed=self._on_dictionary_dialog_closed,
        )

    def _restore_script_grab(self) -> None:
        with contextlib.suppress(tk.TclError):
            if self.winfo_exists():
                self.grab_set()
                self.lift()

    def _on_dictionary_dialog_closed(self) -> None:
        self._dict_dialog = None
        self._restore_script_grab()

    def _after_dictionary_add(self, tags: list[str]) -> None:
        self._refresh_add_dictionary_visibility()
        if tags:
            self._focus_tag_in_active(tags[-1])

    def _close_dictionary_dialog(self) -> None:
        dlg = self._dict_dialog
        if dlg is None:
            return
        with contextlib.suppress(tk.TclError):
            if dlg.winfo_exists():
                dlg._on_cancel()
            else:
                self._dict_dialog = None

    def _on_destroy(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        self._close_dictionary_dialog()

    def _lookup_ctx_ready(self, op_id: str) -> bool:
        """True when the loaded (or pending) lookup table satisfies ``op_id``."""
        ctx = self._lookup_ctx
        if op_id == "lookup_ptid":
            return ctx.present
        if op_id == "lookup_dateoffset":
            return ctx.present and ctx.has_dateoffset
        if op_id == "rebasedate":
            return ctx.present and ctx.has_basedate
        return True

    def _lookup_unmet_message(self, op_id: str) -> str:
        if op_id == "lookup_dateoffset":
            return _(
                "The lookup table has no dateoffset entries. "
                "Load a .properties file that includes dateoffset/<PatientID>=N lines, "
                "or choose a different operand."
            )
        if op_id == "rebasedate":
            return _(
                "The lookup table has no basedate entries. "
                "Load a .properties file that includes basedate/<PatientID>=YYYYMMDD lines, "
                "or choose a different operand."
            )
        return _(
            "No patient lookup table is loaded. "
            "Load a CTP .properties file with ptid/<PatientID>=… lines, "
            "or choose a different operand."
        )

    def _ensure_lookup_for_operand(self, op_id: str) -> bool:
        """Open LookupTableDialog when needed; return True if ``op_id`` can proceed."""
        if self._lookup_ctx_ready(op_id):
            return True
        if not self._run_lookup_table_dialog():
            return False
        if self._lookup_ctx_ready(op_id):
            return True
        messagebox.showerror(
            _("Patient Lookup Table"),
            self._lookup_unmet_message(op_id),
            parent=self,
        )
        return False

    def _on_lookup_table_button(self) -> None:
        """Load or replace the CTP lookup table for the selected lookup-dependent rule."""
        if self._selected_tag is None:
            return
        op_id = self._pending_operand_id() or self._rule_operand_id() or "keep"
        if not self._run_lookup_table_dialog():
            return
        if op_id in _LOOKUP_TABLE_OPERANDS and not self._lookup_ctx_ready(op_id):
            messagebox.showerror(
                _("Patient Lookup Table"),
                self._lookup_unmet_message(op_id),
                parent=self,
            )
        if self._selected_tag is not None:
            self._load_selection(self._selected_tag)

    def _run_lookup_table_dialog(self) -> bool:
        """Open the lookup-table dialog and wait; return True if the user accepted."""

        def on_pending(preview: CtpLookupPreview) -> None:
            self._pending_lookup_preview = preview
            if self._on_pending_lookup_preview is not None:
                self._on_pending_lookup_preview(preview)

        def on_document_patched(preview: CtpLookupPreview) -> None:
            self._pending_lookup_preview = preview if self.project_controller is None else None
            if self.project_controller is not None:
                private = private_anonymizer_script_path(self.project_model)
                self._script_path = private
            self._refresh_lookup_context()
            self._refresh_path_label()
            self._refresh_list(focus_tag=self._selected_tag)

        dialog = LookupTableDialog(
            self,
            project_controller=self.project_controller,
            on_script_path_changed=self._on_script_path_changed,
            on_pending_preview=on_pending if self.project_controller is None else None,
            script_document=self._document,
            on_document_patched=on_document_patched,
        )
        self.wait_window(dialog)
        with contextlib.suppress(tk.TclError):
            if self.winfo_exists():
                self.grab_set()
                self.lift()
        return bool(dialog.committed())

    def _on_revert(self) -> None:
        if not messagebox.askyesno(
            _("Revert"),
            _("Reload the script from disk and discard unsaved edits?"),
            parent=self,
        ):
            return
        try:
            self._document = load_script_rules(self._script_path)
        except Exception as exc:
            messagebox.showerror(_("Edit Anonymizer Script"), str(exc), parent=self)
            return
        self._clear_selection()
        self._refresh_add_dictionary_visibility()
        self._refresh_lookup_context()
        self._refresh_list()

    def _on_accept(self) -> None:
        self._close_dictionary_dialog()
        try:
            if self.project_controller is not None:
                dest = commit_script_edit(self.project_controller, self._document)
            else:
                dest = stage_script_edit(self.project_model, self._document)
            if self._on_script_path_changed is not None:
                self._on_script_path_changed(dest)
            self._script_path = dest
            self._refresh_path_label()
            self._committed = True
        except Exception as exc:
            logger.exception("Script edit commit failed")
            messagebox.showerror(_("Edit Anonymizer Script"), str(exc), parent=self)
            return
        messagebox.showinfo(
            _("Edit Anonymizer Script"),
            _("Anonymizer script was updated successfully."),
            parent=self,
        )
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_cancel(self, _event=None) -> None:
        self._close_dictionary_dialog()
        teardown_ctk_toplevel(self, parent=self.master)

    def committed(self) -> bool:
        return self._committed


class OperandParamDialog(AppToplevel):
    """Prompt for an operand parameter with a clear units/meaning description.

    Layout: intro message → ux_fields entry → optional detail (e.g. DATEINC field list) → buttons.
    Padding matches settings dialogs (``_CHILD_DIALOG_PAD`` around the frame and on each row).
    """

    _LINE_PX = 17
    _DIALOG_W = 520
    _WRAP = 480
    # Day offset range (~±100 years); age band width in whole years.
    _DATEINC_MIN = -36500
    _DATEINC_MAX = 36500
    _ROUND_MIN = 1
    _ROUND_MAX = 120
    _ALWAYS_MAX_CHARS = 64

    def __init__(
        self,
        parent,
        *,
        title: str,
        message: str,
        initial: int | str,
        kind: str = "int",
        detail: str | None = None,
        detail_title: str | None = None,
    ):
        super().__init__(master=parent)
        # Build while withdrawn so the first paint is already centered (no +0+0 flash).
        self.withdraw()
        self.result: int | str | None = None
        self._title = title
        self._kind = kind if kind in ("int", "int_signed", "str", "da") else "int"
        self.title(title)
        self._detail = (detail or "").strip() or None
        self._detail_title = (detail_title or "").strip() or None
        self._has_detail = self._detail is not None
        self._long_intro = message.count("\n") >= 6 or len(message) > 420
        self.resizable(bool(self._has_detail or self._long_intro), bool(self._has_detail or self._long_intro))
        self.minsize(480 if self._has_detail else 420, 180)

        pad = _CHILD_DIALOG_PAD
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        frame.grid_columnconfigure(1, weight=1)
        row = 0

        if self._long_intro and not self._has_detail:
            intro_h = self._text_height(message, parent=parent, chrome=self._CHROME_WITHOUT_DETAIL)
            intro = ctk.CTkTextbox(frame, wrap="word", height=intro_h, activate_scrollbars=True)
            intro.grid(row=row, column=0, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
            intro.insert("1.0", message)
            intro.configure(state="disabled")
        else:
            ctk.CTkLabel(frame, text=message, justify="left", wraplength=self._WRAP, anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0)
            )
        row += 1

        self._int_var: ctk.IntVar | None = None
        self._str_var: ctk.StringVar | None = None
        if self._kind == "int_signed":
            self._int_var = int_entry(
                view=frame,
                label=_("Day offset") + ":",
                initial_value=int(initial),
                min=self._DATEINC_MIN,
                max=self._DATEINC_MAX,
                tooltipmsg=None,
                row=row,
                col=0,
                pad=pad,
                sticky="nw",
                focus_set=True,
            )
        elif self._kind == "int":
            self._int_var = int_entry(
                view=frame,
                label=_("Band width (years)") + ":",
                initial_value=int(initial),
                min=self._ROUND_MIN,
                max=self._ROUND_MAX,
                tooltipmsg=None,
                row=row,
                col=0,
                pad=pad,
                sticky="nw",
                focus_set=True,
            )
        elif self._kind == "da":
            self._str_var = str_entry(
                view=frame,
                label=_("Origin (YYYYMMDD)") + ":",
                initial_value=str(initial),
                min_chars=dicom_date_chars,
                max_chars=dicom_date_chars,
                charset=string.digits,
                tooltipmsg=None,
                row=row,
                col=0,
                pad=pad,
                sticky="nw",
                width_chars=dicom_date_chars,
                focus_set=True,
            )
        else:
            self._str_var = str_entry(
                view=frame,
                label=_("Fixed value") + ":",
                initial_value=str(initial),
                min_chars=1,
                max_chars=self._ALWAYS_MAX_CHARS,
                charset=string.ascii_letters + string.digits + " -_./",
                tooltipmsg=None,
                row=row,
                col=0,
                pad=pad,
                sticky="nw",
                width_chars=24,
                focus_set=True,
            )
        row += 1

        if self._has_detail:
            assert self._detail is not None
            if self._detail_title:
                ctk.CTkLabel(
                    frame,
                    text=self._detail_title,
                    justify="left",
                    wraplength=self._WRAP,
                    anchor="w",
                ).grid(row=row, column=0, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
                row += 1
            detail_h = self._text_height(self._detail, parent=parent, chrome=self._CHROME_WITH_DETAIL)
            detail_box = ctk.CTkTextbox(frame, wrap="word", height=detail_h, activate_scrollbars=True)
            # No extra top pad when a title row already separated the list.
            detail_top = 0 if self._detail_title else pad
            detail_box.grid(
                row=row, column=0, columnspan=2, sticky="ew", padx=pad, pady=(detail_top, 0)
            )
            detail_box.insert("1.0", self._detail)
            detail_box.configure(state="disabled")
            row += 1

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.grid(row=row, column=0, columnspan=2, sticky="e", padx=pad, pady=pad)
        ctk.CTkButton(btns, text=_("Cancel"), width=90, command=self._on_cancel).pack(side="left", padx=(0, pad))
        ctk.CTkButton(btns, text=_("OK"), width=90, command=self._on_ok).pack(side="left")

        self._place_centered_on_parent(parent)
        self.deiconify()
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, self._on_cancel)
        self.grab_set()
        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", self._on_cancel)
        self.wait_window()

    _CHROME_WITHOUT_DETAIL = 120
    _CHROME_WITH_DETAIL = 220  # intro label + entry + buttons + padding

    def _text_height(self, text: str, *, parent, chrome: int) -> int:
        """Pixel height for a textbox that fits ``text``, clamped to the parent."""
        lines = text.count("\n") + 1
        wrap_extra = sum(max(0, (len(line) - 1) // 70) for line in text.splitlines() or [text])
        needed = (lines + wrap_extra) * self._LINE_PX + 12
        max_h = 560
        with contextlib.suppress(tk.TclError):
            parent.update_idletasks()
            parent_h = int(parent.winfo_height())
            if parent_h > 1:
                max_h = max(80, parent_h - chrome - 40)
        return max(80, min(needed, max_h))

    def _place_centered_on_parent(self, parent) -> None:
        self.update_idletasks()
        width = max(self._DIALOG_W if self._has_detail else 420, int(self.winfo_reqwidth()))
        height = int(self.winfo_reqheight())
        with contextlib.suppress(tk.TclError):
            parent.update_idletasks()
            parent_h = int(parent.winfo_height())
            if parent_h > 1:
                height = min(height, max(200, parent_h - 20))
        place_toplevel_centered_on_parent(self, parent, width=width, height=height)

    def _on_ok(self) -> None:
        if self._kind in ("int", "int_signed"):
            assert self._int_var is not None
            try:
                value = int(self._int_var.get())
            except (tk.TclError, ValueError):
                if self._kind == "int_signed":
                    messagebox.showerror(
                        self._title,
                        _("Enter a whole number (may be negative)."),
                        parent=self,
                    )
                else:
                    messagebox.showerror(self._title, _("Enter a whole number ≥ 1."), parent=self)
                return
            if self._kind == "int" and value < self._ROUND_MIN:
                messagebox.showerror(self._title, _("Enter a whole number ≥ 1."), parent=self)
                return
            self.result = value
            teardown_ctk_toplevel(self, parent=self.master)
            return

        assert self._str_var is not None
        raw = self._str_var.get().strip()
        if self._kind == "da":
            if len(raw) != dicom_date_chars or not raw.isdigit():
                messagebox.showerror(
                    self._title,
                    _("Enter a date as YYYYMMDD (eight digits)."),
                    parent=self,
                )
                return
            try:
                from datetime import datetime

                datetime.strptime(raw, "%Y%m%d")
            except ValueError:
                messagebox.showerror(
                    self._title,
                    _("Enter a valid calendar date as YYYYMMDD."),
                    parent=self,
                )
                return
            self.result = raw
            teardown_ctk_toplevel(self, parent=self.master)
            return

        if not raw:
            messagebox.showerror(
                self._title,
                _("Enter a non-empty fixed value."),
                parent=self,
            )
            return
        if raw.startswith("@"):
            messagebox.showerror(
                self._title,
                _("Fixed value must be literal text, not another @ operand."),
                parent=self,
            )
            return
        self.result = raw
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_cancel(self, _event=None) -> None:
        self.result = None
        teardown_ctk_toplevel(self, parent=self.master)


class AddFromDictionaryDialog(AppToplevel):
    """Non-modal picker: parent stays usable; closes when parent does."""

    _BUTTON_WIDTH = 120

    def __init__(
        self,
        parent: AnonymizerScriptDialog,
        *,
        document: ScriptDocument,
        on_added: Callable[[list[str]], None],
        on_closed: Callable[[], None] | None = None,
    ):
        super().__init__(master=parent)
        self._document = document
        self._on_added = on_added
        self._on_closed = on_closed
        self._hits = []
        self._search_after_id: str | None = None
        self._char_width_px = max(7, default_char_width_px())
        self._closing = False

        self.title(_("Add from Dictionary"))
        self.resizable(True, True)
        self.minsize(560, 420)
        self._build()
        self._run_search()
        self.wait_visibility()
        self.lift()
        self.focus_force()
        # Non-modal relative to parent: parent released its grab so both stay interactive.
        install_modal_dismiss(self, self._on_cancel)
        self.bind("<Escape>", self._on_cancel)
        self.bind("<Destroy>", self._on_destroy, add="+")

    def _build(self) -> None:
        pad = _CHILD_DIALOG_PAD
        btn_w = self._BUTTON_WIDTH
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Index chrome (matches Dataset / Edit Anonymizer Script)
        index_frame = ctk.CTkFrame(self)
        index_frame.grid(row=0, column=0, sticky="nsew", padx=pad, pady=(pad, 0))
        index_frame.grid_columnconfigure(0, weight=1)
        index_frame.grid_rowconfigure(1, weight=1)

        self._search_var = tk.StringVar(value="")
        self._search_var.trace_add("write", self._on_search_trace)
        ctk.CTkEntry(
            index_frame,
            textvariable=self._search_var,
            placeholder_text=_("Search missing tags (optional, min 2 chars)"),
        ).grid(row=0, column=0, sticky="ew", padx=pad, pady=pad)

        list_frame = ctk.CTkFrame(index_frame, fg_color="transparent")
        list_frame.grid(row=1, column=0, sticky="nsew", padx=pad, pady=(0, pad))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            list_frame,
            columns=("name", "tag", "vr"),
            show="headings",
            style="Treeview",
            selectmode="extended",
        )
        self._tree.heading("name", text=_("Name"))
        self._tree.heading("tag", text=_("Tag"))
        self._tree.heading("vr", text=_("VR"))
        self._tree.column("name", width=self._char_width_px * 28, stretch=True, anchor="w")
        self._tree.column("tag", width=self._char_width_px * 10, stretch=False, anchor="w")
        self._tree.column("vr", width=self._char_width_px * 6, stretch=False, anchor="w")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=yscroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self._tree.bind("<Double-Button-1>", lambda _e: self._on_add())
        self._tree.bind("<Return>", lambda _e: self._on_add())

        ctk.CTkLabel(
            index_frame,
            text=_(
                "Only tags missing from the script are listed. Leave search empty to browse. "
                "Select multiple with Shift-click and Ctrl/Cmd-click."
            ),
            justify="left",
            anchor="w",
            wraplength=520,
        ).grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, pad))

        # Button bar (Dataset-style)
        button_frame = ctk.CTkFrame(self)
        button_frame.grid(row=1, column=0, sticky="ew", padx=pad, pady=pad)
        button_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            button_frame,
            text=_("Select All"),
            width=btn_w,
            command=self._select_all,
        ).grid(row=0, column=1, sticky="e", padx=pad, pady=pad)
        ctk.CTkButton(
            button_frame,
            text=_("Clear Selection"),
            width=btn_w,
            command=self._clear_selection,
        ).grid(row=0, column=2, sticky="e", padx=(0, pad), pady=pad)
        ctk.CTkButton(
            button_frame,
            text=_("Cancel"),
            width=btn_w,
            command=self._on_cancel,
        ).grid(row=0, column=3, sticky="e", padx=(0, pad), pady=pad)
        ctk.CTkButton(
            button_frame,
            text=_("Add"),
            width=btn_w,
            command=self._on_add,
        ).grid(row=0, column=4, sticky="e", padx=(0, pad), pady=pad)

    def _on_search_trace(self, *_args) -> None:
        if self._search_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(_SEARCH_DEBOUNCE_MS, self._run_search)

    def _run_search(self) -> None:
        self._hits = search_missing_dictionary_tags(self._document, self._search_var.get(), limit=200)
        for item in self._tree.get_children():
            self._tree.delete(item)
        for hit in self._hits:
            self._tree.insert(
                "",
                "end",
                iid=hit.tag,
                values=(hit.keyword, format_dicom_tag(hit.tag), hit.vr),
            )

    def _select_all(self) -> None:
        self._tree.selection_set(*self._tree.get_children(""))

    def _clear_selection(self) -> None:
        self._tree.selection_set([])

    def _on_add(self) -> None:
        selection = list(self._tree.selection())
        if not selection:
            messagebox.showinfo(_("Add from Dictionary"), _("Select one or more dictionary tags first."), parent=self)
            return
        hits_by_tag = {h.tag: h for h in self._hits}
        added: list[str] = []
        for tag in selection:
            hit = hits_by_tag.get(tag)
            if hit is None:
                continue
            try:
                add_rule_from_dictionary(self._document, tag=hit.tag, name=hit.keyword, operation="")
            except Exception as exc:
                messagebox.showerror(_("Add from Dictionary"), str(exc), parent=self)
                break
            added.append(hit.tag)
        if not added:
            return
        self._on_added(added)
        self._run_search()

    def _notify_closed(self) -> None:
        callback = self._on_closed
        self._on_closed = None
        if callback is not None:
            callback()

    def _on_cancel(self, _event=None) -> None:
        if self._closing:
            return
        self._closing = True
        self._notify_closed()
        teardown_ctk_toplevel(self, parent=self.master)

    def _on_destroy(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        if self._closing:
            return
        self._closing = True
        self._notify_closed()
