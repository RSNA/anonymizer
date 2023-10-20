from typing import Union
import customtkinter as ctk
import logging
from model.project import NetworkTimeouts
from utils.translate import _
from utils.ux_fields import int_entry

logger = logging.getLogger(__name__)


class NetworkTimeoutsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        timeouts: NetworkTimeouts,
        title: str = _("Network Timeouts in SECONDS"),
    ):
        super().__init__()
        self.timeouts = timeouts
        self.title(title)
        self.lift()  # lift window on top
        self.attributes("-topmost", True)  # stay on top
        # self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[NetworkTimeouts, None] = None
        self._create_widgets()
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)

    def _create_widgets(self):
        logger.debug(f"_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.debug(f"Font Character Width in pixels: ±{char_width_px}")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        self.connection_var = int_entry(
            view=self,
            label=_("TCP Connection:"),
            initial_value=int(self.timeouts.tcp_connection),
            min=0,
            max=60,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
            focus_set=True,
        )

        row += 1

        self.acse_var = int_entry(
            view=self,
            label=_("DICOM Association Messages (ACSE):"),
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
            view=self,
            label=_("DICOM Service Element Messages (DIMSE):"),
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
            view=self,
            label=_("Close Inactive Connection:"),
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

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
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
        logger.info(f"_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._user_input
