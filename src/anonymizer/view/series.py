import gc
import logging
import tkinter as ttk
from pathlib import Path

# from tkinter import Listbox
import customtkinter as ctk
import numpy as np
from pydicom import Dataset

from anonymizer.controller.create_projections import load_series_frames
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.translate import _
from anonymizer.view.image import ImageViewer

logger = logging.getLogger(__name__)


class SeriesView(ctk.CTkToplevel):
    def __init__(self, parent, anon_model: AnonymizerModel, series_path: Path):
        super().__init__(master=parent)

        if not series_path.is_dir():
            raise ValueError(f"{series_path} is not a valid directory")

        self._anon_model = anon_model
        self._series_dir = series_path

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
        self._sv_frame.grid_columnconfigure(2, weight=1)

        list_frame = ctk.CTkFrame(self._sv_frame)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(2, weight=1)

        whitelist_title = ctk.CTkButton(list_frame, text="WHITE LIST", command=self.insert_entry_into_whitelist)
        whitelist_title.grid(row=0, column=0, sticky="ew")

        self.whitelist_entry = ctk.CTkEntry(list_frame)
        self.whitelist_entry.grid(row=1, column=0, sticky="ew")
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.whitelist = ttk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.whitelist.yview)
        self.whitelist.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.populate_listbox()

        self.image_viewer = ImageViewer(self._sv_frame, self._frames)
        self.image_viewer.grid(row=0, column=1, sticky="nsew")
        self.image_viewer._canvas.focus_set()

        # logger.info(f"SeriesView for series_path: {series_path}")
        # self.bind("<FocusIn>", self.on_focus_in)
        # self.bind("<FocusOut>", self.on_focus_out)
        # self.bind("<Button-1>", lambda event: logger.info("SeriesView Clicked"))

    def on_focus_in(self, event):
        logger.info("SeriesView has focus")

    def on_focus_out(self, event):
        logger.info("SeriesView lost focus")

    def whitelist_button_clicked_or_entry_return(self, event):
        self.insert_entry_into_whitelist()

    def insert_entry_into_whitelist(self):
        item = self.whitelist_entry.get()
        for i in range(self.whitelist.size()):  # Iterate through existing items
            if self.whitelist.get(i) == item:
                logger.warning(f"'{item}' already exists.")
                return  # Item is already present, don't add it

        self.whitelist.insert(0, item)
        self.whitelist.select_set(0)
        self.whitelist_entry.delete(0, ctk.END)

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

    def get_input(self):
        self.focus()
        self.master.wait_window(self)
        return None

    def populate_listbox(self):
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
        self.whitelist.insert(ttk.END, "FLEXION")
        self.whitelist.insert(ttk.END, "EXTENSION")
        self.whitelist.insert(ttk.END, "OBLIQUE")
        self.whitelist.insert(ttk.END, "AXIAL")
        self.whitelist.insert(ttk.END, "CORONAL")
        self.whitelist.insert(ttk.END, "SAGITTAL")
        self.whitelist.insert(ttk.END, "STANDING")
        self.whitelist.insert(ttk.END, "SITTING")
        self.whitelist.insert(ttk.END, "RECUMBENT")
        self.whitelist.insert(ttk.END, "UPRIGHT")
        self.whitelist.insert(ttk.END, "WEIGHT_BEARING")
        self.whitelist.insert(ttk.END, "NON_WEIGHT_BEARING")
        self.whitelist.insert(ttk.END, "SKYLINE")
        self.whitelist.insert(ttk.END, "TANGENTIAL")
        self.whitelist.insert(ttk.END, "SUNRISE")
        self.whitelist.insert(ttk.END, "MERCHANT")
        self.whitelist.insert(ttk.END, "TUNNEL")
        self.whitelist.insert(ttk.END, "MORTISE")
        self.whitelist.insert(ttk.END, "GRASHEY")
        self.whitelist.insert(ttk.END, "WEST_POINT")
        self.whitelist.insert(ttk.END, "ZANCA")
        self.whitelist.insert(ttk.END, "SWIMMERS")
        self.whitelist.insert(ttk.END, "JUDET")
        self.whitelist.insert(ttk.END, "INLET")
        self.whitelist.insert(ttk.END, "OUTLET")
        self.whitelist.insert(ttk.END, "CAUDAL")
        self.whitelist.insert(ttk.END, "CRANIAL")
        self.whitelist.insert(ttk.END, "FROG_LEG")
        self.whitelist.insert(ttk.END, "CROSS_TABLE")
        self.whitelist.insert(ttk.END, "ROSENBERG")
        self.whitelist.insert(ttk.END, "SHOOTING")
        self.whitelist.insert(ttk.END, "STRESS")
        self.whitelist.insert(ttk.END, "DYNAMIC")
        self.whitelist.insert(ttk.END, "STATIC")
        self.whitelist.insert(ttk.END, "TRACTION")
        self.whitelist.insert(ttk.END, "COMPRESSION")
        self.whitelist.insert(ttk.END, "EXTERNAL")
        self.whitelist.insert(ttk.END, "INTERNAL")
        self.whitelist.insert(ttk.END, "NEUTRAL")
        self.whitelist.insert(ttk.END, "ROTATED")
        self.whitelist.insert(ttk.END, "FLEXED")
        self.whitelist.insert(ttk.END, "EXTENDED")
