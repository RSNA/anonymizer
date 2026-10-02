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

import contextlib
import logging
import tkinter as tk

import customtkinter as ctk

from anonymizer.model.settings_limits import (
    AET_MAX_CHARS,
    AET_MIN_CHARS,
    IP_MAX_CHARS,
    IP_MIN_CHARS,
    IP_PORT_MAX,
    IP_PORT_MIN,
)
from anonymizer.view.common.fonts import default_char_width_px


def _focus_entry_cursor_at_end(entry: ctk.CTkEntry) -> None:
    """Focus ``entry`` and place the insert cursor after the last character."""

    def _place() -> None:
        with contextlib.suppress(tk.TclError):
            entry.focus_set()
            entry.icursor("end")

    # Defer until the hosting window is mapped (e.g. modal built while withdrawn).
    def _on_map(_event=None) -> None:
        with contextlib.suppress(tk.TclError):
            entry.unbind("<Map>")
        entry.after_idle(_place)

    with contextlib.suppress(tk.TclError):
        if bool(entry.winfo_ismapped()):
            entry.after_idle(_place)
        else:
            entry.bind("<Map>", _on_map, add="+")

# Entry Limits (re-export from settings_limits — keystroke behavior unchanged):

# Network Addresses:
ip_min_chars = IP_MIN_CHARS
ip_max_chars = IP_MAX_CHARS
aet_min_chars = AET_MIN_CHARS
aet_max_chars = AET_MAX_CHARS
ip_port_min = IP_PORT_MIN
ip_port_max = IP_PORT_MAX

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


def validate_int_entry(final_value: str, *, allow_negative: bool, max_chars: int) -> bool:
    """Keystroke filter for integer fields (optional leading minus when signed)."""
    if final_value == "":
        return True
    if allow_negative and final_value == "-":
        return True
    body = final_value[1:] if allow_negative and final_value.startswith("-") else final_value
    if not body.isdigit():
        return False
    return len(final_value) <= max_chars


def _validatecommand(
    view: ctk.CTkFrame | ctk.CTkToplevel,
    allowed_chars: str,
    max_chars: int | None,
) -> tuple:
    """Tk validatecommand that only substitutes ``%P``.

    Charset / max are closed over in Python — never passed as Tcl words. That
    avoids breakage when ``allowed_chars`` contains spaces or Tcl metacharacters
    (e.g. ``string.printable`` used for username/password fields).
    """
    max_s: str | None = None if max_chars is None else str(max_chars)

    def _validate(final_value: str) -> bool:
        return validate_entry(final_value, allowed_chars, max_s)

    return (view.register(_validate), "%P")


def _int_validatecommand(
    view: ctk.CTkFrame | ctk.CTkToplevel,
    *,
    allow_negative: bool,
    max_chars: int,
) -> tuple:
    def _validate(final_value: str) -> bool:
        return validate_int_entry(final_value, allow_negative=allow_negative, max_chars=max_chars)

    return (view.register(_validate), "%P")


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

    char_width_px = default_char_width_px()
    width_px = (max_chars + 3) * char_width_px if width_chars == 20 and max_chars else (width_chars + 3) * char_width_px
    if not enabled:
        ctk_entry = ctk.CTkLabel(view, textvariable=str_var)
    else:
        ctk_entry = ctk.CTkEntry(
            view,
            width=width_px,
            textvariable=str_var,
            validate="key",
            validatecommand=_validatecommand(view, charset, max_chars),
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

    if focus_set and enabled:
        _focus_entry_cursor_at_end(ctk_entry)
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
    # NOTE: `customtkinter.CTkEntry` reads `textvariable` during an internal callback
    # while the user is typing. Passing a `ctk.IntVar` as `textvariable` crashes
    # when the entry is temporarily empty (`""`) because `IntVar.get()` throws.
    #
    # Fix: bind the entry widget to a `ctk.StringVar` (safe for empty text) and
    # mirror it into the returned `ctk.IntVar`.
    int_var = ctk.IntVar(view, value=initial_value)
    text_var = ctk.StringVar(view, value=str(initial_value))
    allow_negative = min < 0
    # ``min``/``max`` shadow builtins — compute char width without calling ``max()``.
    hi_chars = len(str(max))
    lo_chars = len(str(min))
    max_chars = hi_chars if hi_chars >= lo_chars else lo_chars
    # TODO: why is this not accurate?
    digit_width_px = default_char_width_px()
    width = (max_chars + 3) * digit_width_px
    ctk_label = ctk.CTkLabel(view, text=label)
    ctk_label.grid(row=row, column=col, padx=pad, pady=(pad, 0), sticky=sticky)
    ctk_entry = ctk.CTkEntry(
        view,
        width=width,
        textvariable=text_var,
        validate="key",
        validatecommand=_int_validatecommand(
            view, allow_negative=allow_negative, max_chars=max_chars
        ),
    )

    def entry_callback(event):
        # Keep empty text editable and avoid forcing a value while the user clears.
        if text_var.get() == "":
            return
        if text_var.get() == "-":
            return
        int_entry_change(event, int_var, min, max)
        # Normalize the visible text after range clamping on commit.
        text_var.set(str(int_var.get()))

    def _sync_int_from_text(*_args) -> None:
        """Keep `int_var` in sync while typing without rewriting user input."""
        text = text_var.get()
        if text == "" or text == "-":
            return
        try:
            value = int(text)
        except ValueError:
            return
        if int_var.get() != value:
            int_var.set(value)

    def _sync_text_from_int(*_args) -> None:
        """Keep the entry text in sync when code calls ``int_var.set``."""
        try:
            value = int_var.get()
        except Exception:
            return
        text = str(value)
        if text_var.get() != text:
            text_var.set(text)

    ctk_entry.bind("<Return>", entry_callback)
    ctk_entry.bind("<FocusOut>", entry_callback)
    ctk_entry.grid(row=row, column=col + 1, padx=pad, pady=(pad, 0), sticky="nw")

    if focus_set:
        _focus_entry_cursor_at_end(ctk_entry)

    text_var.trace_add("write", _sync_int_from_text)
    int_var.trace_add("write", _sync_text_from_int)
    return int_var
