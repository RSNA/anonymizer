from typing import Union
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import logging
from model.project import LoggingLevels
from utils.translate import _

logger = logging.getLogger(__name__)


class LoggingLevelsDialog(tk.Toplevel):
    # class LoggingLevelsDialog(ctk.CTkToplevel):
    level_options = ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]

    def level_to_option(self, level: int) -> str:
        if level == logging.DEBUG:
            return "DEBUG"
        elif level == logging.INFO:
            return "INFO"
        elif level == logging.WARN:
            return "WARN"
        elif level == logging.ERROR:
            return "ERROR"
        elif level == logging.CRITICAL:
            return "CRITICAL"
        else:
            raise ValueError(f"Invalid logging level: {level}")

    def option_to_level(self, option: str) -> int:
        if option == "DEBUG":
            return logging.DEBUG
        elif option == "INFO":
            return logging.INFO
        elif option == "WARN":
            return logging.WARN
        elif option == "ERROR":
            return logging.ERROR
        elif option == "CRITICAL":
            return logging.CRITICAL
        else:
            raise ValueError(f"Invalid option: {option}")

    def __init__(
        self,
        parent,
        levels: LoggingLevels,
        title: str = _("Logging Levels"),
    ):
        super().__init__(master=parent)
        self.levels = levels
        self.title(title)
        self.lift()
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[LoggingLevels, None] = None
        self._create_widgets()
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    def _create_widgets(self):
        logger.debug(f"_create_widgets")
        PAD = 10

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        anonymizer_label = ctk.CTkLabel(self, text="Anonymizer Level:")
        anonymizer_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.anonymizer_level_var = ctk.StringVar(
            value=self.level_to_option(self.levels.anonymizer)
        )
        self.anonymizer_level = ctk.CTkOptionMenu(
            self,
            values=self.level_options,
            variable=self.anonymizer_level_var,
        )
        self.anonymizer_level.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        row += 1

        pynetdicom_label = ctk.CTkLabel(self, text="PYNETDICOM Level:")
        pynetdicom_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.pynetdicom_level_var = ctk.StringVar(
            value=self.level_to_option(self.levels.pynetdicom)
        )
        self.pynetdicom_level = ctk.CTkOptionMenu(
            self,
            values=self.level_options,
            variable=self.pynetdicom_level_var,
        )
        self.pynetdicom_level.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        row += 1

        pynetdicom_label = ctk.CTkLabel(self, text="PYDICOM Debug:")
        pynetdicom_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.pydicom_debug_var = ctk.BooleanVar(value=self.levels.pydicom)
        self.pydicom_debug = ctk.CTkSwitch(
            self,
            text="",
            variable=self.pydicom_debug_var,
            onvalue=True,
            offvalue=False,
            command=self._pydicom_debug_event,
        )
        self.pydicom_debug.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        row += 1

        self._ok_button = ctk.CTkButton(
            self, width=100, text=_("Ok"), command=self._ok_event
        )
        self._ok_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _pydicom_debug_event(self):
        logger.info(f"_pydicom_debug_event")
        if self.pydicom_debug_var.get():
            if not messagebox.askyesno(
                _("Warning"),
                _(
                    "Enabling debug mode in pydicom will cause PHI to be written to the log file. "
                    "Are you sure you want to enable pydicom debug mode?"
                ),
            ):
                self.pydicom_debug_var.set(False)

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._ok_button.focus_set()
        self._user_input = LoggingLevels(
            self.option_to_level(self.anonymizer_level_var.get()),
            self.option_to_level(self.pynetdicom_level_var.get()),
            self.pydicom_debug_var.get(),
        )
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return self._user_input
