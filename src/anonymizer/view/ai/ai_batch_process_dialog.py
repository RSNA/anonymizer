"""AI batch process progress dialog for PHI Index study selection."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from anonymizer.controller.ai.tseg.config import BATCH_MEMORY_POLL_INTERVAL_SEC
from anonymizer.controller.ai_batch_process import (
    AiBatchAlgorithm,
    AiBatchProcessOptions,
    AiBatchSummary,
    count_pending_series,
    enumerate_series_for_studies,
    format_ai_batch_completion_summary,
    format_ai_batch_phase_label,
    normalize_selected_algorithms,
)
from anonymizer.controller.project import ProjectController
from anonymizer.controller.work_state import WorkState
from anonymizer.utils.memory import (
    MemoryGuard,
    MemorySnapshot,
    capture_memory_snapshot,
    estimate_batch_resources,
    format_memory_snapshot_label,
)
from anonymizer.utils.translate import _
from anonymizer.view.job_poller import BATCH_POLL_MS, JobPoller

logger = logging.getLogger(__name__)


def _memory_label_color(snapshot: MemorySnapshot) -> str | None:
    guard = MemoryGuard()
    pressure = guard.check(snapshot)
    if pressure == "abort":
        return "#CC3333"
    if pressure == "warn":
        return "#CC8800"
    return None


class AiBatchProcessDialog(tk.Toplevel):
    """Modal dialog that runs selected AI algorithms in a background thread."""

    POLL_MS = BATCH_POLL_MS

    def __init__(
        self,
        parent,
        controller: ProjectController,
        studies: list[tuple[str, str]],
        options: AiBatchProcessOptions,
    ) -> None:
        super().__init__(master=parent)
        self._controller = controller
        self._studies = studies
        self._batch_options = options
        self._cancelled = False
        self._closing = False
        self._summary: AiBatchSummary | None = None
        self._work_state = WorkState()
        self._worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._poll_after_id: str | None = None
        self._memory_poll_stop = threading.Event()
        self._job_poller: JobPoller | None = None
        self._batch_fraction = 0.0
        self._batch_phase = ""

        algorithms = normalize_selected_algorithms(options.algorithms)
        series_count = len(enumerate_series_for_studies(controller.model.images_dir(), studies))
        study_label = _("study") if len(studies) == 1 else _("studies")
        series_label = _("series") if series_count == 1 else _("series")
        algo_label = _("algorithm") if len(algorithms) == 1 else _("algorithms")
        self._sub_title = (
            _("Processing")
            + f" {len(studies)} {study_label}, "
            + f"{series_count} {series_label}, "
            + f"{len(algorithms)} {algo_label}"
        )

        self.title(_("AI Batch Process"))
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self.text_box_width = 800
        self.text_box_height = 300
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
        frame.rowconfigure(5, weight=1)
        frame.columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=self._sub_title, anchor="w").grid(
            row=0,
            column=0,
            padx=pad,
            pady=(pad, pad),
            sticky="ew",
        )

        self._progressbar = ctk.CTkProgressBar(frame)
        self._progressbar.grid(row=1, column=0, padx=pad, sticky="ew")
        self._progressbar.set(0)

        self._phase_label = ctk.CTkLabel(frame, text="", anchor="w")
        self._phase_label.grid(row=2, column=0, padx=pad, pady=(0, 2), sticky="ew")

        self._progress_label = ctk.CTkLabel(frame, text="", anchor="w")
        self._progress_label.grid(row=3, column=0, padx=pad, pady=(0, pad), sticky="ew")

        self._memory_label = ctk.CTkLabel(frame, text="", anchor="w")
        self._memory_label.grid(row=4, column=0, padx=pad, pady=(0, pad), sticky="ew")
        self._update_memory_label(capture_memory_snapshot())

        self._text_box = ctk.CTkTextbox(
            frame,
            border_width=1,
            width=self.text_box_width,
            height=self.text_box_height,
            wrap="none",
        )
        self._text_box.grid(row=5, column=0, padx=pad, pady=(0, pad), sticky="nswe")

        self._cancel_button = ctk.CTkButton(frame, text=_("Cancel"), command=self._on_cancel)
        self._cancel_button.grid(row=6, column=0, padx=pad, pady=(0, pad), sticky="e")

    def _update_memory_label(self, snapshot: MemorySnapshot | None) -> None:
        if snapshot is None:
            self._memory_label.configure(text=_("Memory available") + ": —")
            return
        color = _memory_label_color(snapshot)
        kwargs: dict = {"text": format_memory_snapshot_label(snapshot)}
        if color is not None:
            kwargs["text_color"] = color
        self._memory_label.configure(**kwargs)

    def _append_log(self, text: str) -> None:
        self._text_box.insert(tk.END, text)
        self._text_box.see(tk.END)

    def _confirm_memory_preflight(self) -> bool:
        algorithms = normalize_selected_algorithms(self._batch_options.algorithms)
        series_items = enumerate_series_for_studies(self._controller.model.images_dir(), self._studies)
        pending_counts = count_pending_series(
            series_items,
            self._controller.anonymizer.model,
            algorithms,
        )
        pending_total = max(pending_counts.values(), default=0)
        estimate = estimate_batch_resources(
            includes_pixel_phi=AiBatchAlgorithm.REMOVE_PIXEL_PHI in algorithms
            and pending_counts.get(AiBatchAlgorithm.REMOVE_PIXEL_PHI, 0) > 0,
            includes_harmonize=AiBatchAlgorithm.HARMONIZE in algorithms
            and pending_counts.get(AiBatchAlgorithm.HARMONIZE, 0) > 0,
            includes_face_blur=AiBatchAlgorithm.FACE_BLUR in algorithms
            and pending_counts.get(AiBatchAlgorithm.FACE_BLUR, 0) > 0,
        )
        snapshot = capture_memory_snapshot()
        if snapshot is None or pending_total == 0:
            return True
        if snapshot.available_mb >= estimate.min_available_mb:
            return True
        available_gb = snapshot.available_mb / 1024
        required_gb = estimate.min_available_mb / 1024
        critical = snapshot.available_mb < estimate.min_available_mb * 0.5
        message = (
            estimate.notes
            + f"\n\n{_('Available memory')}: {available_gb:.1f} GB\n"
            + f"{_('Recommended')}: {required_gb:.1f} GB\n\n"
            + _("Continue anyway?")
        )
        if critical:
            return messagebox.askyesno(
                _("Insufficient memory"),
                message,
                icon="warning",
                parent=self,
            )
        return messagebox.askyesno(
            _("Low memory warning"),
            message,
            icon="warning",
            parent=self,
        )

    def _start_worker(self) -> None:
        algorithms = normalize_selected_algorithms(self._batch_options.algorithms)
        if not algorithms:
            self._append_log(_("No algorithms selected.") + "\n")
            self._finish_dialog()
            return
        if not self._confirm_memory_preflight():
            self._append_log(_("AI batch process cancelled before start.") + "\n")
            self._summary = AiBatchSummary(cancelled=True)
            self._finish_dialog()
            return

        threading.Thread(
            target=self._memory_poll_worker,
            name="AiBatchMemoryPoll",
            daemon=True,
        ).start()
        self._job_poller = JobPoller(
            self,
            self._work_state,
            on_tick=self._on_batch_tick,
            on_done=self._on_batch_done,
            poll_ms=self.POLL_MS,
        )
        self._job_poller.start()
        threading.Thread(
            target=self._batch_worker,
            name="AiBatchProcessWorker",
            daemon=True,
        ).start()

    def _on_batch_tick(self, work_state: WorkState) -> None:
        for line in work_state.drain_logs():
            self._append_log(line)
        if work_state.status:
            self._progress_label.configure(text=work_state.status)
        while True:
            try:
                kind, payload = self._worker_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                algorithm, algorithm_index, algorithms_total, message, fraction = payload  # type: ignore[misc]
                self._batch_phase = format_ai_batch_phase_label(
                    algorithm,
                    algorithm_index=algorithm_index,
                    algorithms_total=algorithms_total,
                )
                self._batch_fraction = min(1.0, max(0.0, fraction))
                self._phase_label.configure(text=self._batch_phase)
                self._progress_label.configure(text=message)
                self._progressbar.set(self._batch_fraction)
            elif kind == "memory":
                self._update_memory_label(payload)  # type: ignore[arg-type]

    def _on_batch_done(self, _algorithm, work_state: WorkState) -> None:
        if work_state.error:
            self._append_log(_("ERROR") + f": {work_state.error}\n")
        if isinstance(work_state.result, AiBatchSummary):
            self._summary = work_state.result
        self._finish_dialog()

    def _memory_poll_worker(self) -> None:
        interval = max(0.5, float(BATCH_MEMORY_POLL_INTERVAL_SEC))
        while not self._memory_poll_stop.wait(interval):
            snapshot = capture_memory_snapshot()
            if snapshot is not None:
                self._worker_queue.put(("memory", snapshot))

    def _batch_worker(self) -> None:
        try:

            def on_progress(
                _series_index: int,
                _series_total: int,
                algorithm,
                algorithm_index: int,
                algorithms_total: int,
                message: str,
                fraction: float,
            ) -> None:
                self._worker_queue.put(
                    (
                        "progress",
                        (algorithm, algorithm_index, algorithms_total, message, fraction),
                    )
                )

            def on_log(message: str) -> None:
                self._worker_queue.put(("log", message))

            def on_memory(snapshot: MemorySnapshot) -> None:
                self._worker_queue.put(("memory", snapshot))

            summary = self._controller.ai_batch_process(
                self._studies,
                self._batch_options,
                progress=on_progress,
                cancelled=lambda: self._cancelled,
                on_log=on_log,
                memory_callback=on_memory,
                work_state=self._work_state,
            )
            if not self._work_state.done:
                self._work_state.finish(summary)
        except Exception as exc:
            logger.exception("AI batch process worker failed")
            if not self._work_state.done:
                self._work_state.fail(str(exc))
        finally:
            self._memory_poll_stop.set()

    def _finish_dialog(self) -> None:
        if self._summary is not None and self._summary.cancelled:
            self._append_log(_("AI batch process cancelled.") + "\n")
        elif self._summary is not None:
            self._append_log(format_ai_batch_completion_summary(self._summary) + "\n")
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
        self._work_state.request_cancel()
        self._progress_label.configure(text=_("Cancelling after current step") + "…")

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._cancelled = True
        self._memory_poll_stop.set()
        if self._poll_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        self.destroy()

    def get_input(self) -> AiBatchSummary | None:
        self.focus()
        self.master.wait_window(self)
        return self._summary
