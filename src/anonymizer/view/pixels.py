import logging
from dataclasses import dataclass
from enum import Enum
from math import ceil
from pathlib import Path

import customtkinter as ctk
import numpy as np
from cv2 import (
    COLOR_RGB2GRAY,
    CV_8U,
    INTER_AREA,
    MORPH_RECT,
    # MORPH_CLOSE,
    # RETR_EXTERNAL,
    # CHAIN_APPROX_SIMPLE,
    # FILLED,
    NORM_MINMAX,
    # equalizeHist,
    Canny,
    GaussianBlur,
    createCLAHE,
    cvtColor,
    dilate,
    # morphologyEx,
    # findContours,
    # drawContours,
    getStructuringElement,
    normalize,
    resize,
)
from PIL import Image
from pydicom import Dataset, dcmread
from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut

from anonymizer.utils.storage import get_dcm_files
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


@dataclass
class kaleidoscope:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    images: list[Image.Image]


class KaleidoscopeImageSize(Enum):
    # rect size in pixels (width, height)
    SMALL = (100, 100)
    MEDIUM = (200, 200)
    LARGE = (300, 300)

    def width(self):
        return self.value[0]

    def height(self):
        return self.value[1]


class KaleidoscopePAD(Enum):
    # padx, pady in pixels
    SMALL = (2, 4)
    MEDIUM = (3, 6)
    LARGE = (5, 10)

    def width(self):
        return self.value[0]

    def height(self):
        return self.value[1]


PAD_MAP: dict[KaleidoscopeImageSize, KaleidoscopePAD] = {
    KaleidoscopeImageSize.SMALL: KaleidoscopePAD.SMALL,
    KaleidoscopeImageSize.MEDIUM: KaleidoscopePAD.MEDIUM,
    KaleidoscopeImageSize.LARGE: KaleidoscopePAD.LARGE,
}


def get_pad(size):
    return PAD_MAP[size]


class PixelsView(ctk.CTkToplevel):
    KS_FRAME_RELATIVE_SIZE = (0.9, 0.9)  # fraction of screen size (width, height)
    WIDGET_PAD = 10
    IMAGE_PAD = 2  # pixels between the kaleidoscopes images when combined
    key_to_image_size_mapping: dict[str, KaleidoscopeImageSize] = {
        "S": KaleidoscopeImageSize.SMALL,
        "M": KaleidoscopeImageSize.MEDIUM,
        "L": KaleidoscopeImageSize.LARGE,
    }
    DEFAULT_SIZE = "S"

    def _get_series_paths(self) -> list[Path]:
        return [
            series_path
            for patient_id in self._patient_ids
            for study_path in (self._base_dir / Path(patient_id)).iterdir()
            if study_path.is_dir()
            for series_path in study_path.iterdir()
            if series_path.is_dir()
        ]

    def __init__(
        self,
        mono_font: ctk.CTkFont,
        base_dir: Path,
        patient_ids: list[str] | None = None,
    ):
        super().__init__()
        self._data_font = mono_font  # get mono font from app

        if not base_dir.is_dir():
            raise ValueError(f"{base_dir} is not a valid directory")

        # If patient_ids is not specified, iterate through ALL patient sub-directories to compile patient_ids:
        if patient_ids is None:
            patient_ids = [str(p) for p in base_dir.iterdir() if p.is_dir()]

        if not patient_ids:
            raise ValueError("No patients for PixelsView")

        self._patient_ids = patient_ids
        self._base_dir = base_dir

        self._series_paths = self._get_series_paths()
        if not self._series_paths:
            raise ValueError("No series paths found for patient list")

        self._total_series = len(self._series_paths)
        self._image_size = KaleidoscopeImageSize.SMALL

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.resizable(width=False, height=False)

        self._ks_frame_width = int(self.KS_FRAME_RELATIVE_SIZE[0] * self.winfo_screenwidth())
        self._ks_frame_height = int(self.KS_FRAME_RELATIVE_SIZE[1] * self.winfo_screenheight())

        self._page_number = 0
        self._rows = 0
        self._cols = 0
        self._pages = 0
        self._loading_page = False
        self._ks_labels = {}
        self._calc_layout()
        self._update_title()
        self._create_widgets()

        logger.info(
            f"PixelsView for Patients={len(self._patient_ids)}, Total Series={self._total_series}, Total Pages={self._pages}"
        )

        # Bind Arrow buttons to page control
        self.bind("<Left>", lambda e: self._on_page_slider(max(0, self._page_number - 1)))
        self.bind(
            "<Right>",
            lambda e: self._on_page_slider(min(self._pages - 1, self._page_number + 1)),
        )
        self.bind("<MouseWheel>", self._mouse_wheel)

        self._update_image_size(self.DEFAULT_SIZE)

    def _update_title(self):
        title = (
            _("View")
            + f" {len(self._patient_ids)} "
            + (_("Patients") if len(self._patient_ids) > 1 else _("Patient"))
            + " "
            + _("with")
            + f" {self._total_series} "
            + _("Series")
        )

        if self._pages > 1:
            title = title + " " + _("over") + f" {self._pages} " + _("Pages")

        self.title(title)

    def _calc_layout(self):
        padded_combined_width = (
            3 * self._image_size.width() + 2 * self.IMAGE_PAD + 2 * get_pad(self._image_size).width()
        )
        padded_combined_height = self._image_size.height() + get_pad(self._image_size).height()

        self._rows = self._ks_frame_height // padded_combined_height
        self._cols = self._ks_frame_width // padded_combined_width
        self._pages = ceil(self._total_series / (self._rows * self._cols))

    def _create_widgets(self):
        logger.info("_create_widgets")
        PAD = self.WIDGET_PAD

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. Kaleidoscope Frame:
        self._ks_frame = ctk.CTkFrame(
            self,
            width=self._ks_frame_width,
            height=self._ks_frame_height,
            fg_color="black",
        )
        self._ks_frame.grid(row=0, column=0, padx=PAD, pady=PAD, sticky="nsew")

        # 2. Bottom Frame for paging & image sizing:
        self._paging_frame = ctk.CTkFrame(self)
        self._paging_frame.grid(row=1, column=0, padx=PAD, pady=(0, PAD), sticky="ew")
        self._paging_frame.grid_columnconfigure(0, weight=1)

        self._page_slider = ctk.CTkSlider(
            self._paging_frame,
            from_=0,
            to=1,
            number_of_steps=1,
            command=self._on_page_slider,
        )
        self._page_slider.grid(row=0, column=0, padx=PAD, pady=0, sticky="we")
        self._page_slider.set(0)

        self._page_label = ctk.CTkLabel(self._paging_frame, text="Page ...")
        self._page_label.grid(row=0, column=1, padx=PAD, pady=0, sticky="e")

        # Segmented Button for kaleidoscope image size selection
        self._image_size_button = ctk.CTkSegmentedButton(
            self._paging_frame, values=["S", "M", "L"], command=self._update_image_size
        )
        self._image_size_button.set(self.DEFAULT_SIZE)
        self._image_size_button.grid(row=0, column=2)

    def _mouse_wheel(self, event):
        if event.delta > 0:  # Scroll up
            next_page_number = self._page_number + 1
            if next_page_number >= self._pages:
                return
        elif event.delta < 0:
            next_page_number = self._page_number - 1
            if next_page_number < 0:
                return

        self._on_page_slider(next_page_number)

    def _update_image_size(self, value):
        logger.info(f"Updating image size to {value}")

        self._image_size = self.key_to_image_size_mapping[value]
        self._calc_layout()

        for widget in self._ks_frame.winfo_children():
            widget.destroy()
        self._ks_frame.update()
        self._ks_labels.clear()

        self._page_slider.configure(to=self._pages - 1, number_of_steps=self._pages)

        # Redraw the kaleidoscope frame with new size
        self._populate_ks_frame(self._page_number)

    def _on_page_slider(self, value):
        if self._loading_page:
            return

        logger.info(f"value: {value}, current_page: {self._page_number}")

        if abs(value - self._page_number) < 1:
            next_page_number = self._page_number + 1 if value > self._page_number else self._page_number - 1
        else:
            next_page_number = round(value)

        if next_page_number == self._page_number:
            logger.warning("page event to update to same page number")
            return

        try:
            self._loading_page = True  # prevent re-entry, use lock instead?
            self._page_slider.configure(state="disabled")
            self._populate_ks_frame(next_page_number)
        finally:
            self._page_slider.configure(state="normal")
            self._page_slider.set(next_page_number)
            self._loading_page = False

    def _populate_ks_frame(self, page_number: int):
        """Populate the Kaleidoscope frame with images for the given page number."""
        logger.info(f"Populate ks_frame page={page_number}")
        self._page_number = page_number
        self._page_label.configure(text=_("Page") + f" {self._page_number + 1} " + _("of") + f" {self._pages}")

        if not hasattr(self, "_ks_labels"):
            self._ks_labels = {}  # Initialize labels dictionary if not present

        def create_or_update_label(row, col, image, kaleidoscope=None):
            """Create or update a label at the given grid position."""
            label_key = (row, col)

            # Create or fetch the label
            if label_key not in self._ks_labels:
                label = ctk.CTkLabel(self._ks_frame, text="")
                label.grid(
                    row=row,
                    column=col,
                    padx=(0, get_pad(self._image_size).value[0]),
                    pady=(0, get_pad(self._image_size).value[1]),
                    sticky="nsew",
                )
                self._ks_labels[label_key] = label
            else:
                label = self._ks_labels[label_key]

            # Clear previous image and bind new event if applicable
            old_image = getattr(label, "image", None)
            if old_image:
                del old_image  # Explicitly delete the old image reference
            label.configure(image=image)
            # label.image = image  # Keep reference to avoid garbage collection

            label.unbind("<Button-1>")
            if kaleidoscope:
                label.bind(
                    "<Button-1>",
                    lambda event, k=kaleidoscope: self._on_image_click(event, k),
                )

        def generate_black_image():
            """Generate a black placeholder image."""
            size = (
                3 * self._image_size.width() + 2 * self.IMAGE_PAD,
                self._image_size.height(),
            )
            black_image = Image.new(mode="RGB", size=size, color="black")
            return ctk.CTkImage(light_image=black_image, size=size)

        def generate_combined_image(series_path):
            """Generate a combined image from the series."""
            kaleidoscope = self._create_kaleidoscope_from_series(series_path)
            combined_width = 3 * self._image_size.width() + 2 * self.IMAGE_PAD
            combined_image = Image.new(
                mode="RGB",
                size=(combined_width, self._image_size.height()),
                color="black",
            )
            for i, image in enumerate(kaleidoscope.images):
                resized_image = image.resize(self._image_size.value)
                combined_image.paste(resized_image, (i * (self._image_size.width() + self.IMAGE_PAD), 0))
            return (
                ctk.CTkImage(
                    light_image=combined_image,
                    size=(combined_width, self._image_size.height()),
                ),
                kaleidoscope,
            )

        # Populate the grid
        start_index = page_number * self._rows * self._cols
        ks_index = start_index

        for row in range(self._rows):
            for col in range(self._cols):
                if ks_index < self._total_series:
                    # Generate and display the combined image for the series
                    series_path = self._series_paths[ks_index]
                    ctk_image, kaleidoscope = generate_combined_image(series_path)
                    create_or_update_label(row, col, ctk_image, kaleidoscope)
                else:
                    # Display a black image for unused grid cells
                    create_or_update_label(row, col, generate_black_image())

                ks_index += 1
                self._ks_frame.update()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self.destroy()

    def _on_image_click(self, event, kaleidoscope: kaleidoscope):
        logger.info(f"Kaleidoscope clicked: kaleidoscope: {kaleidoscope}")

    def _resize_or_pad_image(self, image_np: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
        """Resize or pad an image to match the target size (height, width)."""
        target_height, target_width = target_size
        logger.info(
            f"Resize image in series from {image_np.shape[1]}x{image_np.shape[0]} to {target_width}x{target_height}"
        )

        # Resize and interpolate
        scale = min(target_width / image_np.shape[1], target_height / image_np.shape[0])
        resized_np = resize(
            image_np,
            (int(image_np.shape[0] * scale), int(image_np.shape[1] * scale)),
            interpolation=INTER_AREA,
        )

        # Calculate offsets for centering
        y_offset = (target_height - resized_np.shape[0]) // 2
        x_offset = (target_width - resized_np.shape[1]) // 2

        # Create a padded image with the same number of channels as the resized image
        if resized_np.ndim == 3:  # RGB (3 channels)
            padded_image = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        else:  # Grayscale (1 channel)
            padded_image = np.zeros((target_height, target_width), dtype=np.uint8)

        # Place the resized image in the center of the padded image
        padded_image[
            y_offset : y_offset + resized_np.shape[0],
            x_offset : x_offset + resized_np.shape[1],
        ] = resized_np

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

        medium_contrast = np.zeros_like(pixels)
        normalize(
            src=pixels,
            dst=medium_contrast,
            alpha=0,
            beta=255,
            norm_type=NORM_MINMAX,
            dtype=CV_8U,
        )
        medium_contrast = medium_contrast.astype(np.uint8)
        # Apply CLAHE for enhanced contrast
        clahe = createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray_clahe = clahe.apply(medium_contrast)

        # Apply Gaussian Blur to reduce noise
        blurred = GaussianBlur(medium_contrast, (5, 5), 0)

        # Apply Canny edge detection with adjusted thresholds
        edges = Canny(blurred, threshold1=100, threshold2=200)

        # Dilate edges to make them more pronounced
        kernel = getStructuringElement(shape=MORPH_RECT, ksize=(2, 2))
        edges_dilated = dilate(src=edges, kernel=kernel, iterations=2)

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
            .resize(
                (
                    KaleidoscopeImageSize.LARGE.value[0] * 2,
                    KaleidoscopeImageSize.LARGE.value[1] * 2,
                ),
                Image.Resampling.NEAREST,
            )
            for img in [medium_contrast, gray_clahe, edges_dilated]
        ]

        return kaleidoscope(
            patient_id=ds.PatientID,
            study_uid=ds.StudyInstanceUID,
            series_uid=ds.SeriesInstanceUID,
            series_description=ds.get("SeriesDescription", "?"),
            images=thumbnails,
        )

    def _normalize_uint8(self, image: np.ndarray) -> np.ndarray:
        """Normalize and convert an image to uint8."""
        return normalize(
            src=image,
            dst=np.empty_like(image),
            alpha=0,
            beta=255,
            norm_type=NORM_MINMAX,
            dtype=CV_8U,
        ).astype(np.uint8)

    def _create_kaleidoscope_from_series(self, series_path: Path) -> kaleidoscope:
        # Load and process the series: [min,mean,max] projections multi-frame or [mean,clahe,edge] for single-frame

        dcm_paths: list[Path] = sorted(get_dcm_files(series_path))

        if len(dcm_paths) == 0:
            raise ValueError(f"No DICOM files found in {series_path}")

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

        # Compute min, mean, and max projections
        min_projection = self._normalize_uint8(np.min(all_series_frames, axis=0))
        mean_projection = self._normalize_uint8(np.mean(all_series_frames, axis=0))
        max_projection = self._normalize_uint8(np.max(all_series_frames, axis=0))

        thumbnails = [
            Image.fromarray(img).resize(
                (
                    KaleidoscopeImageSize.LARGE.value[0] * 2,
                    KaleidoscopeImageSize.LARGE.value[1] * 2,
                ),
                Image.Resampling.NEAREST,
            )
            for img in [min_projection, mean_projection, max_projection]
        ]

        return kaleidoscope(
            patient_id=ds.PatientID,
            study_uid=ds.StudyInstanceUID,
            series_uid=ds.SeriesInstanceUID,
            series_description=ds.get("SeriesDescription", "?"),
            images=thumbnails,
        )
