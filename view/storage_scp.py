import string
import customtkinter as ctk
from CTkToolTip import CTkToolTip
from CTkMessagebox import CTkMessagebox
import logging
from controller.project import DICOMNode, DICOMRuntimeError
from utils.translate import _
import prototyping.config as config
import prototyping.dicom_storage_scp as dicom_storage_scp
from view.storage_dir import get_storage_directory
from utils.network import get_local_ip_addresses
from utils.ux_fields import (
    int_entry,
    str_entry,
    aet_max_chars,
    aet_min_chars,
    ip_port_max,
    ip_port_min,
)

logger = logging.getLogger(__name__)

# Default values:
ip_addr = "127.0.0.1"
ip_port = 104
aet = "ANONSTORE"
scp_autostart = False

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def create_view(view: ctk.CTkFrame, PAD: int = 10):
    logger.info(f"Creating Configure DICOM Storage SCP View")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(5, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found.")]
        logger.error(local_ips[0])

    # TODO: create dicom node class to encapsulate these variables, move to ux_fields.py
    scp_label = ctk.CTkLabel(view, text=_("Local Server:"))
    scp_label.grid(row=0, column=0, pady=(PAD, 0), sticky="nw")

    # IP Address:
    ip_var = ctk.StringVar(view, value=ip_addr)
    local_ips_optionmenu = ctk.CTkOptionMenu(
        view,
        dynamic_resizing=False,
        values=local_ips,
        variable=ip_var,
        command=lambda *args: config.save(__name__, "ip_addr", ip_var.get()),
    )
    ip_ToolTip = CTkToolTip(
        local_ips_optionmenu,
        message=_("Local IP address to listen on for incoming DICOM files"),
    )
    local_ips_optionmenu.grid(row=0, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

    port_var = int_entry(
        view=view,
        label=_("Port:"),
        initial_value=ip_port,
        min=ip_port_min,
        max=ip_port_max,
        tooltipmsg=f"Port number to listen on for incoming DICOM files",
        row=0,
        col=2,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="ip_port",
    )

    aet_var = str_entry(
        view=view,
        label=_("AET:"),
        initial_value=aet,
        min_chars=aet_min_chars,
        max_chars=aet_max_chars,
        charset=string.digits + string.ascii_uppercase + " ",
        tooltipmsg=_(f"DICOM AE Title: uppercase alphanumeric & spaces"),
        row=0,
        col=4,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="aet",
    )

    # SCP Server On/Off Switch:
    scp_var = ctk.BooleanVar(view, value=False)

    def scp_switch_event():
        logger.info("scp_switch_event")
        if scp_var.get():
            try:
                dicom_storage_scp.start(
                    DICOMNode(ip_var.get(), port_var.get(), aet_var.get(), True),
                    get_storage_directory(),
                )
                scp_var.set(True)
            except DICOMRuntimeError as e:
                scp_var.set(False)
                CTkMessagebox(
                    title=_("Storage Server Startup Error"),
                    message=f"{e}",
                    icon="cancel",
                )
        else:
            dicom_storage_scp.stop()

    scp_switch = ctk.CTkSwitch(
        view,
        text="SCP Server",
        command=scp_switch_event,
        variable=scp_var,
    )
    scp_switch.grid(row=0, column=6, pady=PAD, sticky="n")

    # SCP Server Autostart Checkbox:
    scp_autostart_var = ctk.BooleanVar(view, value=scp_autostart)

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
    )
    scp_autostart_checkbox.grid(row=0, column=7, padx=PAD, pady=PAD, sticky="n")

    # Handle SCP Server Autostart:
    if scp_autostart:
        try:
            logger.info("Autostart Local Storage Server...")
            dicom_storage_scp.start(
                DICOMNode(ip_addr, ip_port, aet, True), get_storage_directory()
            )
            scp_var.set(True)
        except DICOMRuntimeError as e:
            CTkMessagebox(
                title=_("Storage Server Startup Error"), message=f"{e}", icon="cancel"
            )
