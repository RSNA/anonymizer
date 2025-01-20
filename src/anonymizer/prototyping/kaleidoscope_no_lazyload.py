from pathlib import Path
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
from anonymizer.utils.storage import get_dcm_files, count_series
from anonymizer.utils.translate import _


logger = logging.getLogger(__name__)


@dataclass
class kaleidoscope:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    images: list[Image.Image]


class KaleidoscopeView(ctk.CTkToplevel):
    THUMBNAIL_SIZE = (400, 400)  # width x height pixels

    def __init__(self, mono_font: ctk.CTkFont, patient_ids: list[str], base_dir: Path):
        super().__init__()
        self._data_font = mono_font  # get mono font from app
        self._patient_ids = patient_ids
        self._base_dir = base_dir
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.title(_("Kaleidoscope") + f" {len(patient_ids)} " + _("selected patient(s)"))
        self.geometry("1250x900")
        # TODO: set geometry of kaleidoscope window according to screen dimensions
        # screen_width = self.winfo_screenwidth()
        # screen_height = self.winfo_screenheight()
        self._columns = 3
        self._kaleidoscopes: list[kaleidoscope] = []
        self._series_to_process = count_series(base_dir, patient_ids)
        self._create_widgets()
        self._stop_event = threading.Event()
        self._ks_worker = threading.Thread(
            target=self._load_kaleidoscopes_worker, args=(self._stop_event,), name="Load_Kaleidoscopes"
        )
        self._ks_worker.start()

        logger.info(
            f"KaleidoscopeView for Patients={len(self._patient_ids)}, Total Series={self._series_to_process}, Columns={self._columns}"
        )

    def _create_widgets(self):
        logger.info(f"_create_widgets")
        PAD = 5
        ButtonWidth = 100
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. Kaleidoscope Frame:
        self._ks_frame = ctk.CTkScrollableFrame(self, fg_color="black")
        self._ks_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nswe")
        self._ks_frame.grid_rowconfigure(0, weight=1)

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
        self._update_load_progress(0)

    def _update_load_progress(self, series_processed):
        self._progressbar.set(series_processed / self._series_to_process)
        state_label = _("Loading")
        entity_label = _("Series")
        if series_processed == self._series_to_process:
            state_label = _("Loaded") + " "
        msg = state_label + f" {series_processed} " + _("of") + f" {self._series_to_process} " + entity_label
        self._status.configure(text=msg)

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
        for widget in self._ks_frame.winfo_children():
            widget.unbind("<Button-1>")  # Unbind events
            widget.destroy()  # Explicitly destroy widget

        self._ks_frame.destroy()
        self._status_frame.destroy()
        self.destroy()

    def _on_image_click(self, event, kaleidoscope: kaleidoscope):
        logger.info(f"Image clicked: kaleidoscope: {kaleidoscope}")

    def _load_patient_image_frames(self, patient_ids: list[str]):

        # Anonymizer allocates UIDs sequentially as they arrive, sort in this order:
        # TODO: work out an efficient way to sort according to series.InstanceNumber
        # (perhaps add instance number to end or beginning of instance filename?)
        dcm_paths = sorted(
            dcm_path for patient_id in patient_ids for dcm_path in get_dcm_files(Path(self._base_dir / patient_id))
        )

        logger.info(f"load images frames from {len(dcm_paths)} dicom file(s)")

        total_thumbnails = 0

        # Loop through all dicom files for these patient(s):
        for dcm_path in dcm_paths:

            ds = dcmread(dcm_path)

            pixels = ds.pixel_array
            pi = ds.get("PhotometricInterpretation", None)
            if pi is None:
                continue

            if pi in ["MONOCHROME1", "MONOCHROME2"]:  # Grayscale
                pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)

            normalize(src=pixels, dst=pixels, alpha=0, beta=255, norm_type=NORM_MINMAX, dtype=-1, mask=None)
            pixels = pixels.astype(np.uint8)

            if pi == "MONOCHROME1":  # 0 = white
                pixels = np.invert(pixels)

            no_of_frames = ds.get("NumberOfFrames", 1)

            # Loop through all frames in this dicom file's pixel data:
            for frame in range(no_of_frames):

                ctk_image = ctk.CTkImage(
                    light_image=Image.fromarray(pixels if no_of_frames == 1 else pixels[frame])
                    .convert("RGB")
                    .resize(tuple(dim * 2 for dim in self.THUMBNAIL_SIZE), Image.Resampling.NEAREST),
                    size=self.THUMBNAIL_SIZE,
                )

                label = ctk.CTkLabel(self._frame, image=ctk_image, text="")
                row = int(total_thumbnails // self._columns)
                col = int(total_thumbnails % self._columns)
                label.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
                total_thumbnails += 1

                label.bind(
                    "<Button-1>",  # Left mouse button click event
                    lambda event, path=dcm_path, frame_number=frame: self._on_image_click(event, path, frame_number),
                )

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

    def _single_frame_kaleidoscope(self, ds: Dataset):

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

        self._kaleidoscopes.append(
            kaleidoscope(
                patient_id=ds.PatientID,
                study_uid=ds.StudyInstanceUID,
                series_uid=ds.SeriesInstanceUID,
                series_description=ds.get("SeriesDescription", "?"),
                images=thumbnails,
            )
        )

    def _process_series(self, dcm_paths: list[str], patient_id: str):
        """Process DICOM series and create a kaleidoscope object."""
        ds = dcmread(dcm_paths[0])
        pi = ds.get("PhotometricInterpretation", None)
        if pi is None:
            raise ValueError("No PhotometricInterpretation")

        grayscale = pi in ["MONOCHROME1", "MONOCHROME2"]
        no_of_frames = ds.get("NumberOfFrames", 1)

        if len(dcm_paths) == 1 and no_of_frames == 1:
            self._single_frame_kaleidoscope(ds)
            return

        target_size = (ds.get("Rows", None), ds.get("Columns", None))
        all_series_frames = []

        for dcm_path in dcm_paths:
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

        self._kaleidoscopes.append(
            kaleidoscope(
                patient_id=patient_id,
                study_uid=ds.StudyInstanceUID,
                series_uid=ds.SeriesInstanceUID,
                series_description=ds.get("SeriesDescription", "?"),
                images=thumbnails,
            )
        )

    def _update_sheet(self, kaleidoscope: kaleidoscope):
        series_processed = len(self._kaleidoscopes)
        total_thumbnails = 3 * series_processed - 3

        for image in kaleidoscope.images:
            ctk_image = ctk.CTkImage(light_image=image, size=self.THUMBNAIL_SIZE)
            label = ctk.CTkLabel(self._ks_frame, image=ctk_image, text="")
            row = int(total_thumbnails // self._columns)
            col = int(total_thumbnails % self._columns)
            label.grid(row=row, column=col, padx=2, pady=10, sticky="nsew")
            total_thumbnails += 1
            label.bind("<Button-1>", lambda event, kaleidoscope=kaleidoscope: self._on_image_click(event, kaleidoscope))

        self._update_load_progress(series_processed)

    def _load_kaleidoscopes_worker(self, stop_event: threading.Event):

        logger.info("_load_kaleidoscopes_worker start")

        for patient_id in self._patient_ids:
            patient_path = self._base_dir / Path(patient_id)
            if not patient_path.is_dir():
                continue

            for study_path in patient_path.iterdir():
                if not study_path.is_dir():
                    continue

                for series_path in study_path.iterdir():
                    if stop_event.is_set():
                        break

                    if not series_path.is_dir():
                        continue

                    dcm_paths = sorted(get_dcm_files(series_path))
                    logger.info(f"Processing series in {series_path} with {len(dcm_paths)} DICOM file(s)")

                    if len(dcm_paths) == 0:
                        continue

                    # Process the series for projections or single-frame enhancement
                    self._process_series(dcm_paths, patient_id)

                    # Update the sheet with the latest kaleidoscope
                    self._update_sheet(self._kaleidoscopes[-1])

        logger.info("_load_kaleidoscopes_worker end")
