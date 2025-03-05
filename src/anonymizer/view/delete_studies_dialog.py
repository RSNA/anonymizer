import logging
import tkinter as tk
from typing import Union

import customtkinter as ctk

from anonymizer.controller.project import ProjectController
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class DeleteStudiesDialog(tk.Toplevel):
    """
    A dialog window for deleting studies from AnonymizerModel and removing associated files from disk.

    Args:
        parent: The parent widget.
        controller (ProjectController): The project controller
        studies (list[tuple[str, str]): List of tuples: (Anonymized Patient ID, Anonymizded Study UID) identifying studies to delete

    Attributes:
        _sub_title (str): The sub-title of the dialog.
        _controller (AnonymizerController): The controller for the anonymizer.
        _studies (list[tuple[str, str]): The studies to delete.
        _cancelled (bool): Flag indicating if the import was cancelled.
        _scrolled_to_bottom (bool): Flag indicating if the text box is scrolled to the bottom.
        studies_processed (int): The number of files processed.
    """

    def __init__(
        self,
        parent,
        controller: ProjectController,
        studies: list[tuple[str, str]],
    ) -> None:
        super().__init__(master=parent)
        title = _("Delete Studies")
        sub_title = _("Deleting") + f" {len(studies)} {_('study') if len(studies) == 1 else _('studies')}"

        self.title(title)
        self._sub_title: str = sub_title
        self._controller: ProjectController = controller
        self._studies: list[tuple[str, str]] = studies
        self._cancelled = False
        self._scrolled_to_bottom = False
        self.studies_processed = 0

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.text_box_width = 800
        if len(self._studies) > 10:
            self.text_box_height = 400
        else:
            self.text_box_height = 200
        self.resizable(True, True)
        self._user_input: Union[list, None] = None
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self.wait_visibility()
        self.grab_set()  # make dialog modal
        self.after(250, self._delete_studies)

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

        self._progress_label = ctk.CTkLabel(self._frame, text="")
        self._progress_label.grid(row=row, column=0, padx=PAD, pady=(0, PAD), sticky="nw")

        row += 1

        self._text_box = ctk.CTkTextbox(
            self._frame, border_width=1, width=self.text_box_width, height=self.text_box_height, wrap="none"
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

    def _delete_studies(self) -> None:
        """
        Delete the studies.
        """
        logger.info("_delete_studies")

        studies_to_process: int = len(self._studies)
        self._text_box.focus_set()

        for row, study in enumerate(self._studies):
            if self._cancelled:
                return

            # If user has scrolled to the bottom, keep it there
            if self._text_box.yview()[1] == 1.0:
                self._text_box.see(tk.END)
                self._text_box.yview_moveto(1.0)

            self._progress_label.configure(text=_("Deleting") + f" {row} " + _("of") + f" {studies_to_process}")

            if self._controller.delete_study(*study):
                self._text_box.insert(tk.END, f"{study} => OK\n")
            else:
                self._text_box.insert(tk.END, f"{study} => FAILED\n")

            self.studies_processed += 1
            self._progressbar.set(self.studies_processed / studies_to_process)
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
        return self.studies_processed
