"""Read-only report text canvas: formatted slots with entity highlights (click to exclude)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from tkinter import Misc

import customtkinter as ctk

from anonymizer.controller.ai.embedded_phi.ner.detect_phi import SlotScan
from anonymizer.controller.ai.embedded_phi.ner.phi_entity import SCORED_LABELS
from anonymizer.controller.ai.embedded_phi.report.content_text import TextSlot
from anonymizer.view.reports.entity_colors import entity_color_hex

_EXCLUDED_TAG = "ent_excluded"
_HEADER_TAG = "slot_header"


class ReportCanvas(ctk.CTkTextbox):
    """Text view of all report slots. Rendering only — state lives in ``ReportSession``."""

    def __init__(
        self,
        master: Misc,
        *,
        on_toggle: Callable[[str, int], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("wrap", "word")
        super().__init__(master, **kwargs)
        self._on_toggle = on_toggle
        self._starts: dict[str, str] = {}
        # (slot_key, entity.start, entity.end)
        self._spans: list[tuple[str, int, int]] = []
        tk_text = self._textbox
        for label in SCORED_LABELS:
            tk_text.tag_configure(f"ent_{label}", background=entity_color_hex(label), foreground="#ffffff")
        tk_text.tag_configure(_EXCLUDED_TAG, overstrike=True, background="", foreground="#888888")
        tk_text.tag_configure(_HEADER_TAG, foreground="#888888", spacing1=8)
        tk_text.tag_raise("sel")
        tk_text.bind("<Button-1>", self._on_click, add="+")
        self.configure(state="disabled")

    def show_slots(self, slots: Sequence[TextSlot], *, empty_message: str = "", show_headers: bool = False) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self._starts.clear()
        self._spans.clear()
        if not slots:
            self.insert("end", empty_message)
        for slot in slots:
            if show_headers and slot.context:
                self.insert("end", f"{slot.context}\n", _HEADER_TAG)
            self._starts[slot.key] = self.index("end-1c")
            self.insert("end", f"{slot.text}\n\n")
        self.configure(state="disabled")

    def highlight(self, scans: Sequence[SlotScan], is_excluded: Callable[[str, int], bool]) -> None:
        tk_text = self._textbox
        for label in SCORED_LABELS:
            tk_text.tag_remove(f"ent_{label}", "1.0", "end")
        tk_text.tag_remove(_EXCLUDED_TAG, "1.0", "end")
        self._spans.clear()
        for scan in scans:
            base = self._starts.get(scan.slot.key)
            if base is None:
                continue
            for ent in scan.entities:
                a, b = f"{base}+{ent.start}c", f"{base}+{ent.end}c"
                if is_excluded(scan.slot.key, ent.start):
                    tk_text.tag_add(_EXCLUDED_TAG, a, b)
                else:
                    tk_text.tag_add(f"ent_{ent.label}", a, b)
                self._spans.append((scan.slot.key, ent.start, ent.end))

    def see_entity(self, slot_key: str, start: int) -> None:
        base = self._starts.get(slot_key)
        if base is not None:
            self._textbox.see(f"{base}+{start}c")

    def _on_click(self, event) -> str | None:
        if self._on_toggle is None:
            return None
        index = self._textbox.index(f"@{event.x},{event.y}")
        hit = self._entity_at(index)
        if hit is None:
            return None
        self._on_toggle(*hit)
        return "break"

    def _entity_at(self, index: str) -> tuple[str, int] | None:
        for slot_key, start, end in self._spans:
            base = self._starts.get(slot_key)
            if base is None:
                continue
            try:
                click_off = self._textbox.count(base, index, "chars")
            except Exception:  # noqa: BLE001
                continue
            if click_off is None:
                continue
            off = int(click_off[0] if isinstance(click_off, tuple) else click_off)
            if start <= off < end:
                return slot_key, start
        return None
