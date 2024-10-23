from pathlib import Path
import logging
import pydicom
from pydicom.pixel_data_handlers.util import apply_voi_lut, apply_modality_lut
import numpy as np
from PIL import Image
from cv2 import normalize, NORM_MINMAX, equalizeHist
import customtkinter as ctk
from utils.storage import patient_dcm_files
from utils.translate import _

logger = logging.getLogger(__name__)


class ContactSheet(ctk.CTkToplevel):
    THUMBNAIL_SIZE = (150, 150)  # width x height pixels

    def __init__(self, patient_ids, base_dir):
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
        self._load_patient_image_frames(patient_ids)

    def _on_image_click(self, event, dcm_path, frame_number):
        logger.info(f"Image clicked: {dcm_path}, Frame: {frame_number}")

    def _load_patient_image_frames(self, patient_ids):

        # Anonymizer allocates UIDs sequentially as they arrive, sort in this order:
        # TODO: work out an efficient way to sort according to series.InstanceNumber
        # (perhaps add instance number to end or beginning of instance filename?)
        dcm_paths = sorted(
            dcm_path for patient_id in patient_ids for dcm_path in patient_dcm_files(Path(self._base_dir / patient_id))
        )

        logger.info(f"load images frames from {len(dcm_paths)} dicom file(s)")

        total_thumbnails = 0

        # Loop through all dicom files for these patient(s):
        for dcm_path in dcm_paths:

            ds = pydicom.dcmread(dcm_path)

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
