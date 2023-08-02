import string
import customtkinter as ctk
from CTkToolTip import CTkToolTip
import logging
from utils.translate import _
import utils.config as config
from utils.network import get_local_ip_addresses
from utils.ux_verify import (
    validate_entry,
    int_entry_change,
    str_entry_change,
    ip_min_chars,
    ip_max_chars,
    aet_max_chars,
    aet_min_chars,
    ip_port_max,
    ip_port_min,
)

# import controller.dicom_QR_find_scu as dicom_QR_find_scu
from controller.dicom_echo_scu import echo

logger = logging.getLogger(__name__)

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
scp_ip_addr = "127.0.0.1"
scp_ip_port = 104
scp_aet = "RSNA"
scu_ip_addr = "127.0.0.1"
scu_aet = "ANONSCU"

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Configure DICOM Query/Retrieve SCU View")
    char_width_px = ctk.CTkFont().measure("A")
    digit_width_px = ctk.CTkFont().measure("9")
    validate_entry_cmd = view.register(validate_entry)
    logger.info(f"Font Character Width in pixels: ±{char_width_px}")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(5, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found")]
        logger.error(local_ips[0])

    # SCP UX variables:
    scp_ip_var = ctk.StringVar(view, value=scp_ip_addr)
    scp_port_var = ctk.IntVar(view, value=scp_ip_port)
    scp_aet_var = ctk.StringVar(view, value=scp_aet)
    scu_ip_var = ctk.StringVar(view, value=scu_ip_addr)
    scu_aet_var = ctk.StringVar(view, value=scu_aet)

    # Q/R SCP IP Address:
    def scp_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to {scp_aet_var.get()}...")
        # Echo SCP:
        if echo(
            scp_ip_var.get(),
            scp_port_var.get(),
            scp_aet_var.get(),
            scu_ip_var.get(),
            scu_aet_var.get(),
        ):
            logger.info(f"Echo to {scp_aet_var.get()} successful")
            scp_button.configure(text_color="light green")
        else:
            logger.error(f"Echo to {scp_aet_var.get()} failed")
            scp_button.configure(text_color="red")

    scp_button = ctk.CTkButton(
        view, text=_("DICOM Q/R SCP:"), command=lambda: scp_button_event(scp_button)
    )
    scp_button.grid(row=0, column=0, pady=(PAD, 0), sticky="nw")
    scp_button_tooltip = CTkToolTip(scp_button, message=_(f"Click to check connection"))

    scp_ip_entry = ctk.CTkEntry(
        view,
        width=int(ip_max_chars * digit_width_px),
        textvariable=scp_ip_var,
        validate="key",
        validatecommand=(
            validate_entry_cmd,
            "%P",
            string.digits + ".",
            str(ip_max_chars),
        ),
    )
    scp_ip_tooltip = CTkToolTip(
        scp_ip_entry,
        message=_(f"Remote IP address [{ip_min_chars}..{ip_max_chars}] chars"),
    )
    scp_ip_entry.grid(row=0, column=1, pady=(PAD, 0), padx=PAD, sticky="nw")

    # Q/R SCP IP Port:
    ip_port_max_chars = len(str(ip_port_max)) + 2
    scp_port_label = ctk.CTkLabel(view, text=_("Port:"))
    scp_port_label.grid(row=0, column=2, pady=(PAD, 0), sticky="nw")

    scp_port_entry = ctk.CTkEntry(
        view,
        width=int(ip_port_max_chars * digit_width_px),
        textvariable=scp_port_var,
        validate="key",
        validatecommand=(validate_entry_cmd, "%P", string.digits, ip_port_max_chars),
    )
    scp_port_entry_tooltip = CTkToolTip(
        scp_port_entry,
        message=_(f"Remote IP port [{ip_port_min}..{ip_port_max}]"),
    )
    entry_callback = lambda event: int_entry_change(
        event, scp_port_var, ip_port_min, ip_port_max, __name__, "scp_ip_port"
    )
    scp_port_entry.bind("<Return>", entry_callback)
    scp_port_entry.bind("<FocusOut>", entry_callback)
    scp_port_entry.grid(row=0, column=3, pady=(PAD, 0), padx=PAD, sticky="n")

    # Q/R SCP AET:
    scp_aet_label = ctk.CTkLabel(view, text=_("AET:"))
    scp_aet_label.grid(row=0, column=4, pady=(PAD, 0), sticky="nw")

    scp_aet_entry = ctk.CTkEntry(
        view,
        width=int(aet_max_chars * char_width_px),
        textvariable=scp_aet_var,
        validate="key",
        validatecommand=(
            validate_entry_cmd,
            "%P",
            string.digits + string.ascii_uppercase + " ",
            str(aet_max_chars),
        ),
    )
    scp_aet_entry_tooltip = CTkToolTip(
        scp_aet_entry,
        message=_(f"Remote AE Title [{aet_min_chars}..{aet_max_chars}] chars"),
    )
    entry_callback = lambda event: str_entry_change(
        event, scp_aet_var, aet_min_chars, aet_max_chars, __name__, "scp_aet"
    )
    scp_aet_entry.bind("<Return>", entry_callback)
    scp_aet_entry.bind("<FocusOut>", entry_callback)
    scp_aet_entry.grid(row=0, column=5, pady=(PAD, 0), padx=PAD, sticky="nw")

    # Q/R SCU IP Address:
    scu_label = ctk.CTkLabel(view, text=_("DICOM Q/R SCU:"))
    scu_label.grid(row=0, column=6, pady=(PAD, 0), sticky="nw")

    local_ips_optionmenu = ctk.CTkOptionMenu(
        view,
        dynamic_resizing=False,
        values=local_ips,
        variable=scu_ip_var,
        command=lambda *args: config.save(__name__, "scu_ip_addr", scu_ip_var.get()),
    )
    scu_ip_ToolTip = CTkToolTip(
        local_ips_optionmenu,
        message=_("Local IP address interface"),
    )
    local_ips_optionmenu.grid(row=0, column=7, pady=(PAD, 0), padx=PAD, sticky="nw")

    # Q/R SCU AET:
    scp_aet_label = ctk.CTkLabel(view, text=_("AET:"))
    scp_aet_label.grid(row=0, column=8, pady=(PAD, 0), sticky="nw")
    scu_aet_entry = ctk.CTkEntry(
        view,
        width=int(aet_max_chars * char_width_px),
        textvariable=scu_aet_var,
        validate="key",
        validatecommand=(
            validate_entry_cmd,
            "%P",
            string.digits + string.ascii_uppercase + " ",
            str(aet_max_chars),
        ),
    )
    scu_aet_entry_tooltip = CTkToolTip(
        scu_aet_entry,
        message=_(f"Local AE Title [{aet_min_chars}..{aet_max_chars}] chars"),
    )
    entry_callback = lambda event: str_entry_change(
        event, scu_aet_var, aet_min_chars, aet_max_chars, __name__, "scu_aet"
    )
    scu_aet_entry.bind("<Return>", entry_callback)
    scu_aet_entry.bind("<FocusOut>", entry_callback)
    scu_aet_entry.grid(row=0, column=9, pady=(PAD, 0), padx=PAD, sticky="nw")

    # SCU Client Log:
    scu_log = ctk.CTkTextbox(
        view,
        wrap="none",
    )

    # dicom_storage_scp.loghandler(scp_log)
    scu_log.grid(row=1, pady=(PAD, 0), columnspan=10, sticky="nswe")
