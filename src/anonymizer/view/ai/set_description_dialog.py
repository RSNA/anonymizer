"""Modal to pick one RadLex/LOINC description and apply it to a Dataset multi-select."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import customtkinter as ctk
from customtkinter import ThemeManager

from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.tooltip import MotionTooltipController

logger = logging.getLogger(__name__)

CatalogKind = Literal["radlex", "loinc"]

ExpandCatalogLoader = Callable[[], tuple[list[str], dict[str, str | None]]]
ComposeOptionsLoader = Callable[[bool], dict[str, list[str]]]
ComposeFormatter = Callable[[dict[str, str]], str]

_EMPTY_CODE_DISPLAY = "—"


@dataclass(frozen=True)
class SetDescriptionDialogResult:
    applied: bool = False
    description: str | None = None
    loinc_number: str | None = None


@dataclass(frozen=True)
class RadLexComposeSpec:
    """Component-wise RadLex Playbook composer (avoids cartesian full catalogs)."""

    field_order: tuple[str, ...]
    field_labels: dict[str, str]
    initial: dict[str, str]
    load_options: ComposeOptionsLoader
    format_description: ComposeFormatter


def _catalog_label(kind: CatalogKind, modality: str = "", *, full: bool = False) -> str:
    mod = (modality or "").strip()
    if kind == "loinc":
        if full:
            if mod:
                return _("Full {modality} LOINC study catalog").format(modality=mod)
            return _("Full LOINC study catalog")
        if mod:
            return _("{modality} LOINC study descriptions (closest matches)").format(modality=mod)
        return _("LOINC study descriptions (closest matches)")
    if full:
        if mod:
            return _("Compose {modality} RadLex Playbook (all codes)").format(modality=mod)
        return _("Compose RadLex Playbook (all codes)")
    if mod:
        return _("{modality} RadLex Playbook series descriptions (closest matches)").format(modality=mod)
    return _("RadLex Playbook series descriptions (closest matches)")


def _compose_catalog_label(modality: str = "", *, full_vocab: bool = False) -> str:
    mod = (modality or "").strip()
    if full_vocab:
        if mod:
            return _("Compose {modality} RadLex · all codes per field").format(modality=mod)
        return _("Compose RadLex · all codes per field")
    if mod:
        return _("Compose {modality} RadLex · closest codes per field").format(modality=mod)
    return _("Compose RadLex · closest codes per field")


def _compose_blank_header(modality: str = "") -> str:
    """Header when a blank / unharmonized series opens directly in stepwise Compose."""
    mod = (modality or "").strip()
    if mod:
        return _("No description yet · pick each {modality} RadLex field").format(modality=mod)
    return _("No description yet · pick each RadLex field")


def _expand_button_label(kind: CatalogKind) -> str:
    if kind == "loinc":
        return _("Show full LOINC catalog…")
    return _("Compose RadLex…")


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


def _display_code(code: str) -> str:
    return _EMPTY_CODE_DISPLAY if code == "" else code


def _code_from_display(label: str) -> str:
    return "" if label == _EMPTY_CODE_DISPLAY else label


class SetDescriptionDialog(AppToplevel):
    """Pick one description from a scrollable list, or compose RadLex field-by-field.

    Startup conditions (one chrome, one compose entry, one sizer):

    * **List** — harmonized (or LOINC): filterable choices; optional Compose RadLex…
    * **Compose closest** — Compose RadLex… button: ``full_vocab=False``, all fields
    * **Compose stepwise** — unharmonized auto-open: ``full_vocab=True``, reveal L→R;
      after Body/Plane/Contrast unlock remainder with "—"; blank hides Closest toggle
    """

    PAD = 10
    DIALOG_WIDTH = 640
    DIALOG_HEIGHT = 480
    MIN_WIDTH = 480
    MIN_HEIGHT = 360
    LIST_HEIGHT = 18
    COMPOSE_BODY_LIST_HEIGHT = 12

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
        expand_loader: ExpandCatalogLoader | None = None,
        showing_full_catalog: bool = False,
        compose_spec: RadLexComposeSpec | None = None,
        start_in_compose: bool = False,
        compose_full_vocab: bool = False,
        blank_compose: bool = False,
    ):
        super().__init__(master=parent)
        self.withdraw()
        self.title(title)
        self._result = SetDescriptionDialogResult()
        self._choice_meta = dict(choice_meta)
        self._choices = list(choices)
        self._filtered = list(choices)
        self._closing = False
        self._filter_ready = False
        self._catalog_kind = catalog_kind
        self._modality = modality
        self._expand_loader = expand_loader
        self._showing_full_catalog = showing_full_catalog
        self._compose_spec = compose_spec
        self._compose_mode = False
        self._full_vocab = False
        self._compose_options: dict[str, list[str]] = {}
        self._compose_listboxes: dict[str, tk.Listbox] = {}
        self._compose_cells: dict[str, ctk.CTkFrame] = {}
        self._compose_chosen: dict[str, str] = {}
        # False = step-by-step reveal; True = show every field (closest / unlocked).
        self._compose_show_all = False
        self._compose_visible_count = 1
        self._list_theme = ("gray90", "#014F8F", "#3a7ebf", "#DCE4EE")
        self._field_label_font = ctk.CTkFont(size=13, weight="bold")
        self._start_in_compose = start_in_compose and compose_spec is not None
        self._compose_full_vocab_on_open = bool(compose_full_vocab)
        # Blank unharmonized: stepwise all-codes with no Closest toggle.
        self._blank_compose = bool(blank_compose) and self._start_in_compose
        self._blank_compose_hint = (
            _compose_blank_header(modality) if self._blank_compose else None
        )

        self.resizable(True, True)
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

        # Single chrome for every startup; compose always enters via ``_enter_compose_mode``.
        self._create_widgets(hint=hint, initial=initial)
        self.update_idletasks()
        self.deiconify()
        self.wait_visibility()
        self.lift()
        self.grab_set()
        if self._start_in_compose:
            # Same entry as Compose RadLex…; ``full_vocab`` selects closest vs stepwise.
            self._enter_compose_mode(full_vocab=self._compose_full_vocab_on_open)
            self._ok_button.focus()
        else:
            self._filter_entry.focus()

    def _create_widgets(self, *, hint: str, initial: str) -> None:
        pad = self.PAD
        self._frame = ctk.CTkFrame(self)
        self._frame.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._frame.grid_columnconfigure(0, weight=1)
        # List mode stretches the catalog row; compose clears this weight.
        self._frame.grid_rowconfigure(3, weight=1)

        self._hint_label = ctk.CTkLabel(
            self._frame,
            text=hint,
            anchor="w",
            justify="left",
            wraplength=self.DIALOG_WIDTH - 4 * pad,
        )
        self._hint_label.grid(row=0, column=0, sticky="ew", padx=pad, pady=(pad, 4))

        self._catalog_label = ctk.CTkLabel(
            self._frame,
            text=_catalog_label(
                self._catalog_kind,
                self._modality,
                full=self._showing_full_catalog,
            ),
            anchor="w",
            font=ctk.CTkFont(weight="bold"),
        )
        if not self._start_in_compose:
            self._catalog_label.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, pad))

        self._preview_var = tk.StringVar(value="")
        self._preview_label = ctk.CTkLabel(
            self._frame,
            textvariable=self._preview_var,
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
        )

        self._filter_var = tk.StringVar(value="")
        self._filter_entry = ctk.CTkEntry(
            self._frame, textvariable=self._filter_var, placeholder_text=_("Filter…")
        )
        self._filter_entry.grid(row=2, column=0, sticky="ew", padx=pad, pady=(0, 6))

        self._list_host = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._list_host.grid(row=3, column=0, sticky="nsew", padx=pad)
        self._list_host.grid_columnconfigure(0, weight=1)
        self._list_host.grid_rowconfigure(0, weight=1)

        theme_host = _find_theme_host(self.master) or _find_theme_host(self)
        if theme_host is not None:
            self._list_theme = _listbox_theme_colors(theme_host)
        bg, fg, select_bg, select_fg = self._list_theme

        scrollbar = ctk.CTkScrollbar(self._list_host, orientation="vertical")
        self._listbox = tk.Listbox(
            self._list_host,
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

        self._compose_host = ctk.CTkFrame(self._frame, fg_color="transparent")

        self._count_var = tk.StringVar(value="")
        self._count_label = ctk.CTkLabel(self._frame, textvariable=self._count_var, anchor="w")
        self._count_label.grid(row=4, column=0, sticky="ew", padx=pad, pady=(6, 0))

        self._footer = ctk.CTkFrame(self._frame, fg_color="transparent")
        self._footer.grid(row=5, column=0, sticky="ew", padx=pad, pady=(pad, pad))
        self._footer.grid_columnconfigure(0, weight=1)

        self._footer_left = ctk.CTkFrame(self._footer, fg_color="transparent")
        self._footer_left.grid(row=0, column=0, sticky="w")
        self._expand_button: ctk.CTkButton | None = None
        self._vocab_button: ctk.CTkButton | None = None
        if self._compose_spec is not None and self._catalog_kind == "radlex":
            self._expand_button = ctk.CTkButton(
                self._footer_left,
                width=200,
                text=_("Compose RadLex…"),
                command=self._enter_compose_mode,
            )
            self._expand_button.pack(side="left")
        elif self._expand_loader is not None and not self._showing_full_catalog:
            self._expand_button = ctk.CTkButton(
                self._footer_left,
                width=200,
                text=_expand_button_label(self._catalog_kind),
                command=self._expand_to_full_catalog,
            )
            self._expand_button.pack(side="left")

        btn_row = ctk.CTkFrame(self._footer, fg_color="transparent")
        btn_row.grid(row=0, column=1, sticky="e")
        ctk.CTkButton(btn_row, width=100, text=_("Cancel"), command=self._on_cancel).pack(
            side="left", padx=(0, 8)
        )
        self._ok_button = ctk.CTkButton(btn_row, width=100, text=_("Apply"), command=self._ok_event)
        self._ok_button.pack(side="left")

        self._populate_list(initial if initial in self._choices else (self._choices[0] if self._choices else ""))
        if not self._choices:
            self._ok_button.configure(state="disabled")

        self.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.geometry(f"{self.DIALOG_WIDTH}x{self.DIALOG_HEIGHT}")
        self._filter_ready = True
        self._filter_var.trace_add("write", lambda *_args: self._on_filter_changed())

    def _compose_field_keys(self) -> list[str]:
        assert self._compose_spec is not None
        return [f for f in self._compose_spec.field_order if f in self._compose_options]

    def _compose_core_fields(self) -> list[str]:
        """Fields revealed one-by-one before unlocking optional remainder.

        CT/MR: through IV contrast, then the rest appear with "—" selected.
        Planar (no contrast): step through every field.
        """
        fields = self._compose_field_keys()
        if "contrast" in fields:
            return fields[: fields.index("contrast") + 1]
        return fields

    def _compose_list_row_height(self, visible: list[str]) -> int:
        """Shared listbox height: fit short lists; cap at COMPOSE_BODY_LIST_HEIGHT."""
        if not visible:
            return 4
        longest = max((len(self._compose_options.get(k) or []) for k in visible), default=4)
        return max(4, min(self.COMPOSE_BODY_LIST_HEIGHT, longest))

    def _hide_list_chrome(self) -> None:
        """Remove list-only widgets; shared by every compose entry."""
        with contextlib.suppress(tk.TclError):
            self._filter_entry.grid_remove()
            self._list_host.grid_remove()
            self._count_label.grid_remove()
            self._catalog_label.grid_remove()
        if self._expand_button is not None:
            self._expand_button.pack_forget()
            self._expand_button.destroy()
            self._expand_button = None
        with contextlib.suppress(tk.TclError):
            self._frame.pack_configure(expand=False)
            self._frame.grid_rowconfigure(3, weight=0)

    def _place_compose_chrome(self, *, header_text: str) -> None:
        """Grid hint / preview / fields / footer — one layout for closest and stepwise."""
        pad = self.PAD
        self._hint_label.configure(
            text=header_text,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._preview_label.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, 8))
        self._build_compose_ui()
        self._compose_host.grid(row=2, column=0, sticky="nw", padx=pad)
        self._footer.grid(row=3, column=0, sticky="ew", padx=pad, pady=(pad, pad))
        self._frame.grid_rowconfigure(2, weight=0)
        self._frame.grid_rowconfigure(3, weight=0)

    def _sync_vocab_button(self, *, full_vocab: bool) -> None:
        """Closest / Show all toggle — omitted for blank stepwise (nothing to approximate)."""
        if self._blank_compose:
            if self._vocab_button is not None:
                self._vocab_button.pack_forget()
                self._vocab_button.destroy()
                self._vocab_button = None
            return
        label = _("Closest codes") if full_vocab else _("Show all codes")
        if self._vocab_button is None:
            self._vocab_button = ctk.CTkButton(
                self._footer_left,
                width=160,
                text=label,
                command=self._toggle_full_vocab,
            )
            self._vocab_button.pack(side="left")
        else:
            self._vocab_button.configure(text=label)

    def _enter_compose_mode(self, *, full_vocab: bool = False) -> None:
        """Enter compose. ``full_vocab=False`` = Compose RadLex…; ``True`` = stepwise all codes."""
        if self._compose_spec is None or self._compose_mode:
            return
        try:
            self._compose_options = self._compose_spec.load_options(full_vocab)
        except Exception:
            logger.exception("Failed to load RadLex component options")
            return
        self._compose_mode = True
        self._full_vocab = full_vocab
        self._hide_list_chrome()

        # Closest = every field filled; all-codes = reveal step by step from the left.
        self._compose_show_all = not full_vocab
        fields = self._compose_field_keys()
        if self._compose_show_all:
            self._compose_chosen = dict(self._compose_spec.initial)
            self._compose_visible_count = len(fields)
        else:
            self._compose_chosen = {}
            self._compose_visible_count = 1

        if self._blank_compose_hint and full_vocab:
            header_text = self._blank_compose_hint
        else:
            header_text = _compose_catalog_label(self._modality, full_vocab=full_vocab)
        self._place_compose_chrome(header_text=header_text)
        self._sync_vocab_button(full_vocab=full_vocab)

        self._ok_button.configure(state="normal")
        self._refresh_compose_lists()
        self._update_preview()
        self._size_compose_window()

    def _size_compose_window(self) -> None:
        """Size to mapped compose content + outer pack pads (no grey strip under buttons)."""
        self.update_idletasks()
        pad = self.PAD
        host_w = footer_w = 0
        with contextlib.suppress(tk.TclError):
            host_w = int(self._compose_host.winfo_reqwidth() or 0)
            footer_w = int(self._footer.winfo_reqwidth() or 0)
        content_w = max(host_w, footer_w, 200)
        with contextlib.suppress(tk.TclError):
            self._hint_label.configure(wraplength=max(180, content_w))
        self.update_idletasks()

        # Prefer mapped geometry (accurate after wait_visibility / Compose button click).
        bottom = 0
        right = 0
        for widget in (
            self._hint_label,
            self._preview_label,
            self._compose_host,
            self._footer,
        ):
            with contextlib.suppress(tk.TclError):
                y = int(widget.winfo_y())
                h = int(widget.winfo_height() or widget.winfo_reqheight() or 0)
                x = int(widget.winfo_x())
                w = int(widget.winfo_width() or widget.winfo_reqwidth() or 0)
                bottom = max(bottom, y + h)
                right = max(right, x + w)

        # Inner grid pads around footer/hint + outer pack padx/pady on ``_frame``.
        inner_w = max(right + pad, content_w + 2 * pad)
        inner_h = max(bottom + pad, 120)
        width = max(inner_w + 2 * pad, 240)
        height = max(inner_h + 2 * pad, 200)
        self.minsize(width, height)
        self.maxsize(width, height)
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)

    @staticmethod
    def _compose_list_width(codes: list[str]) -> int:
        """Listbox ``width`` from measured text pixels (avoids oversized char cells)."""
        import tkinter.font as tkfont

        font = tkfont.nametofont("TkTextFont")
        zero = max(1, int(font.measure("0")))
        px = max((int(font.measure(_display_code(c))) for c in codes), default=zero)
        return max(4, (px + zero - 1) // zero)

    def _build_compose_ui(self) -> None:
        assert self._compose_spec is not None
        for child in self._compose_host.winfo_children():
            child.destroy()
        self._compose_listboxes.clear()
        self._compose_cells.clear()

        bg, fg, select_bg, select_fg = self._list_theme
        all_fields = self._compose_field_keys()
        visible = all_fields[: self._compose_visible_count]
        scroll_border = select_bg
        list_height = self._compose_list_row_height(visible)

        for col, field_key in enumerate(visible):
            self._compose_host.grid_columnconfigure(col, weight=0)
            cell = ctk.CTkFrame(self._compose_host, fg_color="transparent")
            cell.grid(row=0, column=col, sticky="nw", padx=(0, 6), pady=(0, 4))
            self._compose_cells[field_key] = cell

            label = self._compose_spec.field_labels.get(field_key, field_key)
            ctk.CTkLabel(
                cell,
                text=label,
                anchor="w",
                font=self._field_label_font,
            ).grid(row=0, column=0, sticky="w", pady=(0, 4))

            codes = self._compose_options.get(field_key) or []
            list_width = self._compose_list_width(codes)
            wants_scroll = len(codes) > list_height

            if wants_scroll:
                box = tk.Frame(
                    cell,
                    bg=bg,
                    highlightbackground=scroll_border,
                    highlightcolor=scroll_border,
                    highlightthickness=1,
                    bd=0,
                )
                box.grid(row=1, column=0, sticky="nw")
                lb = tk.Listbox(
                    box,
                    height=list_height,
                    width=list_width,
                    border=0,
                    bg=bg,
                    fg=fg,
                    selectbackground=select_bg,
                    selectforeground=select_fg,
                    highlightthickness=0,
                    activestyle="none",
                    exportselection=False,
                )
                sb = tk.Scrollbar(box, orient="vertical", command=lb.yview)
                lb.configure(yscrollcommand=sb.set)
                lb.pack(side="left", fill="y")
                sb.pack(side="right", fill="y")
            else:
                lb = tk.Listbox(
                    cell,
                    height=list_height,
                    width=list_width,
                    border=0,
                    bg=bg,
                    fg=fg,
                    selectbackground=select_bg,
                    selectforeground=select_fg,
                    highlightthickness=0,
                    activestyle="none",
                    exportselection=False,
                )
                lb.grid(row=1, column=0, sticky="nw")
            lb.bind("<<ListboxSelect>>", lambda _e, k=field_key: self._on_compose_select(k))
            self._compose_listboxes[field_key] = lb
            self._bind_compose_code_tooltip(lb, field_key)

    def _bind_compose_code_tooltip(self, listbox: tk.Listbox, field_key: str) -> None:
        """Hover gloss for abbreviated Playbook codes (``CODE — full name``)."""
        from anonymizer.controller.ai.harmonize.playbook import playbook_component_code_tooltip

        def _text_for_position(event: tk.Event) -> str | None:
            try:
                index = int(listbox.nearest(event.y))
            except (tk.TclError, TypeError, ValueError):
                return None
            if index < 0:
                return None
            try:
                display = str(listbox.get(index))
            except tk.TclError:
                return None
            return playbook_component_code_tooltip(field_key, _code_from_display(display))

        MotionTooltipController(
            listbox,
            _text_for_position,
            parent=self,
            debounce_ms=200,
        ).bind()

    def _toggle_full_vocab(self) -> None:
        if self._compose_spec is None:
            return
        self._full_vocab = not self._full_vocab
        try:
            self._compose_options = self._compose_spec.load_options(self._full_vocab)
        except Exception:
            logger.exception("Failed to reload RadLex component options")
            self._full_vocab = not self._full_vocab
            return

        fields = self._compose_field_keys()
        if not self._full_vocab:
            self._compose_show_all = True
            self._compose_visible_count = len(fields)
            for key in fields:
                if key not in self._compose_chosen:
                    self._compose_chosen[key] = self._compose_spec.initial.get(key, "")
            header = _compose_catalog_label(self._modality, full_vocab=False)
        else:
            if self._compose_show_all:
                self._compose_visible_count = len(fields)
            header = (
                self._blank_compose_hint
                if self._blank_compose_hint and not self._compose_show_all
                else _compose_catalog_label(self._modality, full_vocab=True)
            )

        self._hint_label.configure(text=header)
        self._sync_vocab_button(full_vocab=self._full_vocab)
        self._build_compose_ui()
        self._refresh_compose_lists()
        self._size_compose_window()
        self._update_preview()

    def _refresh_compose_lists(self) -> None:
        assert self._compose_spec is not None
        for field_key, lb in self._compose_listboxes.items():
            codes = list(self._compose_options.get(field_key) or [])
            lb.delete(0, tk.END)
            if codes:
                lb.insert(tk.END, *[_display_code(c) for c in codes])
            lb.selection_clear(0, tk.END)
            if field_key not in self._compose_chosen:
                continue
            selected = self._compose_chosen[field_key]
            display = _display_code(selected)
            displays = [_display_code(c) for c in codes]
            if display in displays:
                index = displays.index(display)
                lb.selection_set(index)
                lb.activate(index)
                lb.see(index)

    def _on_compose_select(self, field_key: str) -> None:
        if self._closing or not self._compose_mode:
            return
        code = self._selected_compose_code(field_key)
        if code is None:
            return
        self._compose_chosen[field_key] = code
        if not self._compose_show_all:
            fields = self._compose_field_keys()
            core = self._compose_core_fields()
            next_visible = self._compose_visible_count
            if core and field_key == core[-1]:
                for key in fields[len(core) :]:
                    self._compose_chosen.setdefault(key, "")
                next_visible = len(fields)
                self._compose_show_all = True
            else:
                try:
                    idx = fields.index(field_key)
                except ValueError:
                    idx = -1
                next_visible = min(len(fields), idx + 2)
            if next_visible > self._compose_visible_count:
                self._compose_visible_count = next_visible
                if self._compose_visible_count >= len(fields):
                    self._compose_show_all = True
                self._build_compose_ui()
                self._refresh_compose_lists()
                self._size_compose_window()
        self._update_preview()

    def _selected_compose_code(self, field_key: str) -> str | None:
        lb = self._compose_listboxes.get(field_key)
        if lb is None:
            return None
        sel = lb.curselection()
        if not sel:
            return None
        return _code_from_display(str(lb.get(sel[0])))

    def _compose_field_map(self) -> dict[str, str]:
        assert self._compose_spec is not None
        result: dict[str, str] = {}
        for field_key in self._compose_spec.field_order:
            if field_key in self._compose_chosen:
                result[field_key] = self._compose_chosen[field_key]
            elif self._compose_show_all:
                code = self._selected_compose_code(field_key)
                if code is None:
                    opts = self._compose_options.get(field_key) or []
                    code = self._compose_spec.initial.get(field_key, opts[0] if opts else "")
                result[field_key] = code
            else:
                result[field_key] = ""
        return result

    def _update_preview(self) -> None:
        if self._compose_spec is None:
            return
        fields = self._compose_field_map()
        try:
            text = self._compose_spec.format_description(fields)
        except Exception:
            logger.exception("Failed to format RadLex preview")
            text = ""
        if text:
            self._preview_var.set(_("Preview: {description}").format(description=text))
            self._ok_button.configure(state="normal")
        elif self._compose_chosen:
            self._preview_var.set(_("Preview: …"))
            self._ok_button.configure(state="disabled")
        else:
            self._preview_var.set(_("Preview: (pick a field)"))
            self._ok_button.configure(state="disabled")

    def _expand_to_full_catalog(self) -> None:
        if self._expand_loader is None or self._showing_full_catalog:
            return
        button = self._expand_button
        if button is not None:
            button.configure(state="disabled")
        try:
            choices, meta = self._expand_loader()
        except Exception:
            logger.exception("Failed to load full description catalog")
            if button is not None:
                with contextlib.suppress(tk.TclError):
                    button.configure(state="normal")
            return
        if not choices:
            if button is not None:
                with contextlib.suppress(tk.TclError):
                    button.configure(state="normal")
            return
        selected = self._selected_label()
        self._choices = list(choices)
        self._choice_meta = dict(meta)
        self._showing_full_catalog = True
        self._catalog_label.configure(text=_catalog_label(self._catalog_kind, self._modality, full=True))
        if button is not None:
            button.pack_forget()
            button.destroy()
            self._expand_button = None
        self._apply_filter()
        if selected and selected in self._filtered:
            self._populate_list(selected)

    def _on_filter_changed(self) -> None:
        if not self._filter_ready or self._closing or self._compose_mode:
            return
        self._apply_filter()

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
        if self._filtered:
            self._listbox.insert(tk.END, *self._filtered)

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
        if self._compose_mode and self._compose_spec is not None:
            fields = self._compose_field_map()
            try:
                description = self._compose_spec.format_description(fields).strip()
            except Exception:
                logger.exception("Failed to format composed RadLex description")
                return
            if not description:
                return
            self._result = SetDescriptionDialogResult(
                applied=True,
                description=description,
                loinc_number=None,
            )
            self._closing = True
            teardown_ctk_toplevel(self, parent=self.master)
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
    expand_loader: ExpandCatalogLoader | None = None,
    showing_full_catalog: bool = False,
    compose_spec: RadLexComposeSpec | None = None,
    start_in_compose: bool = False,
    compose_full_vocab: bool = False,
    blank_compose: bool = False,
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
        expand_loader=expand_loader,
        showing_full_catalog=showing_full_catalog,
        compose_spec=compose_spec,
        start_in_compose=start_in_compose,
        compose_full_vocab=compose_full_vocab,
        blank_compose=blank_compose,
    )
    return dialog.get_input()
