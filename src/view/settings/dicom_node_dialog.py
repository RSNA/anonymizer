from typing import Union
import tkinter as tk
import customtkinter as ctk
import string
import logging
from model.project import DICOMNode
from utils.translate import _
from utils.network import get_local_ip_addresses, dns_lookup

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


class DICOMNodeDialog(tk.Toplevel):
    # class DICOMNodeDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        address: DICOMNode,
        title: str = _("DICOM Node"),
    ):
        super().__init__(master=parent)
        self.address = address
        self.title(title)
        self.resizable(False, False)
        self._user_input: Union[DICOMNode, None] = None
        self.bind("<Return>", self._enter_keypress)
        self.bind("<Escape>", self._escape_keypress)
        self._create_widgets()
        self.wait_visibility()
        self.grab_set()  # make dialog modal

    def _create_widgets(self):
        logger.debug(f"_create_widgets")
        PAD = 10

        char_width_px = ctk.CTkFont().measure("A")
        logger.debug(f"Font Character Width in pixels: ±{char_width_px}")

        self._frame = ctk.CTkFrame(self)
        self._frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

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

            scp_label = ctk.CTkLabel(self._frame, text=_("Address:"))
            scp_label.grid(row=0, column=0, padx=PAD, pady=(PAD, 0), sticky="nw")

            self.ip_var = ctk.StringVar(self._frame, value=self.address.ip)
            local_ips_optionmenu = ctk.CTkOptionMenu(
                self._frame,
                dynamic_resizing=False,
                values=local_ips,
                variable=self.ip_var,
            )
            local_ips_optionmenu.grid(row=row, column=1, padx=PAD, pady=(PAD, 0), sticky="nw")
            local_ips_optionmenu.focus_set()
        else:
            self.domain_name_var = str_entry(
                view=self._frame,
                label=_("Domain Name:"),
                initial_value="",
                min_chars=3,
                max_chars=30,
                charset=string.digits + ".-" + string.ascii_lowercase + string.ascii_uppercase,
                tooltipmsg=None,
                row=row,
                col=0,
                pad=PAD,
                sticky="nw",
                focus_set=True,
            )

            row += 1

            self._dns_lookup_button = ctk.CTkButton(
                self._frame, width=100, text=_("DNS Lookup"), command=self._dns_lookup_event
            )
            self._dns_lookup_button.grid(
                row=row,
                column=1,
                padx=PAD,
                pady=PAD,
                sticky="w",
            )

            row += 1

            self.ip_var = str_entry(
                view=self._frame,
                label=_("IP Address:"),
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
            view=self._frame,
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
            view=self._frame,
            label=_("AE Title:"),
            initial_value=self.address.aet,
            min_chars=aet_min_chars,
            max_chars=aet_max_chars,
            charset=string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|",
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

    def _dns_lookup_event(self, event=None):
        self.ip_var.set(dns_lookup(self.domain_name_var.get()))

    def _enter_keypress(self, event):
        logger.info(f"_enter_pressed")
        self._ok_event()

    def _ok_event(self, event=None):
        self._user_input = DICOMNode(
            self.ip_var.get(),
            int(self.port_var.get()),
            self.aet_var.get(),
            self.address.local,
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
