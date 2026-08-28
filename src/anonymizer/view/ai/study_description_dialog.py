"""Dialog to pick a LOINC StudyDescription when ranking is ambiguous."""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import customtkinter as ctk

from anonymizer.controller.ai.harmonize import (
    StudyDescriptionOffer,
    apply_study_description_offer,
    resolve_study_description_offers,
)
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

logger = logging.getLogger(__name__)


@dataclass
class StudyDescriptionDialogResult:
    applied: bool = False
    description: str | None = None
    updated_study_uids: tuple[str, ...] = field(default_factory=tuple)
    auto_applied: bool = False


class StudyDescriptionDialog(AppToplevel):
    PAD = 12
    MIN_WIDTH = 560

    def __init__(
        self,
        parent: tk.Misc,
        *,
        offer: StudyDescriptionOffer,
        images_dir: Path,
        anon_model,
    ) -> None:
        super().__init__(master=parent)
        self._offer = offer
        self._images_dir = Path(images_dir)
        self._anon_model = anon_model
        self._result = StudyDescriptionDialogResult()
        self._closing = False

        self.title(_("Study Description (LOINC)"))
        self.resizable(True, False)
        self.minsize(self.MIN_WIDTH, 280)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _e: self._on_cancel())

        self.grid_columnconfigure(0, weight=1)

        pad = self.PAD
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text=_("Several LOINC study descriptions are close matches. Choose one."),
            anchor="w",
            wraplength=self.MIN_WIDTH - 2 * pad,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(body, text=_("Series descriptions") + ":", anchor="w").grid(
            row=1, column=0, sticky="w", pady=(pad, 2)
        )
        series_text = "\n".join(offer.fingerprint) if offer.fingerprint else "—"
        series_box = ctk.CTkTextbox(body, height=min(120, 24 + 18 * max(1, len(offer.fingerprint))), wrap="word")
        series_box.grid(row=2, column=0, sticky="ew")
        series_box.insert("1.0", series_text)
        series_box.configure(state="disabled")

        ctk.CTkLabel(body, text=_("Study description") + ":", anchor="w").grid(
            row=3, column=0, sticky="w", pady=(pad, 2)
        )

        self._match_by_label: dict[str, tuple[str, str]] = {}
        labels: list[str] = []
        for match in offer.matches:
            label = f"{match.long_common_name}  ({match.loinc_number})"
            self._match_by_label[label] = (match.long_common_name, match.loinc_number)
            labels.append(label)
        if not labels:
            labels = [_("No LOINC matches")]

        self._description_var = tk.StringVar(value=labels[0])
        self._menu = ctk.CTkOptionMenu(
            body,
            variable=self._description_var,
            values=labels,
            width=self.MIN_WIDTH - 2 * pad,
        )
        self._menu.grid(row=4, column=0, sticky="ew")

        peer_count = len(offer.peer_study_uids)
        # Default on: researchers typically share one study type across the project.
        self._apply_peers_var = tk.IntVar(value=1 if peer_count > 0 else 0)
        peer_label = _("Also apply to other studies with the same series descriptions") + f" ({peer_count})"
        self._peer_checkbox = ctk.CTkCheckBox(
            body,
            text=peer_label,
            variable=self._apply_peers_var,
        )
        self._peer_checkbox.grid(row=5, column=0, sticky="w", pady=(pad, 0))
        if peer_count == 0:
            self._peer_checkbox.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", padx=pad, pady=(0, pad))
        footer.grid_columnconfigure(0, weight=1)

        btn_row = ctk.CTkFrame(footer, fg_color="transparent")
        btn_row.grid(row=0, column=0, sticky="e")
        ctk.CTkButton(btn_row, text=_("Cancel"), width=100, command=self._on_cancel).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text=_("Apply"), width=100, command=self._on_apply).pack(side="left")

        self.lift()
        self.focus()
        with contextlib.suppress(tk.TclError):
            self.grab_set()

    def _on_cancel(self) -> None:
        self._close()

    def _on_apply(self) -> None:
        label = self._description_var.get()
        mapped = self._match_by_label.get(label)
        if mapped is None:
            return
        description, loinc_number = mapped
        description = description.strip()
        if not description:
            return
        apply_peers = self._apply_peers_var.get() == 1 and bool(self._offer.peer_study_uids)
        try:
            updated = apply_study_description_offer(
                images_dir=self._images_dir,
                anon_model=self._anon_model,
                offer=self._offer,
                description=description,
                apply_to_peers=apply_peers,
                loinc_number=loinc_number,
            )
        except Exception:
            logger.exception("Failed to apply study description")
            updated = []
        self._result = StudyDescriptionDialogResult(
            applied=bool(updated),
            description=description if updated else None,
            updated_study_uids=tuple(updated),
        )
        self._close()

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        parent = self.master
        teardown_ctk_toplevel(self, parent=parent)

    def get_input(self) -> StudyDescriptionDialogResult:
        self.focus()
        self.master.wait_window(self)
        return self._result


def show_study_description_dialog(
    parent: tk.Misc,
    *,
    offer: StudyDescriptionOffer,
    images_dir: Path,
    anon_model,
) -> StudyDescriptionDialogResult:
    dialog = StudyDescriptionDialog(
        parent,
        offer=offer,
        images_dir=images_dir,
        anon_model=anon_model,
    )
    return dialog.get_input()


def resolve_and_show_study_description_offers(
    parent: tk.Misc,
    *,
    offers: list[StudyDescriptionOffer],
    images_dir: Path,
    anon_model,
    on_auto_applied: Callable[[StudyDescriptionOffer, list[str]], None] | None = None,
) -> list[StudyDescriptionDialogResult]:
    """
    Auto-apply clear fingerprint groups; show one dialog per ambiguous group.

    ``on_auto_applied`` is called with (offer, updated_uids) for each silent apply.
    """
    ambiguous, auto_results = resolve_study_description_offers(
        images_dir=images_dir,
        anon_model=anon_model,
        offers=offers,
    )
    results: list[StudyDescriptionDialogResult] = []
    for offer, updated in auto_results:
        if on_auto_applied is not None:
            on_auto_applied(offer, updated)
        results.append(
            StudyDescriptionDialogResult(
                applied=bool(updated),
                description=offer.matches[0].long_common_name if updated and offer.matches else None,
                updated_study_uids=tuple(updated),
                auto_applied=True,
            )
        )
    for offer in ambiguous:
        if anon_model.get_study_harmonized_description(offer.anon_study_uid):
            continue
        results.append(
            show_study_description_dialog(
                parent,
                offer=offer,
                images_dir=images_dir,
                anon_model=anon_model,
            )
        )
    return results


# Backward-compatible name used by batch dialog.
def show_study_description_offers(
    parent: tk.Misc,
    *,
    offers: list[StudyDescriptionOffer],
    images_dir: Path,
    anon_model,
) -> list[StudyDescriptionDialogResult]:
    return resolve_and_show_study_description_offers(
        parent,
        offers=offers,
        images_dir=images_dir,
        anon_model=anon_model,
    )
