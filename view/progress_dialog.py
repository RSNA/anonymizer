from re import sub
from typing import Dict, Union
from queue import Queue
import customtkinter as ctk
from tkinter import ttk
import logging
from utils.translate import _

logger = logging.getLogger(__name__)


class ProgressDialog(ctk.CTkToplevel):
    progress_update_interval = 300

    def __init__(
        self,
        Q_to_monitor: Queue,
        title: str = _("Progress Dialog"),
        sub_title: str = _("Please wait..."),
    ):
        super().__init__()
        self._Q_to_monitor = Q_to_monitor
        # latch items in queue for progress bar max value
        self._maxQ = Q_to_monitor.qsize()
        if self._maxQ == 0:
            self._maxQ = 1
        self.title(title)
        self._sub_title = sub_title
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)
        # self.grab_set()  # make dialog modal
        self._user_input: Union[list, None] = None
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self._create_widgets()
        self.bind("<Escape>", self._escape_keypress)
        self._update_progress()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10

        self._sub_title_label = ctk.CTkLabel(self, text=_(self._sub_title))
        self._sub_title_label.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="w")

        self._progressbar = ctk.CTkProgressBar(self)
        self._progressbar.grid(
            row=1,
            column=0,
            padx=(PAD, 2 * PAD),
            pady=(PAD, 0),
            sticky="ew",
        )

        self._progressbar.set(0)

        self._progress_label = ctk.CTkLabel(self, text=f"Process 0 of {self._maxQ}")
        self._progress_label.grid(row=2, column=0, padx=PAD, pady=(0, PAD), sticky="w")

        self._cancel_button = ctk.CTkButton(
            self, text=_("Cancel"), command=self._on_cancel
        )
        self._cancel_button.grid(
            row=3,
            column=0,
            padx=PAD,
            pady=(0, PAD),
            sticky="e",
        )

    def _update_progress(self):
        self._last_qsize = self._Q_to_monitor.qsize()

        if self._last_qsize == 0:
            logger.info(f"Q is empty, progress bar exit")
            self._progressbar.set(1)
            self.grab_release()
            self.destroy()
            return

        current_ndx = self._maxQ - self._last_qsize
        self._progressbar.set(current_ndx / self._maxQ)
        self._progress_label.configure(text=f"Processing {current_ndx} of {self._maxQ}")
        self.after(self.progress_update_interval, self._update_progress)

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info(
            f"_on_cancel {self._Q_to_monitor.qsize()} remain in Q, clearing Q..."
        )
        # dump all items in queue to clear it
        # TODO: #5 if this is an Import operation it is possible than unsolicited C-STORE-RQ will be lost
        while not self._Q_to_monitor.empty():
            self._Q_to_monitor.get()
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._last_qsize
