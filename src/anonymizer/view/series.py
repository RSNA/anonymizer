import difflib
import gc
import logging
import os
import tkinter as ttk
from enum import StrEnum, auto
from pathlib import Path
from pprint import pformat

import customtkinter as ctk
import numpy as np
import torch
from easyocr import Reader
from pydicom import Dataset

from anonymizer.controller.create_projections import apply_windowing, get_wl_ww, load_series_frames
from anonymizer.controller.remove_pixel_phi import (
    OCRText,
    UserRectangle,
    blackout_rectangular_areas,
    detect_text,
    remove_text,
)
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.translate import _
from anonymizer.view.image import ImageViewer

logger = logging.getLogger(__name__)


# Edit Contexts:
class EditContext(StrEnum):
    FRAME = auto()  # apply edits to current frame only
    SERIES = auto()  # apply edits to every frame in series
    # TODO: PROJECT = auto()  # apply edits to all series in project


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
        self.edit_context: EditContext = EditContext.FRAME
        self.detected_text: dict[int, list[OCRText]] = {}  # Store all detected text per frame

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self._ds, self._frames = self.load_frames(series_path)

        if self._ds is None or self._frames is None:
            raise ValueError(f"Error loading frames from {series_path}")

        self.single_frame: bool = len(self._frames) == 1
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
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)
        self.whitelist_entry.grid(row=1, columnspan=2, sticky="ew")

        # Whitelist listbox & scrollbar:
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.whitelist = ttk.Listbox(list_frame, border=0, yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.whitelist.yview)
        self.whitelist.bind("<Delete>", self.whitelist_delete_keypressed)
        self.whitelist.bind("<BackSpace>", self.whitelist_delete_keypressed)
        self.whitelist.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")

        # ImageViewer:
        self.image_viewer = ImageViewer(
            self._sv_frame,
            self._frames,
            *get_wl_ww(self._ds),
            add_to_whitelist_callback=self.add_to_whitelist,
            regenerate_series_projections_callback=self.regenerate_series_projections,
        )
        self.image_viewer.grid(row=0, column=1, sticky="nsew")

        # Control Frame:
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, columnspan=2, sticky="ew", padx=self.PAD, pady=self.PAD)
        # self.control_frame.grid_columnconfigure(0, weight=1)

        # Edit Context Segmented Button:
        col = 0
        edit_context_label = ctk.CTkLabel(self.control_frame, text=_("Edit Context") + ":")
        edit_context_label.grid(row=0, column=col, padx=(self.PAD, 0))
        col += 1
        self.edit_context_combo_box = ctk.CTkComboBox(
            self.control_frame,
            state="readonly",
            values=[
                member.value.upper()
                for member in EditContext
                if not (self.single_frame and member == EditContext.SERIES)
            ],
            command=self.edit_context_change,
        )
        self.edit_context_combo_box.set(EditContext.FRAME.upper())
        self.edit_context_combo_box.grid(row=0, column=col, padx=self.PAD, pady=self.PAD)
        col += 1

        # Detect Text Button:
        self.detect_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text=_("Detect Text"), command=self.detect_text_button_clicked
        )
        self.detect_button.grid(row=0, column=col, padx=self.PAD, pady=self.PAD)
        col += 1

        # Remove Text Button:
        self.remove_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text=_("Remove Text"), command=self.remove_text_button_clicked
        )
        self.remove_button.grid(row=0, column=col, padx=self.PAD, pady=self.PAD, sticky="w")
        col += 1

        # Blackout Area Button:
        self.blackout_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text=_("Blackout Area"), command=self.blackout_button_clicked
        )
        self.blackout_button.grid(row=0, column=col, padx=self.PAD, pady=self.PAD, sticky="w")
        col += 1

        # Status label:
        self.status_label = ctk.CTkLabel(self.control_frame, text="")
        self.status_label.grid(row=0, column=col, padx=self.PAD, pady=self.PAD, sticky="e")
        self.control_frame.grid_columnconfigure(col, weight=1)  # Make status label expand.

        self.populate_listbox()

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

    def update_status(self, message: str):
        """Updates the status label."""
        self.status_label.configure(text=message)
        self.status_label.update()

    def add_to_whitelist(self, text: str):
        whitelist = self.whitelist.get(0, ttk.END)
        try:
            ndx = whitelist.index(text)
            # Already in whitelist, hightlight:
            self.whitelist.select_set(ndx)
        except ValueError:
            # Not in whitelist, insert:
            logger.info(f"Adding to whitelist: {text}")
            self.whitelist.insert(0, text)

    def insert_entry_into_whitelist(self):
        new_item = self.whitelist_entry.get()
        self.add_to_whitelist(new_item)
        self.whitelist_entry.delete(0, ctk.END)

    def whitelist_button_clicked_or_entry_return(self, event):
        self.insert_entry_into_whitelist()

    def whitelist_delete_keypressed(self, event):
        selected_indices = self.whitelist.curselection()

        if not selected_indices:  # Check if anything is selected
            return

        # Delete items in reverse order to avoid index issues.
        for i in reversed(selected_indices):
            self.whitelist.delete(i)
            self.whitelist.select_set(i - 1)
            self.whitelist.activate(i - 1)

    def edit_context_change(self, choice):
        logger.info(f"Edit Context changed to: {choice}")
        self.edit_context = EditContext[choice]
        self.image_viewer.set_overlay_propagation(self.edit_context == EditContext.SERIES)

    def regenerate_series_projections(self):
        if self._frames is not None and not self.single_frame:
            logger.info("Regenerate Series Projections")
            self._frames[0] = np.min(self._frames, axis=0)
            self._frames[1] = np.mean(self._frames, axis=0).astype(self._frames.dtype)
            self._frames[2] = np.max(self._frames, axis=0)

    def load_frames(self, series_path: Path) -> tuple[Dataset, np.ndarray]:
        """Loads, processes, and combines series frames and projections."""
        ds, series_frames = load_series_frames(series_path)

        logger.info(f"SERIES FRAMES BEFORE PROJ DATA TYPE={series_frames.dtype}")

        # Do not generate projections for single-frame series:
        if series_frames.shape[0] == 1:  # Single-frame case
            logger.info("Load single frame high-res, normalised")
            return ds, series_frames

        # Generate Projections for multi-frame series
        # (3 frames, Height, Width, Channels) - Min, Mean, Max
        projections = np.stack(
            [
                np.min(series_frames, axis=0),
                np.mean(series_frames, axis=0).astype(series_frames.dtype),
                np.max(series_frames, axis=0),
            ],
            axis=0,
        )
        return ds, np.concatenate([projections, series_frames], axis=0)

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
        # TODO: use thread for this if models not downloaded yet, provide status updates during download:
        # TODO: optimize so reader is only initialised once - reference passed by ProjectionView or IndexView or global?
        self._ocr_reader = Reader(
            lang_list=["en", "de", "fr", "es"],
            gpu=True,
            model_storage_directory=model_dir,
            verbose=True,
        )

        logging.info("OCR Reader initialised successfully")

    # def filter_text_data(self, frame_index: int) -> list[OCRText]:
    #     """Filters the text_data for a frame based on the whitelist."""
    #     if frame_index not in self.detected_text:
    #         return []

    #     whitelist_set = set(item.upper().strip() for item in self.whitelist.get(0, "end"))
    #     filtered_results = []

    #     for ocr_text in self.detected_text[frame_index]:
    #         if ocr_text.text and ocr_text.text.upper() not in whitelist_set:
    #             filtered_results.append(ocr_text)
    #     return filtered_results

    def filter_text_data(self, frame_index: int, similarity_threshold: float = 0.75) -> list[OCRText]:
        """
        Filters the text_data for a frame based on fuzzy matching against the whitelist.
        Keeps text if its similarity threshold to ALL whitelist items is <= 0.75.
        # TODO: provide UX to modify similarity threshold
        """
        # Use unfiltered_text_data which stores the raw OCR results
        if frame_index not in self.detected_text:
            return []

        # Preprocess whitelist items once
        whitelist_set = [item.upper().strip() for item in self.whitelist.get(0, "end") if item.strip()]
        if not whitelist_set:  # If whitelist is empty, return all results
            return self.detected_text.get(frame_index, [])

        filtered_results = []
        for ocr_text in self.detected_text[frame_index]:
            if not ocr_text.text:  # Skip if OCR text is empty
                continue

            processed_ocr_text = ocr_text.text.upper().strip()
            is_similar_to_whitelist = False

            # Check similarity against each whitelist item
            for whitelist_item in whitelist_set:
                # Use SequenceMatcher to get the similarity ratio
                similarity = difflib.SequenceMatcher(None, processed_ocr_text, whitelist_item).ratio()

                if similarity > similarity_threshold:
                    is_similar_to_whitelist = True
                    logger.debug(
                        f"'{ocr_text.text}' matched whitelist item '{whitelist_item}' "
                        f"with similarity ratio {similarity:.2f}. Filtering out."
                    )
                    break  # Found a close match, no need to check further

            # Keep the text only if it wasn't similar to any whitelist item
            if not is_similar_to_whitelist:
                filtered_results.append(ocr_text)

        return filtered_results

    def draw_text_overlay(self, frame_index: int):
        """Draws text boxes on the overlay for the given frame, based on filtered text_data."""
        filtered_text_data = self.filter_text_data(frame_index)  # Filter *before* drawing
        self.image_viewer.set_text_overlay_data(frame_index, filtered_text_data)

    def process_single_frame_ocr(self, frame_index: int):
        """Performs OCR on a single frame, filters, and stores results."""
        with torch.no_grad():
            if self._ocr_reader:
                results = detect_text(
                    pixels=apply_windowing(
                        self.image_viewer.current_wl,
                        self.image_viewer.current_ww,
                        self.image_viewer.images[frame_index],
                    ),
                    ocr_reader=self._ocr_reader,
                    draw_boxes_and_text=False,
                )
                if results:
                    logger.debug(f"OCR Results:\n{pformat(results)}")
                    self.detected_text[frame_index] = results
                    self.draw_text_overlay(frame_index)

    def detect_text_for_series(self):
        """Detects text in all frames of the series."""
        self.update_status(_("Detecting text in all frames..."))
        total_frames = self.image_viewer.num_images
        for i in range(total_frames):
            self.image_viewer.load_and_display_image(i)  # Goto series start
            self.process_single_frame_ocr(i)
            self.update_status(_("OCR on frame: ") + str(i + 1))

    def detect_text_button_clicked(self):
        logger.info("Detecting text...")

        if self._ocr_reader is None:
            self.initialise_ocr()

        # Check if GPU available
        logger.info(f"Apple MPS (Metal) GPU Available: {torch.backends.mps.is_available()}")
        logger.info(f"CUDA GPU Available: {torch.cuda.is_available()}")

        if self.edit_context == EditContext.FRAME:
            self.update_status(_("OCR on current frame..."))
            self.process_single_frame_ocr(self.image_viewer.current_image_index)
            self.update_status(_("OCR on current frame complete"))
        else:
            self.detect_text_for_series()
            self.update_status(_("OCR on all frames complete"))

        # TODO: work out what to do beyond propagting edits in overlays when edit context is PROJECT

        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    def remove_text_from_single_frame(self, frame_index: int, ocr_texts: list[OCRText]):
        logger.debug(f"Remove {len(ocr_texts)} words from frame {frame_index}")
        raw_frame = self.image_viewer.images[frame_index]
        windowed_frame = apply_windowing(self.image_viewer.current_wl, self.image_viewer.current_ww, raw_frame)
        self.image_viewer.images[frame_index] = remove_text(raw_frame, windowed_frame, ocr_texts)
        ocr_texts.clear()

    def remove_text_from_series(self):
        total_frames = self.image_viewer.num_images
        self.image_viewer.clear_cache()
        for i in range(total_frames):
            if i in self.image_viewer.overlay_data:
                ocr_texts = self.image_viewer.overlay_data[i].ocr_texts
                if ocr_texts:
                    self.remove_text_from_single_frame(i, ocr_texts)
                self.image_viewer.load_and_display_image(i)
                self.update()
        self.image_viewer.clear_cache()
        self.regenerate_series_projections()
        self.image_viewer.load_and_display_image(0)

    def remove_text_button_clicked(self):
        logger.debug(f"Removing text, current edit context={self.edit_context}")

        if self._ocr_reader is None:
            self.initialise_ocr()

        if self.edit_context == EditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            ocr_texts = self.image_viewer.overlay_data[ndx].ocr_texts
            if not ocr_texts:
                logger.warning("No text has been detected in current frame to remove")
                self.update_status(_("No text detected in current frame to remove"))
                return
            self.update_status(_("Removing text from current frame..."))
            self.remove_text_from_single_frame(ndx, ocr_texts)
            self.update_status(_("Text removed from current frame"))
            self.image_viewer.refresh_current_image()
        else:
            self.update_status(_("Removing text from all frames in series..."))
            self.remove_text_from_series()
            self.update_status(_("Text removed from all frames in series"))

        # TODO: Remove all in PROJECT if modality and image size constant

    def blackout_areas_in_single_frame(self, frame_index: int, user_rects: list[UserRectangle]):
        logger.debug(f"Blackout {len(user_rects)} rects from frame {frame_index}")
        blackout_rectangular_areas(self.image_viewer.images[frame_index], user_rects)
        user_rects.clear()

    def blackout_areas_in_series(self):
        total_frames = self.image_viewer.num_images
        self.image_viewer.clear_cache()
        for i in range(total_frames):
            if i not in self.image_viewer.overlay_data:
                continue
            user_rects = self.image_viewer.overlay_data[i].user_rects
            if user_rects:
                self.blackout_areas_in_single_frame(i, user_rects)
            self.image_viewer.load_and_display_image(i)
            self.update()
        self.image_viewer.clear_cache()
        self.regenerate_series_projections()
        self.image_viewer.load_and_display_image(0)

    def blackout_button_clicked(self):
        logger.debug(f"Blackout text, current edit context[{self.edit_context}]")

        if self.edit_context == EditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            user_rects = self.image_viewer.overlay_data[ndx].user_rects
            if not user_rects:
                logger.warning("No blackout user rect has been define in current frame to blackout")
                self.update_status(_("No blackout area(s) in current frame"))
                return
            self.update_status(_("Blackout areas in current frame..."))
            self.blackout_areas_in_single_frame(ndx, user_rects)
            if not self.single_frame:
                self.image_viewer.clear_cache()
                self.regenerate_series_projections()
            self.update_status(_("Areas blacked out in current frame"))
            self.image_viewer.refresh_current_image()
        else:
            self.update_status(_("Removing text from all frames in series..."))
            self.blackout_areas_in_series()
            self.update_status(_("Text removed from all frames in series"))

    def populate_listbox(self):
        # TODO: create standard dictionary of likely to appear on medical images
        # translate dictionary into all languages, copy to relevant locales as phi_whitelist.csv
        # TODO: provide user option to load and use this dictionary
        # TODO: consider modality specific dictionaries, context sensitive to series modality
        whitelist_items = [
            "L",
            "R",
            "PORTABLE",
            "LEFT",
            "RIGHT",
            "SUPINE",
            "PRONE",
            "LATERAL",
            "ANTERIOR",
            "POSTERIOR",
            "DECUBITUS",
            "ERECT",
            "OBLIQUE",
            "AXIAL",
            "CORONAL",
            "SAGITTAL",
            "STANDING",
            "SITTING",
            "RECUMBENT",
            "UPRIGHT",
            "SEMI-UPRIGHT",
        ]
        for item in whitelist_items:
            self.whitelist.insert(ttk.END, item)

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self.grab_release()
        self.destroy()

        if hasattr(self, "image_viewer") and self.image_viewer:
            self.image_viewer.clear_cache()

        if self._ocr_reader:
            # Attempt to unload the model
            del self._ocr_reader
            self._ocr_reader = None
            gc.collect()

        self._frames = None
        self._ds = None
        self._projection = None
        gc.collect()
