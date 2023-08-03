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


# Entry field callback functions for validating user input and saving to config.json:
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
    module_name: str,
    config_name: str,
) -> None:
    try:
        value = var.get()
    except:
        value = 0
    if value > max:
        var.set(max)
    elif value < min:
        var.set(min)
    config.save(module_name, config_name, var.get())


def str_entry_change(
    event: tk.Event,
    var: ctk.StringVar,
    min_len: int,
    max_len: int,
    module_name: str,
    config_name: str,
) -> None:
    value = var.get()
    if len(value) > max_len:
        var.set(value[:max_len])
    elif len(value) < min_len:
        var.set(value[:min_len])
    config.save(module_name, config_name, var.get())


def str_entry(
    view,
    var,
    validate_entry_cmd,
    char_width_px,
    label,
    min_chars,
    max_chars,
    charset,
    tooltipmsg,
    row,
    col,
    pad,
    sticky,
    default=None,
):
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    ctk_entry = ctk.CTkEntry(
        view,
        width=int(max_chars * char_width_px),
        textvariable=var,
        validate="key",
        validatecommand=(
            validate_entry_cmd,
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
        event, var, min_chars, max_chars, view.winfo_name(), label
    )
    ctk_entry.bind("<Return>", entry_callback)
    ctk_entry.bind("<FocusOut>", entry_callback)
    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")
