"""Horos-style Metadata tree for the current Series View slice.

Layout and Treeview tones follow Dataset View (framed index + Series View
control bar). Alternating row backgrounds use theme grays. Detect PHI runs
Embedded PHI NER on Content cells and highlights hits Dataset-View style
(entity-color background tag, white text); hovering Content with detected
PHI shows the entity color chip (fields without PHI have no hover tooltip).
"""

import contextlib
import logging
import platform
import queue
import threading
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from tkinter import messagebox, ttk

import customtkinter as ctk
from customtkinter import ThemeManager
from pydicom import dcmread
from pydicom.dataset import Dataset

from anonymizer.controller.ai.embedded_phi.metadata.detect import detect_phi_in_texts, entity_count_by_label
from anonymizer.controller.ai.embedded_phi.metadata.extract import apply_text_at_path, is_anonymizer_field
from anonymizer.controller.ai.embedded_phi.metadata.viewer_tree import (
    ITEM_NAME,
    STRUCTURAL_TAG,
    VALUE_NAME,
    MetadataTreeNode,
    build_metadata_tree,
    filter_metadata_tree,
)
from anonymizer.controller.ai.embedded_phi.ner.engine import REPLACE_MODE_VALUES, SCORED_LABELS, Entity, ReplaceMode
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import MetadataNerItem
from anonymizer.controller.ai.embedded_phi.pixel.detect_text import OcrWhitelistMatchSettings
from anonymizer.controller.ai.embedded_phi.report.process_report_text import remove_phi
from anonymizer.controller.ai.feature_availability import report_text_phi_ready
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import (
    AppCTkToplevel,
    install_modal_dismiss,
    place_toplevel_centered_on_parent,
)
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.fonts import char_width_px
from anonymizer.view.common.tooltip import MotionTooltipController, TooltipContent
from anonymizer.view.common.ux_fields import button_width_for_label, truncate_series_description
from anonymizer.view.reports.entity_colors import entity_color_hex, entity_label_display, entity_scored_family
from anonymizer.view.reports.report_text_review import (
    detect_phi_button_label,
    remove_phi_button_label,
    replace_mode_labels,
)

logger = logging.getLogger(__name__)

_PAD = 10
_BUTTON_WIDTH = 100
_STATUS_WRAPLENGTH = 600
_POLL_MS = 100
# Column character budgets (Dataset-style mono sizing).
_NAME_CHARS = 28
_TAG_CHARS = 12
_CONTENT_CHARS = 48
_PHI_TAG_PREFIX = "phi_"
_CONTENT_COLUMN_ID = "#2"  # #0=tree name, #1=tag, #2=content
# Treeview disclosure indent per depth level (Tk default ~20px).
_TREE_INDENT_PX = 20
_TREE_ROW_HEIGHT_PX = 22
# Dialog grows vertically only as far as the tree needs, capped at this
# fraction of the screen height.
_MAX_SCREEN_HEIGHT_FRACTION = 0.85
_DIALOG_CHROME_HEIGHT_PX = 150
_DIALOG_DEFAULT_WIDTH = 960
_DIALOG_DEFAULT_HEIGHT = 600


def metadata_dialog_size(
    *,
    screen_width: int,
    screen_height: int,
    required_width: int,
    required_height: int,
) -> tuple[int, int]:
    """Dialog size: at least the default, growing to fit content.

    Width grows so every Field Name fits; height grows only when the tree
    needs it, never beyond 85% of the screen height.

    Args:
        screen_width: Screen width in pixels.
        screen_height: Screen height in pixels.
        required_width: Width the panel needs (longest Field Name included).
        required_height: Height the panel plus dialog chrome needs.

    Returns:
        (width, height) in pixels.
    """
    max_height = int(screen_height * _MAX_SCREEN_HEIGHT_FRACTION)
    width = min(max(_DIALOG_DEFAULT_WIDTH, required_width), max(720, screen_width - 40))
    height = min(max(_DIALOG_DEFAULT_HEIGHT, required_height), max(400, max_height))
    return width, height


def _phi_display_labels(entities: Sequence[Entity]) -> list[str]:
    """Distinct entity labels in span order, for Content-column markers."""
    ordered = sorted(entities, key=lambda e: (e.start, e.end))
    return list(dict.fromkeys(str(e.label).upper() for e in ordered if str(e.label).strip()))


def _phi_hover_text(content: str, entities: Sequence[Entity]) -> str:
    """Hover text: each NER class followed by its actual detected PHI text."""
    parts: list[str] = []
    for ent in sorted(entities, key=lambda e: (e.start, e.end)):
        label = str(ent.label).upper().strip()
        if not label:
            continue
        detected = str(content)[ent.start : ent.end]
        parts.append(f"{label}: {detected}" if detected else label)
    return " · ".join(parts)


def _content_display_text(
    content: str, entities: Sequence[Entity], *, excluded: bool = False
) -> str:
    """Content cell text; PHI hits carry their category in the Content column.

    ttk.Treeview tags are row-wide — they cannot color only the matched
    span inside one cell — so the row is highlighted Dataset-View style
    (entity background) and this marker makes the class explicit in Content.
    Fields excluded from Remove show the plain Content (no marker).
    """
    if excluded:
        return content
    labels = _phi_display_labels(entities)
    if not labels:
        return content
    return f"{content}  [{' · '.join(labels)}]"


def _treeview_font_family() -> str:
    """Treeview mono family from the theme (Dataset / global Treeview metrics)."""
    os_map = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}
    os_key = os_map.get(platform.system(), "macOS")
    tv = ThemeManager.theme.get("Treeview") or {}
    return (tv.get("font") or {}).get(os_key, {}).get("family") or "Courier New"


def _mono_char_width_px() -> int:
    """Match Dataset / global Treeview mono metrics without allocating AppFonts."""
    return char_width_px(ctk.CTkFont(family=_treeview_font_family(), size=12))


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


def _metadata_window_title(dataset: Dataset) -> str:
    """Dialog title naming the series this Metadata view belongs to."""
    title = _("Metadata")
    series_desc = truncate_series_description(str(getattr(dataset, "SeriesDescription", "") or ""))
    series_uid = str(getattr(dataset, "SeriesInstanceUID", "") or "").strip()
    modality = str(getattr(dataset, "Modality", "") or "").strip()
    if series_desc:
        title += f" — {series_desc}"
    elif series_uid:
        title += f" — …{series_uid[-12:]}"
    if modality:
        title += f" ({modality})"
    return title


def _format_detection_status(
    entities_by_text: Mapping[str, Sequence[Entity]],
    *,
    field_count: int | None = None,
    private_uid_count: int = 0,
    private_date_count: int = 0,
) -> str:
    """Report View–style detection rollup (same wording / entity families).

    field_count is the number of fields (tree rows) where PHI was
    detected; when omitted it falls back to the number of distinct Content
    values with entities. Private UID/date fields are reported separately:
    they are handled by the anonymizer script (UID remapping / date
    shifting), not scored by Detect PHI — the user must see that.
    """
    private_note = ""
    if private_uid_count or private_date_count:
        private_note = (
            f" · Private data: {private_uid_count} UID, {private_date_count} date "
            "fields handled by anonymizer UID remapping / date delta "
            "(not scored by Detect PHI)"
        )
    raw = entity_count_by_label(entities_by_text)
    counts: dict[str, int] = {}
    for label, n in raw.items():
        family = entity_scored_family(label)
        counts[family] = counts.get(family, 0) + n
    total = sum(counts.values())
    if total == 0:
        return _("No PHI detected.") + private_note
    if field_count is None:
        field_count = sum(1 for ents in entities_by_text.values() if ents)
    ner_parts: list[str] = []
    for label in SCORED_LABELS:
        n = counts.get(label, 0)
        if n:
            ner_parts.append(f"{entity_label_display(label)} {n}")
    for label, n in sorted(counts.items()):
        if label not in SCORED_LABELS and n:
            ner_parts.append(f"{label} {n}")
    field_word = "field" if field_count == 1 else "fields"
    status = _("Detection complete") + f" ({total} in {field_count} {field_word})"
    if ner_parts:
        status += f": {', '.join(ner_parts)}"
    return status + private_note


class MetadataTreePanel(ctk.CTkFrame):
    """Expandable Field Name / Tag / Content tree (Dataset-framed chrome)."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_phi_toggle: Callable[[str, bool], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_phi_toggle = on_phi_toggle
        self._ds: Dataset | None = None
        self._roots: list[MetadataTreeNode] = []
        self._content_by_iid: dict[str, str] = {}
        self._entities_by_content: dict[str, tuple[Entity, ...]] = {}
        self._excluded_contents: set[str] = set()
        self._pending_cleaned_by_tag_path: dict[str, str] = {}
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
        self._tree.bind("<Button-1>", self._on_tree_click, add="+")
    @property
    def tree(self) -> ttk.Treeview:
        return self._tree

    def set_dataset(self, ds: Dataset) -> None:
        self._ds = ds
        self._roots = build_metadata_tree(ds)
        self._entities_by_content.clear()
        self._excluded_contents.clear()
        self._fit_name_column()
        self._rebuild()

    def _fit_name_column(self) -> None:
        """Widen the Field Name column so every field name is fully visible."""
        required = _NAME_CHARS * self._char_width_px

        def walk(nodes: Sequence[MetadataTreeNode], depth: int) -> None:
            nonlocal required
            for node in nodes:
                text_px = len(str(node.name or "")) * self._char_width_px
                required = max(required, text_px + depth * _TREE_INDENT_PX + 2 * _PAD)
                walk(node.children, depth + 1)

        walk(self._roots, 0)
        self._name_col_px = required
        self._tree.column("#0", width=self._name_col_px, minwidth=self._name_col_px)
        self._search_entry.configure(width=max(80, self._name_col_px))

    def required_width_px(self) -> int:
        """Panel width needed with the fitted Field Name column (incl. scrollbar)."""
        tag_px = _TAG_CHARS * self._char_width_px
        content_px = _CONTENT_CHARS * self._char_width_px
        return self._name_col_px + tag_px + content_px + _TREE_INDENT_PX + 4 * _PAD

    def required_height_px(self) -> int:
        """Panel height needed to show every top-level row without scrolling."""
        rows = max(1, len(self._roots))
        toolbar_px = 50
        heading_px = 28
        return toolbar_px + heading_px + rows * _TREE_ROW_HEIGHT_PX + 2 * _PAD

    def content_texts(self) -> list[str]:
        """All Content cell strings currently in the tree model (pre-search filter)."""
        return [item.text for item in self.content_ner_items()]

    def content_ner_items(self) -> list[MetadataNerItem]:
        """Content cells with field name / VR for radiology pre-NER filtering."""
        out: list[MetadataNerItem] = []

        def walk(
            nodes: Sequence[MetadataTreeNode],
            *,
            parent_name: str = "",
            parent_vr: str = "",
        ) -> None:
            for node in nodes:
                raw_name = str(node.name or "").strip()
                # value / item children inherit the parent element's
                # field name and VR, so code/date VRs still filter them.
                name = parent_name if raw_name in {ITEM_NAME, VALUE_NAME, STRUCTURAL_TAG} else raw_name
                vr = str(node.vr or "") or parent_vr
                # value children duplicate the parent's joined Content;
                # detect/remove operate on the parent field as one unit.
                if node.content and raw_name != VALUE_NAME:
                    out.append(
                        MetadataNerItem(
                            text=node.content,
                            field_name=name,
                            tag=str(node.tag or ""),
                            vr=vr,
                            tag_path=str(node.tag_path or ""),
                            is_anonymizer_field=is_anonymizer_field(
                                tag=str(node.tag or ""),
                                name=str(node.name or ""),
                                tag_path=str(node.tag_path or ""),
                            ),
                            is_date=vr.upper() in {"DA", "DT"},
                        )
                    )
                walk(node.children, parent_name=name, parent_vr=vr)

        walk(self._roots)
        return out

    def apply_phi_entities(self, entities_by_content: Mapping[str, Sequence[Entity]]) -> int:
        """Apply NER hits: Content markers + Report Viewer entity colors. Returns hit count."""
        self._excluded_contents.clear()
        self._entities_by_content = {
            str(text): tuple(ents) for text, ents in entities_by_content.items() if ents
        }
        self._rebuild()
        hit_iids = [iid for iid, text in self._content_by_iid.items() if text in self._entities_by_content]
        for iid in hit_iids:
            self._reveal_iid(iid)
        self._restripe_visible()
        return sum(len(ents) for ents in self._entities_by_content.values())

    def phi_field_count(self) -> int:
        """Number of fields (tree rows) whose Content has detected PHI."""
        return sum(
            1 for text in self._content_by_iid.values() if text in self._entities_by_content
        )

    def private_uid_date_counts(self) -> tuple[int, int]:
        """(UID, date) field counts among private tags (odd group number).

        These are the fields the anonymizer script handles by UID remapping
        / date delta; Detect PHI excludes them from NER scoring.
        """
        uids = 0
        dates = 0

        def walk(nodes: Sequence[MetadataTreeNode]) -> None:
            nonlocal uids, dates
            for node in nodes:
                tag = str(node.tag or "").strip()
                raw_name = str(node.name or "").strip()
                if len(tag) >= 4 and raw_name != VALUE_NAME:
                    try:
                        group = int(tag[:4], 16)
                    except ValueError:
                        group = 0
                    if group % 2 == 1:
                        vr = str(node.vr or "").upper()
                        if vr == "UI":
                            uids += 1
                        elif vr in {"DA", "DT"}:
                            dates += 1
                walk(node.children)

        walk(self._roots)
        return uids, dates

    def has_phi(self) -> bool:
        """True when any Content has detected PHI (included or excluded)."""
        return bool(self._entities_by_content)

    def active_entities_by_content(self) -> dict[str, tuple[Entity, ...]]:
        """Detected PHI not excluded from Remove (Report View _active_entities)."""
        return {
            text: ents
            for text, ents in self._entities_by_content.items()
            if text not in self._excluded_contents
        }

    def apply_cleaned_texts(self, cleaned_by_content: Mapping[str, str]) -> int:
        """Write cleaned Content back to the dataset at each field's tag path.

        Uses the existing apply_text_at_path writer; returns the number
        of fields changed. Cleaned paths stay pending until Save writes
        them to disk (see pending_cleaned_by_tag_path).
        """
        if self._ds is None:
            return 0
        changed: dict[str, str] = {}

        def walk(nodes: Sequence[MetadataTreeNode]) -> None:
            for node in nodes:
                if (
                    node.content in cleaned_by_content
                    and str(node.name or "").strip() not in {ITEM_NAME, VALUE_NAME}
                ):
                    cleaned = cleaned_by_content[node.content]
                    apply_text_at_path(self._ds, node.tag_path, cleaned)  # type: ignore[arg-type]
                    changed[node.tag_path] = cleaned
                walk(node.children)

        walk(self._roots)
        self._pending_cleaned_by_tag_path.update(changed)
        self.set_dataset(self._ds)
        return len(changed)

    def pending_cleaned_by_tag_path(self) -> dict[str, str]:
        """Cleaned tag_path → text writes not yet saved to disk."""
        return dict(self._pending_cleaned_by_tag_path)

    def clear_pending_cleaned(self) -> None:
        """Drop pending cleaned writes after a successful Save."""
        self._pending_cleaned_by_tag_path.clear()

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
        # PHI rows: same highlight pattern as Dataset View's "green" tag —
        # entity class background, white foreground, applied as the row's
        # only tag (see _restripe_visible).
        for label in SCORED_LABELS:
            self._tree.tag_configure(
                f"{_PHI_TAG_PREFIX}{label}",
                background=entity_color_hex(label),
                foreground="white",
            )
        self._tree.tag_configure(
            f"{_PHI_TAG_PREFIX}UNKNOWN",
            background=entity_color_hex("UNKNOWN"),
            foreground="white",
        )
        # Excluded from Remove (Report View excluded spans): grey text.
        self._tree.tag_configure("phi_excluded", foreground="#888888")

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
        display_content = _content_display_text(
            node.content,
            self._entities_by_content.get(node.content, ()),
            excluded=node.content in self._excluded_contents,
        )
        self._tree.insert(
            parent,
            "end",
            iid=iid,
            text=node.name,
            values=(node.tag, display_content),
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
            if ents and text in self._excluded_contents:
                self._tree.item(iid, tags=("phi_excluded",))
            elif ents:
                label = _primary_phi_label(ents)
                phi_tag = f"{_PHI_TAG_PREFIX}{label if label in SCORED_LABELS else 'UNKNOWN'}"
                # Dataset View pattern: highlight tag is the row's only tag.
                # Combining it with the zebra stripe let the stripe (later
                # tag wins) override the entity background/foreground.
                self._tree.item(iid, tags=(phi_tag,))
            else:
                self._tree.item(iid, tags=(stripe,))

    def _on_tree_click(self, event: tk.Event) -> None:
        """Click Content with detected PHI toggles it out of / into Remove."""
        if self._tree.identify_column(event.x) != _CONTENT_COLUMN_ID:
            return
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return
        text = str(self._content_by_iid.get(row_id) or "")
        if text not in self._entities_by_content:
            return
        if text in self._excluded_contents:
            self._excluded_contents.discard(text)
            excluded = False
        else:
            self._excluded_contents.add(text)
            excluded = True
        values = self._tree.item(row_id, "values")
        tag_value = str(values[0]) if values else ""
        self._tree.item(
            row_id,
            values=(
                tag_value,
                _content_display_text(
                    text, self._entities_by_content[text], excluded=excluded
                ),
            ),
        )
        self._restripe_visible()
        if self._on_phi_toggle is not None:
            self._on_phi_toggle(text, excluded)

    def _content_tooltip(self, event: tk.Event) -> TooltipContent | None:
        """Entity color chip on hover — only for Content with detected PHI."""
        if self._tree.identify_column(event.x) != _CONTENT_COLUMN_ID:
            return None
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return None
        text = str(self._content_by_iid.get(row_id) or "")
        ents = self._entities_by_content.get(text, ())
        if not ents:
            return None
        labels = _phi_display_labels(ents)
        if not labels:
            return None
        return TooltipContent(
            text=_phi_hover_text(text, ents),
            bg=entity_color_hex(labels[0]),
            fg="#ffffff",
            bold=True,
        )

class MetadataAssessmentDialog(AppCTkToplevel):
    """Metadata tree dialog: Series View _sv_frame + control_frame chrome."""

    PAD = _PAD
    BUTTON_WIDTH = _BUTTON_WIDTH
    STATUS_WRAPLENGTH = _STATUS_WRAPLENGTH
    POLL_MS = _POLL_MS
    DEFAULT_WIDTH = _DIALOG_DEFAULT_WIDTH
    DEFAULT_HEIGHT = _DIALOG_DEFAULT_HEIGHT

    def __init__(
        self,
        parent: tk.Misc,
        *,
        dataset: Dataset,
        project_dir: Path | None = None,
        modality: str | None = None,
        whitelist: Sequence[str] | None = None,
        whitelist_match_settings: OcrWhitelistMatchSettings | None = None,
        dataset_path: Path | None = None,
    ) -> None:
        super().__init__(master=parent)
        self._parent = parent
        self._dataset = dataset
        self._dataset_path = Path(dataset_path) if dataset_path is not None else None
        self._dirty = False
        self._mode_labels = replace_mode_labels()
        self._project_dir = project_dir
        self._modality = modality or str(getattr(dataset, "Modality", "") or "") or None
        self._whitelist = list(whitelist) if whitelist is not None else None
        self._whitelist_match_settings = whitelist_match_settings
        self._destroyed = False
        self._detecting = False
        self._detect_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self.withdraw()
        self.title(_metadata_window_title(dataset))
        self.minsize(720, 400)
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Outer shell like Series View: nested CTkFrames get top_fg_color (toolbar group).
        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=self.PAD, pady=self.PAD, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(0, weight=1)

        self._panel = MetadataTreePanel(
            self._sv_frame, fg_color="transparent", on_phi_toggle=self._on_phi_toggle
        )
        self._panel.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=(self.PAD, 0))
        self._panel.set_dataset(dataset)

        # Nested in _sv_frame so this bar uses theme top_fg_color (Series View chrome).
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

        # Report View Remove flow: hidden until Detect finds PHI.
        self.remove_button = ctk.CTkButton(
            action_group,
            width=button_width_for_label(remove_phi_button_label("blank"), minimum=self.BUTTON_WIDTH),
            text=remove_phi_button_label("blank"),
            command=self._on_remove,
        )
        self.remove_button.grid(row=0, column=1, padx=2, pady=0)
        mode_labels = list(self._mode_labels)
        self.mode_var = tk.StringVar(value=mode_labels[0] if mode_labels else "")
        self.mode_menu = ctk.CTkOptionMenu(
            action_group,
            values=mode_labels,
            variable=self.mode_var,
            width=120,
            command=lambda _v: self._refresh_remove_label(),
        )
        self.mode_menu.grid(row=0, column=2, padx=(2, self.PAD), pady=0)
        self.remove_button.grid_remove()
        self.mode_menu.grid_remove()

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

        footer_right = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        footer_right.grid(row=1, column=2, padx=self.PAD, pady=(0, self.PAD), sticky="e")
        save_label = _("Save")
        self.save_button = ctk.CTkButton(
            footer_right,
            width=button_width_for_label(save_label, minimum=self.BUTTON_WIDTH),
            text=save_label,
            command=self._on_save,
        )
        self.save_button.grid(row=0, column=0, padx=(0, 2), pady=0, sticky="e")
        close_label = _("Close")
        self.close_button = ctk.CTkButton(
            footer_right,
            width=button_width_for_label(close_label, minimum=self.BUTTON_WIDTH),
            text=close_label,
            command=self._on_close,
        )
        self.close_button.grid(row=0, column=1, padx=(2, 0), pady=0, sticky="e")
        self._refresh_state()

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
        """Center on the SeriesView parent; grow to fit, capped at 85% screen height."""
        try:
            screen_width = int(self.winfo_screenwidth())
            screen_height = int(self.winfo_screenheight())
        except tk.TclError:
            logger.debug("Could not size Metadata dialog", exc_info=True)
            screen_width, screen_height = self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT
        width, height = metadata_dialog_size(
            screen_width=screen_width,
            screen_height=screen_height,
            required_width=self._panel.required_width_px() + 4 * self.PAD,
            required_height=self._panel.required_height_px() + _DIALOG_CHROME_HEIGHT_PX,
        )
        place_toplevel_centered_on_parent(self, self._parent, width=width, height=height)

    def _escape_keypress(self, _event: tk.Event | None = None) -> str:
        self._on_close()
        return "break"

    def _selected_mode(self) -> ReplaceMode:
        return self._mode_labels.get(self.mode_var.get(), REPLACE_MODE_VALUES[0])

    def _refresh_remove_label(self) -> None:
        self.remove_button.configure(text=remove_phi_button_label(self._selected_mode()))

    def _set_remove_toolbar_present(self, present: bool) -> None:
        # Use grid_info (not winfo_ismapped): ismapped is false while the
        # toplevel is withdrawn, even when the widget is still in the grid.
        for widget in (self.remove_button, self.mode_menu):
            try:
                in_grid = bool(widget.grid_info())
            except tk.TclError:
                continue
            if present and not in_grid:
                with contextlib.suppress(tk.TclError):
                    widget.grid()
            elif not present and in_grid:
                with contextlib.suppress(tk.TclError):
                    widget.grid_remove()

    def _refresh_state(self) -> None:
        """Report View state gating: Remove only with detections, Save only when dirty."""
        has_phi = self._panel.has_phi()
        has_active = bool(self._panel.active_entities_by_content())
        show_remove = has_phi and not self._detecting
        self._set_remove_toolbar_present(show_remove)
        self.detect_button.configure(state="disabled" if self._detecting else "normal")
        if show_remove:
            self.remove_button.configure(state="normal" if has_active else "disabled")
            self.mode_menu.configure(state="normal")
        self.save_button.configure(
            state="normal" if (self._dirty and self._dataset_path is not None) else "disabled"
        )
        self._refresh_remove_label()

    def _on_phi_toggle(self, _text: str, excluded: bool) -> None:
        if excluded:
            self._set_status(_("Excluded from Remove") + ". " + _("Click again to include."))
        else:
            self._set_status(_("Included for Remove") + ". " + _("Click to exclude."))
        self._refresh_state()

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
        self._refresh_state()
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
        if kind == "error":
            self._set_status(_("Detection failed") + f": {payload}")
            self._refresh_state()
            return
        entities_by_text = payload  # type: ignore[assignment]
        assert isinstance(entities_by_text, dict)
        self._panel.apply_phi_entities(entities_by_text)
        private_uids, private_dates = self._panel.private_uid_date_counts()
        self._set_status(
            _format_detection_status(
                entities_by_text,
                field_count=self._panel.phi_field_count(),
                private_uid_count=private_uids,
                private_date_count=private_dates,
            )
        )
        self._refresh_state()

    def _on_remove(self) -> None:
        """Report View Remove: blank/synthesise active PHI spans in each field."""
        active = self._panel.active_entities_by_content()
        if not active:
            return
        synthetic = self._selected_mode() == "synth"
        cleaned = {
            text: remove_phi(text, list(ents), synthetic=synthetic)
            for text, ents in active.items()
        }
        removed = sum(len(ents) for ents in active.values())
        self._panel.apply_cleaned_texts(cleaned)
        self._dirty = True
        self._refresh_state()
        self._set_status(
            _("Removed Embedded PHI") + f" ({removed}). " + _("Save to write changes.")
        )

    def _on_save(self) -> None:
        """Write pending cleaned fields to the source DICOM file (pixels preserved)."""
        if self._dataset_path is None or not self._dirty:
            return
        pending = self._panel.pending_cleaned_by_tag_path()
        try:
            full = dcmread(str(self._dataset_path))
            for tag_path, cleaned in pending.items():
                apply_text_at_path(full, tag_path, cleaned)
            record_deid_method_codes(full, {DeidMethodCode.CLEAN_DESCRIPTORS})
            full.save_as(str(self._dataset_path), enforce_file_format=True)
        except Exception:
            logger.exception("Metadata Save failed for %s", self._dataset_path)
            self._set_status(_("Save failed") + f": {self._dataset_path}")
            return
        self._panel.clear_pending_cleaned()
        self._dirty = False
        self._refresh_state()
        self._set_status(_("Changes saved"))

    def _on_close(self) -> None:
        if self._dirty and not messagebox.askyesno(
            title=_("Metadata"),
            message=_("Discard unsaved changes?"),
            parent=self,
        ):
            return
        self._destroyed = True
        teardown_ctk_toplevel(self, parent=self._parent)
