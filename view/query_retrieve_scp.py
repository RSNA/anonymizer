import logging
import string
from queue import Queue, Empty, Full
import time
import customtkinter as ctk
import pandas as pd
from tkinter import ttk
from CTkToolTip import CTkToolTip
from controller.dicom_return_codes import C_PENDING_A, C_PENDING_B, C_SUCCESS, C_FAILURE
from utils.translate import _
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
    patient_name_max_chars,
    patient_id_max_chars,
    accession_no_max_chars,
    dicom_date_chars,
    modality_max_chars,
    modality_min_chars,
    ux_poll_find_response_interval,
)
from controller.dicom_ae import DICOMNode
from controller.dicom_echo_scu import echo
from controller.dicom_find_scu import find, find_ex, FindRequest, FindResponse
from controller.dicom_move_scu import MoveRequest, move_ex
from controller.dicom_storage_scp import get_storage_scp_aet

logger = logging.getLogger(__name__)

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
scp_ip_addr = "127.0.0.1"
scp_ip_port = 104
scp_aet = "RSNA"
scu_ip_addr = "127.0.0.1"
scu_aet = "ANONSCU"

# C-FIND DICOM attributes to display in the results Treeview:
# Key: DICOM field name, Value: (display name, centre justify)
attr_map = {
    "PatientName": (_("Patient Name"), 20, False),
    "PatientID": (_("Patient ID"), 10, False),
    "StudyDate": (_("Date"), 8, True),
    "StudyDescription": (_("Study Description"), 20, False),
    "AccessionNumber": (_("Accession No."), 15, True),
    "ModalitiesInStudy": (_("Modality"), 9, True),
    "NumberOfStudyRelatedSeries": (_("Series"), 6, True),
    "NumberOfStudyRelatedInstances": (_("Images"), 6, True),
    "StudyInstanceUID": (
        _("StudyInstanceUID"),
        0,
        False,
    ),  # not for display, for find/move
}

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def create_view(view: ctk.CTkFrame, PAD: int):
    logger.info(f"Creating Query/Retrieve SCU View")
    view.grid_rowconfigure(2, weight=1)
    view.grid_columnconfigure(6, weight=1)
    char_width_px = ctk.CTkFont().measure("A")

    local_ips = get_local_ip_addresses()
    if local_ips:
        logger.info(f"Local IP addresses: {local_ips}")
    else:
        local_ips = [_("No local IP addresses found")]
        logger.error(local_ips[0])

    # Q/R SCP IP Address:
    def scp_echo_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to {scp_aet_var.get()}...")
        scp_button.configure(text_color="light grey")
        # Echo SCP:
        if echo(
            DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False),
            DICOMNode(scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True),
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

    scp_ip_var = str_entry(
        view=view,
        label=_("Remote Server:"),
        initial_value=scp_ip_addr,
        min_chars=ip_min_chars,
        max_chars=ip_max_chars,
        charset=string.digits + ".",
        tooltipmsg=_(f"Remote IP address"),
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

    # Q/R SCU IP Address:
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

    # QUERY PARAMETERS:
    # Create new frame
    query_param_frame = ctk.CTkFrame(view)
    query_param_frame.grid(row=1, pady=(PAD, 0), columnspan=11, sticky="nswe")
    # Patient Name
    patient_name_var = str_entry(
        view=query_param_frame,
        label=_("Patient Name:"),
        initial_value="",
        min_chars=0,
        max_chars=patient_name_max_chars,
        charset=string.ascii_letters
        + string.digits
        + "- ' ^ *"
        + "À-ÖØ-öø-ÿ"
        + string.whitespace,
        tooltipmsg="Alphabetic ^ spaces * for wildcard",
        row=0,
        col=0,
        pad=PAD,
        sticky="nw",
    )
    # Patient ID
    patient_id_var = ctk.StringVar(view)
    patient_id_var = str_entry(
        query_param_frame,
        label=_("Patient ID:"),
        initial_value="",
        min_chars=0,
        max_chars=patient_id_max_chars,
        charset=string.ascii_letters + string.digits + "*",
        tooltipmsg="Alpha-numeric, * for wildcard",
        row=1,
        col=0,
        pad=PAD,
        sticky="nw",
    )
    # Accession No.
    accession_no_var = str_entry(
        view=query_param_frame,
        label=_("Accession No.:"),
        initial_value="",
        min_chars=0,
        max_chars=accession_no_max_chars,
        charset=string.ascii_letters + string.digits + " */-_",
        tooltipmsg="Alpha-numeric, * for wildcard",
        row=2,
        col=0,
        pad=PAD,
        sticky="nw",
    )

    # Study Date:
    study_date_var = str_entry(
        view=query_param_frame,
        label=_("Study Date:"),
        initial_value="",
        min_chars=dicom_date_chars,
        max_chars=dicom_date_chars,
        charset=string.digits + "*",
        tooltipmsg=_("Numeric YYYYMMDD, * for wildcard"),
        row=0,
        col=3,
        pad=PAD,
        sticky="nw",
    )

    # Modality:
    modality_var = str_entry(
        view=query_param_frame,
        label=_("Modality:"),
        initial_value="",
        min_chars=modality_min_chars,
        max_chars=modality_max_chars,
        charset=string.ascii_uppercase,
        tooltipmsg=_("Modality Code"),
        row=1,
        col=3,
        pad=PAD,
        sticky="nw",
    )

    # Managing C-FIND results Treeview:
    fixed_width_font = ("Courier", 14)  # Specify the font family and size
    # Create a custom style for the Treeview
    # TODO: see if theme manager can do this and stor in rsna_color_scheme_font.json
    style = ttk.Style()
    style.configure(
        "Treeview", font=fixed_width_font
    )  # Set the font for the Treeview style

    tree = ttk.Treeview(
        view, show="headings", style="Treeview", columns=list(attr_map.keys())[:-1]
    )
    tree.grid(row=2, column=0, columnspan=11, sticky="nswe")
    # Set tree column headers, width and justification
    for col in tree["columns"]:
        tree.heading(col, text=attr_map[col][0])
        tree.column(
            col,
            width=attr_map[col][1] * char_width_px,
            anchor="center" if attr_map[col][2] else "w",
        )

    def update_treeview_data(tree: ttk.Treeview, data: pd.DataFrame):
        # Insert new data
        logger.info(f"update_treeview_data items: {len(data)}")
        for _, row in data.iterrows():
            display_values = [
                val for col, val in row.items() if col != "StudyInstanceUID"
            ]
            tree.insert("", "end", iid=row["StudyInstanceUID"], values=display_values)

    # Query Button:
    def monitor_query_response(ux_Q: Queue, tree: ttk.Treeview):
        results = []
        query_finished = False
        while not ux_Q.empty():
            try:
                resp: FindResponse = ux_Q.get_nowait()
                logger.debug(f"{resp}")
                if resp.status.Status in [C_PENDING_A, C_PENDING_B, C_SUCCESS]:
                    if resp.identifier:
                        results.append(resp.identifier)
                    if resp.status.Status == C_SUCCESS:
                        query_finished = True
                        logger.info(f"Query finished, {len(results)} results")
                else:
                    assert resp.status.Status == C_FAILURE
                    query_finished = True
                    logger.error(f"Query failed: {resp.status.ErrorComment}")
                    # TODO:Display error box with resp.ErrorComment

                ux_Q.task_done()

            except Empty:
                logger.info("Queue is empty")
            except Full:
                logger.error("Queue is full")

        # Create Pandas DataFrame from results and display in Treeview:
        if results:
            logger.info(f"monitor_query_response: processing {len(results)} results")
            # List the DICOM attributes in the desired order using the keys from the mapping
            ordered_attrs = list(attr_map.keys())
            data_dicts = [
                {
                    attr_map[attr][0]: getattr(ds, attr, None)
                    for attr in ordered_attrs
                    if hasattr(ds, attr)
                }
                for ds in results
            ]
            df = pd.DataFrame(data_dicts)

            # Update the treeview with the new data
            update_treeview_data(tree, df)

        if not query_finished:
            # Re-trigger monitor callback:
            tree.after(
                ux_poll_find_response_interval, monitor_query_response, ux_Q, tree
            )

    # TODO: query on <Return> // move to next query entry on <Return>
    # TODO: only enable query if server healthy, disable query button during find request
    def query_button_pressed(tree: ttk.Treeview):
        logger.info(f"Query button pressed, initiate find request...")
        # Clear tree:
        tree.delete(*tree.get_children())
        ux_Q = Queue()
        req: FindRequest = FindRequest(
            DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False),
            DICOMNode(scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True),
            patient_name_var.get(),
            patient_id_var.get(),
            accession_no_var.get(),
            study_date_var.get(),
            modality_var.get(),
            ux_Q,
        )
        find_ex(req)
        # Start FindResponse monitor:
        tree.after(ux_poll_find_response_interval, monitor_query_response, ux_Q, tree)

    # TODO: only enable retrieve if storage scp is running:
    def retrieve_button_pressed():
        uids = list(tree.selection())
        logger.info(f"Retrieve button pressed")
        logger.info(f"Retrieving StudyInstanceUIDs: {uids}")

        dest_scp_aet = get_storage_scp_aet()
        if dest_scp_aet is None:
            logger.error(f"Storage SCP AET is None. Is it running?")
            return

        # Create 1 UX queue to handle the full move / retrieve operation
        ux_Q = Queue()
        scu = DICOMNode(scu_ip_var.get(), 0, scu_aet_var.get(), False)
        scp = DICOMNode(scp_ip_var.get(), scp_port_var.get(), scp_aet_var.get(), True)

        for uid in uids:
            req = MoveRequest(scu, scp, dest_scp_aet, uid, ux_Q)
            move_ex(req)

    # Create a Scrollbar and associate it with the Treeview
    scrollbar = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    scrollbar.grid(row=2, column=11, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    query_button = ctk.CTkButton(
        query_param_frame, text=_("Query"), command=lambda: query_button_pressed(tree)
    )
    query_button.grid(row=2, column=4, padx=PAD, pady=PAD, sticky="nswe")

    retrieve_button = ctk.CTkButton(
        query_param_frame, text=_("Import & Anonymize"), command=retrieve_button_pressed
    )
    retrieve_button.grid(row=2, column=5, padx=PAD, pady=PAD, sticky="nswe")
