import logging
import tkinter as tk
from tkinter import messagebox
from typing import Union

import customtkinter as ctk

from anonymizer.model.project import LoggingLevels
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class LoggingLevelsDialog(tk.Toplevel):
    """
    A dialog window for selecting logging levels.

    Args:
        parent: The parent window.
        levels: An instance of LoggingLevels class.

    Attributes:
        level_options (list): A list of available logging level options.
        _user_input (LoggingLevels or None): The user-selected logging levels.

    Methods:
        level_to_option(level: int) -> str: Converts a logging level to its corresponding option.
        option_to_level(option: str) -> int: Converts an option to its corresponding logging level.
        _create_widgets(): Creates the widgets for the dialog window.
        _pydicom_debug_event(): Event handler for the pydicom debug switch.
        _enter_keypress(event): Event handler for the Enter key press.
        _ok_event(event): Event handler for the Ok button click.
        _escape_keypress(event): Event handler for the Escape key press.
        _on_cancel(): Event handler for canceling the dialog.
        get_input() -> LoggingLevels: Gets the user-selected logging levels.

    """

    level_options = ["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]

    def level_to_option(self, level: int) -> str:
        """
        Converts a logging level to its corresponding option.

        Args:
            level: The logging level.

        Returns:
            str: The corresponding option.

        Raises:
            ValueError: If the logging level is invalid.
        """
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
        """
        Converts an option to its corresponding logging level.

        Args:
            option: The option.

        Returns:
            int: The corresponding logging level.

        Raises:
            ValueError: If the option is invalid.
        """
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
    ):
        super().__init__(master=parent)
        self.levels = levels
        self.title(_("Logging Levels"))
        self.resizable(False, False)
        self._user_input: Union[LoggingLevels, None] = None
        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()  # make dialog modal
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    def _create_widgets(self):
        logger.debug("_create_widgets")
        PAD = 10

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        anonymizer_label = ctk.CTkLabel(self, text="Anonymizer Level:")
        anonymizer_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.anonymizer_level_var = ctk.StringVar(value=self.level_to_option(self.levels.anonymizer))
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

        self.pynetdicom_level_var = ctk.StringVar(value=self.level_to_option(self.levels.pynetdicom))
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

        sql_dbg_label = ctk.CTkLabel(self, text="SQLAlchemy Debug:")
        sql_dbg_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.sql_debug_var = ctk.BooleanVar(value=self.levels.sql)
        self.sql_debug = ctk.CTkSwitch(
            self,
            text="",
            variable=self.sql_debug_var,
            onvalue=True,
            offvalue=False,
            # command=self._sql_debug_event,
        )
        self.sql_debug.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        row += 1

        store_incoming_label = ctk.CTkLabel(self, text="Store incoming DICOM in private/source:")
        store_incoming_label.grid(row=row, column=0, padx=PAD, pady=PAD, sticky="w")

        self.store_incoming_var = ctk.BooleanVar(value=self.levels.store_dicom_source)
        self.store_incoming = ctk.CTkSwitch(
            self,
            text="",
            variable=self.store_incoming_var,
            onvalue=True,
            offvalue=False,
            # command=self._sql_debug_event,
        )
        self.store_incoming.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="w",
        )

        row += 1

        self._ok_button = ctk.CTkButton(self, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _pydicom_debug_event(self):
        logger.info("_pydicom_debug_event")
        if self.pydicom_debug_var.get():
            if not messagebox.askyesno(
                title=_("Warning"),
                message=_("Enabling debug mode in pydicom will cause PHI to be written to the log file.")
                + _(
                    "All incoming datasets, via network or file import, will also be written to the private subdirectory of storage folder."
                )
                + "\n\n"
                + _("Are you sure you want to enable pydicom debug mode?"),
            ):
                self.pydicom_debug_var.set(False)

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._ok_button.focus_set()
        self._user_input = LoggingLevels(
            anonymizer=self.option_to_level(self.anonymizer_level_var.get()),
            pynetdicom=self.option_to_level(self.pynetdicom_level_var.get()),
            pydicom=self.pydicom_debug_var.get(),
            sql=self.sql_debug_var.get(),
            store_dicom_source=self.store_incoming_var.get(),
        )
        self.grab_release()
        self.destroy()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        """
        Gets the user-selected logging levels.

        Returns:
            LoggingLevels: The user-selected logging levels.
        """
        self.focus()
        self.master.wait_window(self)
        return self._user_input
