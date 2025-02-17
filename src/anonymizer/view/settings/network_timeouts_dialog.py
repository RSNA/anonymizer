import logging
import tkinter as tk
from typing import Union

import customtkinter as ctk

from anonymizer.model.project import NetworkTimeouts
from anonymizer.utils.translate import _
from anonymizer.view.ux_fields import int_entry

logger = logging.getLogger(__name__)


class NetworkTimeoutsDialog(tk.Toplevel):
    """
    A dialog window for configuring network timeouts.

    Args:
        parent: The parent widget.
        timeouts: An instance of NetworkTimeouts containing the initial timeout values.

    Attributes:
        timeouts (NetworkTimeouts): The network timeouts.
        _user_input (Union[NetworkTimeouts, None]): The user input for network timeouts.

    Methods:
        _create_widgets: Create the widgets for the dialog.
        _enter_keypress: Event handler for the Enter key press.
        _ok_event: Event handler for the OK button click.
        _escape_keypress: Event handler for the Escape key press.
        _on_cancel: Event handler for the Cancel button click.
        get_input: Get the user input for network timeouts.

    """

    def __init__(
        self,
        parent,
        timeouts: NetworkTimeouts,
    ):
        super().__init__(master=parent)
        self.timeouts = timeouts
        self.title(_("Network Timeouts in SECONDS"))
        self.resizable(False, False)
        self._user_input: Union[NetworkTimeouts, None] = None
        self._create_widgets()
        self.wait_visibility()
        self.lift()
        self.grab_set()  # make dialog modal
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    def _create_widgets(self):
        logger.debug("_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.debug(f"Font Character Width in pixels: ±{char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        self.connection_var = int_entry(
            view=self._frame,
            label=_("TCP Connection") + ":",
            initial_value=int(self.timeouts.tcp_connection),
            min=0,
            max=15,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            focus_set=True,
        )

        row += 1

        self.acse_var = int_entry(
            view=self._frame,
            label=_("DICOM Association Messages (ACSE)") + ":",
            initial_value=int(self.timeouts.acse),
            min=0,
            max=120,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.dimse_var = int_entry(
            view=self._frame,
            label=_("DICOM Service Element Messages (DIMSE)") + ":",
            initial_value=int(self.timeouts.dimse),
            min=0,
            max=120,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.network_var = int_entry(
            view=self._frame,
            label=_("Network (Close Inactive Connection)") + ":",
            initial_value=int(self.timeouts.network),
            min=0,
            max=600,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self._ok_button = ctk.CTkButton(self._frame, width=100, text=_("Ok"), command=self._ok_event)
        self._ok_button.grid(
            row=row,
            column=1,
            padx=PAD,
            pady=PAD,
            sticky="e",
        )

    def _enter_keypress(self, event):
        logger.info("_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._ok_button.focus_set()
        self._user_input = NetworkTimeouts(
            self.connection_var.get(),
            self.acse_var.get(),
            self.dimse_var.get(),
            self.network_var.get(),
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
        self.focus()
        self.master.wait_window(self)
        return self._user_input
