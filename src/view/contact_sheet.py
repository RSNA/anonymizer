from pathlib import Path
import logging
from dataclasses import dataclass
from pydicom import dcmread
from pydicom.pixel_data_handlers.util import apply_voi_lut, apply_modality_lut
import numpy as np
from PIL import Image
from cv2 import normalize, NORM_MINMAX, CV_8U
import customtkinter as ctk
from utils.storage import get_dcm_files
from utils.translate import _


logger = logging.getLogger(__name__)


@dataclass
class kaleidoscope:
    patient_id: str
    study_uid: str
    series_uid: str
    series_description: str
    thumbnails: list[Image.Image]


class ContactSheet(ctk.CTkToplevel):
    THUMBNAIL_SIZE = (200, 200)  # width x height pixels

    def __init__(self, patient_ids: list[str], base_dir: Path):
        super().__init__()
        self._patient_ids = patient_ids
        self._base_dir = base_dir
        self.geometry("800x900")
        self.title(_("Contact sheet for") + f" {len(patient_ids)} " + _("selected patient(s)"))
        # screen_width = self.winfo_screenwidth()
        # screen_height = self.winfo_screenheight()
        self._frame = ctk.CTkScrollableFrame(self, fg_color="black")
        self._frame.pack(fill="both", expand=True)
        self._columns = max(800 // self.THUMBNAIL_SIZE[0], 1)
        logger.info(f"ContactSheet for Patients={len(patient_ids)}, Columns={self._columns}")
        self._create_kaleidoscopes(patient_ids)
        self._create_sheet()

    def _on_image_click(self, event, kaleidoscope):
        logger.info(f"Image clicked: kaleidoscope: {kaleidoscope}")

    def _load_patient_image_frames(self, patient_ids):

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

    def _create_kaleidoscopes(self):

        self._kaleidoscopes = []

        for patient_id in self._patient_ids:

            patient_path = self._base_dir / Path(patient_id)

            for study_path in patient_path.iterdir():

                if not study_path.is_dir():
                    continue

                for series_path in study_path.iterdir():

                    if not series_path.is_dir():
                        continue

                    dcm_paths = sorted(get_dcm_files(series_path))

                    logger.info(f"Processing series in {series_path} with {len(dcm_paths)} DICOM file(s)")

                    cumulative_pixels = []
                    frame_count = 0

                    for dcm_path in dcm_paths:
                        ds = dcmread(dcm_path)
                        pixels = ds.pixel_array
                        pi = ds.get("PhotometricInterpretation", None)
                        if pi is None:
                            continue

                        if pi in ["MONOCHROME1", "MONOCHROME2"]:
                            pixels = apply_voi_lut(apply_modality_lut(pixels, ds), ds)
                            normalize(
                                src=pixels,
                                dst=pixels,
                                alpha=0,
                                beta=255,
                                norm_type=NORM_MINMAX,
                                dtype=CV_8U,
                                mask=None,
                            )
                            pixels = pixels.astype(np.uint8)
                            if pi == "MONOCHROME1":
                                pixels = np.invert(pixels)

                        no_of_frames = ds.get("NumberOfFrames", 1)
                        if no_of_frames == 1:
                            cumulative_pixels += pixels if pixels.ndim == 2 else np.sum(pixels, axis=0)
                            frame_count += 1
                        else:
                            for frame in range(no_of_frames):
                                frame_data = pixels[frame] if pixels.ndim == 3 else pixels[..., frame]
                                cumulative_pixels += frame_data
                                frame_count += 1

                        mean_pixels = (cumulative_pixels / frame_count).astype(np.uint8)
                        low_contrast = np.clip(mean_pixels * 0.5, 0, 255).astype(np.uint8)
                        high_contrast = np.clip(mean_pixels * 1.5, 0, 255).astype(np.uint8)

                        thumbnails = [
                            Image.fromarray(img)
                            .convert("RGB")
                            .resize(tuple(dim * 2 for dim in self.THUMBNAIL_SIZE), Image.Resampling.NEAREST)
                            for img in [low_contrast, mean_pixels, high_contrast]
                        ]

                        self._kaleidoscopes.append(
                            kaleidoscope(
                                patient_id=patient_id,
                                study_uid=ds.StudyInstanceUID,
                                series_uid=ds.SeriesInstanceUID,
                                series_description=ds.get("SeriesDescription", "?"),
                                thumbnails=thumbnails,
                            )
                        )

    def _create_sheet(self):
        total_thumbnails = 0

        for kaleidoscope in self._kaleidoscopes:
            ctk_image = ctk.CTkImage(light_image=kaleidoscope.thumbnails[1], size=self.THUMBNAIL_SIZE)
            label = ctk.CTkLabel(self._frame, image=ctk_image, text="")
            row = int(total_thumbnails // self._columns)
            col = int(total_thumbnails % self._columns)
            label.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
            total_thumbnails += 1
            label.bind(
                "<Button-1>",
                lambda event, kaleidoscope=kaleidoscope: self._on_image_click(event, kaleidoscope),
            )

        # # Add rotation logic
        # def rotate_images():
        #     index = 0
        #     while True:
        #         ctk_image.configure(light_image=thumbnails[index])
        #         self._frame.update_idletasks()
        #         self._frame.after(500)  # Wait for 0.5 seconds
        #         index = (index + 1) % len(thumbnails)
