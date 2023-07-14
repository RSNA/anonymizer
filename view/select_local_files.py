import os
from pathlib import Path
from pydicom.misc import is_dicom
from typing import Sequence
import customtkinter as ctk
from tkinter import Tk, filedialog
from CTkToolTip import *  # TOD: see CtkThemeBuilder source for including CTkToolTip source
import logging
from pydicom import dcmread
from controller.anonymize import anonymize_dataset
from utils.translate import _
from view.storage_dir import storage_directory

logger = logging.getLogger(__name__)

file_extension_filters = [
    ("dcm Files", "*.dcm"),
    ("dicom Files", "*.dicom"),
    ("All Files", "*.*"),
]


def _insert_files_into_textbox(
    textbox: ctk.CTkTextbox, file_paths: Sequence[str], anonymize_button: ctk.CTkButton
):
    if file_paths:
        for file_path in file_paths:
            if os.path.isfile(file_path) and is_dicom(file_path):
                textbox.configure(state="normal")
                textbox.insert(ctk.END, file_path + "\n")
                anonymize_button.configure(state="normal")
                textbox.configure(state="disabled")
        textbox.see(ctk.END)


def _open_file_dialog(textbox: ctk.CTkTextbox, anonymize_button: ctk.CTkButton):
    paths = filedialog.askopenfilenames(
        filetypes=file_extension_filters
    )  # for multiple files
    if paths:
        _insert_files_into_textbox(textbox, paths, anonymize_button)


def _open_directory_dialog(
    textbox: ctk.CTkTextbox,
    anonymize_button: ctk.CTkButton,
    recurse: bool = True,
):
    logging.info(f"open_directory_dialog recurse:{recurse}")
    path = filedialog.askdirectory()  # for directory
    if path:
        if recurse:
            # Recurse into subdirectories
            for root, dirs, files in os.walk(path):
                file_paths = [os.path.join(root, file) for file in files]
                _insert_files_into_textbox(textbox, file_paths, anonymize_button)
        else:
            # Only consider files in the top-level directory
            file_paths = [
                os.path.join(path, file)
                for file in os.listdir(path)
                if os.path.isfile(os.path.join(path, file))
            ]
            _insert_files_into_textbox(textbox, file_paths, anonymize_button)


# Read the DICOM files one by one into memory and anonymize them
# Do not store any PHI on disk in temp files etc.
def anonymize_files(files: list[str]):
    logging.info(f"anonymize files:{files}")
    for file in files:
        ds = dcmread(file)
        anonymize_dataset(ds)
        ds.save_as(Path(storage_directory, file))


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Select Local Files View")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(2, weight=1)

    # Selected Local Files Scrollable Text Box:
    selected_files = ctk.CTkTextbox(view, wrap="none", state="disabled")
    selected_files.grid(row=1, columnspan=3, sticky="nswe")

    overlay_label = ctk.CTkLabel(
        selected_files,
        text=_(
            "Add local DICOM files to anonymize by clicking Select File(s) or Select Directory above"
        ),
    )
    overlay_label.place(relx=0.5, rely=0.5, anchor="center")

    def textbox_change(event):
        overlay_label.place_forget()

    selected_files.bind("<<Modified>>", textbox_change)

    # TODO: add ability to drag and drop files into textbox, see https://github.com/TomSchimansky/CustomTkinter/issues/934

    anonymize_button = ctk.CTkButton(
        view,
        text=_("Anonymize"),
        state="disabled",
        command=anonymize_files(selected_files.get("1.0", ctk.END).split("\n")),
    )
    anonymize_button.grid(row=2, column=2, padx=PAD, pady=PAD, sticky="e")

    select_files_button = ctk.CTkButton(
        view,
        text=_("Select File(s)"),
        command=lambda: _open_file_dialog(selected_files, anonymize_button),
    )
    select_files_button.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nw")

    recurse_subdirs_var = ctk.BooleanVar(view, value=True)
    recurse_subdirs_checkbox = ctk.CTkCheckBox(
        view, text=_("Include Subdirectories"), variable=recurse_subdirs_var
    )
    recurse_subdirs_checkbox.grid(row=0, column=2, padx=PAD, pady=PAD, sticky="nw")

    select_dir_button = ctk.CTkButton(
        view,
        text=_("Select Directory"),
        command=lambda: _open_directory_dialog(
            selected_files, anonymize_button, recurse_subdirs_var.get()
        ),
    )
    select_dir_button.grid(row=0, column=1, padx=PAD, pady=PAD, sticky="nw")
