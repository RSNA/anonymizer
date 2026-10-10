"""Read-only report text panel: unicode body with entity highlights (click to exclude)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from tkinter import Misc

import customtkinter as ctk

from anonymizer.controller.ai.embedded_phi.ner.ner import SCORED_LABELS, Entity
from anonymizer.view.common.tooltip import MotionTooltipController, TooltipContent
from anonymizer.view.reports.entity_colors import entity_color_hex

_EXCLUDED_TAG = "ent_excluded"


class ReportCanvas(ctk.CTkTextbox):
    """Text panel for report unicode. Rendering only — state lives in the View."""

    def __init__(
        self,
        master: Misc,
        *,
        on_toggle: Callable[[int], None] | None = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("wrap", "word")
        super().__init__(master, **kwargs)
        self._on_toggle = on_toggle
        self._entities: list[Entity] = []
        tk_text = self._textbox
        for label in SCORED_LABELS:
            tk_text.tag_configure(f"ent_{label}", background=entity_color_hex(label), foreground="#ffffff")
        tk_text.tag_configure(_EXCLUDED_TAG, overstrike=True, background="", foreground="#888888")
        tk_text.tag_raise("sel")
        tk_text.bind("<Button-1>", self._on_click, add="+")
        MotionTooltipController(tk_text, self._entity_tooltip_text, parent=self).bind()
        self.configure(state="disabled")

    def show_text(self, text: str, *, empty_message: str = "") -> None:
        """
        Replace panel contents with ``text``.

        Args:
            text: Report unicode to display.
            empty_message: Shown when ``text`` is empty.
        """
        self.configure(state="normal")
        self.delete("1.0", "end")
        self._entities.clear()
        body = str(text or "")
        if not body.strip():
            self.insert("end", empty_message or "")
        else:
            self.insert("end", body)
        self.configure(state="disabled")

    def highlight(self, entities: Sequence[Entity], is_excluded: Callable[[int], bool]) -> None:
        """
        Color entity spans; excluded spans use overstrike.

        Args:
            entities: PHI spans with offsets into the displayed text.
            is_excluded: Returns True when ``entity.start`` is excluded from Remove.
        """
        tk_text = self._textbox
        for label in SCORED_LABELS:
            tk_text.tag_remove(f"ent_{label}", "1.0", "end")
        for ent in self._entities:
            tk_text.tag_remove(f"ent_{ent.label}", "1.0", "end")
        tk_text.tag_remove(_EXCLUDED_TAG, "1.0", "end")
        self._entities = list(entities)
        for ent in self._entities:
            a, b = f"1.0+{ent.start}c", f"1.0+{ent.end}c"
            if is_excluded(ent.start):
                tk_text.tag_add(_EXCLUDED_TAG, a, b)
            else:
                tag = f"ent_{ent.label}"
                tk_text.tag_configure(tag, background=entity_color_hex(ent.label), foreground="#ffffff")
                tk_text.tag_add(tag, a, b)

    def _offset_at(self, event) -> int:  # noqa: ANN001
        index = self._textbox.index(f"@{event.x},{event.y}")
        return len(self._textbox.get("1.0", index))

    def _entity_at(self, offset: int) -> Entity | None:
        for ent in self._entities:
            if ent.start <= offset < ent.end:
                return ent
        return None

    def _entity_tooltip_text(self, event) -> TooltipContent | None:  # noqa: ANN001
        """Hover chip: product label only (white on entity color). Score is not shown."""
        ent = self._entity_at(self._offset_at(event))
        if ent is None:
            return None
        label = str(ent.label).upper()
        return TooltipContent(text=label, bg=entity_color_hex(label), fg="#ffffff")

    def _on_click(self, event) -> None:  # noqa: ANN001
        if self._on_toggle is None:
            return
        ent = self._entity_at(self._offset_at(event))
        if ent is not None:
            self._on_toggle(ent.start)
