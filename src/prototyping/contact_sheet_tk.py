import os
import platform
import pydicom
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import Frame, Canvas, Scrollbar, NW


# Function to apply high-contrast windowing to DICOM image pixel data
def apply_high_contrast_windowing(pixels):
    mean_val = np.mean(pixels)
    std_val = np.std(pixels)
    min_val = mean_val - std_val
    max_val = mean_val + std_val
    windowed_pixels = np.clip(pixels, min_val, max_val)
    windowed_pixels = ((windowed_pixels - min_val) / (max_val - min_val)) * 255.0
    return windowed_pixels.astype(np.uint8)


# Load DICOM image, apply high contrast windowing, and convert to Pillow Image
def load_dicom_image(filepath, target_size=(150, 150)):
    ds = pydicom.dcmread(filepath)
    pixels = ds.pixel_array
    windowed_pixels = apply_high_contrast_windowing(pixels)
    image = Image.fromarray(windowed_pixels).convert("L")
    image = image.resize(target_size, Image.Resampling.LANCZOS)
    return image


# Display all images in a scrollable grid (4 columns)
class DICOMContactSheet(tk.Tk):
    def __init__(self, dicom_dir, columns=4):
        super().__init__()
        self.title("DICOM Contact Sheet with High Contrast and Mouse Scroll")
        self.geometry("800x600")

        # Store all DICOM file paths
        self.dicom_dir = dicom_dir
        self.filepaths = [os.path.join(dicom_dir, f) for f in os.listdir(dicom_dir) if f.endswith(".dcm")]

        # Create canvas with scrollbar for displaying images
        self.canvas = Canvas(self, bg="white")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollbar = Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Create a frame inside the canvas to hold images
        self.frame = Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor=NW)

        # Bind the configuration of the canvas to update scroll region
        self.frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # Bind the mouse wheel to scroll
        self.bind_mouse_scroll()

        # Load all images and display them in the grid
        self.load_images(columns)

    # Function to load and display DICOM images in a grid
    def load_images(self, columns):
        row, col = 0, 0
        for filepath in self.filepaths:
            image = load_dicom_image(filepath)
            img_tk = ImageTk.PhotoImage(image)
            label = tk.Label(self.frame, image=img_tk)
            label.grid(row=row, column=col, padx=5, pady=5)
            label.image = img_tk  # Keep a reference to avoid garbage collection

            col += 1
            if col == columns:
                col = 0
                row += 1

    # Bind mouse scroll based on platform
    def bind_mouse_scroll(self):
        system = platform.system()

        if system == "Windows" or system == "Darwin":  # macOS and Windows
            self.canvas.bind_all("<MouseWheel>", self.on_mouse_scroll)
        elif system == "Linux":
            self.canvas.bind_all("<Button-4>", self.on_mouse_scroll)
            self.canvas.bind_all("<Button-5>", self.on_mouse_scroll)

    # Scroll canvas with the mouse wheel
    def on_mouse_scroll(self, event):
        system = platform.system()

        # Windows and macOS: positive delta = scroll up, negative = scroll down
        if system == "Windows" or system == "Darwin":
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        # Linux older versions (Button-4 is up, Button-5 is down)
        elif system == "Linux":
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")


# Run the application
if __name__ == "__main__":
    dicom_directory = "/Users/michaelevans/Documents/CODE/RSNA/TCIA/DATA/Pseudo-PHI-DICOM-Dataset/Evaluation/manifest-1617826555824/Pseudo-PHI-DICOM-Data/6451050561/07-28-1961-NA-NA-56598/PET IR CTAC WB-48918"
    app = DICOMContactSheet(dicom_directory)
    app.mainloop()
