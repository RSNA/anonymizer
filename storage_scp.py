import tkinter as tk
import customtkinter as ctk
from CTkToolTip import *
import netifaces
import logging

from yaml import Event
from translate import _
import config

logger = logging.getLogger(__name__)

ip_addr = "127.0.0.1"
ip_port = 104
aet = "ANONSTORE"

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def get_local_ip_addresses():
    ip_addresses = []
    interfaces = netifaces.interfaces()
    for interface in interfaces:
        addresses = netifaces.ifaddresses(interface)
        if netifaces.AF_INET in addresses:
            for address_info in addresses[netifaces.AF_INET]:
                ip_address = address_info["addr"]
                ip_addresses.append(ip_address)
    return ip_addresses


# Entry field callback functions for validating user input and saving to config.json:
# TODO: Move these to utils.py
def int_entry_change(
    event: Event, var: ctk.IntVar, min: int, max: int, config_name: str
):
    value = var.get()
    if value > max:
        var.set(max)
    elif value < min:
        var.set(min)
    config.save(__name__, config_name, var.get())


def str_entry_change(
    var: ctk.StringVar, min_len: int, max_len: int, name: str, *args
) -> None:
    value = var.get()
    if len(value) > max_len:
        var.set(value[:max_len])
    elif len(value) < min_len:
        var.set(value[:min_len])
    config.save(__name__, name, var.get())


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Configure DICOM Storage SCP View")
    char_width_px = ctk.CTkFont().measure("M")
    logger.info(f"Font Character Width: ±{char_width_px}")
    view.grid_rowconfigure(0, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found.")]
        logger.error(local_ips[0])

    dicom_scp_label = ctk.CTkLabel(view, text=_("DICOM Storage SCP:"))
    dicom_scp_label.grid(row=0, column=0, pady=(PAD, 0), sticky="n")

    # IP Address:
    ip_var = ctk.StringVar(view, value=ip_addr)
    ip_var.trace_add(
        "write", lambda *args: str_entry_change(ip_var, 8, 15, "ip_addr", *args)
    )
    local_ips_optionmenu = ctk.CTkOptionMenu(
        view,
        dynamic_resizing=False,
        values=local_ips,
        variable=ip_var,
    )
    ip_ToolTip = CTkToolTip(
        local_ips_optionmenu,
        message=_("Local IP address to listen on for incoming DICOM files."),
    )
    local_ips_optionmenu.grid(row=0, column=1, pady=(PAD, 0), padx=PAD, sticky="n")

    # IP Port:
    ip_port_min = 104
    ip_port_max = 65535
    port_label = ctk.CTkLabel(view, text=_("Port:"))
    port_label.grid(row=0, column=2, pady=(PAD, 0), sticky="n")
    port_var = ctk.IntVar(view, value=ip_port)
    port_entry = ctk.CTkEntry(
        view, width=len(str(ip_port_max)) * char_width_px, textvariable=port_var
    )
    port_entry_tooltip = CTkToolTip(
        port_entry,
        message=_(
            "Port number to listen on for incoming DICOM files: [{ip_port_min}..{ip_port_max}]"
        ),
    )
    # port_var.trace_add(
    #     "write",
    #     lambda *args: entry_edit(port_entry, len(str(ip_port_max)), *args),
    # )
    entry_callback = lambda event: int_entry_change(
        event, port_var, ip_port_min, ip_port_max, "ip_port"
    )
    port_entry.bind("<Return>", entry_callback)
    port_entry.bind("<FocusOut>", entry_callback)
    port_entry.grid(row=0, column=3, pady=(PAD, 0), padx=PAD, sticky="n")

    # AET:
    aet_label = ctk.CTkLabel(view, text=_("AET:"))
    aet_label.grid(row=0, column=4, pady=(PAD, 0), sticky="n")
    aet_var = ctk.StringVar(view, value=aet)
    aet_entry = ctk.CTkEntry(view, width=120, textvariable=aet_var)
    aet_var.trace("w", lambda *args: config.save(__name__, "aet", aet_var.get()))
    aet_entry.grid(row=0, column=5, pady=(PAD, 0), padx=PAD, sticky="n")

    # SCP Server On/Off Switch:
    scp_var = ctk.StringVar(value="on")

    def scp_switch_event():
        logging.info("scp_switch_event toggled, current value:", scp_var.get())
        scp_var.set("off")

    scp_switch = ctk.CTkSwitch(
        view,
        text="SCP Server",
        command=scp_switch_event,
        variable=scp_var,
        onvalue="on",
        offvalue="off",
    )
    scp_switch.grid(row=0, column=6, pady=PAD, sticky="n")

    # SCP Server Autostart Checkbox:
    autostart_var = ctk.StringVar(value="on")

    def autostart_checkbox_event():
        logging.info(
            f"autostart_checkbox_event toggled, current value: {autostart_var.get()}"
        )

    autostart_checkbox = ctk.CTkCheckBox(
        view,
        text="Autostart",
        command=autostart_checkbox_event,
        variable=autostart_var,
        onvalue="on",
        offvalue="off",
    )
    autostart_checkbox.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="n")
