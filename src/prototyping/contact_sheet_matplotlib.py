import os
import pydicom
import numpy as np
import cv2
import numpy as np
import matplotlib.pyplot as plt


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


def load_dicom_image(filepath, target_size):
    ds = pydicom.dcmread(filepath)
    pixels = ds.pixel_array

    if ds.PhotometricInterpretation == "RGB":
        pixels = ds.pixel_array.astype(np.uint8)  # Assume the data is already in RGB format
    else:
        # Apply windowing for grayscale images
        pixels = apply_high_contrast_windowing(ds.pixel_array)
        # pixels = np.stack((pixels,) * 3, axis=-1)  # Convert to 3-channel RGB format

    # Resize using cv2 for better performance
    pixels = cv2.resize(pixels, target_size, interpolation=cv2.INTER_LINEAR)
    return pixels


# Compile DICOM files from the given patient IDs
def compile_dicom_files(patient_ids, base_dir):
    dicom_files = []
    for patient_id in patient_ids:
        patient_path = os.path.join(base_dir, patient_id)
        for study_uid in os.listdir(patient_path):
            study_path = os.path.join(patient_path, study_uid)
            for series_uid in os.listdir(study_path):
                series_path = os.path.join(study_path, series_uid)
                for file in os.listdir(series_path):
                    if file.endswith(".dcm"):
                        dicom_files.append(os.path.join(series_path, file))
    return dicom_files


def display_contact_sheet(patient_ids, base_dir, image_size=(150, 150), columns=4):
    # Load DICOM files
    dicom_files = compile_dicom_files(patient_ids, base_dir)

    # Load images
    images = [load_dicom_image(filepath, target_size=image_size) for filepath in dicom_files]

    # Calculate number of rows
    rows = len(images) // columns + (1 if len(images) % columns != 0 else 0)

    # Create a figure for the contact sheet
    fig, axes = plt.subplots(rows, columns, figsize=(columns * 2, rows * 2), constrained_layout=True)
    axes = axes.flatten()  # Flatten to easily index each subplot

    for i, ax in enumerate(axes):
        if i < len(images):
            ax.imshow(images[i])
            ax.axis("off")
        else:
            ax.axis("off")  # Hide any extra axes

    plt.show()
