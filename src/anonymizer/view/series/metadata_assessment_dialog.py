"""View-only Horos-style Metadata tree for the current Series View slice.

Layout and Treeview tones follow Dataset View (framed index + Series View
control bar). Alternating row backgrounds use theme grays. Detect PHI runs
Embedded PHI NER on Content cells and highlights hits with Report Viewer
entity colors / hover chips.
"""

from __future__ import annotations

import logging
import platform
import queue
import threading
import tkinter as tk
from collections.abc import Mapping, Sequence
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk
from customtkinter import ThemeManager
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_phi_in_texts, entity_count_by_label
from anonymizer.controller.ai.embedded_phi.metadata.extract import is_anonymizer_field
from anonymizer.controller.ai.embedded_phi.metadata.viewer_tree import (
    ITEM_NAME,
    STRUCTURAL_TAG,
    VALUE_NAME,
    MetadataTreeNode,
    build_metadata_tree,
    filter_metadata_tree,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import SCORED_LABELS, Entity
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import OcrWhitelistMatchSettings
from anonymizer.controller.ai.feature_availability import report_text_phi_ready
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppCTkToplevel, install_modal_dismiss
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import char_width_px
from anonymizer.view.common.tooltip import MotionTooltipController, TooltipContent
from anonymizer.view.common.ux_fields import button_width_for_label
from anonymizer.view.reports.entity_colors import entity_color_hex, entity_label_display, entity_scored_family
from anonymizer.view.reports.report_text_review import detect_phi_button_label

logger = logging.getLogger(__name__)

_CONTENT_COLUMN_ID = "#2"  # #0=tree name, #1=tag, #2=content
_PAD = 10
_BUTTON_WIDTH = 100
_STATUS_WRAPLENGTH = 600
_POLL_MS = 100
# Column character budgets (Dataset-style mono sizing).
_NAME_CHARS = 28
_TAG_CHARS = 12
_CONTENT_CHARS = 48
_PHI_TAG_PREFIX = "phi_"


def _mono_char_width_px() -> int:
    """Match Dataset / global Treeview mono metrics without allocating AppFonts."""

    os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
    os_key = os_map.get(platform.system(), "macOS")
    tv = ThemeManager.theme.get("Treeview") or {}
    family = (tv.get("font") or {}).get(os_key, {}).get("family") or "Courier New"
    return char_width_px(ctk.CTkFont(family=family, size=12))


def _treeview_theme_colors(host: tk.Misc) -> tuple[str, str, str, str]:
    """Resolve Treeview bg / fg / selected colors (same path as Dataset / app startup)."""
    apply = getattr(host, "_apply_appearance_mode", None)
    if apply is None:
        parent = getattr(host, "master", None)
        apply = getattr(parent, "_apply_appearance_mode", None) if parent is not None else None
    if apply is None:
        apply = ctk.CTk()._apply_appearance_mode  # type: ignore[attr-defined]

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


def _stripe_pair(host: tk.Misc, base_bg: str) -> tuple[str, str]:
    """Even/odd row backgrounds from theme grays (never pure white)."""
    apply = getattr(host, "_apply_appearance_mode", None)
    if apply is None:
        parent = getattr(host, "master", None)
        apply = getattr(parent, "_apply_appearance_mode", None) if parent is not None else None
    def _pick(pair: object) -> object:
        return pair[0] if isinstance(pair, (list, tuple)) else pair

    if apply is None:
        apply = _pick

    # Treeview bg (gray90 / gray13) + CTkFrame top_fg (gray85 / gray16).
    frame = ThemeManager.theme.get("CTkFrame") or {}
    alt = frame.get("top_fg_color", ["gray85", "gray16"])
    odd = str(apply(alt))
    even = base_bg
    if odd.casefold() == even.casefold():
        odd = str(apply(["gray86", "gray16"]))
    return even, odd


def _primary_phi_label(entities: Sequence[Entity]) -> str:
    """First Report Viewer color family by span start (NER or DICOM-keyword label)."""
    if not entities:
        return ""
    ordered = sorted(entities, key=lambda e: (e.start, e.end))
    return entity_scored_family(ordered[0].label)


def _format_detection_status(entities_by_text: Mapping[str, Sequence[Entity]]) -> str:
    """Report View–style detection rollup (same wording / entity families)."""
    raw = entity_count_by_label(entities_by_text)
    counts: dict[str, int] = {}
    for label, n in raw.items():
        family = entity_scored_family(label)
        counts[family] = counts.get(family, 0) + n
    total = sum(counts.values())
    if total == 0:
        return _("No PHI detected.")
    ner_parts: list[str] = []
    for label in SCORED_LABELS:
        n = counts.get(label, 0)
        if n:
            ner_parts.append(f"{entity_label_display(label)} {n}")
    for label, n in sorted(counts.items()):
        if label not in SCORED_LABELS and n:
            ner_parts.append(f"{label} {n}")
    status = _("Detection complete") + f" ({total})"
    if ner_parts:
        status += f": {', '.join(ner_parts)}"
    return status


class MetadataTreePanel(ctk.CTkFrame):
    """Expandable Field Name / Tag / Content tree (Dataset-framed chrome)."""

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._roots: list[MetadataTreeNode] = []
        self._content_by_iid: dict[str, str] = {}
        self._entities_by_content: dict[str, tuple[Entity, ...]] = {}
        self._search_var = tk.StringVar(value="")
        self._char_width_px = _mono_char_width_px()
        self._name_col_px = _NAME_CHARS * self._char_width_px

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Search (Field Name width) + Expand/Collapse top-right.
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=_PAD, pady=(_PAD, 0))
        toolbar.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(toolbar, text=_("Search") + ":").grid(row=0, column=0, sticky="w")
        self._search_entry = ctk.CTkEntry(
            toolbar,
            textvariable=self._search_var,
            width=max(80, self._name_col_px),
        )
        self._search_entry.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self._search_var.trace_add("write", self._on_search_changed)
        expand_label = _("Expand")
        self._expand_button = ctk.CTkButton(
            toolbar,
            width=button_width_for_label(expand_label, minimum=_BUTTON_WIDTH),
            text=expand_label,
            command=self.expand_all,
        )
        self._expand_button.grid(row=0, column=3, padx=(0, 4), sticky="e")
        collapse_label = _("Collapse")
        self._collapse_button = ctk.CTkButton(
            toolbar,
            width=button_width_for_label(collapse_label, minimum=_BUTTON_WIDTH),
            text=collapse_label,
            command=self.collapse_all,
        )
        self._collapse_button.grid(row=0, column=4, sticky="e")

        # Dataset-style framed index: tree + scrollbar inside CTkFrame.
        self._index_frame = ctk.CTkFrame(self)
        self._index_frame.grid(row=1, column=0, sticky="nsew", padx=_PAD, pady=_PAD)
        self._index_frame.grid_columnconfigure(0, weight=1)
        self._index_frame.grid_rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            self._index_frame,
            columns=("tag", "content"),
            show="tree headings",
            style="Treeview",
            selectmode="browse",
        )
        self._tree.heading("#0", text=_("Field Name"), anchor="w")
        self._tree.heading("tag", text=_("Tag"), anchor="w")
        self._tree.heading("content", text=_("Content"), anchor="w")
        tag_px = _TAG_CHARS * self._char_width_px
        content_px = _CONTENT_CHARS * self._char_width_px
        self._tree.column(
            "#0",
            width=self._name_col_px,
            minwidth=8 * self._char_width_px,
            stretch=False,
            anchor="w",
        )
        self._tree.column("tag", width=tag_px, minwidth=tag_px, stretch=False, anchor="w")
        self._tree.column("content", width=content_px, minwidth=content_px // 2, stretch=True, anchor="w")

        yscroll = ttk.Scrollbar(self._index_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=yscroll.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")

        self._configure_row_tags()
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open_close, add="+")
        self._tree.bind("<<TreeviewClose>>", self._on_tree_open_close, add="+")
        MotionTooltipController(self._tree, self._content_tooltip, parent=self).bind()

    @property
    def tree(self) -> ttk.Treeview:
        return self._tree

    def set_dataset(self, ds: Dataset) -> None:
        self._roots = build_metadata_tree(ds)
        self._entities_by_content.clear()
        self._rebuild()

    def content_texts(self) -> list[str]:
        """All Content cell strings currently in the tree model (pre-search filter)."""
        return [item.text for item in self.content_ner_items()]

    def content_ner_items(self) -> list[MetadataNerItem]:
        """Content cells with field name / VR for radiology pre-NER filtering."""
        out: list[MetadataNerItem] = []

        def walk(nodes: Sequence[MetadataTreeNode]) -> None:
            for node in nodes:
                if node.content:
                    name = str(node.name or "").strip()
                    if name in {ITEM_NAME, VALUE_NAME, STRUCTURAL_TAG}:
                        name = ""
                    out.append(
                        MetadataNerItem(
                            text=node.content,
                            field_name=name,
                            tag=str(node.tag or ""),
                            vr=str(node.vr or ""),
                            tag_path=str(node.tag_path or ""),
                            is_anonymizer_field=is_anonymizer_field(
                                tag=str(node.tag or ""),
                                name=str(node.name or ""),
                                tag_path=str(node.tag_path or ""),
                            ),
                            is_date=str(node.vr or "").upper() in {"DA", "DT"},
                        )
                    )
                walk(node.children)

        walk(self._roots)
        return out

    def apply_phi_entities(self, entities_by_content: Mapping[str, Sequence[Entity]]) -> int:
        """Apply NER hits: Content markers + Report Viewer entity colors. Returns hit count."""
        self._entities_by_content = {
            str(text): tuple(ents) for text, ents in entities_by_content.items() if ents
        }
        self._rebuild()
        hit_iids = [iid for iid, text in self._content_by_iid.items() if text in self._entities_by_content]
        for iid in hit_iids:
            self._reveal_iid(iid)
        self._restripe_visible()
        return sum(len(ents) for ents in self._entities_by_content.values())

    def clear_phi_highlights(self) -> None:
        self._entities_by_content.clear()
        self._rebuild()

    def expand_all(self) -> None:
        for iid in self._all_iids():
            self._tree.item(iid, open=True)
        self._restripe_visible()

    def collapse_all(self) -> None:
        for iid in self._all_iids():
            self._tree.item(iid, open=False)
        self._restripe_visible()

    def _configure_row_tags(self) -> None:
        bg, fg, _sel_bg, _sel_fg = _treeview_theme_colors(self)
        even, odd = _stripe_pair(self, bg)
        self._tree.tag_configure("row_even", background=even, foreground=fg)
        self._tree.tag_configure("row_odd", background=odd, foreground=fg)
        for label in SCORED_LABELS:
            self._tree.tag_configure(
                f"{_PHI_TAG_PREFIX}{label}",
                background=entity_color_hex(label),
                foreground="#ffffff",
            )
        self._tree.tag_configure(
            f"{_PHI_TAG_PREFIX}UNKNOWN",
            background=entity_color_hex("UNKNOWN"),
            foreground="#ffffff",
        )

    def _on_search_changed(self, *_args: object) -> None:
        self._rebuild()

    def _on_tree_open_close(self, _event: tk.Event | None = None) -> None:
        self._restripe_visible()

    def _rebuild(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._content_by_iid.clear()
        visible = filter_metadata_tree(self._roots, self._search_var.get())
        for index, node in enumerate(visible):
            self._insert_node("", node, path_key=f"r{index}")
        if self._search_var.get().strip():
            for iid in self._all_iids():
                self._tree.item(iid, open=True)
        self._restripe_visible()

    def _insert_node(self, parent: str, node: MetadataTreeNode, *, path_key: str) -> str:
        iid = f"{path_key}:{node.tag_path}"
        if self._tree.exists(iid):
            iid = f"{iid}#{id(node)}"
        self._tree.insert(
            parent,
            "end",
            iid=iid,
            text=node.name,
            values=(node.tag, node.content),
            open=False,
        )
        self._content_by_iid[iid] = node.content
        for i, child in enumerate(node.children):
            self._insert_node(iid, child, path_key=f"{path_key}.{i}")
        return iid

    def _all_iids(self) -> list[str]:
        out: list[str] = []

        def walk(parent: str) -> None:
            for iid in self._tree.get_children(parent):
                out.append(iid)
                walk(iid)

        walk("")
        return out

    def _visible_iids(self) -> list[str]:
        """Depth-first visible rows (respects open/closed), for Horos zebra striping."""
        out: list[str] = []

        def walk(parent: str) -> None:
            for iid in self._tree.get_children(parent):
                out.append(iid)
                if self._tree.item(iid, "open"):
                    walk(iid)

        walk("")
        return out

    def _reveal_iid(self, iid: str) -> None:
        parent = self._tree.parent(iid)
        while parent:
            self._tree.item(parent, open=True)
            parent = self._tree.parent(parent)
        self._tree.see(iid)

    def _restripe_visible(self) -> None:
        for i, iid in enumerate(self._visible_iids()):
            stripe = "row_odd" if i % 2 else "row_even"
            text = self._content_by_iid.get(iid, "")
            ents = self._entities_by_content.get(text, ())
            if ents:
                label = _primary_phi_label(ents)
                phi_tag = f"{_PHI_TAG_PREFIX}{label if label in SCORED_LABELS else 'UNKNOWN'}"
                # PHI tag first → higher priority than zebra (Report Viewer entity color).
                self._tree.item(iid, tags=(phi_tag, stripe))
            else:
                self._tree.item(iid, tags=(stripe,))

    def _content_tooltip(self, event: tk.Event) -> str | TooltipContent | None:
        if self._tree.identify_column(event.x) != _CONTENT_COLUMN_ID:
            return None
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return None
        text = str(self._content_by_iid.get(row_id) or "")
        ents = self._entities_by_content.get(text, ())
        if ents:
            labels = list(dict.fromkeys(str(e.label).upper() for e in ents))
            primary = labels[0]
            chip = " · ".join(labels)
            return TooltipContent(text=chip, bg=entity_color_hex(primary), fg="#ffffff")
        stripped = text.strip()
        return stripped or None


class MetadataAssessmentDialog(AppCTkToplevel):
    """Metadata tree dialog: Series View ``_sv_frame`` + control_frame chrome."""

    PAD = _PAD
    BUTTON_WIDTH = _BUTTON_WIDTH
    STATUS_WRAPLENGTH = _STATUS_WRAPLENGTH
    POLL_MS = _POLL_MS
    DEFAULT_WIDTH = 960
    DEFAULT_HEIGHT = 600

    def __init__(
        self,
        parent: tk.Misc,
        *,
        dataset: Dataset,
        project_dir: Path | None = None,
        modality: str | None = None,
        whitelist: Sequence[str] | None = None,
        whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
    ) -> None:
        super().__init__(master=parent)
        self._parent = parent
        self._dataset = dataset
        self._project_dir = project_dir
        self._modality = modality or str(getattr(dataset, "Modality", "") or "") or None
        self._whitelist = list(whitelist) if whitelist is not None else None
        self._whitelist_match_settings = whitelist_match_settings
        self._destroyed = False
        self._detecting = False
        self._detect_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.withdraw()
        self.title(_("Metadata"))
        self.minsize(720, 400)
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Outer shell like Series View: nested CTkFrames get top_fg_color (toolbar group).
        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(0, weight=1)

        self._panel = MetadataTreePanel(self._sv_frame, fg_color="transparent")
        self._panel.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=(self.PAD, 0))
        self._panel.set_dataset(dataset)

        # Nested in ``_sv_frame`` so this bar uses theme ``top_fg_color`` (Series View chrome).
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, column=0, sticky="ew", padx=self.PAD, pady=self.PAD)
        self.control_frame.grid_columnconfigure(0, weight=0)
        self.control_frame.grid_columnconfigure(1, weight=1)
        self.control_frame.grid_columnconfigure(2, weight=0)

        action_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        action_group.grid(row=0, column=0, padx=(0, self.PAD), pady=self.PAD, sticky="w")

        detect_label = detect_phi_button_label()
        self.detect_button = ctk.CTkButton(
            action_group,
            width=button_width_for_label(detect_label, minimum=self.BUTTON_WIDTH),
            text=detect_label,
            command=self._on_detect,
        )
        self.detect_button.grid(row=0, column=0, padx=(self.PAD, 2), pady=0)

        self._status_label = ctk.CTkLabel(
            self.control_frame,
            text="",
            anchor="w",
            justify="left",
            wraplength=self.STATUS_WRAPLENGTH,
        )
        self._status_label.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=self.PAD,
            pady=(0, self.PAD),
            sticky="w",
        )

        close_label = _("Close")
        self.close_button = ctk.CTkButton(
            self.control_frame,
            width=button_width_for_label(close_label, minimum=self.BUTTON_WIDTH),
            text=close_label,
            command=self._on_close,
        )
        self.close_button.grid(row=1, column=2, padx=self.PAD, pady=(0, self.PAD), sticky="e")

        self._position_near_parent()
        self.deiconify()
        self.wait_visibility()
        self.lift()
        install_modal_dismiss(self, self._on_close)
        self.grab_set()
        self.bind("<Escape>", self._escape_keypress)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @property
    def panel(self) -> MetadataTreePanel:
        return self._panel

    @property
    def tree(self) -> ttk.Treeview:
        return self._panel.tree

    def _set_status(self, text: str) -> None:
        if not self._destroyed:
            self._status_label.configure(text=text)

    def _position_near_parent(self) -> None:
        try:
            self.update_idletasks()
            parent_x = int(self._parent.winfo_rootx())
            parent_y = int(self._parent.winfo_rooty())
            parent_w = max(1, int(self._parent.winfo_width()))
            parent_h = max(1, int(self._parent.winfo_height()))
            w = self.DEFAULT_WIDTH
            h = self.DEFAULT_HEIGHT
            x = parent_x + max(0, (parent_w - w) // 2)
            y = parent_y + max(0, (parent_h - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            logger.debug("Could not position Metadata dialog", exc_info=True)
            self.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}")

    def _escape_keypress(self, _event: tk.Event | None = None) -> str:
        self._on_close()
        return "break"

    def _on_detect(self) -> None:
        if self._detecting:
            return
        if not report_text_phi_ready():
            messagebox.showwarning(
                _("Embedded PHI"),
                _("Embedded PHI models are not downloaded. Install them under AI Features."),
                parent=self,
            )
            return
        self._detecting = True
        self.detect_button.configure(state="disabled")
        self._set_status(_("Detecting…"))
        items = self._panel.content_ner_items()
        ds = self._dataset
        project_dir = self._project_dir
        modality = self._modality
        whitelist = self._whitelist
        match_settings = self._whitelist_match_settings
        def _worker() -> None:
            try:
                self._detect_queue.put(
                    (
                        "ok",
                        detect_phi_in_texts(
                            ds=ds,
                            items=items,
                            whitelist=whitelist,
                            whitelist_match_settings=match_settings,
                            project_dir=project_dir,
                            modality=modality,
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Metadata Detect PHI failed")
                self._detect_queue.put(("error", str(exc)))

        threading.Thread(target=_worker, name="MetadataDetectPHI", daemon=True).start()
        self.after(self.POLL_MS, self._poll_detect)

    def _poll_detect(self) -> None:
        if self._destroyed:
            return
        try:
            kind, payload = self._detect_queue.get_nowait()
        except queue.Empty:
            self.after(self.POLL_MS, self._poll_detect)
            return
        self._detecting = False
        if not self._destroyed:
            self.detect_button.configure(state="normal")
        if kind == "error":
            self._set_status(_("Detection failed") + f": {payload}")
            return
        entities_by_text = payload  # type: ignore[assignment]
        assert isinstance(entities_by_text, dict)
        self._panel.apply_phi_entities(entities_by_text)
        self._set_status(_format_detection_status(entities_by_text))

    def _on_close(self) -> None:
        self._destroyed = True
        teardown_ctk_toplevel(self, parent=self._parent)
