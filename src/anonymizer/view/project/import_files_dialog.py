import contextlib
import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Union

import customtkinter as ctk

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel

logger = logging.getLogger(__name__)


class ImportFilesDialog(AppToplevel):
    """
    A dialog window for importing files and performing anonymization.

    File anonymization runs on a background thread so the Tk main loop stays
    responsive and a second file dialog cannot be opened re-entrantly.
    """

    POLL_MS = 100

    def __init__(
        self,
        parent,
        controller: AnonymizerController,
        paths: list[str] | tuple[str, ...],
    ) -> None:
        super().__init__(master=parent)
        title = _("Import Files")
        sub_title = _("Importing") + f" {len(paths)} {_('file') if len(paths) == 1 else _('files')}"

        self.title(title)
        self._sub_title: str = sub_title
        self._data_font = parent.mono_font
        self._controller: AnonymizerController = controller
        self._paths: list[str] | tuple[str, ...] = paths
        self._cancelled = False
        self._closing = False
        self._worker_done = False
        self._scrolled_to_bottom = False
        self.files_processed = 0
        self._worker_queue: queue.Queue = queue.Queue()
        self._poll_after_id: str | None = None

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.text_box_width = 800
        if len(self._paths) > 10:
            self.text_box_height = 400
        else:
            self.text_box_height = 200
        self.resizable(True, True)
        self._user_input: Union[list, None] = None
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self.wait_visibility()
        self.grab_set()
        self.after(250, self._start_worker)

    def _create_widgets(self) -> None:
        logger.info("_create_widgets")
        PAD = 10

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")
        self._frame.rowconfigure(3, weight=1)
        self._frame.columnconfigure(0, weight=1)

        row = 0

        self._sub_title_label = ctk.CTkLabel(self._frame, text=self._sub_title)
        self._sub_title_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="nw")

        row += 1

        self._progressbar = ctk.CTkProgressBar(self._frame)
        self._progressbar.grid(
            row=row,
            column=0,
            padx=PAD,
            sticky="ew",
        )

        row += 1

        self._progressbar.set(0)

        self._progress_label = ctk.CTkLabel(self._frame, text="", font=self._data_font)
        self._progress_label.grid(row=row, column=0, padx=PAD, pady=(0, PAD), sticky="nw")

        row += 1

        self._text_box = ctk.CTkTextbox(
            self._frame,
            border_width=1,
            width=self.text_box_width,
            height=self.text_box_height,
            wrap="none",
            font=self._data_font,
        )

        self._text_box.grid(row=row, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")

        row += 1

        self._cancel_button = ctk.CTkButton(self._frame, text=_("Cancel"), command=self._on_cancel)
        self._cancel_button.grid(
            row=row,
            column=0,
            padx=PAD,
            pady=(0, PAD),
            sticky="e",
        )

    def _start_worker(self) -> None:
        self._text_box.focus_set()
        thread = threading.Thread(
            target=self._import_worker,
            name="ImportFilesWorker",
            daemon=True,
        )
        thread.start()
        self._schedule_poll()

    def _import_worker(self) -> None:
        files_to_process = len(self._paths)
        try:
            for path in self._paths:
                if self._cancelled:
                    break

                file_index = self.files_processed + 1
                parts = path.split(os.sep)
                if len(parts) > 2:
                    abridged_path = f"{file_index}: .../{parts[-3]}/{parts[-2]}/{parts[-1]}"
                else:
                    abridged_path = f"{file_index}: {path}"

                error_msg, ds = self._controller.anonymize_file(Path(path))
                self.files_processed += 1
                self._worker_queue.put(
                    (
                        "file",
                        (
                            abridged_path,
                            error_msg,
                            str(ds.PatientID) if ds and hasattr(ds, "PatientID") else None,
                            file_index,
                            files_to_process,
                        ),
                    )
                )
            self._worker_queue.put(("done", self.files_processed))
        except Exception as exc:
            logger.exception("Import files worker failed")
            self._worker_queue.put(("error", str(exc)))

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

            if kind == "file":
                abridged_path, error_msg, patient_id, file_index, files_to_process = payload
                if self._text_box.yview()[1] == 1.0:
                    self._text_box.see(tk.END)
                    self._text_box.yview_moveto(1.0)
                self._progress_label.configure(
                    text=_("Processing") + f" {file_index} " + _("of") + f" {files_to_process}"
                )
                if error_msg:
                    self._text_box.insert(tk.END, f"{abridged_path}\n=> {error_msg}\n")
                elif patient_id:
                    self._text_box.insert(tk.END, f"{abridged_path} => {patient_id}\n")
                else:
                    self._text_box.insert(tk.END, f"{abridged_path} => [No Dataset]\n")
                self._progressbar.set(file_index / files_to_process)
            elif kind == "done":
                self._finish_dialog()
                return
            elif kind == "error":
                self._text_box.insert(tk.END, _("ERROR") + f": {payload}\n")
                self._finish_dialog()
                return

        self._schedule_poll()

    def _finish_dialog(self) -> None:
        self._worker_done = True
        self._progressbar.set(1.0 if self.files_processed else 0.0)
        self._text_box.configure(state="disabled")
        self._cancel_button.configure(text=_("Close"), command=self._on_close)

    def _escape_keypress(self, event) -> None:
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self) -> None:
        if self._worker_done:
            self._on_close()
            return
        self._cancelled = True
        self._progress_label.configure(text=_("Cancelling after current file") + "…")

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
        teardown_ctk_toplevel(self, parent=self.master)

    def get_input(self) -> int:
        self.focus()
        self.master.wait_window(self)
        return self.files_processed
