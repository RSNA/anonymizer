import string
import tkinter as tk
import customtkinter as ctk
from CTkToolTip import *
import netifaces
import logging
from utils.translate import _
import utils.config as config
import controller.dicom_scp as dicom_scp
from view.storage_dir import storage_directory

logger = logging.getLogger(__name__)

ip_addr = "127.0.0.1"
ip_port = 104
aet = "ANONSTORE"
scp_autostart = "off"
scp_log_font_family = "courier"
scp_log_font_size = 13

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
def validate_entry(final_value: str, allowed_chars: str, max: str):
    # BUG: max is always a string, so convert to int
    if len(final_value) > int(max):
        return False
    for char in final_value:
        if char not in allowed_chars:
            return False
    return True


def int_entry_change(
    event: tk.Event, var: ctk.IntVar, min: int, max: int, config_name: str
) -> None:
    try:
        value = var.get()
    except:
        value = 0
    if value > max:
        var.set(max)
    elif value < min:
        var.set(min)
    config.save(__name__, config_name, var.get())


def str_entry_change(
    event: tk.Event, var: ctk.StringVar, min_len: int, max_len: int, config_name: str
) -> None:
    value = var.get()
    if len(value) > max_len:
        var.set(value[:max_len])
    elif len(value) < min_len:
        var.set(value[:min_len])
    config.save(__name__, config_name, var.get())


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Configure DICOM Storage SCP View")
    char_width_px = ctk.CTkFont().measure("A")
    validate_entry_cmd = view.register(validate_entry)
    logger.info(f"Font Character Width in pixels: ±{char_width_px}")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(5, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found.")]
        logger.error(local_ips[0])

    dicom_scp_label = ctk.CTkLabel(view, text=_("DICOM Storage SCP:"))
    dicom_scp_label.grid(row=0, column=0, pady=(PAD, 0), sticky="nw")

    # IP Address:
    ip_var = ctk.StringVar(view, value=ip_addr)
    local_ips_optionmenu = ctk.CTkOptionMenu(
        view,
        dynamic_resizing=True,
        values=local_ips,
        variable=ip_var,
        command=lambda *args: config.save(__name__, "ip_addr", ip_var.get()),
    )
    ip_ToolTip = CTkToolTip(
        local_ips_optionmenu,
        message=_("Local IP address to listen on for incoming DICOM files."),
    )
    local_ips_optionmenu.grid(row=0, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

    # IP Port:
    ip_port_min = 104
    ip_port_max = 65535
    ip_port_max_chars = len(str(ip_port_max))
    port_label = ctk.CTkLabel(view, text=_("Port:"))
    port_label.grid(row=0, column=2, pady=(PAD, 0), sticky="nw")
    port_var = ctk.IntVar(view, value=ip_port)
    port_entry = ctk.CTkEntry(
        view,
        width=int(ip_port_max_chars * char_width_px),
        textvariable=port_var,
        validate="key",
        validatecommand=(validate_entry_cmd, "%P", string.digits, ip_port_max_chars),
    )
    port_entry_tooltip = CTkToolTip(
        port_entry,
        message=_(
            f"Port number to listen on for incoming DICOM files: [{ip_port_min}..{ip_port_max}]"
        ),
    )
    entry_callback = lambda event: int_entry_change(
        event, port_var, ip_port_min, ip_port_max, "ip_port"
    )
    port_entry.bind("<Return>", entry_callback)
    port_entry.bind("<FocusOut>", entry_callback)
    port_entry.grid(row=0, column=3, pady=(PAD, 0), padx=PAD, sticky="n")

    # AET:
    aet_label = ctk.CTkLabel(view, text=_("AET:"))
    aet_label.grid(row=0, column=4, pady=(PAD, 0), sticky="nw")
    aet_min_chars = 3
    aet_max_chars = 16
    aet_var = ctk.StringVar(view, value=aet)
    aet_entry = ctk.CTkEntry(
        view,
        width=int(aet_max_chars * char_width_px),
        textvariable=aet_var,
        validate="key",
        validatecommand=(
            validate_entry_cmd,
            "%P",
            string.digits + string.ascii_uppercase + " ",
            str(aet_max_chars),
        ),
    )
    aet_entry_tooltip = CTkToolTip(
        aet_entry,
        message=_(
            f"DICOM AE Title: uppercase alphanumeric & spaces [{aet_min_chars}..{aet_max_chars}] chars"
        ),
    )
    entry_callback = lambda event: str_entry_change(
        event, aet_var, aet_min_chars, aet_max_chars, "aet"
    )
    aet_entry.bind("<Return>", entry_callback)
    aet_entry.bind("<FocusOut>", entry_callback)
    aet_entry.grid(row=0, column=5, pady=(PAD, 0), padx=PAD, sticky="nw")

    # SCP Server On/Off Switch:
    scp_var = ctk.StringVar(value="off")

    def scp_switch_event():
        logger.info("scp_switch_event")
        if scp_var.get() == "on":
            if not dicom_scp.start(
                ip_var.get(), port_var.get(), aet_var.get(), storage_directory
            ):
                scp_var.set("off")
        else:
            if not dicom_scp.stop():
                scp_var.set("on")

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
    scp_autostart_var = ctk.StringVar(value=scp_autostart)

    def scp_autostart_checkbox_event():
        logging.info(
            f"scp_autostart_var toggled, current value: {scp_autostart_var.get()}"
        )
        config.save(__name__, "scp_autostart", scp_autostart_var.get())

    scp_autostart_checkbox = ctk.CTkCheckBox(
        view,
        text="Autostart",
        command=scp_autostart_checkbox_event,
        variable=scp_autostart_var,
        onvalue="on",
        offvalue="off",
    )
    scp_autostart_checkbox.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="n")

    # SCP Server Log:
    scp_log = ctk.CTkTextbox(
        view,
        wrap="none",
        font=ctk.CTkFont(family=scp_log_font_family, size=scp_log_font_size),
    )
    dicom_scp.loghandler(scp_log)
    scp_log.grid(row=1, columnspan=8, sticky="nswe")

    # Handle SCP Server Autostart:
    if scp_autostart == "on":
        if not dicom_scp.start(ip_addr, ip_port, aet, storage_directory):
            scp_var.set("off")
        else:
            scp_var.set("on")
