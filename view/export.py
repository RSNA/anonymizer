import os
import logging
import string
import queue
import threading
import customtkinter as ctk
from tkinter import ttk
from CTkToolTip import CTkToolTip
from view.storage_dir import get_storage_directory
from utils.translate import _
from utils.storage import count_dcm_files
import utils.config as config
from utils.network import get_local_ip_addresses
from utils.ux_fields import (
    str_entry,
    int_entry,
    adjust_column_width,
    ip_min_chars,
    ip_max_chars,
    aet_max_chars,
    aet_min_chars,
    ip_port_max,
    ip_port_min,
)
from controller.dicom_echo_scu import echo
from controller.dicom_send_scu import (
    DICOMNode,
    export_patients,
    ExportRequest,
    ExportResponse,
)

logger = logging.getLogger(__name__)

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
monitor_export_interval = 0.1  # seconds
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
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(6, weight=1)

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found")]
        logger.error(local_ips[0])

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
    scp_ip_var = str_entry(
        view=view,
        label=_("Remote Server:"),
        initial_value=scp_ip_addr,
        min_chars=ip_min_chars,
        max_chars=ip_max_chars,
        charset=string.digits + ".",
        tooltipmsg=_("Remote IP address"),
        row=0,
        col=1,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="scp_ip_addr",
    )

    scp_port_var = int_entry(
        view=view,
        label=_("Port:"),
        initial_value=scp_ip_port,
        min=ip_port_min,
        max=ip_port_max,
        tooltipmsg=_(f"Port number to listen on for incoming DICOM files"),
        row=0,
        col=3,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="scp_ip_port",
    )

    scp_aet_var = str_entry(
        view=view,
        label=_("AET:"),
        initial_value=scp_aet,
        min_chars=aet_min_chars,
        max_chars=aet_max_chars,
        charset=string.digits + string.ascii_uppercase + " ",
        tooltipmsg=_(f"Remote AE Title uppercase alphanumeric"),
        row=0,
        col=5,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="scp_aet",
    )

    # SCU IP Address:
    scu_ip_var = ctk.StringVar(view, value=scu_ip_addr)
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
    scu_aet_var = str_entry(
        view=view,
        label=_("AET:"),
        initial_value=scu_aet,
        min_chars=aet_min_chars,
        max_chars=aet_max_chars,
        charset=string.digits + string.ascii_uppercase + " ",
        tooltipmsg=_(f"Local AE Title uppercase alphanumeric"),
        row=0,
        col=9,
        pad=PAD,
        sticky="nw",
        module=__name__,
        var_name="scu_aet",
    )

    # Managing Anonymizer Store Directory Treeview:
    def update_treeview_from_storage_direcctory(tree: ttk.Treeview):
        store_dir = get_storage_directory()
        logger.info(f"Updating treeview data from {store_dir} ")
        # Directory Names = Patient IDs
        patient_ids = [f for f in os.listdir(store_dir) if not f.startswith(".")]
        # Clear existing items
        for item in tree.get_children():
            tree.delete(item)

        # Insert new data
        for pt_id in patient_ids:
            file_count = count_dcm_files(store_dir + "/" + pt_id)
            tree.insert("", "end", iid=pt_id, values=[pt_id, file_count, 0])

        for col_id in tree["columns"]:
            adjust_column_width(tree, col_id, padding=5)

    tree = ttk.Treeview(view, show="headings")
    tree.grid(row=1, column=0, pady=(PAD, 0), columnspan=11, sticky="nswe")

    # TODO: exported state: when and where, required to be tracked?
    tree["columns"] = [
        _("Patient ID"),
        _("Files"),
        _("Files Sent"),
        _("Errors"),
        # _("Exported Date"),
    ]

    for col in tree["columns"]:
        tree.heading(col, text=col)

    # Setup display tags:
    tree.tag_configure("green", foreground="light green")
    tree.tag_configure("red", foreground="red")

    update_treeview_from_storage_direcctory(tree)

    # Create a Scrollbar and associate it with the Treeview
    scrollbar = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    scrollbar.grid(row=1, column=11, pady=(PAD, 0), sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    # Refresh Button:
    def refresh_button_pressed():
        logger.info(f"Refresh button pressed")
        update_treeview_from_storage_direcctory(tree)

    refresh_button = ctk.CTkButton(
        view, text=_("Refresh"), command=refresh_button_pressed
    )
    refresh_button.grid(row=2, column=0, columnspan=2, padx=PAD, pady=PAD, sticky="we")

    # Select All Button:
    def select_all_button_pressed(tree: ttk.Treeview):
        logger.info(f"Select All button pressed")

        all_items = set(tree.get_children())
        selected_items = set(tree.selection())

        # If all items are already selected, unselect them.
        # Otherwise, select all items.
        if all_items == selected_items:
            for item in all_items:
                tree.selection_remove(item)
            select_all_button.configure(text=_("Select All"))
        else:
            for item in all_items:
                tree.selection_add(item)
            select_all_button.configure(text=_("Unselect All"))

    select_all_button = ctk.CTkButton(
        view, text=_("Select All"), command=lambda: select_all_button_pressed(tree)
    )
    select_all_button.grid(row=2, column=8, padx=PAD, pady=PAD, sticky="e")

    def monitor_export_queue(remaining_patients: int, ux_Q: queue.Queue):
        critical_error = False
        while not ux_Q.empty():
            try:
                resp: ExportResponse = ux_Q.get_nowait()
                logger.info(f"{resp}")
                # Check for full export termination due to critical error:
                if resp.errors == -1:
                    critical_error = True
                    break

                # If one file failed to send, mark the patient as red:
                if resp.errors != 0:
                    tree.item(resp.patient_id, tags="red")
                # Update treeview item:
                tree.item(
                    resp.patient_id,
                    values=[
                        resp.patient_id,
                        resp.files_to_send,
                        resp.files_sent,
                        resp.errors,
                    ],
                )
                # Check for completion of this patient's export:
                if resp.files_to_send == resp.files_sent + resp.errors:
                    logger.info(f"Patient {resp.patient_id} export complete")
                    # remove selection highlight to indicate export of this item finished
                    tree.selection_remove(resp.patient_id)
                    remaining_patients -= 1
                    if resp.errors == 0:
                        tree.item(resp.patient_id, tags="green")

            except queue.Empty:
                logger.info("Queue is empty")

        # Check for completion of full export:
        if remaining_patients == 0 or critical_error:
            if critical_error:
                logger.error("Critical export error detected, aborting monitore")
            else:
                logger.info("All patients exported")
            # re-enable refresh and select_all buttons now export is complete
            refresh_button.configure(state=ctk.NORMAL)
            select_all_button.configure(state=ctk.NORMAL)
            # re-enable tree interaction now export is complete
            tree.configure(selectmode="extended")
            return

        threading.Timer(
            monitor_export_interval,
            monitor_export_queue,
            args=(remaining_patients, ux_Q),
        ).start()

    def export_button_pressed():
        logger.info(f"Export button pressed")
        sel_patient_ids = list(tree.selection())
        patients_to_send = len(sel_patient_ids)
        if patients_to_send == 0:
            logger.error(f"No patients selected for export")
            return

        # Create 1 UX queue to handle the full export operation:
        ux_Q = queue.Queue()
        scu = DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False)
        scp = DICOMNode(scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True)

        # Export all selected patients using a background thread pool:
        export_patients(
            ExportRequest(
                scu,
                scp,
                sel_patient_ids,
                ux_Q,
            )
        )

        logger.info(f"Export of {patients_to_send} patients initiated")
        # disable tree interaction during export:
        tree.configure(selectmode="none")
        # disable refresh, select_all and export buttons while export is in progress
        export_button.configure(state=ctk.DISABLED)
        refresh_button.configure(state=ctk.DISABLED)
        select_all_button.configure(state=ctk.DISABLED)
        monitor_export_queue(patients_to_send, ux_Q)  # trigger the queue monitor

    def update_export_button_state():
        if tree.selection():
            export_button.configure(
                state=ctk.NORMAL
            )  # Enable button if there's a selection
        else:
            export_button.configure(
                state=ctk.DISABLED
            )  # Disable button if no selection

    tree.bind("<<TreeviewSelect>>", lambda e: update_export_button_state())

    export_button = ctk.CTkButton(
        view,
        text=_("Export"),
        state=ctk.DISABLED,
        command=lambda: export_button_pressed(),
    )
    export_button.grid(row=2, column=10, padx=PAD, pady=PAD, sticky="e")
