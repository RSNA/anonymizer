import os
from pathlib import Path
from pydicom.misc import is_dicom
from typing import Sequence
import customtkinter as ctk
from tkinter import Tk, filedialog
from CTkToolTip import CTkToolTip
from CTkListbox import CTkListbox
import logging
from pydicom import dcmread, config
from controller.anonymizer import anonymize_dataset
from utils.translate import _
from prototyping.storage_dir import storage_directory
import model.project as project

logger = logging.getLogger(__name__)

# Set Value validation to WARN not RAISE by pydicom
config.settings.reading_validation_mode = config.WARN
config.settings.writing_validation_mode = config.WARN
# Running your code with this turned on will help identify any parts of your code that are not compatible with the known changes in the next major version of pydicom.
config.future_behavior(True)

logger = logging.getLogger(__name__)


file_extension_filters = [
    ("dcm Files", "*.dcm"),
    ("dicom Files", "*.dicom"),
    ("All Files", "*.*"),
]


def _insert_files_into_textbox(
    listbox: CTkListbox, file_paths: Sequence[str], anonymize_button: ctk.CTkButton
):
    if file_paths:
        for file_path in file_paths:
            if os.path.isfile(file_path) and is_dicom(file_path):
                listbox.insert("END", file_path)
                anonymize_button.configure(state="normal")


def _open_file_dialog(listbox: CTkListbox, anonymize_button: ctk.CTkButton):
    paths = filedialog.askopenfilenames(
        filetypes=file_extension_filters
    )  # for multiple files
    if paths:
        _insert_files_into_textbox(listbox, paths, anonymize_button)


def _open_directory_dialog(
    listbox: CTkListbox,
    anonymize_button: ctk.CTkButton,
    recurse: bool = True,
):
    logging.info(f"open_directory_dialog recurse:{recurse}")
    path = filedialog.askdirectory(title=_("Select DICOM Directory"))
    if path:
        if recurse:
            # Recurse into subdirectories
            for root, dirs, files in os.walk(path):
                file_paths = [os.path.join(root, file) for file in files]
                _insert_files_into_textbox(listbox, file_paths, anonymize_button)
        else:
            # Only consider files in the top-level directory
            file_paths = [
                os.path.join(path, file)
                for file in os.listdir(path)
                if os.path.isfile(os.path.join(path, file))
            ]
            _insert_files_into_textbox(listbox, file_paths, anonymize_button)


# Read the DICOM files one by one into memory and anonymize them
# Do not store any PHI on disk in temp files etc.
def anonymize_files(listbox: CTkListbox):
    logging.info(f"anonymize_files: file_count:{listbox.size()}")
    for ndx in range(listbox.size()):
        file = str(listbox.get(ndx))
        if not os.path.isfile(file):
            logger.error(f"File does not exist: {file}")
            continue
        if not is_dicom(file):
            logger.error(f"File is not DICOM: {file}")
            continue
        ds = dcmread(file)
        anonymize_dataset(ds)
        # TODO: handle errors, send to quarantine, etc., try / except around ds.save_as() on critical error return
        # TODO: dest path = storage_directory / [SITE-ID]-[ANON-PatientID] / Study-[Modality]-[StudyDate]-[????] / Series-[SeriesNumber] / Image-[InstanceNumber]
        dest_path = Path(
            storage_directory,
            project.SITEID + "-" + ds.PatientName,
            "Study" + "-" + ds.Modality + "-" + ds.StudyDate,
            "Series" + "-" + ds.SeriesNumber,
            "Image" + "-" + ds.InstanceNumber,
        )
        ds.save_as(dest_path)
        listbox.configure(text_color="green")
        listbox.insert(ndx, f"{file} => {dest_path}")


def create_view(view: ctk.CTkFrame):
    PAD = 10
    logger.info(f"Creating Select Local Files View")
    view.grid_rowconfigure(1, weight=1)
    view.grid_columnconfigure(2, weight=1)

    # Selected Local Files Scrollable Text Box:
    selected_files = CTkListbox(view)
    selected_files.grid(row=1, columnspan=3, sticky="nswe")

    # overlay_label = ctk.CTkLabel(
    #     selected_files,
    #     text=_(
    #         "Add local DICOM files to anonymize by clicking Select File(s) or Select Directory above"
    #     ),
    # )
    # overlay_label.place(relx=0.5, rely=0.5, anchor="center")

    # def textbox_change(event):
    #     overlay_label.place_forget()

    # selected_files.bind("<<Modified>>", textbox_change)

    # TODO: add ability to drag and drop files into textbox, see https://github.com/TomSchimansky/CustomTkinter/issues/934

    anonymize_button = ctk.CTkButton(
        view,
        text=_("Anonymize"),
        state="disabled",
        command=lambda: anonymize_files(selected_files),
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
