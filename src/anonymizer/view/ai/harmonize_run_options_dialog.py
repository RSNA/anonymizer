"""Combined pre-run options for Series View Harmonize (mapping vs model + brain)."""

from __future__ import annotations

import contextlib
import tkinter as tk
from dataclasses import dataclass

import customtkinter as ctk

from anonymizer.model.anonymizer import DescriptionMappingRecord
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.catalog import AiFeatureId, feature_description
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel


@dataclass(frozen=True)
class HarmonizeRunOptionsResult:
    apply_mapping: bool = False
    include_brain_structures: bool = False
    cancelled: bool = True


class HarmonizeRunOptionsDialog(AppToplevel):
    """One modal for mapping apply vs run-model and optional brain structures."""

    PAD = 16
    DIALOG_WIDTH = 480
    BUTTON_WIDTH = 100

    def __init__(
        self,
        parent: tk.Misc,
        *,
        mapping: DescriptionMappingRecord | None,
        offer_brain: bool,
        brain_description: str = "",
    ) -> None:
        super().__init__(parent)
        self.title(_("Harmonize options"))
        self._parent = parent
        self._mapping = mapping
        self._offer_brain = offer_brain
        self._brain_description = brain_description
        self._result = HarmonizeRunOptionsResult()
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        pad = self.PAD
        wrap = self.DIALOG_WIDTH - 2 * pad
        self.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_columnconfigure(0, weight=1)

        row = 0
        self._run_model_var = tk.IntVar(value=0 if mapping is not None else 1)
        self._brain_var = tk.IntVar(value=0)

        if mapping is not None:
            ctk.CTkLabel(
                body,
                text=_("A saved description mapping matches this series:"),
                anchor="w",
                justify="left",
                wraplength=wrap,
            ).grid(row=row, column=0, sticky="ew", pady=(0, 6))
            row += 1
            ctk.CTkLabel(
                body,
                text=f'"{mapping.original_display}" → "{mapping.harmonized_description}"',
                anchor="w",
                justify="left",
                wraplength=wrap,
                font=ctk.CTkFont(weight="bold"),
            ).grid(row=row, column=0, sticky="ew", pady=(0, 8))
            row += 1
            ctk.CTkRadioButton(
                body,
                text=_("Apply mapping"),
                variable=self._run_model_var,
                value=0,
                command=self._sync_brain_enabled,
            ).grid(row=row, column=0, sticky="w", pady=(0, 4))
            row += 1
            ctk.CTkRadioButton(
                body,
                text=_("Run Harmonize model"),
                variable=self._run_model_var,
                value=1,
                command=self._sync_brain_enabled,
            ).grid(row=row, column=0, sticky="w", pady=(0, 8))
            row += 1
        elif offer_brain:
            ctk.CTkLabel(
                body,
                text=_("This appears to be a CT head study. Run detailed brain structure segmentation?"),
                anchor="w",
                justify="left",
                wraplength=wrap,
            ).grid(row=row, column=0, sticky="ew", pady=(0, 6))
            row += 1
            if brain_description:
                ctk.CTkLabel(
                    body,
                    text=brain_description,
                    anchor="w",
                    justify="left",
                    wraplength=wrap,
                    text_color=("gray40", "gray60"),
                ).grid(row=row, column=0, sticky="ew", pady=(0, 8))
                row += 1

        self._brain_checkbox: ctk.CTkCheckBox | None = None
        if offer_brain and mapping is not None:
            self._brain_checkbox = ctk.CTkCheckBox(
                body,
                text=_("Brain structures (CT Head when present)"),
                variable=self._brain_var,
            )
            self._brain_checkbox.grid(row=row, column=0, sticky="w", pady=(0, 4))
            row += 1
            if brain_description:
                ctk.CTkLabel(
                    body,
                    text=brain_description,
                    anchor="w",
                    justify="left",
                    wraplength=wrap,
                    text_color=("gray40", "gray60"),
                ).grid(row=row, column=0, sticky="ew", pady=(0, 8))
                row += 1
            self._sync_brain_enabled()
        elif offer_brain and mapping is None:
            # Brain-only: Yes/No via Continue with checkbox default off matching askyesno default=no.
            self._brain_checkbox = ctk.CTkCheckBox(
                body,
                text=_("Run detailed brain structure segmentation"),
                variable=self._brain_var,
            )
            self._brain_checkbox.grid(row=row, column=0, sticky="w", pady=(0, 12))
            row += 1

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.grid(row=row, column=0, sticky="e", pady=(4, 0))
        ctk.CTkButton(
            buttons,
            text=_("Cancel"),
            width=self.BUTTON_WIDTH,
            command=self._on_cancel,
        ).pack(side="left", padx=(0, pad // 2))
        ctk.CTkButton(
            buttons,
            text=_("Continue"),
            width=self.BUTTON_WIDTH,
            command=self._on_continue,
        ).pack(side="left")

        self._place_centered_on_parent()
        self.wait_visibility()
        self.lift()
        self.grab_set()
        self.focus_set()

    def _place_centered_on_parent(self) -> None:
        """Size to content and open centered over the parent window."""
        self.update_idletasks()
        width = max(self.DIALOG_WIDTH, int(self.winfo_reqwidth()))
        height = int(self.winfo_reqheight())
        parent = self._parent
        with contextlib.suppress(tk.TclError):
            parent.update_idletasks()
            x = int(parent.winfo_rootx()) + max(0, (int(parent.winfo_width()) - width) // 2)
            y = int(parent.winfo_rooty()) + max(0, (int(parent.winfo_height()) - height) // 2)
            screen_w = int(self.winfo_screenwidth())
            screen_h = int(self.winfo_screenheight())
            x = max(0, min(x, screen_w - width))
            y = max(0, min(y, screen_h - height))
            self.geometry(f"{width}x{height}+{x}+{y}")
            return
        self.geometry(f"{width}x{height}")

    def _sync_brain_enabled(self) -> None:
        if self._brain_checkbox is None:
            return
        if self._mapping is not None and self._run_model_var.get() != 1:
            self._brain_var.set(0)
            self._brain_checkbox.configure(state="disabled")
        else:
            self._brain_checkbox.configure(state="normal")

    def _on_cancel(self) -> None:
        self._result = HarmonizeRunOptionsResult(cancelled=True)
        teardown_ctk_toplevel(self)

    def _on_continue(self) -> None:
        run_model = self._run_model_var.get() == 1 if self._mapping is not None else True
        apply_mapping = self._mapping is not None and not run_model
        include_brain = bool(self._offer_brain and run_model and self._brain_var.get() == 1)
        self._result = HarmonizeRunOptionsResult(
            apply_mapping=apply_mapping,
            include_brain_structures=include_brain,
            cancelled=False,
        )
        teardown_ctk_toplevel(self)

    def get_result(self) -> HarmonizeRunOptionsResult:
        return self._result


def show_harmonize_run_options_dialog(
    parent: tk.Misc,
    *,
    mapping: DescriptionMappingRecord | None,
    offer_brain: bool,
) -> HarmonizeRunOptionsResult:
    """Show combined options when mapping and/or brain apply; otherwise return run-model defaults."""
    if mapping is None and not offer_brain:
        return HarmonizeRunOptionsResult(apply_mapping=False, include_brain_structures=False, cancelled=False)

    brain_description = ""
    if offer_brain:
        brain_description = feature_description(AiFeatureId.BRAIN_STRUCTURES.value)

    dialog = HarmonizeRunOptionsDialog(
        parent,
        mapping=mapping,
        offer_brain=offer_brain,
        brain_description=brain_description,
    )
    parent.wait_window(dialog)
    return dialog.get_result()
