import os
from datetime import datetime
import logging
from queue import Queue, Empty, Full
import customtkinter as ctk
from tkinter import ttk
from controller.project import ProjectController, ExportRequest, ExportResponse
from utils.translate import _
from utils.storage import count_dcm_files_and_studies
from utils.ux_fields import (
    ux_poll_local_storage_interval,
    ux_poll_export_response_interval,
)


logger = logging.getLogger(__name__)


# Export attributes to display in the results Treeview:
# Key: column id: (column name, width, centre justify)
attr_map = {
    "Patient_Name": (_("Patient Name"), 10, False),
    "Anon_PatientID": (_("Anonymized ID"), 10, True),
    "Studies": (_("Studies"), 10, True),
    "Files": (_("Images"), 10, True),
    "DateTime": (_("Date Time"), 15, True),
    "FilesSent": (_("Images Sent"), 10, True),
}
# TODO: exported state: when and where, required to be tracked?

_select_all_state = False


def create_view(view: ctk.CTkFrame, PAD: int, project_controller: ProjectController):
    logger.info(f"Creating Export View")
    char_width_px = ctk.CTkFont().measure("A")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(6, weight=1)

    # SCP Echo Button:
    # TODO: implement watchdog heartbeats for all servers activated
    def scp_echo_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to Export Server...")
        scp_button.configure(text_color="light grey")
        # Echo SCP:
        if project_controller.echo("EXPORT"):
            logger.info(f"Echo Export Server successful")
            scp_button.configure(text_color="light green")
        else:
            logger.error(f"Echo to Export Server failed")
            scp_button.configure(text_color="red")

    scp_echo_button = ctk.CTkButton(
        view,
        width=int(5 * char_width_px),
        text=_("ECHO EXPORT SERVER"),
        command=lambda: scp_echo_button_event(scp_echo_button),
    )
    # scp_echo_button.grid(row=0, column=0, padx=(0, PAD), pady=(PAD, 0), sticky="nw")

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
    tree.tag_configure("red", background="red")

    # Set background color of treeview to light grey for all rows:
    # ttk.Style().configure(
    #     "Treeview", background="lightgray", fieldbackground="lightgray"
    # )

    # Managing Anonymizer Store Directory Treeview:
    def update_tree_from_storage_direcctory():
        # Storage Directory Sub-directory Names = Patient IDs
        # Sequentially added
        anon_pt_ids = [
            f
            for f in sorted(os.listdir(project_controller.storage_dir))
            if not f.startswith(".") and not f.endswith(".pkl")
        ]

        existing_iids = set(tree.get_children())
        not_in_treeview = sorted(set(anon_pt_ids) - existing_iids)

        # Insert NEW data
        for anon_pt_id in not_in_treeview:
            study_count, file_count = count_dcm_files_and_studies(
                os.path.join(project_controller.storage_dir, anon_pt_id)
            )
            phi_name = project_controller.anonymizer.model.get_phi_name(anon_pt_id)
            tree.insert(
                "",
                0,
                iid=anon_pt_id,
                values=[phi_name, anon_pt_id, study_count, file_count],
            )

        if not_in_treeview:
            logger.info(f"Added {len(not_in_treeview)} new patients to treeview")

        # To handle updates to incoming studies
        # Update the values of the last 10 patients in the store directory
        for anon_pt_id in anon_pt_ids[-10:]:
            study_count, file_count = count_dcm_files_and_studies(
                os.path.join(project_controller.storage_dir, anon_pt_id)
            )
            current_values = list(tree.item(anon_pt_id, "values"))
            current_values[2] = str(study_count)
            current_values[3] = str(file_count)
            tree.item(anon_pt_id, values=current_values)

        # tree.after(ux_poll_local_storage_interval, update_tree_from_storage_direcctory)

    # Populate treeview with existing patients
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

    def monitor_export_queue(remaining_patients: int, ux_Q: Queue):
        export_error = False
        while not ux_Q.empty():
            try:
                resp: ExportResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")

                # Update treeview item:
                current_values = list(tree.item(resp.patient_id, "values"))
                # Ensure there are at least 6 values in the list:
                while len(current_values) < 6:
                    current_values.append("")
                # Format the date and time as "YYYY-MM-DD HH:MM:SS"
                current_values[4] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_values[5] = str(resp.files_sent)
                tree.item(resp.patient_id, values=current_values)

                # Check for completion or critical error of this patient's export
                if resp.complete:
                    logger.info(f"Patient {resp.patient_id} export complete")
                    # remove selection highlight to indicate export of this item/patient is finished
                    tree.selection_remove(resp.patient_id)
                    remaining_patients -= 1

                if resp.error:
                    tree.item(resp.patient_id, tags="red")
                    export_error = True
                    break
                else:
                    tree.item(resp.patient_id, tags="green")

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Unselect
        # Check for completion of full export:
        if remaining_patients == 0 or export_error:
            if export_error:
                logger.error("Export error detected, aborting monitor")
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

        # Export all selected patients using a background thread pool
        project_controller.export_patients(
            ExportRequest(
                "EXPORT",
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
