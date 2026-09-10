"""Modal to pick one RadLex/LOINC description and apply it to a Dataset multi-select."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from dataclasses import dataclass
from typing import Literal

import customtkinter as ctk
from customtkinter import ThemeManager

from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

logger = logging.getLogger(__name__)

CatalogKind = Literal["radlex", "loinc"]


@dataclass(frozen=True)
class SetDescriptionDialogResult:
    applied: bool = False
    description: str | None = None
    loinc_number: str | None = None


def _catalog_label(kind: CatalogKind, modality: str = "") -> str:
    mod = (modality or "").strip()
    if kind == "loinc":
        if mod:
            return _("{modality} LOINC study descriptions").format(modality=mod)
        return _("LOINC study descriptions")
    if mod:
        return _("{modality} RadLex Playbook series descriptions").format(modality=mod)
    return _("RadLex Playbook series descriptions")


def _find_theme_host(widget: tk.Misc) -> tk.Misc | None:
    """Walk masters to the CTk root that applies appearance-mode theme colors."""
    current: tk.Misc | None = widget
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if callable(getattr(current, "_apply_appearance_mode", None)):
            return current
        nxt = getattr(current, "master", None)
        if nxt is None or nxt is current:
            break
        current = nxt
    return None


def _listbox_theme_colors(host: tk.Misc) -> tuple[str, str, str, str]:
    """Same Treeview palette the app configures globally at startup."""
    apply = host._apply_appearance_mode  # type: ignore[attr-defined]
    theme = ThemeManager.theme
    bg = apply(theme["CTkFrame"]["fg_color"])
    fg = apply(theme["CTkLabel"]["text_color"])
    select_bg = apply(theme["CTkButton"]["fg_color"])
    select_fg = apply(theme["CTkButton"]["text_color"])
    tv = theme.get("Treeview") or {}
    if "bg_color" in tv:
        bg = apply(tv["bg_color"])
    if "text_color" in tv:
        fg = apply(tv["text_color"])
    if "selected_bg_color" in tv:
        select_bg = apply(tv["selected_bg_color"])
    if "selected_color" in tv:
        select_fg = apply(tv["selected_color"])
    return str(bg), str(fg), str(select_bg), str(select_fg)


class SetDescriptionDialog(AppToplevel):
    """Pick one description from a scrollable list (Listbox + CTkScrollbar, global theme colors)."""

    PAD = 10
    DIALOG_WIDTH = 640
    DIALOG_HEIGHT = 480
    MIN_WIDTH = 480
    MIN_HEIGHT = 360
    LIST_HEIGHT = 18

    def __init__(
        self,
        parent: tk.Misc,
        *,
        title: str,
        hint: str,
        choices: list[str],
        choice_meta: dict[str, str | None],
        initial: str,
        catalog_kind: CatalogKind,
        modality: str = "",
    ):
        super().__init__(master=parent)
        self.title(title)
        self._result = SetDescriptionDialogResult()
        self._choice_meta = dict(choice_meta)
        self._choices = list(choices)
        self._filtered = list(choices)
        self._closing = False

        self.resizable(True, True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

        self._create_widgets(hint=hint, catalog_kind=catalog_kind, initial=initial, modality=modality)
        self.wait_visibility()
        self.lift()
        self.grab_set()

    def _create_widgets(
        self, *, hint: str, catalog_kind: CatalogKind, initial: str, modality: str
    ) -> None:
        pad = self.PAD

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(body, text=hint, anchor="w", justify="left", wraplength=self.DIALOG_WIDTH - 2 * pad).grid(
            row=0, column=0, sticky="ew", pady=(0, 4)
        )
        ctk.CTkLabel(
            body,
            text=_catalog_label(catalog_kind, modality),
            anchor="w",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=1, column=0, sticky="ew", pady=(0, pad))

        self._filter_var = tk.StringVar(value="")
        filter_entry = ctk.CTkEntry(body, textvariable=self._filter_var, placeholder_text=_("Filter…"))
        filter_entry.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self._filter_var.trace_add("write", lambda *_args: self._apply_filter())

        list_frame = ctk.CTkFrame(body, fg_color="transparent")
        list_frame.grid(row=3, column=0, sticky="nsew")
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)

        theme_host = _find_theme_host(self.master) or _find_theme_host(self)
        if theme_host is not None:
            bg, fg, select_bg, select_fg = _listbox_theme_colors(theme_host)
        else:
            bg, fg, select_bg, select_fg = ("gray90", "#014F8F", "#3a7ebf", "#DCE4EE")

        scrollbar = ctk.CTkScrollbar(list_frame, orientation="vertical")
        self._listbox = tk.Listbox(
            list_frame,
            height=self.LIST_HEIGHT,
            border=0,
            yscrollcommand=scrollbar.set,
            bg=bg,
            fg=fg,
            selectbackground=select_bg,
            selectforeground=select_fg,
            highlightthickness=0,
            activestyle="none",
            exportselection=False,
        )
        scrollbar.configure(command=self._listbox.yview)
        self._listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._listbox.bind("<Double-Button-1>", self._ok_event)

        self._count_var = tk.StringVar(value="")
        ctk.CTkLabel(body, textvariable=self._count_var, anchor="w").grid(
            row=4, column=0, sticky="ew", pady=(6, 0)
        )

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, pad))
        footer.grid_columnconfigure(0, weight=1)
        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="e")
        ctk.CTkButton(btn_row, width=100, text=_("Cancel"), command=self._on_cancel).pack(side="left", padx=(0, 8))
        self._ok_button = ctk.CTkButton(btn_row, width=100, text=_("Apply"), command=self._ok_event)
        self._ok_button.pack(side="left")

        self._populate_list(initial if initial in self._choices else (self._choices[0] if self._choices else ""))
        if not self._choices:
            self._ok_button.configure(state="disabled")

        self.geometry(f"{self.DIALOG_WIDTH}x{self.DIALOG_HEIGHT}")
        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        filter_entry.focus()

    def _apply_filter(self) -> None:
        needle = self._filter_var.get().strip().lower()
        if not needle:
            self._filtered = list(self._choices)
        else:
            self._filtered = [c for c in self._choices if needle in c.lower()]
        selected = self._selected_label()
        self._populate_list(selected if selected in self._filtered else "")

    def _populate_list(self, select_label: str) -> None:
        self._listbox.delete(0, tk.END)
        for label in self._filtered:
            self._listbox.insert(tk.END, label)

        total = len(self._choices)
        shown = len(self._filtered)
        if shown == total:
            self._count_var.set(_("{n} descriptions").format(n=total))
        else:
            self._count_var.set(_("{shown} of {total} descriptions").format(shown=shown, total=total))

        if not self._filtered:
            self._ok_button.configure(state="disabled")
            return
        self._ok_button.configure(state="normal")
        index = 0
        if select_label:
            with contextlib.suppress(ValueError):
                index = self._filtered.index(select_label)
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(index)
        self._listbox.activate(index)
        self._listbox.see(index)

    def _selected_label(self) -> str:
        sel = self._listbox.curselection()
        if not sel:
            return ""
        return str(self._listbox.get(sel[0]))

    def _enter_keypress(self, _event=None) -> None:
        self._ok_event()

    def _ok_event(self, _event=None) -> None:
        if self._closing:
            return
        label = self._selected_label().strip()
        if not label or label not in self._choices:
            return
        description = label
        loinc_number = self._choice_meta.get(label)
        if "  (" in label and label.endswith(")"):
            description = label.rsplit("  (", 1)[0].strip()
            if loinc_number is None:
                code = label.rsplit("  (", 1)[-1].rstrip(")")
                loinc_number = code or None
        self._result = SetDescriptionDialogResult(
            applied=True,
            description=description,
            loinc_number=loinc_number,
        )
        self._closing = True
        teardown_ctk_toplevel(self, parent=self.master)

    def _escape_keypress(self, _event=None) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        if self._closing:
            return
        self._closing = True
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self) -> SetDescriptionDialogResult:
        self.focus()
        self.master.wait_window(self)
        return self._result


def show_set_description_dialog(
    parent: tk.Misc,
    *,
    title: str,
    hint: str,
    choices: list[str],
    choice_meta: dict[str, str | None] | None = None,
    initial: str = "",
    catalog_kind: CatalogKind = "radlex",
    modality: str = "",
) -> SetDescriptionDialogResult:
    meta = choice_meta or {label: None for label in choices}
    dialog = SetDescriptionDialog(
        parent,
        title=title,
        hint=hint,
        choices=choices,
        choice_meta=meta,
        initial=initial,
        catalog_kind=catalog_kind,
        modality=modality,
    )
    return dialog.get_input()
