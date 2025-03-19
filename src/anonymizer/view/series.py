import gc
import logging
import os
import tkinter as ttk
from pathlib import Path
from pprint import pformat

import customtkinter as ctk
import numpy as np
import torch
from easyocr import Reader
from pydicom import Dataset

from anonymizer.controller.create_projections import load_series_frames
from anonymizer.controller.remove_pixel_phi import detect_text
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.translate import _
from anonymizer.view.image import ImageViewer

logger = logging.getLogger(__name__)


class SeriesView(ctk.CTkToplevel):
    BUTTON_WIDTH = 100
    PAD = 10

    def __init__(self, parent, anon_model: AnonymizerModel, series_path: Path):
        super().__init__(master=parent)

        if not series_path.is_dir():
            raise ValueError(f"{series_path} is not a valid directory")

        self._anon_model = anon_model
        self._series_dir = series_path
        self._ocr_reader = None  # only created if user clicks "Detect Text" button

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self._ds, self._frames = self.load_frames(series_path)

        if self._ds is None or self._frames is None:
            raise ValueError(f"Error loading frames from {series_path}")

        self._update_title()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # SeriesView Frame:
        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(1, weight=1)

        # Whitelist frame:
        list_frame = ctk.CTkFrame(self._sv_frame)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=self.PAD)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(2, weight=1)

        # Whitelist button:
        whitelist_title = ctk.CTkButton(list_frame, text="WHITE LIST", command=self.insert_entry_into_whitelist)
        whitelist_title.grid(row=0, columnspan=2, sticky="ew")

        # Whitelist entry:
        self.whitelist_entry = ctk.CTkEntry(list_frame)
        self.whitelist_entry.grid(row=1, columnspan=2, sticky="ew")
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)

        # Whitelist listbox & scrollbar:
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.whitelist = ttk.Listbox(list_frame, border=0, yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.whitelist.yview)
        self.whitelist.bind("<Delete>", self.whitelist_delete_keypressed)
        self.whitelist.bind("<BackSpace>", self.whitelist_delete_keypressed)

        self.whitelist.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")

        # ImageViewer:
        self.image_viewer = ImageViewer(self._sv_frame, self._frames)
        self.image_viewer.grid(row=0, column=1, sticky="nsew")

        # Control Frame:
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, columnspan=2, sticky="ew", padx=self.PAD, pady=self.PAD)
        # self.control_frame.grid_columnconfigure(0, weight=1)

        # Detect Text Button:
        self.detect_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text="Detect Text", command=self.detect_text_button_clicked
        )
        self.detect_button.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)

        # Remove Text Button:
        self.remove_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text="Remove Text", command=self.remove_text_button_clicked
        )
        self.remove_button.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="w")

        self.populate_listbox()

    def whitelist_button_clicked_or_entry_return(self, event):
        self.insert_entry_into_whitelist()

    def in_whitelist(self, item: str) -> bool:
        return all(self.whitelist.get(i) != item for i in range(self.whitelist.size()))

    def insert_entry_into_whitelist(self):
        item = self.whitelist_entry.get()
        if self.in_whitelist(item):
            return

        self.whitelist.insert(0, item)
        # self.whitelist.select_set(0, 0)
        self.whitelist_entry.delete(0, ctk.END)

    def whitelist_delete_keypressed(self, event):
        selected_indices = self.whitelist.curselection()

        if not selected_indices:  # Check if anything is selected
            return

        # Delete items in reverse order to avoid index issues.
        for i in reversed(selected_indices):
            self.whitelist.delete(i)
            self.whitelist.select_set(i - 1)
            self.whitelist.activate(i - 1)

    def load_frames(self, series_path: Path) -> tuple[Dataset, np.ndarray]:
        """Loads, processes, and combines series frames and projections."""
        ds, series_frames = load_series_frames(series_path)

        if series_frames.shape[0] == 1:  # Single-frame case
            logger.info("Load single frame high-res, normalised")
            return ds, series_frames

        # Re-Generate Projections for multi-frame series
        # (3 frames, Height, Width, Channels) - Min, Mean, Max
        projections = np.stack(
            [
                np.min(series_frames, axis=0),
                np.mean(series_frames, axis=0).astype(np.uint8),
                np.max(series_frames, axis=0),
            ],
            axis=0,
        )
        return ds, np.concatenate([projections, series_frames], axis=0)

    def _update_title(self):
        if self._ds:
            phi = self._anon_model.get_phi(self._ds.PatientID)
            if phi:
                title = (
                    _("Series View for")
                    + f" {phi.patient_name} PHI ID:{phi.patient_id} ANON ID: {self._ds.PatientID}"
                    + f" {self._ds.get('SeriesDescription', '')} "
                )
                self.title(title)

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self.grab_release()
        self.destroy()

        if hasattr(self, "image_viewer") and self.image_viewer:
            self.image_viewer.clear_cache()

        self._frames = None
        self._ds = None
        self._projection = None
        gc.collect()

    def initialise_ocr(self):
        # Once-off initialisation of easyocr.Reader (and underlying pytorch model):
        # if pytorch models not downloaded yet, they will be when Reader initializes
        logging.info("OCR Reader initialising...")

        model_dir = Path("assets") / "ocr" / "model"  # Default is: Path("~/.EasyOCR/model").expanduser()
        if not model_dir.exists():
            # TODO: notify user via status bar or messagebox
            logger.warning(
                f"EasyOCR model directory: {model_dir}, does not exist, EasyOCR will create it, models still to be downloaded..."
            )
        else:
            logger.info(f"EasyOCR downloaded models: {os.listdir(model_dir)}")

        # Initialize the EasyOCR reader with the desired language(s), if models are not in model_dir, they will be downloaded
        self._ocr_reader = Reader(
            lang_list=["en", "de", "fr", "es"],
            model_storage_directory=model_dir,
            verbose=True,
        )

        logging.info("OCR Reader initialised successfully")

    def detect_text_button_clicked(self):
        logger.info("Detecting text...")

        if self._ocr_reader is None:
            self.initialise_ocr()

        # Check if GPU available
        logger.info(f"Apple MPS (Metal) GPU Available: {torch.backends.mps.is_available()}")
        logger.info(f"CUDA GPU Available: {torch.cuda.is_available()}")

        with torch.no_grad():
            if self._ocr_reader:
                ocr_list = detect_text(
                    pixels=self.image_viewer.get_current_image(), ocr_reader=self._ocr_reader, draw_boxes=True
                )
                if ocr_list:
                    logger.info(f"Detected Text:\n{pformat(ocr_list)}")
                    self.image_viewer.refresh_current_image()

    def remove_text_button_clicked(self):
        logger.info("Removing text...")
        pass

    def populate_listbox(self):
        # TODO: create standard dictionary of likely to appear on medical images
        # translate dictionary into all languages, copy to relevant locales as phi_whitelist.csv
        # TODO: provide user option to load and use this dictionary
        # TODO: consider modality specific dictionaries, context sensitive to series modality
        self.whitelist.insert(ttk.END, "L")
        self.whitelist.insert(ttk.END, "R")
        self.whitelist.insert(ttk.END, "PORTABLE")
        self.whitelist.insert(ttk.END, "LEFT")
        self.whitelist.insert(ttk.END, "RIGHT")
        self.whitelist.insert(ttk.END, "SUPINE")
        self.whitelist.insert(ttk.END, "PRONE")
        self.whitelist.insert(ttk.END, "LATERAL")
        self.whitelist.insert(ttk.END, "ANTERIOR")
        self.whitelist.insert(ttk.END, "POSTERIOR")
        self.whitelist.insert(ttk.END, "DECUBITUS")
        self.whitelist.insert(ttk.END, "ERECT")
        self.whitelist.insert(ttk.END, "OBLIQUE")
        self.whitelist.insert(ttk.END, "AXIAL")
        self.whitelist.insert(ttk.END, "CORONAL")
        self.whitelist.insert(ttk.END, "SAGITTAL")
        self.whitelist.insert(ttk.END, "STANDING")
        self.whitelist.insert(ttk.END, "SITTING")
        self.whitelist.insert(ttk.END, "RECUMBENT")
        self.whitelist.insert(ttk.END, "UPRIGHT")
        self.whitelist.insert(ttk.END, "SEMI-UPRIGHT")
