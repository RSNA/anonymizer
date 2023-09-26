from typing import Union
import customtkinter as ctk
import string
import logging
from controller.project import DICOMNode
from utils.translate import _
from utils.network import get_local_ip_addresses

from utils.ux_fields import (
    str_entry,
    int_entry,
    ip_min_chars,
    ip_max_chars,
    aet_max_chars,
    aet_min_chars,
    ip_port_max,
    ip_port_min,
)

logger = logging.getLogger(__name__)


class DICOMNodeDialog(ctk.CTkToplevel):
    def __init__(
        self,
        address: DICOMNode,
        title: str = _("DICOM Node"),
    ):
        super().__init__()
        self.address = address
        self.title(title)
        self.lift()  # lift window on top
        self.attributes("-topmost", True)  # stay on top
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(False, False)
        self.grab_set()  # make dialog modal
        self._user_input: Union[DICOMNode, None] = None
        self._create_widgets()

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.info(f"Font Character Width in pixels: ±{char_width_px}")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        row = 0

        if self.address.local:
            local_ips = get_local_ip_addresses()
            if local_ips:
                logger.info(f"Local IP addresses: {local_ips}")
            else:
                local_ips = [_("No local IP addresses found.")]
                logger.error(local_ips[0])

            scp_label = ctk.CTkLabel(self, text=_("Address:"))
            scp_label.grid(row=0, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

            self.ip_var = ctk.StringVar(self, value=self.address.ip)
            local_ips_optionmenu = ctk.CTkOptionMenu(
                self,
                dynamic_resizing=False,
                values=local_ips,
                variable=self.ip_var,
            )
            local_ips_optionmenu.grid(
                row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw"
            )
        else:
            # TODO: allow domain names & DNS lookup
            self.ip_var = str_entry(
                view=self,
                label=_("Address:"),
                initial_value=self.address.ip,
                min_chars=ip_min_chars,
                max_chars=ip_max_chars,
                charset=string.digits + ".",
                tooltipmsg=None,
                row=row,
                col=0,
                pad=PAD,
                sticky="nw",
            )

        row += 1

        self.port_var = int_entry(
            view=self,
            label=_("Port:"),
            initial_value=self.address.port,
            min=ip_port_min,
            max=ip_port_max,
            tooltipmsg=None,
            row=row,
            col=0,
            pad=PAD,
            sticky="nw",
        )

        row += 1

        self.aet_var = str_entry(
            view=self,
            label=_("AE Title:"),
            initial_value=self.address.aet,
            min_chars=aet_min_chars,
            max_chars=aet_max_chars,
            charset=string.printable,
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

    def _ok_event(self, event=None):
        self._user_input = DICOMNode(
            self.ip_var.get(),
            self.port_var.get(),
            self.aet_var.get(),
            self.address.local,
        )
        self.grab_release()
        self.destroy()

    def _on_cancel(self):
        self.grab_release()
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self._user_input
