from pathlib import Path
import time
import logging
import threading
from dataclasses import dataclass
from pydicom import dcmread, Dataset
from pydicom.pixel_data_handlers.util import apply_voi_lut, apply_modality_lut
import numpy as np
from PIL import Image
from cv2 import (
    resize,
    normalize,
    equalizeHist,
    Canny,
    cvtColor,
    createCLAHE,
    GaussianBlur,
    dilate,
    morphologyEx,
    findContours,
    drawContours,
    getStructuringElement,
    INTER_AREA,
    NORM_MINMAX,
    CV_8U,
    COLOR_RGB2GRAY,
    MORPH_RECT,
    MORPH_CLOSE,
    RETR_EXTERNAL,
    CHAIN_APPROX_SIMPLE,
    FILLED,
)

import customtkinter as ctk
from utils.storage import get_dcm_files, count_series
from utils.translate import _


logger = logging.getLogger(__name__)


@dataclass
class kaleidoscope:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    images: list[Image.Image]


class KaleidoscopeView(ctk.CTkToplevel):
    WORKER_THREAD_SLEEP_SECS = 0.075  # for UX responsiveness
    THUMBNAIL_SIZE = (100, 100)  # width x height pixels
    MAX_ROWS = 1000
    PAD = 5

    def __init__(self, mono_font: ctk.CTkFont, base_dir: Path, patient_ids: list[str] = None):
        super().__init__()
        self._data_font = mono_font  # get mono font from app

        if not base_dir.is_dir():
            raise ValueError(f"{base_dir} is not a valid directory")

        # If patient_ids not specified, iterate through ALL patient sub-directories to compile patient_ids:
        if patient_ids is None:
            patient_ids = [p for p in base_dir.iterdir() if p.is_dir()]

        if not patient_ids:
            raise ValueError("No patients for kaleidoscope")

        self._patient_ids = patient_ids
        self._base_dir = base_dir
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(width=True, height=True)
        self._columns = 3
        self._rows = 0
        self._create_widgets()
        self._kaleidoscopes: list[kaleidoscope] = []
        self._total_series = count_series(base_dir, patient_ids)
        self.title(
            _("View")
            + f" {len(patient_ids)} "
            + (_("Patients") if len(patient_ids) > 1 else _("Patient"))
            + f" {self._total_series} "
            + _("Series")
        )
        self._update_load_progress(1)
        self._stop_event = threading.Event()
        self._ks_worker = threading.Thread(target=self._load_kaleidoscopes_worker, name="Load_Kaleidoscopes")
        self._ks_worker.start()
        self.after(250, self._populate_ks_frame)
        logger.info(
            f"KaleidoscopeView for Patients={len(self._patient_ids)}, Total Series={self._total_series}, Columns={self._columns}"
        )

        self.after(500, self)

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = self.PAD
        ButtonWidth = 100
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. Kaleidoscope Frame:
        self._ks_frame = ctk.CTkScrollableFrame(
            self,
            width=(self.THUMBNAIL_SIZE[0] + PAD) * 3,
            height=3 * self.winfo_screenheight() // 4,
            fg_color="black",
        )
        self._ks_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")

        self.canvas = self._ks_frame._parent_canvas

        # 2. STATUS Frame:
        self._status_frame = ctk.CTkFrame(self)
        self._status_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="nswe")

        # Status and progress bar:
        self._status = ctk.CTkLabel(self._status_frame, font=self._data_font, text="")
        self._status.grid(row=0, column=0, padx=PAD, pady=0, sticky="w")

        self._progressbar = ctk.CTkProgressBar(
            self._status_frame,
        )
        self._progressbar.grid(
            row=0,
            column=1,
            padx=PAD,
            pady=0,
            sticky="w",
        )

    def _update_load_progress(self, series_loaded):
        if not self._total_series:
            self._progressbar.set(1)
        else:
            self._progressbar.set(series_loaded / self._total_series)
        state_label = _("Loading")
        entity_label = _("Series")
        if series_loaded == self._total_series:
            state_label = _("Loaded") + " "
        msg = state_label + f" {series_loaded} " + _("of") + f" {self._total_series} " + entity_label
        self._status.configure(text=msg)

    def _update_sheet(self, kaleidoscope: kaleidoscope):

        for i, image in enumerate(kaleidoscope.images):
            ctk_image = ctk.CTkImage(light_image=image, size=self.THUMBNAIL_SIZE)
            label = ctk.CTkLabel(self._ks_frame, image=ctk_image, text="")
            label.grid(row=self._rows, column=i, padx=self.PAD, pady=self.PAD * 2, sticky="w")
            # label.bind("<Button-1>", lambda event, kaleidoscope=kaleidoscope: self._on_image_click(event, kaleidoscope))

    def _populate_ks_frame(self):
        if self._rows < self.MAX_ROWS and len(self._kaleidoscopes) > self._rows:
            self._update_sheet(self._kaleidoscopes[self._rows])
            self._rows += 1
            self._update_load_progress(len(self._kaleidoscopes))

        if self._rows < self.MAX_ROWS:
            self.after(500, self._populate_ks_frame)
        else:
            logger.info("ks_frame populated")
            self._ks_frame.bind("<Configure>", self._on_scroll)

    def _on_scroll(self, event):
        top, bottom = self.canvas.yview()

        if top < 0.05:
            logger.info("TOP")
        elif bottom > 0.95:
            logger.info("BOTTOM")

        # Need to latch transition ie edge

    def _on_cancel(self):
        logger.info(f"_on_cancel")
        if self._ks_worker and self._ks_worker.is_alive():
            self._stop_event.set()
            self._ks_worker.join()

        # Clear the _kaleidoscopes list to release image references
        for kaleidoscope in self._kaleidoscopes:
            kaleidoscope.images.clear()
        self._kaleidoscopes.clear()

        # Unbind events and destroy widgets
        # TODO: check if this is necessary
        # for widget in self._ks_frame.winfo_children():
        #     widget.unbind("<Button-1>")  # Unbind events
        #     widget.destroy()  # Explicitly destroy widget

        self._ks_frame.destroy()
        self._status_frame.destroy()
        self.destroy()

    def _on_image_click(self, event, kaleidoscope: kaleidoscope):
        logger.info(f"Image clicked: kaleidoscope: {kaleidoscope}")

    def _resize_or_pad_image(self, image: Image.Image, target_size: tuple[int, int]):
        """Resize or pad an image to match the target size (height, width)."""
        target_height, target_width = target_size
        logger.info(f"Resize image in series from {image.shape[1]}x{image.shape[0]} to {target_width}x{target_height}")

        # Resize and interpolate:
        scale = min(target_width / image.shape[1], target_height / image.shape[0])
        resized_image = resize(
            image, (int(image.shape[1] * scale), int(image.shape[0] * scale)), interpolation=INTER_AREA
        )

        # Ensure the resized image has the same type as the original
        resized_image = resized_image.astype(image.dtype)

        # Calculate offsets for centering
        y_offset = (target_height - resized_image.shape[0]) // 2
        x_offset = (target_width - resized_image.shape[1]) // 2

        # Create a padded image with the same number of channels as the resized image
        if image.ndim == 3:  # RGB (3 channels)
            padded_image = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        else:  # Grayscale (1 channel)
            padded_image = np.zeros((target_height, target_width), dtype=np.uint8)

        # Place the resized image in the center of the padded image
        padded_image[y_offset : y_offset + resized_image.shape[0], x_offset : x_offset + resized_image.shape[1]] = (
            resized_image
        )

        return padded_image

    def _single_frame_kaleidoscope(self, ds: Dataset) -> kaleidoscope:

        pi = ds.get("PhotometricInterpretation", None)
        if pi is None:
            raise ValueError("No PhotometricInterpretation ")

        pixels = ds.pixel_array

        if pi in ["MONOCHROME1", "MONOCHROME2"]:
            pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)
            if pi == "MONOCHROME1":
                pixels = np.invert(pixels.astype(np.uint16))
        elif pi == "RGB":
            # Convert to Grayscale
            pixels = cvtColor(pixels, COLOR_RGB2GRAY)

        medium_contrast = normalize(src=pixels, dst=None, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=CV_8U).astype(
            np.uint8
        )
        # Apply CLAHE for enhanced contrast
        clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(medium_contrast)

        # Apply Gaussian Blur to reduce noise
        blurred = GaussianBlur(medium_contrast, (5, 5), 0)

        # Apply Canny edge detection with adjusted thresholds
        edges = Canny(blurred, threshold1=100, threshold2=200)

        # Dilate edges to make them more pronounced
        kernel = getStructuringElement(MORPH_RECT, (2, 2))
        edges_dilated = dilate(edges, kernel, iterations=2)

        # # Use morphological closing to fill gaps and create solid text areas
        # closing_kernel = getStructuringElement(MORPH_RECT, (5, 5))
        # edges_filled = morphologyEx(edges_dilated, MORPH_CLOSE, closing_kernel)

        # # Convert the filled edges to white (255)
        # edges_filled[edges_filled > 0] = 255

        # # Find contours and fill them in the edges image
        # contours, _ = findContours(edges_filled, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
        # filled_edges = np.zeros_like(edges_dilated)

        # # Fill each detected contour
        # drawContours(filled_edges, contours, -1, (255), thickness=FILLED)

        thumbnails = [
            Image.fromarray(img)
            .convert("RGB")
            .resize(tuple(dim * 2 for dim in self.THUMBNAIL_SIZE), Image.Resampling.NEAREST)
            for img in [medium_contrast, gray_clahe, edges_dilated]
        ]

        return kaleidoscope(
            patient_id=ds.PatientID,
            study_uid=ds.StudyInstanceUID,
            series_uid=ds.SeriesInstanceUID,
            series_description=ds.get("SeriesDescription", "?"),
            images=thumbnails,
        )

    def _create_kaleidoscope_from_series(self, series_path: Path) -> kaleidoscope:
        # Load and process the series: [min,mean,max] projections multi-frame or [mean,clahe,edge] for single-frame

        dcm_paths = sorted(get_dcm_files(series_path))

        if len(dcm_paths) == 0:
            return

        logger.info(f"Create Kaleidoscope from {series_path.name} from {len(dcm_paths)} DICOM files")

        ds = dcmread(dcm_paths[0])
        pi = ds.get("PhotometricInterpretation", None)
        if pi is None:
            raise ValueError("No PhotometricInterpretation")

        grayscale = pi in ["MONOCHROME1", "MONOCHROME2"]
        no_of_frames = ds.get("NumberOfFrames", 1)

        if len(dcm_paths) == 1 and no_of_frames == 1:
            return self._single_frame_kaleidoscope(ds)

        target_size = (ds.get("Rows", None), ds.get("Columns", None))
        all_series_frames = []

        for dcm_path in dcm_paths:
            if self._stop_event.is_set():
                return None

            if all_series_frames:
                ds = dcmread(dcm_path)
            pixels = ds.pixel_array

            if grayscale:
                pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)
                if pi == "MONOCHROME1":
                    pixels = np.invert(pixels.astype(np.uint16))
                pixels = np.stack([pixels] * 3, axis=-1)

            if pixels.ndim == 4:
                all_series_frames.append(pixels)
            elif pixels.ndim == 3:
                if pixels.shape[:2] != target_size:
                    pixels = self._resize_or_pad_image(pixels, target_size)
                all_series_frames.append(np.expand_dims(pixels, axis=0))
            else:
                raise ValueError("Unexpected pixel array shape")

        all_series_frames = np.concatenate(all_series_frames, axis=0)

        min_pixels = np.min(all_series_frames, axis=0)
        min_projection = normalize(
            src=min_pixels, dst=None, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=CV_8U
        ).astype(np.uint8)
        mean_pixels = np.mean(all_series_frames, axis=0)
        mean_projection = normalize(
            src=mean_pixels, dst=None, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=CV_8U
        ).astype(np.uint8)
        max_pixels = np.max(all_series_frames, axis=0)
        max_projection = normalize(
            src=max_pixels, dst=None, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=CV_8U
        ).astype(np.uint8)

        thumbnails = [
            Image.fromarray(img).resize(tuple(dim * 2 for dim in self.THUMBNAIL_SIZE), Image.Resampling.NEAREST)
            for img in [min_projection, mean_projection, max_projection]
        ]

        return kaleidoscope(
            patient_id=ds.PatientID,
            study_uid=ds.StudyInstanceUID,
            series_uid=ds.SeriesInstanceUID,
            series_description=ds.get("SeriesDescription", "?"),
            images=thumbnails,
        )

    def _load_kaleidoscopes_worker(self):

        logger.info("_load_kaleidoscopes_worker start")

        # TODO: load all kaleidoscopes from pickle file if it exists

        # Create Kaleidoscopes from DICOM files from local disk storage:
        for patient_id in self._patient_ids:
            patient_path = self._base_dir / Path(patient_id)
            if not patient_path.is_dir():
                continue

            for study_path in patient_path.iterdir():
                if not study_path.is_dir():
                    continue

                for series_path in study_path.iterdir():
                    time.sleep(self.WORKER_THREAD_SLEEP_SECS)
                    if not series_path.is_dir():
                        continue

                    try:
                        kaleidoscope = self._create_kaleidoscope_from_series(series_path)
                    except Exception as e:
                        logger.error(repr(e))

                    if kaleidoscope is None:  # stop_event signalled
                        logger.info("_load_kaleidoscopes_worker cancelled")
                        return

                    self._kaleidoscopes.append(kaleidoscope)

        logger.info("_load_kaleidoscopes_worker end")
