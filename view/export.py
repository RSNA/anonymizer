import os
from datetime import datetime
import logging
import string
from queue import Queue, Empty, Full
from turtle import back
import customtkinter as ctk
from tkinter import ttk
from CTkToolTip import CTkToolTip
from CTkMessagebox import CTkMessagebox
from controller.dicom_storage_scp import get_active_storage_dir
from utils.translate import _
from utils.storage import count_dcm_files_and_studies
import utils.config as config
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
    ux_poll_local_storage_interval,
    ux_poll_export_response_interval,
)
from controller.dicom_echo_scu import echo
from controller.dicom_send_scu import (
    DICOMNode,
    export_patients,
    ExportRequest,
    ExportResponse,
)
from controller.anonymize import phi_name

logger = logging.getLogger(__name__)

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
scp_ip_addr = "127.0.0.1"
scp_ip_port = 104
scp_aet = "PACS"
scu_ip_addr = "127.0.0.1"
scu_aet = "ANONSCU"


# Export attributes to display in the results Treeview:
# Key: column id: (column name, width, centre justify)
attr_map = {
    "Patient_Name": (_("Patient Name"), 10, False),
    "Anon_PatientID": (_("Anonymized ID"), 10, True),
    "Studies": (_("Studies"), 10, True),
    "Files": (_("Files"), 10, True),
    "DateTime": (_("Date Time"), 15, True),
    "FilesSent": (_("Files Sent"), 10, True),
    "Errors": (_("Errors"), 10, True),
}
# TODO: exported state: when and where, required to be tracked?

_select_all_state = False

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
    # TODO: implement watchdog heartbeats for all servers activated
    def scp_echo_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to {scp_aet_var.get()}...")
        scp_button.configure(text_color="light grey")
        # Echo SCP:
        if echo(
            scu=DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False),
            scp=DICOMNode(
                scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True
            ),
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

    # Treeview:
    fixed_width_font = ("Courier", 14, "bold")  # Specify the font family and size
    # TODO: see if theme manager can do this and stor in rsna_color_scheme_font.json
    style = ttk.Style()
    style.configure("Treeview", font=fixed_width_font)

    tree = ttk.Treeview(
        view, show="headings", style="Treeview", columns=list(attr_map.keys())
    )
    tree.grid(row=1, column=0, pady=(PAD, 0), columnspan=11, sticky="nswe")

    # Set tree column headers, width and justification
    for col in tree["columns"]:
        tree.heading(col, text=attr_map[col][0])
        tree.column(
            col,
            width=attr_map[col][1] * char_width_px,
            anchor="center" if attr_map[col][2] else "w",
        )

    # Setup display tags:
    tree.tag_configure("green", background="limegreen")
    tree.tag_configure("red", background="firebrick")

    # Set background color of treeview to light grey for all rows:
    # ttk.Style().configure(
    #     "Treeview", background="lightgray", fieldbackground="lightgray"
    # )

    # Managing Anonymizer Store Directory Treeview:
    def update_tree_from_storage_direcctory():
        store_dir = get_active_storage_dir()

        # Storage Directory Sub-directory Names = Patient IDs
        # Sequentially added
        anon_pt_ids = [
            f for f in sorted(os.listdir(store_dir)) if not f.startswith(".")
        ]

        existing_iids = set(tree.get_children())
        not_in_treeview = sorted(set(anon_pt_ids) - existing_iids)

        # Insert NEW data
        for anon_pt_id in not_in_treeview:
            study_count, file_count = count_dcm_files_and_studies(
                os.path.join(store_dir, anon_pt_id)
            )
            phi_pt_name = phi_name(anon_pt_id)
            tree.insert(
                "",
                0,
                iid=anon_pt_id,
                values=[phi_pt_name, anon_pt_id, study_count, file_count],
            )

        if not_in_treeview:
            logger.info(f"Added {len(not_in_treeview)} new patients to treeview")

        # To handle updates to incoming studies
        # Update the values of the last 10 patients in the store directory
        for anon_pt_id in anon_pt_ids[-10:]:
            study_count, file_count = count_dcm_files_and_studies(
                os.path.join(store_dir, anon_pt_id)
            )
            current_values = list(tree.item(anon_pt_id, "values"))
            current_values[2] = str(study_count)
            current_values[3] = str(file_count)
            tree.item(anon_pt_id, values=current_values)

        tree.after(ux_poll_local_storage_interval, update_tree_from_storage_direcctory)

    # Populate treeview with existing patients, trigger Background task to update treeview dynamically:
    update_tree_from_storage_direcctory()

    # Create a Scrollbar and associate it with the Treeview
    scrollbar = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    scrollbar.grid(row=1, column=11, pady=(PAD, 0), sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    # Refresh Button:
    def refresh_button_pressed():
        logger.info(f"Refresh button pressed")
        # Clear tree to ensure all items are removed before repopulating:
        tree.delete(*tree.get_children())
        update_tree_from_storage_direcctory()
        select_all_button.configure(text=_("Select All"))

    refresh_button = ctk.CTkButton(
        view, text=_("Refresh"), command=refresh_button_pressed
    )
    refresh_button.grid(row=2, column=0, columnspan=2, padx=PAD, pady=PAD, sticky="we")

    # Select All Button:
    def toggle_select(event):
        global _select_all_state
        if not _select_all_state:
            tree.selection_set(tree.get_children())
            select_all_button.configure(text=_("Deselect All"))
            _select_all_state = True
        else:
            for item in tree.selection():
                tree.selection_remove(item)
            select_all_button.configure(text=_("Select All"))
            _select_all_state = False

    select_all_button = ctk.CTkButton(
        view, text=_("Select All"), command=lambda: toggle_select(event=None)
    )
    select_all_button.grid(row=2, column=8, padx=PAD, pady=PAD, sticky="e")

    # TODO: simplify this logic:
    def monitor_export_queue(remaining_patients: int, ux_Q: Queue):
        full_critical_error = False
        while not ux_Q.empty():
            try:
                resp: ExportResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")
                # Check for full export termination due to critical error:
                if resp == ExportResponse.full_export_critical_error():
                    full_critical_error = True
                    CTkMessagebox(
                        title=_("Export Error"),
                        message=f"Remote server connection or timeout Error",
                        icon="cancel",
                    )
                    break

                # If one file failed to send, mark the patient as red:
                if resp.errors != 0:
                    tree.item(resp.patient_id, tags="red")

                # Update treeview item:
                current_values = list(tree.item(resp.patient_id, "values"))
                # Ensure there are at least 7 values in the list:
                while len(current_values) < 7:
                    current_values.append("")
                # Format the date and time as "YYYY-MM-DD HH:MM:SS"
                current_values[4] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_values[5] = str(resp.files_sent)
                current_values[6] = str(resp.errors)
                tree.item(resp.patient_id, values=current_values)

                # Check for completion or critical error of this patient's export
                if (
                    resp == ExportResponse.patient_critical_error(resp.patient_id)
                ) or ExportResponse.patient_export_complete(resp):
                    logger.info(f"Patient {resp.patient_id} export complete")
                    # remove selection highlight to indicate export of this item/patient is finished
                    tree.selection_remove(resp.patient_id)
                    remaining_patients -= 1
                    if resp.errors == 0 and not full_critical_error:
                        tree.item(resp.patient_id, tags="green")

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Check for completion of full export:
        if remaining_patients == 0 or full_critical_error:
            if full_critical_error:
                logger.error("Full export critical error detected, aborting monitor")
                for item in set(tree.selection()):
                    tree.selection_remove(item)
            else:
                logger.info("All patients exported")
            export_button.configure(state=ctk.NORMAL)
            select_all_button.configure(state=ctk.NORMAL)
            # re-enable tree interaction now export is complete
            tree.configure(selectmode="extended")
            return

        tree.after(
            ux_poll_export_response_interval,
            monitor_export_queue,
            remaining_patients,
            ux_Q,
        )

    def export_button_pressed():
        logger.info(f"Export button pressed")
        sel_patient_ids = list(tree.selection())
        if not sel_patient_ids:
            logger.error(f"No patients selected for export")
            return
        patients_to_send = len(sel_patient_ids)
        if patients_to_send == 0:
            logger.error(f"No patients selected for export")
            return

        # Create 1 UX queue to handle the full export operation
        ux_Q = Queue()
        scu = DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False)
        scp = DICOMNode(scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True)

        # Export all selected patients using a background thread pool
        export_patients(
            ExportRequest(
                scu,
                scp,
                sel_patient_ids,
                ux_Q,
            )
        )

        logger.info(f"Export of {patients_to_send} patients initiated")
        # disable tree interaction during export
        tree.configure(selectmode="none")
        # disable select_all and export buttons while export is in progress
        export_button.configure(state=ctk.DISABLED)
        select_all_button.configure(state=ctk.DISABLED)
        # Trigger the queue monitor
        tree.after(
            ux_poll_export_response_interval,
            monitor_export_queue,
            patients_to_send,
            ux_Q,
        )

    # def update_export_button_state():
    #     if tree.selection():
    #         export_button.configure(
    #             state=ctk.NORMAL
    #         )  # Enable button if there's a selection
    #     else:
    #         export_button.configure(
    #             state=ctk.DISABLED
    #         )  # Disable button if no selection

    # tree.bind("<<TreeviewSelect>>", lambda e: update_export_button_state())

    export_button = ctk.CTkButton(
        view,
        text=_("Export"),
        # state=ctk.DISABLED,
        command=lambda: export_button_pressed(),
    )
    export_button.grid(row=2, column=10, padx=PAD, pady=PAD, sticky="e")
