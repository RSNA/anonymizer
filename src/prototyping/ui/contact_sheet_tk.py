import os
from pathlib import Path
import platform
import pydicom
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from customtkinter import CTk, CTkLabel
from tkinter import Frame, Canvas, Scrollbar, NW
from utils.storage import patient_dcm_files


class ContactSheet(tk.Toplevel):
    def __init__(self, patient_ids, base_dir, image_width=150, image_height=150):
        super().__init__()

        # Store all DICOM file paths
        self.filepaths = self._compile_dicom_files(patient_ids, base_dir)

        # Set window dimensions to 60% width and 80% height of the screen
        target_width = int(0.6 * self.winfo_screenwidth())
        # Round target_width to the nearest multiple of image_width
        window_width = round(target_width / image_width) * image_width

        # Calculate the number of columns based on the window width and image size
        columns = window_width // image_width

        # Calculate the number of rows needed based on the number of images
        num_images = len(self.filepaths)
        rows = (num_images // columns) + (1 if num_images % columns > 0 else 0)  # Round up if there are leftover images

        # Set window height based on the number of rows
        window_height = rows * image_height
        window_height = int(0.8 * self.winfo_screenheight())
        self.geometry(f"{window_width}x{window_height}")
        self.resizable(False, True)

        # Set the window title to the name of the series (last directory in the path)
        self.title(f"Contact sheet for {len(patient_ids)} patients")

        # Calculate the number of columns based on the window width and image size
        columns = window_width // image_width

        # Create canvas with scrollbar for displaying images
        self.canvas = Canvas(self, bg="black")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Create a frame inside the canvas to hold images
        self.frame = Frame(self.canvas, bg="black")
        self.canvas.create_window((0, 0), window=self.frame, anchor=NW)

        # Bind the configuration of the canvas to update scroll region
        self.frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # Bind the mouse wheel to scroll
        self._bind_mouse_scroll()

        # Load all images and display them in the grid
        self._load_images(columns, (image_width, image_height))

    # Compile all DICOM files for all given patient IDs
    def _compile_dicom_files(self, patient_ids, base_dir) -> list[str]:
        return [patient_dcm_files(Path(base_dir / patient_id)) for patient_id in patient_ids]

    # Function to apply high-contrast windowing to DICOM image pixel data to emphasize text
    def _apply_high_contrast_windowing(self, pixels):
        # Set the minimum value to zero (black background)
        min_val = 0
        # Calculate the maximum value based on a certain percentile of the pixel intensity
        max_val = np.percentile(pixels, 95)  # Adjust this percentile as needed to emphasize text

        # Apply the windowing
        windowed_pixels = np.clip(pixels, min_val, max_val)
        # Normalize to 0-255 range
        if max_val > min_val:  # Avoid division by zero
            windowed_pixels = ((windowed_pixels - min_val) / (max_val - min_val)) * 255.0
        else:
            windowed_pixels = np.zeros_like(pixels)  # If all pixels are the same, set to zero

        return windowed_pixels.astype(np.uint8)

    def _load_dicom_image(self, filepath, target_size) -> ImageTk.PhotoImage:
        ds = pydicom.dcmread(filepath)
        pixels = ds.pixel_array
        pi = ds.get("PhotometricInterpretation", None)

        if ds.PhotometricInterpretation == "RGB":
            # Extract the pixel array and ensure it's in the right format
            pixels = ds.pixel_array.astype(np.uint8)  # Assuming pixel_array is already in the correct RGB format
            # Ensure the shape is (height, width, channels)
            if pixels.ndim == 4:  # Check if we have multiple frames
                pixels = pixels[0, 0, :, :]  # Extract the first frame (modify as needed for your data)
        else:
            # Handle grayscale images
            pixels = ds.pixel_array
            if pi == "MONOCHROME1":  # 0 = white
                pixels = np.max(pixels) - pixels
            pixels = self._apply_high_contrast_windowing(pixels)

            # Convert grayscale to 3-channel image for compatibility
            # pixels = np.stack((pixels,) * 3, axis=-1)  # Convert to RGB by duplicating the channels

        # Convert to a PIL ImageTk and resize
        return ImageTk.PhotoImage(Image.fromarray(pixels).resize(target_size, Image.Resampling.LANCZOS))

    # Function to load and display DICOM images in a grid
    def _load_images(self, columns, image_size):
        row, col = 0, 0
        for filepath in self.filepaths:
            image = self._load_dicom_image(filepath, target_size=image_size)
            label = CTkLabel(self.frame, image=image, text="")  # Display image without text
            label.grid(row=row, column=col)
            label.image = image  # Keep a reference to avoid garbage collection
            col += 1
            if col == columns:
                col = 0
                row += 1

    # Bind mouse scroll based on platform
    def _bind_mouse_scroll(self):
        system = platform.system()

        if system == "Windows":
            self.canvas.bind_all("<MouseWheel>", self._on_mouse_scroll_windows)
        elif system == "Darwin":  # macOS
            self.canvas.bind_all("<MouseWheel>", self._on_mouse_scroll_mac)
        elif system == "Linux":
            self.canvas.bind_all("<Button-4>", self._on_mouse_scroll_linux)
            self.canvas.bind_all("<Button-5>", self._on_mouse_scroll_linux)

    # Scroll canvas with the mouse wheel on Windows (event.delta is typically in units of 120)
    def _on_mouse_scroll_windows(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # Scroll canvas with the mouse wheel on macOS (event.delta is in smaller units, usually 1 or 2)
    def _on_mouse_scroll_mac(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta)), "units")

    # Scroll canvas with the mouse wheel on Linux
    def _on_mouse_scroll_linux(self, event):
        if event.num == 4:  # Scroll up
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:  # Scroll down
            self.canvas.yview_scroll(1, "units")
