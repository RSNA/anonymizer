import utils.config as config
import tkinter as tk
import customtkinter as ctk


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
    config.save(__name__, config_name, var.get())


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
