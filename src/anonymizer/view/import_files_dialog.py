import logging
import os
import tkinter as tk
from pathlib import Path
from typing import Union

import customtkinter as ctk

from anonymizer.controller.anonymizer import AnonymizerController
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class ImportFilesDialog(tk.Toplevel):
    """
    A dialog window for importing files and performing anonymization.

    Args:
        parent: The parent widget.
        controller (AnonymizerController): The controller for the anonymizer.
        paths (list[str] | tuple[str, ...]): The paths of the files to import.

    Attributes:
        progress_update_interval (int): The interval in milliseconds for updating the progress.
        _sub_title (str): The sub-title of the dialog.
        _data_font: The font for displaying data.
        _controller (AnonymizerController): The controller for the anonymizer.
        _paths (list[str] | tuple[str, ...]): The paths of the files to import.
        _cancelled (bool): Flag indicating if the import was cancelled.
        _scrolled_to_bottom (bool): Flag indicating if the text box is scrolled to the bottom.
        files_processed (int): The number of files processed.
        text_box_width (int): The width of the text box.
        text_box_height (int): The height of the text box.
        _user_input (list | None): The user input.
    """

    def __init__(
        self,
        parent,
        controller: AnonymizerController,
        paths: list[str] | tuple[str, ...],
    ) -> None:
        """
        Initialize the ImportFilesDialog.

        Args:
            parent: The parent widget.
            controller (AnonymizerController): The controller for the anonymizer.
            paths (list[str] | tuple[str, ...]): The paths of the files to import.
        """
        super().__init__(master=parent)
        title = _("Import Files")
        sub_title = _("Importing") + f" {len(paths)} {_('file') if len(paths) == 1 else _('files')}"

        self.title(title)
        self._sub_title: str = sub_title
        self._data_font = parent.mono_font
        self._controller: AnonymizerController = controller
        self._paths: list[str] | tuple[str, ...] = paths
        self._cancelled = False
        self._scrolled_to_bottom = False
        self.files_processed = 0

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
        self.grab_set()  # make dialog modal
        self.after(250, self._anonymize_files)

    def _create_widgets(self) -> None:
        """
        Create the widgets for the dialog.
        """
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

    def _anonymize_files(self) -> None:
        """
        Anonymize the files.
        """
        logger.info("_anonymize_files")

        files_to_process: int = len(self._paths)
        self._text_box.focus_set()

        for path in self._paths:
            if self._cancelled:
                return

            file_index: int = self.files_processed + 1
            parts: list[str] = path.split(os.sep)
            if len(parts) > 2:
                abridged_path = f"{file_index}: .../{parts[-3]}/{parts[-2]}/{parts[-1]}"
            else:
                abridged_path = f"{file_index}: {path}"

            # If user has scrolled to the bottom, keep it there
            if self._text_box.yview()[1] == 1.0:
                self._text_box.see(tk.END)
                self._text_box.yview_moveto(1.0)

            self._progress_label.configure(text=_("Processing") + f" {file_index} " + _("of") + f" {files_to_process}")

            # TODO: Optimize using multiple file processing threads, either use Anonymizer queue
            # or split the files into chunks and process them in parallel:
            (error_msg, ds) = self._controller.anonymize_file(Path(path))

            if error_msg:
                self._text_box.insert(tk.END, f"{abridged_path}\n=> {error_msg}\n")
            else:
                self._text_box.insert(
                    tk.END,
                    (
                        f"{abridged_path} {self._controller.model.get_phi_by_phi_patient_id(ds.PatientID)} => {ds.PatientID}\n"
                        if ds
                        else f"{abridged_path} => [No Dataset]\n"
                    ),
                )

            self.files_processed += 1
            self._progressbar.set(self.files_processed / files_to_process)
            self.update()

        self._text_box.configure(state="disabled")
        self._cancel_button.configure(text=_("Close"))

    def _escape_keypress(self, event) -> None:
        """
        Handle the escape keypress event.
        """
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self) -> None:
        """
        Handle the cancel event.
        """
        self.grab_release()
        self.destroy()
        self._cancelled = True

    def get_input(self) -> int:
        """
        Get the user input.

        Returns:
            int: The number of files processed.
        """
        self.focus()
        self.master.wait_window(self)
        return self.files_processed
