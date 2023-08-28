# User Interface Field Validation & Utilities
import string
import utils.config as config
import tkinter as tk
import customtkinter as ctk
from CTkToolTip import CTkToolTip
from utils.translate import _

# Entry Limits:

# Network Addresses:
ip_min_chars = 7
ip_max_chars = 15
aet_min_chars = 3
aet_max_chars = 16
ip_port_min = 104
ip_port_max = 65535

# DICOM Query Fields:
patient_name_max_chars = 30  # dicomVR PN=64 max
patient_id_max_chars = 30  # dicomVR LO=64 max
accession_no_max_chars = 16  # dicomVR SH=16 max
dicom_date_chars = 8  # dicomVR DA=8 max
modality_min_chars = 2  # dicomVR CS=16 max
modality_max_chars = 3  # dicomVR CS=16 max

# UX Monitor  (find, move, export)
ux_poll_find_response_interval = 500  # milli-seconds
ux_poll_export_response_interval = 300  # milli-seconds
ux_poll_move_response_interval = 500  # milli-seconds
ux_poll_local_storage_interval = 1000  # milli-seconds


# Entry field callback functions for
# validating user input and saving update to config.json:
def validate_entry(final_value: str, allowed_chars: str, max: str):
    # BUG: max is always a string, so convert to int
    if len(final_value) > int(max):
        return False
    for char in final_value:
        if char not in allowed_chars:
            return False
    return True


def int_entry_change(
    event: tk.Event,
    var: ctk.IntVar,
    min: int,
    max: int,
    module_name: str | None = None,
    var_name: str | None = None,
) -> None:
    try:
        value = var.get()
    except:
        value = 0
    if value > max:
        var.set(max)
    elif value < min:
        var.set(min)
    config.save(module_name, var_name, var.get())


def str_entry_change(
    event: tk.Event,
    var: ctk.StringVar,
    min_len: int,
    max_len: int,
    module_name: str | None = None,
    var_name: str | None = None,
) -> None:
    value = var.get()
    if len(value) > max_len:
        var.set(value[:max_len])
    elif len(value) < min_len:
        var.set(value[:min_len])
    if module_name and var_name:
        config.save(module_name, var_name, var.get())


def str_entry(
    view: ctk.CTkFrame,
    label: str,
    initial_value: str,
    min_chars: int,
    max_chars: int,
    charset: str,
    tooltipmsg: str,
    row: int,
    col: int,
    pad: int,
    sticky: str,
    module: str | None = None,
    var_name: str | None = None,
):
    str_var = ctk.StringVar(view, value=initial_value)
    char_width_px = ctk.CTkFont().measure("A")
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    ctk_entry = ctk.CTkEntry(
        view,
        width=int(max_chars * char_width_px),
        textvariable=str_var,
        validate="key",
        validatecommand=(
            view.winfo_toplevel().validate_entry_cmd,  # type: ignore
            "%P",
            charset,
            str(max_chars),
        ),
    )
    entry_tooltip = CTkToolTip(
        ctk_entry,
        message=_(f"{tooltipmsg} [{min_chars}..{max_chars}] chars"),
    )

    entry_callback = lambda event: str_entry_change(
        event, str_var, min_chars, max_chars, module, var_name
    )
    ctk_entry.bind("<Return>", entry_callback)
    ctk_entry.bind("<FocusOut>", entry_callback)
    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")
    return str_var


def int_entry(
    view: ctk.CTkFrame,
    label: str,
    initial_value: int,
    min: int,
    max: int,
    tooltipmsg: str,
    row: int,
    col: int,
    pad: int,
    sticky: str,
    module: str | None = None,
    var_name: str | None = None,
) -> ctk.IntVar:
    int_var = ctk.IntVar(view, value=initial_value)
    max_chars = len(str(max))
    digit_width_px = ctk.CTkFont().measure("A") + 2
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    ctk_entry = ctk.CTkEntry(
        view,
        width=round(max_chars * digit_width_px),
        textvariable=int_var,
        validate="key",
        validatecommand=(
            view.winfo_toplevel().validate_entry_cmd,  # type: ignore
            "%P",
            string.digits,
            max_chars,
        ),
    )
    entry_tooltip = CTkToolTip(
        ctk_entry,
        message=_(f"{tooltipmsg} [{min}..{max}]"),
    )

    entry_callback = lambda event: int_entry_change(
        event, int_var, min, max, module, var_name
    )
    ctk_entry.bind("<Return>", entry_callback)
    ctk_entry.bind("<FocusOut>", entry_callback)
    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")
    return int_var
