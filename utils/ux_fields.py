# User Interface Field Validation & Utilities
import string
import prototyping.config as config
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
    if module_name and var_name:
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
    view: ctk.CTkFrame | ctk.CTkToplevel,
    label: str,
    initial_value: str,
    min_chars: int,
    max_chars: int,
    charset: str,
    tooltipmsg: str | None,
    row: int,
    col: int,
    pad: int,
    sticky: str,
    module: str | None = None,
    var_name: str | None = None,
    enabled: bool = True,
) -> ctk.StringVar:
    str_var = ctk.StringVar(view, value=initial_value)
    char_width_px = ctk.CTkFont().measure("_")
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    width = (max_chars + 3) * char_width_px  # TO DO: this approach is not accurate

    if not enabled:
        ctk_entry = ctk.CTkLabel(view, textvariable=str_var)
    else:
        ctk_entry = ctk.CTkEntry(
            view,
            width=width,
            textvariable=str_var,
            validate="key",
            validatecommand=(
                view.register(validate_entry),
                "%P",
                charset,
                str(max_chars),
            ),
        )

        if tooltipmsg:
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
    view: ctk.CTkFrame | ctk.CTkToplevel,
    label: str,
    initial_value: int,
    min: int,
    max: int,
    tooltipmsg: str | None,
    row: int,
    col: int,
    pad: int,
    sticky: str,
    module: str | None = None,
    var_name: str | None = None,
) -> ctk.IntVar:
    int_var = ctk.IntVar(view, value=initial_value)
    max_chars = len(str(max))
    # TODO: why is this not accurate?
    digit_width_px = ctk.CTkFont().measure("A")
    width = (max_chars + 3) * digit_width_px
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    ctk_entry = ctk.CTkEntry(
        view,
        width=width,
        textvariable=int_var,
        validate="key",
        validatecommand=(
            # view.winfo_toplevel().validate_entry_cmd,  # type: ignore
            view.register(validate_entry),
            "%P",
            string.digits,
            max_chars,
        ),
    )

    if tooltipmsg:
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
