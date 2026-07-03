import os
import platform
import pydicom
import numpy as np
from PIL import Image, ImageTk
import customtkinter as ctk
from customtkinter import CTk, CTkLabel, CTkImage
from tkinter import Frame, Canvas, Scrollbar, NW

# Initialize CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# Function to apply high-contrast windowing to DICOM image pixel data
def apply_high_contrast_windowing(pixels):
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


# Load DICOM image, apply high contrast windowing, and convert to CTkImage
def load_dicom_image(filepath, target_size=(150, 150)):
    ds = pydicom.dcmread(filepath)
    pixels = ds.pixel_array
    windowed_pixels = apply_high_contrast_windowing(pixels)

    # Convert to a PIL Image and resize
    image = Image.fromarray(windowed_pixels).convert("L")
    image = image.resize(target_size, Image.Resampling.LANCZOS)

    # Convert PIL Image to CTkImage
    # ctk_image = CTkImage(light_image=image, dark_image=image, size=target_size)
    # return ctk_image
    return ImageTk.PhotoImage(image)


# Display all images in a scrollable grid with dynamic window size and columns
class DICOMContactSheet(CTk):
    def __init__(self, dicom_dir, image_width=150, image_height=150):
        super().__init__()

        # Get screen width and height to calculate window size
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Set window dimensions to 60% width and 80% height of the screen
        target_width = int(0.6 * screen_width)
        window_width = round(target_width / image_width) * image_width
        window_height = int(0.8 * screen_height)
        self.geometry(f"{window_width}x{window_height}")

        # Set the window title to the name of the series (last directory in the path)
        self.title(f"Series: {os.path.basename(dicom_dir)}")

        # Store all DICOM file paths
        self.dicom_dir = dicom_dir
        self.filepaths = [os.path.join(dicom_dir, f) for f in os.listdir(dicom_dir) if f.endswith(".dcm")]

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
        self.bind_mouse_scroll()

        # Load all images and display them in the grid
        self.load_images(columns, (image_width, image_height))

    # Function to load and display DICOM images in a grid
    def load_images(self, columns, image_size):
        row, col = 0, 0
        for filepath in self.filepaths:
            image = load_dicom_image(filepath, target_size=image_size)
            label = CTkLabel(self.frame, image=image, text="")  # Display image without text
            label.grid(row=row, column=col, padx=0, pady=0)
            label.image = image  # Keep a reference to avoid garbage collection

            col += 1
            if col == columns:
                col = 0
                row += 1

    # Bind mouse scroll based on platform
    def bind_mouse_scroll(self):
        system = platform.system()

        if system == "Windows":
            self.canvas.bind_all("<MouseWheel>", self.on_mouse_scroll_windows)
        elif system == "Darwin":  # macOS
            self.canvas.bind_all("<MouseWheel>", self.on_mouse_scroll_mac)
        elif system == "Linux":
            self.canvas.bind_all("<Button-4>", self.on_mouse_scroll_linux)
            self.canvas.bind_all("<Button-5>", self.on_mouse_scroll_linux)

    # Scroll canvas with the mouse wheel on Windows (event.delta is typically in units of 120)
    def on_mouse_scroll_windows(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # Scroll canvas with the mouse wheel on macOS (event.delta is in smaller units, usually 1 or 2)
    def on_mouse_scroll_mac(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta)), "units")

    # Scroll canvas with the mouse wheel on Linux
    def on_mouse_scroll_linux(self, event):
        if event.num == 4:  # Scroll up
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:  # Scroll down
            self.canvas.yview_scroll(1, "units")


# Run the application
if __name__ == "__main__":
    dicom_directory = "/Users/michaelevans/Documents/CODE/RSNA/TCIA/DATA/Pseudo-PHI-DICOM-Dataset/Evaluation/manifest-1617826555824/Pseudo-PHI-DICOM-Data/6451050561/07-28-1961-NA-NA-56598/PET IR CTAC WB-48918"
    app = DICOMContactSheet(dicom_directory)
    app.mainloop()
