import os
from pathlib import Path
from pydicom.misc import is_dicom
from typing import Sequence
import customtkinter as ctk
from tkinter import Tk, filedialog
from CTkToolTip import CTkToolTip
import logging
from pydicom import dcmread
from controller.anonymize import anonymize_dataset
from utils.translate import _
from view.storage_dir import storage_directory
from utils.storage import local_storage_path
import model.project as project

# The following unused imports are for pyinstaller
# TODO: pyinstaller cmd line special import doesn't work
from pydicom.encoders import (
    pylibjpeg,
    gdcm,
)

logger = logging.getLogger(__name__)

file_extension_filters = [
    ("dcm Files", "*.dcm"),
    ("dicom Files", "*.dicom"),
    ("All Files", "*.*"),
]


def _insert_files_into_textbox(textbox: ctk.CTkTextbox, file_paths: Sequence[str]):
    if file_paths:
        textbox.configure(state="normal")
        for file_path in file_paths:
            if os.path.isfile(file_path) and is_dicom(file_path):
                textbox.insert(ctk.INSERT, file_path + "\n")
        textbox.configure(state="disabled", cursor="arrow")
        textbox.see(ctk.END)


def _open_file_dialog(textbox: ctk.CTkTextbox, anonymize_button: ctk.CTkButton):
    logging.info(f"anonymous_button:{anonymize_button._state}")
    paths = filedialog.askopenfilenames(
        filetypes=file_extension_filters
    )  # for multiple files
    if paths:
        _insert_files_into_textbox(textbox, paths)
        anonymize_button.configure(state="normal")


def _open_directory_dialog(
    textbox: ctk.CTkTextbox,
    anonymize_button: ctk.CTkButton,
    recurse: bool = True,
):
    logging.info(f"recurse:{recurse}")
    path = filedialog.askdirectory(title=_("Select DICOM Directory"))
    if path:
        if recurse:
            # Recurse into subdirectories
            for root, dirs, files in os.walk(path):
                file_paths = [os.path.join(root, file) for file in files]
                _insert_files_into_textbox(textbox, file_paths)
        else:
            # Only consider files in the top-level directory
            file_paths = [
                os.path.join(path, file)
                for file in os.listdir(path)
                if os.path.isfile(os.path.join(path, file))
            ]
            _insert_files_into_textbox(textbox, file_paths)
        anonymize_button.configure(state="normal")


# Read the DICOM files one by one into memory and anonymize them
# Do not store any PHI on disk in temp files etc.
def anonymize_files(textbox: ctk.CTkTextbox, anonymize_button: ctk.CTkButton):
    num_files = int(textbox.index("end-1c").split(".")[0])
    logging.info(f"anonymize files: {num_files-1} files ")
    textbox.configure(state="normal")
    # Iterate through the lines of textbox from first line and anonymize each file, delete from textbox after anonymization
    textbox.see("1.0")
    for i in range(1, num_files + 1):
        # lines count from 1, columns count from 0
        file = textbox.get(f"1.0", "1.end")
        if file.strip() == "":  # handle null string
            textbox.delete("1.0", "2.0")
            continue
        ds = dcmread(file)
        anonymize_dataset(ds)
        # TODO: handle errors, send to quarantine, etc., try / except around ds.save_as() on critical error return
        dest_path = local_storage_path(storage_directory, project.SITEID, ds)
        ds.save_as(dest_path)
        textbox.delete("1.0", "2.0")
        if i % 10 == 0:
            textbox.master.update()
        logger.info(f"{file} => {dest_path}")

    textbox.configure(state="disabled")
    anonymize_button.configure(state="disabled")


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Select Local Files View")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(2, weight=1)

    # Selected Local Files Scrollable Text Box
    # A Text Box is used instead of a List Box (scrolled view of labels and buttons)
    # because it is much faster on view resize and other operations
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
        command=lambda: anonymize_files(selected_files, anonymize_button),
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
