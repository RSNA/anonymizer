"""
User Interface Field Validation & Utilities

This module provides utility functions and classes for validating and manipulating user interface fields in a graphical user interface (GUI) application.

Functions:
- validate_entry() -> bool: Validates the final_value based on the allowed_chars and max length.
- int_entry_change() -> None: Updates the value of an IntVar based on the user input in an entry widget.
- str_entry_change() -> None: Updates the value of a StringVar based on the length constraints.
- str_entry() -> ctk.StringVar: Creates a string entry field in the specified view.
- int_entry() -> ctk.IntVar: Creates an integer entry field with label, initial value, and range.
"""

import logging
import string
import tkinter as tk

import customtkinter as ctk

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


def validate_entry(final_value: str, allowed_chars: str, max: str | None) -> bool:
    """
    Validates the final_value based on the allowed_chars and max length.

    Args:
        final_value (str): The value to be validated.
        allowed_chars (str): The characters allowed in the final_value.
        max (str | None): The maximum length allowed for the final_value.

    Returns:
        bool: True if the final_value is valid, False otherwise.
    """
    if max and max != "None" and len(final_value) > int(max):
        return False
    return all(char in allowed_chars for char in final_value)


def int_entry_change(
    event: tk.Event,
    int_var: ctk.IntVar,
    min: int,
    max: int,
) -> None:
    """
    Update the value of an IntVar based on the user input in an entry widget.

    Args:
        event (tk.Event): The event object triggered by the user action.
        int_var (ctk.IntVar): The IntVar to be updated.
        min (int): The minimum allowed value.
        max (int): The maximum allowed value.

    Returns:
        None
    """
    try:
        value = int_var.get()
    except Exception as e:
        logging.error(f"int_entry_change: {e}")
        return

    if value > max:
        int_var.set(max)
    elif value < min:
        int_var.set(min)


def str_entry_change(
    event: tk.Event,
    var: ctk.StringVar,
    min_len: int,
    max_len: int | None,
) -> None:
    """
    Update the value of a StringVar based on the length constraints.

    Args:
        event (tk.Event): The event that triggered the change.
        var (ctk.StringVar): The StringVar to be updated.
        min_len (int): The minimum length constraint.
        max_len (int | None): The maximum length constraint. None if there is no maximum length.

    Returns:
        None
    """
    value = var.get()
    if max_len and len(value) > max_len:
        var.set(value[:max_len])
    elif len(value) < min_len:
        var.set(value[:min_len])


def str_entry(
    view: ctk.CTkFrame | ctk.CTkToplevel,
    label: str,
    initial_value: str,
    min_chars: int,
    max_chars: int | None,
    charset: str,
    tooltipmsg: str | None,
    row: int,
    col: int,
    pad: int,
    sticky: str,
    enabled: bool = True,
    width_chars: int = 20,
    focus_set=False,
    password=False,
) -> ctk.StringVar:
    """
    Creates a string entry field in the specified view.

    Args:
        view (ctk.CTkFrame | ctk.CTkToplevel): The parent view where the string entry field will be placed.
        label (str): The label text for the string entry field.
        initial_value (str): The initial value of the string entry field.
        min_chars (int): The minimum number of characters allowed in the string entry field.
        max_chars (int | None): The maximum number of characters allowed in the string entry field. None if there is no maximum limit.
        charset (str): The character set allowed in the string entry field.
        tooltipmsg (str | None): The tooltip message for the string entry field. None if no tooltip is needed.
        row (int): The row index where the string entry field will be placed in the view.
        col (int): The column index where the string entry field will be placed in the view.
        pad (int): The padding value for the string entry field.
        sticky (str): The sticky value for the string entry field.
        enabled (bool, optional): Whether the string entry field is enabled or disabled. Defaults to True.
        width_chars (int, optional): The width of the string entry field in characters. Defaults to 20. If this is left at default then max_chars is used if specified.
        focus_set (bool, optional): Whether the string entry field should have focus. Defaults to False.

    Returns:
        ctk.StringVar: The string variable associated with the string entry field.
    """
    str_var = ctk.StringVar(view, value=initial_value)

    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)

    char_width_px = ctk.CTkFont().measure("A")
    width_px = (max_chars + 3) * char_width_px if width_chars == 20 and max_chars else (width_chars + 3) * char_width_px
    if not enabled:
        ctk_entry = ctk.CTkLabel(view, textvariable=str_var)
    else:
        ctk_entry = ctk.CTkEntry(
            view,
            width=width_px,
            textvariable=str_var,
            validate="key",
            validatecommand=(
                view.register(validate_entry),
                "%P",
                charset,
                None if max_chars is None else str(max_chars),
            ),
        )

        if password:
            ctk_entry.configure(show="*")

        def entry_callback(event):
            return str_entry_change(
                event,
                str_var,
                min_chars,
                max_chars,
            )

        ctk_entry.bind("<Return>", entry_callback)
        ctk_entry.bind("<FocusOut>", entry_callback)

    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")

    if focus_set:
        ctk_entry.focus_set()
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
    focus_set=False,
) -> ctk.IntVar:
    """
    Create an integer entry field with label, initial value, and range.

    Args:
        view (ctk.CTkFrame | ctk.CTkToplevel): The parent view for the entry field.
        label (str): The label text for the entry field.
        initial_value (int): The initial value for the entry field.
        min (int): The minimum value allowed for the entry field.
        max (int): The maximum value allowed for the entry field.
        tooltipmsg (str | None): The tooltip message for the entry field.
        row (int): The row position of the entry field in the grid.
        col (int): The column position of the entry field in the grid.
        pad (int): The padding value for the entry field.
        sticky (str): The sticky value for the entry field.
        focus_set (bool, optional): Whether to set the focus on the entry field. Defaults to False.

    Returns:
        ctk.IntVar: The integer variable associated with the entry field.
    """
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
        # TODO: ctk docs state this should be a string var,
        # it works with Int var but raises TclError if entry is empty
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

    def entry_callback(event):
        return int_entry_change(event, int_var, min, max)

    ctk_entry.bind("<Return>", entry_callback)
    ctk_entry.bind("<FocusOut>", entry_callback)
    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")

    if focus_set:
        ctk_entry.focus_set()

    return int_var
