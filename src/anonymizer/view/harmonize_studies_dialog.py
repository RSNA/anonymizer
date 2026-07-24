"""Unattended harmonize progress dialog for PHI Index study selection."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from anonymizer.controller.harmonize import HarmonizeApplyOutcome, HarmonizeStudiesSummary
from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class HarmonizeStudiesDialog(tk.Toplevel):
    """Modal dialog that harmonizes CT series for selected studies in a background thread."""

    POLL_MS = 200

    def __init__(
        self,
        parent,
        controller: ProjectController,
        studies: list[tuple[str, str]],
    ) -> None:
        super().__init__(master=parent)
        self._controller = controller
        self._studies = studies
        self._cancelled = False
        self._closing = False
        self._summary: HarmonizeStudiesSummary | None = None
        self._worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._poll_after_id: str | None = None

        title = _("Harmonize Studies")
        study_label = _("study") if len(studies) == 1 else _("studies")
        self._sub_title = _("Harmonizing") + f" {len(studies)} {study_label}"

        self.title(title)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self.text_box_width = 800
        self.text_box_height = 400 if len(studies) > 3 else 200
        self._create_widgets()
        self.wait_visibility()
        self.grab_set()
        self.after(250, self._start_worker)

    def _create_widgets(self) -> None:
        pad = 10
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nswe")
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=self._sub_title).grid(row=0, column=0, padx=pad, pady=pad, sticky="nw")

        self._progressbar = ctk.CTkProgressBar(frame)
        self._progressbar.grid(row=1, column=0, padx=pad, sticky="ew")
        self._progressbar.set(0)

        self._progress_label = ctk.CTkLabel(frame, text="")
        self._progress_label.grid(row=2, column=0, padx=pad, pady=(0, pad), sticky="nw")

        self._text_box = ctk.CTkTextbox(
            frame,
            border_width=1,
            width=self.text_box_width,
            height=self.text_box_height,
            wrap="none",
        )
        self._text_box.grid(row=3, column=0, padx=pad, pady=(0, pad), sticky="nswe")

        self._cancel_button = ctk.CTkButton(frame, text=_("Cancel"), command=self._on_cancel)
        self._cancel_button.grid(row=4, column=0, padx=pad, pady=(0, pad), sticky="e")

    def _format_outcome_line(self, outcome: HarmonizeApplyOutcome) -> str:
        label = outcome.series_path.name
        if outcome.status == "ok":
            return f"{label} => OK\n"
        if outcome.status == "skipped":
            reason = outcome.message or "skipped"
            return f"{label} => SKIPPED ({reason})\n"
        reason = outcome.message or "failed"
        return f"{label} => FAILED ({reason})\n"

    def _append_log(self, text: str) -> None:
        if self._text_box.yview()[1] == 1.0:
            self._text_box.see(tk.END)
            self._text_box.yview_moveto(1.0)
        self._text_box.insert(tk.END, text)

    def _start_worker(self) -> None:
        if not self._studies:
            self._append_log(_("No CT series found for selected studies.") + "\n")
            self._finish_dialog()
            return

        threading.Thread(
            target=self._harmonize_worker,
            name="HarmonizeStudiesWorker",
            daemon=True,
        ).start()
        self._schedule_poll()

    def _harmonize_worker(self) -> None:
        try:

            def on_progress(series_index: int, total: int, message: str, fraction: float) -> None:
                self._worker_queue.put(
                    (
                        "progress",
                        (series_index, total, message, fraction),
                    )
                )

            def on_outcome(outcome: HarmonizeApplyOutcome) -> None:
                self._worker_queue.put(("log", outcome))

            summary = self._controller.harmonize_studies(
                self._studies,
                progress=on_progress,
                cancelled=lambda: self._cancelled,
                on_outcome=on_outcome,
            )
            self._worker_queue.put(("done", summary))
        except Exception as exc:
            logger.exception("Harmonize studies worker failed")
            self._worker_queue.put(("error", exc))

    def _schedule_poll(self) -> None:
        if self._closing:
            return
        self._poll_after_id = self.after(self.POLL_MS, self._poll_worker)

    def _poll_worker(self) -> None:
        self._poll_after_id = None
        if self._closing or not self.winfo_exists():
            return

        while True:
            try:
                kind, payload = self._worker_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                _series_index, _total, message, fraction = payload  # type: ignore[misc]
                self._progress_label.configure(text=message)
                self._progressbar.set(min(1.0, max(0.0, fraction)))
            elif kind == "log":
                self._append_log(self._format_outcome_line(payload))  # type: ignore[arg-type]
            elif kind == "done":
                self._summary = payload  # type: ignore[assignment]
                self._finish_dialog()
                return
            elif kind == "error":
                self._append_log(f"ERROR: {payload}\n")
                self._finish_dialog()
                return

        self._schedule_poll()

    def _finish_dialog(self) -> None:
        if self._summary is not None and self._summary.cancelled:
            self._append_log(_("Harmonize cancelled.") + "\n")
        elif self._summary is not None:
            self._append_log(
                _("Complete")
                + f": {self._summary.applied} "
                + _("applied")
                + f", {self._summary.skipped} "
                + _("skipped")
                + f", {self._summary.failed} "
                + _("failed")
                + ".\n"
            )
        self._progressbar.set(1.0)
        self._text_box.configure(state="disabled")
        self._cancel_button.configure(text=_("Close"), command=self._on_close)

    def _escape_keypress(self, _event) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        if self._summary is not None or self._text_box.cget("state") == "disabled":
            self._on_close()
            return
        self._cancelled = True
        self._progress_label.configure(text=_("Cancelling after current series") + "…")

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._cancelled = True
        if self._poll_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self.destroy()

    def get_input(self) -> HarmonizeStudiesSummary | None:
        self.focus()
        self.master.wait_window(self)
        return self._summary
