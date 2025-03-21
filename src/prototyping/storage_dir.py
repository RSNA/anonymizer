import customtkinter as ctk
from tkinter import filedialog
import logging
import prototyping.config as config

logger = logging.getLogger(__name__)

# Initialize storage directory
storage_directory = ""


def get_storage_directory():
    return storage_directory


# Load module globals from config.json
settings = config.load(__name__)
globals().update(settings)


def open_directory_dialog(label: ctk.CTkLabel):
    global storage_directory
    path = filedialog.askdirectory()
    if path:
        storage_directory = path
        label.configure(text=storage_directory)
        config.save(__name__, "storage_directory", storage_directory)


def create_view(view: ctk.CTkFrame, name: str):
    PAD = 10
    logger.info(f"Creating {name} View")

    button = ctk.CTkButton(
        view,
        text=name,
        command=lambda: open_directory_dialog(storage_directory_label),
    )
    button.grid(row=0, column=0, pady=PAD, sticky="nw")

    storage_directory_label = ctk.CTkLabel(view, text=storage_directory)
    storage_directory_label.grid(row=0, column=1, pady=PAD, padx=PAD, sticky="nw")
