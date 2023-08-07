import string
import customtkinter as ctk
from numpy import pad
import pandas as pd
from tkinter import ttk, font
from CTkToolTip import CTkToolTip
import logging
from utils.translate import _
import utils.config as config
from utils.network import get_local_ip_addresses
from utils.ux_verify import (
    validate_entry,
    int_entry_change,
    str_entry_change,
    str_entry,
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
)
from utils.logging import install_loghandler

# import controller.dicom_QR_find_scu as dicom_QR_find_scu
import controller.dicom_echo_send_scu as dicom_echo_send_scu
import controller.dicom_QR_find_scu as dicom_QR_find_scu


logger = logging.getLogger(__name__)

# Default values for initialising UX ctk.Vars (overwritten at startup from config.json):
scp_ip_addr = "127.0.0.1"
scp_ip_port = 104
scp_aet = "RSNA"
scu_ip_addr = "127.0.0.1"
scu_aet = "ANONSCU"

# C-FIND DICOM attributes to display in the results Treeview:
attr_map = {
    "PatientName": _("Patient Name"),
    "PatientID": _("Patient ID"),
    "StudyDate": _("Study Date"),
    "StudyDescription": _("Study Description"),
    "AccessionNumber": _("Accession No."),
    "ModalitiesInStudy": _("Modality"),
    "NumberOfStudyRelatedSeries": _("Series"),
    "NumberOfStudyRelatedInstances": _("Instances"),
    "StudyInstanceUID": _("StudyInstanceUID"),  # not for display, for retrieve
}

# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def adjust_column_width(tree, column_id, padding=10):
    """
    Adjust the width of a column in a ttk.Treeview to fit its content.

    Parameters:
    - tree: The Treeview widget.
    - column_id: The identifier of the column to be adjusted.
    - padding: Extra space added to the width (default is 10 pixels).
    """

    # Start with the width of the column header
    max_width = font.Font().measure(column_id)

    # Iterate over each item in the column
    for item in tree.get_children():
        item_value = tree.set(item, column_id)
        item_width = font.Font().measure(item_value)

        # Update max_width if this value is wider than any previously checked
        max_width = max(max_width, item_width)

    # Adjust the column width
    tree.column(column_id, width=max_width + padding)


def create_view(view: ctk.CTkFrame, PAD: int):
    logger.info(f"Creating Configure DICOM Query/Retrieve SCU View")
    char_width_px = ctk.CTkFont().measure("A")
    digit_width_px = ctk.CTkFont().measure("9")
    validate_entry_cmd = view.register(validate_entry)
    logger.info(f"Font Character Width in pixels: ±{char_width_px}")
    view.grid_rowconfigure(2, weight=1)
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

    # Q/R SCP IP Address:
    def scp_echo_button_event(scp_button: ctk.CTkButton):
        logger.info(f"scp_button_event Echo to {scp_aet_var.get()}...")
        scp_button.configure(text_color="light grey")
        # Echo SCP:
        if dicom_echo_send_scu.echo(
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
    scp_label = ctk.CTkLabel(view, text=_("Remote Server:"))
    scp_label.grid(row=0, column=1, pady=(PAD, 0), sticky="nw")
    # TODO: tooltip causes TclError on program close
    # scp_label_tooltip = CTkToolTip(scp_label, message=_("Remote DICOM Storage SCP"))

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
    scp_ip_entry.grid(row=0, column=2, pady=(PAD, 0), padx=PAD, sticky="nw")

    # Q/R SCP IP Port:
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

    # Q/R SCP AET:
    scp_aet_label = ctk.CTkLabel(view, text=_("AET:"))
    scp_aet_label.grid(row=0, column=5, pady=(PAD, 0), sticky="nw")

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
        message=_(
            f"Remote AE Title uppercase alphanumeric [{aet_min_chars}..{aet_max_chars}] chars"
        ),
    )
    entry_callback = lambda event: str_entry_change(
        event, scp_aet_var, aet_min_chars, aet_max_chars, __name__, "scp_aet"
    )
    scp_aet_entry.bind("<Return>", entry_callback)
    scp_aet_entry.bind("<FocusOut>", entry_callback)
    scp_aet_entry.grid(row=0, column=6, pady=(PAD, 0), padx=PAD, sticky="nw")

    # Q/R SCU IP Address:
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

    # Q/R SCU AET:
    scp_aet_label = ctk.CTkLabel(view, text=_("AET:"))
    scp_aet_label.grid(row=0, column=9, pady=(PAD, 0), sticky="nw")
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
    scu_aet_entry.grid(row=0, column=10, pady=(PAD, 0), padx=PAD, sticky="nw")

    # QUERY PARAMETERS:
    # Create new frame
    query_param_frame = ctk.CTkFrame(view)
    # query_param_frame.grid_rowconfigure(0, weight=1)
    # query_param_frame.grid_columnconfigure(0, weight=1)
    query_param_frame.grid(row=1, pady=(PAD, 0), columnspan=11, sticky="nswe")
    # Patient Name
    patient_name_var = ctk.StringVar(view)
    str_entry(
        query_param_frame,
        patient_name_var,
        validate_entry_cmd,
        char_width_px,
        label=_("Patient Name:"),
        min_chars=0,
        max_chars=patient_name_max_chars,
        charset=string.ascii_letters + string.digits + "*",
        tooltipmsg="Alpha-numeric, * for wildcard",
        row=0,
        col=0,
        pad=PAD,
        sticky="nw",
    )
    # Patient ID
    patient_id_var = ctk.StringVar(view)
    str_entry(
        query_param_frame,
        patient_id_var,
        validate_entry_cmd,
        char_width_px,
        label=_("Patient ID:"),
        min_chars=0,
        max_chars=patient_name_max_chars,
        charset=string.ascii_letters + string.digits + "*",
        tooltipmsg="Alpha-numeric, * for wildcard",
        row=1,
        col=0,
        pad=PAD,
        sticky="nw",
    )
    # Accession No.
    accession_no_var = ctk.StringVar(view)
    str_entry(
        query_param_frame,
        accession_no_var,
        validate_entry_cmd,
        char_width_px,
        label=_("Accession No.:"),
        min_chars=0,
        max_chars=patient_name_max_chars,
        charset=string.ascii_letters + string.digits + " */-_",
        tooltipmsg="Alpha-numeric, * for wildcard",
        row=2,
        col=0,
        pad=PAD,
        sticky="nw",
    )

    # Study Date:
    study_date_var = ctk.StringVar(view)
    str_entry(
        query_param_frame,
        study_date_var,
        validate_entry_cmd,
        char_width_px,
        label=_("Study Date:"),
        min_chars=dicom_date_chars,
        max_chars=dicom_date_chars,
        charset=string.digits + "*",
        tooltipmsg="Numeric YYYYMMDD, * for wildcard",
        row=0,
        col=3,
        pad=PAD,
        sticky="nw",
    )

    # Modality:
    modality_var = ctk.StringVar(view)
    str_entry(
        query_param_frame,
        modality_var,
        validate_entry_cmd,
        char_width_px + 4,
        label=_("Modality:"),
        min_chars=modality_min_chars,
        max_chars=modality_max_chars,
        charset=string.ascii_uppercase,
        tooltipmsg="Modality Code",
        row=1,
        col=3,
        pad=PAD,
        sticky="nw",
    )

    # Managing C-FIND results Treeview:
    def update_treeview_data(tree: ttk.Treeview, data: pd.DataFrame):
        # Clear existing items
        for item in tree.get_children():
            tree.delete(item)

        # Insert new data

        for index, row in data.iterrows():
            display_values = [
                val for col, val in row.items() if col != "StudyInstanceUID"
            ]
            tree.insert("", "end", iid=row["StudyInstanceUID"], values=display_values)

        for col_id in tree["columns"]:
            adjust_column_width(tree, col_id, padding=5)

    # Query Button:
    # TODO: query on <Return> // move to next query entry on <Return>
    def query_button_pressed(tree: ttk.Treeview):
        logger.info(f"Query button pressed")
        results = dicom_QR_find_scu.find(
            scp_ip_var.get(),
            scp_port_var.get(),
            scp_aet_var.get(),
            scu_ip_var.get(),
            scu_aet_var.get(),
            patient_name_var.get(),
            patient_id_var.get(),
            accession_no_var.get(),
            study_date_var.get(),
            modality_var.get(),
        )
        # Create Pandas DataFrame from results and display in Treeview:
        if results:
            # List the DICOM attributes in the desired order using the keys from the mapping
            ordered_attrs = list(attr_map.keys())
            data_dicts = [
                {
                    attr_map[attr]: getattr(ds, attr, None)
                    for attr in ordered_attrs
                    if hasattr(ds, attr)
                }
                for ds in results
            ]
            df = pd.DataFrame(data_dicts)

            # Update column headers only if they've changed
            current_cols = list(tree["columns"])
            if current_cols != list(df.columns):
                tree["columns"] = [
                    col for col in df.columns if col != "StudyInstanceUID"
                ]
                for col in tree["columns"]:
                    tree.heading(col, text=col)

            # Update the treeview with the new data
            update_treeview_data(tree, df)
        else:
            logger.info(f"No results returned")

    tree = ttk.Treeview(view, show="headings")
    tree.grid(row=2, column=0, columnspan=11, sticky="nswe")

    def retrieve_button_pressed():
        uids = list(tree.selection())
        logger.info(f"Retrieving StudyInstanceUIDs: {uids}")

    # Create a Scrollbar and associate it with the Treeview
    scrollbar = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    scrollbar.grid(row=2, column=11, sticky="ns")
    tree.configure(yscrollcommand=scrollbar.set)

    query_button = ctk.CTkButton(
        query_param_frame, text=_("Query"), command=lambda: query_button_pressed(tree)
    )
    query_button.grid(row=2, column=4, padx=PAD, pady=PAD, sticky="nswe")

    retrieve_button = ctk.CTkButton(
        query_param_frame, text=_("Retrieve"), command=retrieve_button_pressed
    )
    retrieve_button.grid(row=2, column=5, padx=PAD, pady=PAD, sticky="nswe")

    # SCU Client Log:
    scu_log = ctk.CTkTextbox(
        view,
        wrap="none",
    )

    install_loghandler(dicom_echo_send_scu.logger, scu_log)
    install_loghandler(dicom_QR_find_scu.logger, scu_log)
    scu_log.grid(row=3, pady=(PAD, 0), columnspan=11, sticky="swe")
