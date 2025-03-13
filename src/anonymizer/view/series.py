import gc
import logging
from pathlib import Path

import customtkinter as ctk
import numpy as np
from pydicom import Dataset

from anonymizer.controller.create_projections import (
    ProjectionImageSize,
    load_series_frames,
)
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
        self._sv_frame.grid_columnconfigure(0, weight=1)

        self.image_viewer = ImageViewer(
            self._sv_frame,
            self._frames,
            # ProjectionImageSize.LARGE.width(),  # handles scaling to screen size
            # ProjectionImageSize.LARGE.height(),
        )
        self.image_viewer.grid(row=0, column=0, sticky="nsew")

        logger.info(f"SeriesView for series_path: {series_path}")

        # --- Bind keys using named functions ---
        self.bind("<Left>", self.handle_left)
        self.bind("<Right>", self.handle_right)
        self.bind("<Up>", self.handle_up)
        self.bind("<Down>", self.handle_down)
        self.bind("<Prior>", self.handle_prior)
        self.bind("<Next>", self.handle_next)
        self.bind("<Home>", self.handle_home)
        self.bind("<End>", self.handle_end)
        self.bind("<MouseWheel>", self.handle_mousewheel)
        self.bind("<space>", self.handle_spacebar)

        self.focused_widget = "image_viewer"

    def load_frames(self, series_path: Path) -> tuple[Dataset, np.ndarray]:
        """Loads, processes, and combines series frames and projections."""
        ds, series_frames = load_series_frames(series_path)

        if series_frames.shape[0] == 1:  # Single-frame case
            logger.info("Load single frame high-res, normalised")
            return ds, series_frames

        # Re-Generate Projections for multi-frame series
        # (3, H, W, C) - Min, Mean, Max
        projections = np.stack(
            [
                np.min(series_frames, axis=0),
                np.mean(series_frames, axis=0).astype(np.uint8),
                np.max(series_frames, axis=0),
            ],
            axis=0,
        )
        return ds, np.concatenate([projections, series_frames], axis=0)

    def set_focus_widget(self, widget_name):
        self.focused_widget = widget_name
        print(f"Focus set to: {widget_name}")

    # --- Handler functions for key bindings ---
    def handle_left(self, event):
        self.image_viewer.prev_image(event)

    def handle_right(self, event):
        self.image_viewer.next_image(event)

    def handle_up(self, event):
        self.image_viewer.change_image_up()

    def handle_down(self, event):
        self.image_viewer.change_image_down()

    def handle_prior(self, event):
        self.image_viewer.change_image_prior()

    def handle_next(self, event):
        self.image_viewer.change_image_next()

    def handle_home(self, event):
        self.image_viewer.change_image_home()

    def handle_end(self, event):
        self.image_viewer.change_image_end()

    def handle_mousewheel(self, event):
        self.image_viewer.on_mousewheel(event)

    def handle_spacebar(self, event):
        self.image_viewer.toggle_play()

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
