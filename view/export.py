import os
import logging
import string
import customtkinter as ctk
import queue
from tkinter import ttk
from CTkToolTip import CTkToolTip
from view.storage_dir import get_storage_directory
from utils.translate import _
import utils.config as config
from utils.network import get_local_ip_addresses
from utils.ux_fields import (
    validate_entry,
    int_entry_change,
    str_entry,
    adjust_column_width,
    ip_min_chars,
    ip_max_chars,
    aet_max_chars,
    aet_min_chars,
    ip_port_max,
    ip_port_min,
)
from controller.dicom_echo_scu import echo
from controller.dicom_send_scu import send, SendRequest, SendResponse

logger = logging.getLogger(__name__)

export_queue = queue.Queue()

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
scp_ip_addr = "127.0.0.1"
scp_ip_port = 104
scp_aet = "PACS"
scu_ip_addr = "127.0.0.1"
scu_aet = "ANONSCU"

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def create_view(view: ctk.CTkFrame, PAD: int):
    logger.info(f"Creating Export View")
    char_width_px = ctk.CTkFont().measure("A")
    digit_width_px = ctk.CTkFont().measure("9")
    validate_entry_cmd = view.register(validate_entry)
    logger.info(f"Font Character Width in pixels: ±{char_width_px}")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(6, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found")]
        logger.error(local_ips[0])

    # SCP & SCU UX variables:
    scp_ip_var = ctk.StringVar(view, value=scp_ip_addr)
    scp_port_var = ctk.IntVar(view, value=scp_ip_port)
    scp_aet_var = ctk.StringVar(view, value=scp_aet)
    scu_ip_var = ctk.StringVar(view, value=scu_ip_addr)
    scu_aet_var = ctk.StringVar(view, value=scu_aet)

    # SCP Echo Button:
    # TODO: implement class hierachy for all clients and servers, with watchdog heartbeats for all servers activated
    def scp_echo_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to {scp_aet_var.get()}...")
        scp_button.configure(text_color="light grey")
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

    scp_echo_button = ctk.CTkButton(
        view,
        width=int(5 * char_width_px),
        text=_("ECHO"),
        command=lambda: scp_echo_button_event(scp_echo_button),
    )
    scp_echo_button.grid(row=0, column=0, padx=(0, PAD), pady=(PAD, 0), sticky="nw")
    # TODO: tooltip causes TclError on program close
    # scp_echo_button_tooltip = CTkToolTip(
    #     scp_echo_button,
    #     message=_("Click to check connection from Local SCU to Remote SCP"),
    # )

    # SCP IP Address:
    str_entry(
        view,
        scp_ip_var,
        validate_entry_cmd,
        digit_width_px,
        __name__,
        label=_("Remote Server:"),
        min_chars=ip_min_chars,
        max_chars=ip_max_chars,
        charset=string.digits + ".",
        tooltipmsg=_("Remote IP address"),
        row=0,
        col=1,
        pad=PAD,
        sticky="nw",
    )

    # SCP IP Port:
    ip_port_max_chars = len(str(ip_port_max)) + 2
    scp_port_label = ctk.CTkLabel(view, text=_("Port:"))
    scp_port_label.grid(row=0, column=3, pady=(PAD, 0), sticky="nw")

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
    scp_port_entry.grid(row=0, column=4, pady=(PAD, 0), padx=PAD, sticky="n")

    str_entry(
        view,
        scp_aet_var,
        validate_entry_cmd,
        char_width_px,
        __name__,
        label=_("AET:"),
        min_chars=aet_min_chars,
        max_chars=aet_max_chars,
        charset=string.digits + string.ascii_uppercase + " ",
        tooltipmsg=_("Remote AE Title uppercase alphanumeric"),
        row=0,
        col=5,
        pad=PAD,
        sticky="nw",
    )

    # SCU IP Address:
    scu_label = ctk.CTkLabel(view, text=_("Local Client:"))
    scu_label.grid(row=0, column=7, pady=(PAD, 0), sticky="nw")

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
    local_ips_optionmenu.grid(row=0, column=8, pady=(PAD, 0), padx=PAD, sticky="nw")

    # SCU AET:
    str_entry(
        view,
        scu_aet_var,
        validate_entry_cmd,
        char_width_px,
        __name__,
        label=_("AET:"),
        min_chars=aet_min_chars,
        max_chars=aet_max_chars,
        charset=string.digits + string.ascii_uppercase + " ",
        tooltipmsg=_("Local AE Title uppercase alphanumeric"),
        row=0,
        col=9,
        pad=PAD,
        sticky="nw",
    )

    # Managing Anonymizer Store Directory Treeview:
    def update_treeview_data(tree: ttk.Treeview):
        store_dir = get_storage_directory()
        logger.info(f"Updating treeview data from {store_dir} ")
        anon_dirs = [f for f in os.listdir(store_dir) if not f.startswith(".")]
        # Clear existing items
        for item in tree.get_children():
            tree.delete(item)

        # Insert new data
        for dir in anon_dirs:
            tree.insert("", "end", iid=dir, values=[dir])

        for col_id in tree["columns"]:
            adjust_column_width(tree, col_id, padding=5)

    tree = ttk.Treeview(view, show="headings")
    tree.grid(row=1, column=0, pady=(PAD, 0), columnspan=11, sticky="nswe")

    tree["columns"] = [
        _("Patient ID"),
        _("Studies"),
        _("Files"),
        _("Exported Date"),
    ]
    for col in tree["columns"]:
        tree.heading(col, text=col)
    update_treeview_data(tree)

    # Create a Scrollbar and associate it with the Treeview
    scrollbar = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    scrollbar.grid(row=1, column=11, pady=(PAD, 0), sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    def refresh_button_pressed():
        logger.info(f"Refresh button pressed")
        update_treeview_data(tree)

    refresh_button = ctk.CTkButton(
        view, text=_("Refresh"), command=refresh_button_pressed
    )
    refresh_button.grid(row=2, column=0, columnspan=2, padx=PAD, pady=PAD, sticky="we")

    def export_button_pressed():
        sel_anon_dirs = list(tree.selection())
        logger.info(f"Export button pressed")
        logger.info(f"Exporting: {sel_anon_dirs}")

        for dir in sel_anon_dirs:
            path = get_storage_directory() + "/" + dir
            if not os.path.isdir(path):
                logger.error(f"Selected directory {path} is not a directory")
                continue

            file_paths = []
            for root, _, files in os.walk(path):
                file_paths.extend(
                    os.path.join(root, file) for file in files if file.endswith(".dcm")
                )
            if not file_paths:
                logger.error(f"No DICOM files found in {path}")
                continue

            ux_Q = queue.Queue()

            req: SendRequest = SendRequest(
                scp_ip=scp_ip_var.get(),
                scp_port=scp_port_var.get(),
                scp_ae=scp_aet_var.get(),
                scu_ip=scu_ip_var.get(),
                scu_ae=scu_aet_var.get(),
                dicom_files=file_paths,
                ux_Q=ux_Q,
            )

            if send(req):
                logger.info(f"Export {dir} initiated")

            # TODO: timed callback to update treeview with export status

    export_button = ctk.CTkButton(view, text=_("Export"), command=export_button_pressed)
    export_button.grid(row=2, column=10, padx=PAD, pady=PAD, sticky="e")
