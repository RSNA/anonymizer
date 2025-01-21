import os
import pydicom
import numpy as np
import cv2
import time
from tqdm import tqdm

FACE_MAX_VALUE = 50
FACE_MIN_VALUE = -125

AIR_THRESHOLD = -800
KERNEL_SIZE = 5


def is_dicom(file_path):
    try:
        pydicom.dcmread(file_path)
        return True
    except Exception:
        return False


def get_first_directory(path):
    # Normalize the path to always use Unix-style path separators
    normalized_path = path.replace("\\", "/")
    split_path = normalized_path.split("/")[-1]

    return split_path  # Return None if no directories are found


def list_dicom_directories(root_dir):
    dicom_dirs = set()

    for root, dirs, files in os.walk(root_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if is_dicom(file_path):
                dicom_dirs.add(root)
                break

    return list(dicom_dirs)


def load_scan(path):
    slices = [pydicom.dcmread(path + "/" + s) for s in os.listdir(path)]
    slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
    try:
        slice_thickness = np.abs(slices[0].ImagePositionPatient[2] - slices[1].ImagePositionPatient[2])
    except:
        slice_thickness = np.abs(slices[0].SliceLocation - slices[1].SliceLocation)

    for s in slices:
        s.SliceThickness = slice_thickness

    return slices


def get_pixels_hu(slices):
    image = np.stack([s.pixel_array for s in slices])
    # Convert to int16 (from sometimes int16),
    # should be possible as values should always be low enough (<32k)
    image = image.astype(np.int16)

    # Set outside-of-scan pixels to 0
    # The intercept is usually -1024, so air is approximately 0
    image[image == -2000] = 0

    # Convert to Hounsfield units (HU)
    for slice_number in range(len(slices)):

        intercept = slices[slice_number].RescaleIntercept
        slope = slices[slice_number].RescaleSlope

        if slope != 1:
            image[slice_number] = slope * image[slice_number].astype(np.float64)
            image[slice_number] = image[slice_number].astype(np.int16)

        image[slice_number] += np.int16(intercept)

    return np.array(image, dtype=np.int16)


def binarize_volume(volume, air_hu=AIR_THRESHOLD):
    binary_volume = np.zeros_like(volume, dtype=np.uint8)
    binary_volume[volume <= air_hu] = 1
    return binary_volume


def largest_connected_component(binary_image):
    # Find all connected components and stats
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary_image, connectivity=8)

    # Get the index of the largest component, ignoring the background
    # The background is considered as a component by connectedComponentsWithStats and it is usually the first component
    largest_component_index = np.argmax(stats[1:, cv2.CC_STAT_AREA]) + 1

    # Create an image to keep largest component only
    largest_component_image = np.zeros(labels.shape, dtype=np.uint8)
    largest_component_image[labels == largest_component_index] = 1

    return largest_component_image


def get_largest_component_volume(volume):
    # Initialize an empty array to hold the processed volume
    processed_volume = np.empty_like(volume, dtype=np.uint8)

    # Iterate over each slice in the volume
    for i in range(volume.shape[0]):
        # Process the slice and store it in the processed volume
        processed_volume[i] = largest_connected_component(volume[i])

    return processed_volume


def dilate_volume(volume, kernel_size=KERNEL_SIZE):
    # Create the structuring element (kernel) for dilation
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))

    # Initialize an empty array to hold the dilated volume
    dilated_volume = np.empty_like(volume)

    # Iterate over each slice in the volume
    for i in range(volume.shape[0]):
        # Dilate the slice and store it in the dilated volume
        dilated_volume[i] = cv2.dilate(volume[i].astype(np.uint8), kernel)

    return dilated_volume


def apply_mask_and_get_values(image_volume, mask_volume):
    # Apply the mask by multiplying the image volume with the mask volume
    masked_volume = image_volume * mask_volume

    # Get all unique values in the masked volume, excluding zero
    unique_values = np.unique(masked_volume)
    unique_values = unique_values[unique_values > FACE_MIN_VALUE]
    unique_values = unique_values[unique_values < FACE_MAX_VALUE]

    # Convert numpy array to a list
    unique_values_list = unique_values.tolist()

    return unique_values_list


def apply_random_values_optimized(pixels_hu, dilated_volume, unique_values_list):
    # Initialize new volume as a copy of the original volume
    new_volume = np.copy(pixels_hu)

    # Generate random indices
    random_indices = np.random.choice(len(unique_values_list), size=np.sum(dilated_volume))

    # Select random values from the unique_values_list
    random_values = np.array(unique_values_list)[random_indices]

    # Apply the random values to the locations where dilated_volume equals 1
    new_volume[dilated_volume == 1] = random_values

    return new_volume


def save_new_dicom_files(new_volume, original_dir, out_path, app="_d"):
    # Create a new directory path by appending "_d" to the original directory
    if out_path is None:
        new_dir = original_dir + app
    else:
        new_dir = out_path

    # Create the new directory if it doesn't exist
    if not os.path.exists(new_dir):
        os.makedirs(new_dir)

    # List all DICOM files in the original directory
    dicom_files = [os.path.join(original_dir, f) for f in os.listdir(original_dir) if f.endswith(".dcm")]

    # Sort the dicom_files list by SliceLocation
    dicom_files.sort(key=lambda x: pydicom.dcmread(x).SliceLocation)

    # Loop over each slice of the new volume
    for i in range(new_volume.shape[0]):
        # Get the corresponding original DICOM file
        dicom_file = dicom_files[i]

        # Read the file
        ds = pydicom.dcmread(dicom_file)
        # ds.decompress()

        # Revert the slope and intercept operation on the slice
        new_slice = (new_volume[i] - ds.RescaleIntercept) / ds.RescaleSlope

        # Update the pixel data with the data from the new slice
        ds.PixelData = new_slice.astype(np.int16).tobytes()

        # Generate new file name
        new_file_name = os.path.join(new_dir, f"new_image_{i}.dcm")

        # Save the new DICOM file
        ds.save_as(new_file_name)


def drown_volume(in_path, out_path="deid_ct", replacer="face"):
    """
    Processes DICOM files from the provided directory by binarizing, getting the largest connected component,
    dilating and applying mask. Then applies random values to the dilated volume based on a unique values list
    obtained from the masked volume (or air value). The results are saved as new DICOM files in a specified directory.

    Parameters:
    in_path (str): The path to the directory containing the input DICOM files.
    out_path (str, optional): The path to the directory where the output DICOM files will be saved.
                              If not provided, the output files will be saved in the input directory appended by "_d".
    replacer (str, optional): Indicates what kind of pixels are going to be replaced. Default is 'face'.
                              'face': replaces air and face with random values that are found in the skin and subcutaneous fat.
                              'air': replaces air and face with -1000 HU.
                              int: replaces air and face with int HU.

    Returns:
    None. The function saves new DICOM files and prints the total elapsed time of the operation.
    """
    start_time = time.time()

    dirs = list_dicom_directories(in_path)

    for _d in tqdm(dirs, desc="List of studies"):

        with tqdm(total=8, desc="Processing DICOM Files", leave=False) as pbar:
            # Load the DICOM files
            slices = load_scan(_d)
            pbar.update()

            # Get the pixel values and convert them to Hounsfield Units (HU)
            pixels_hu = get_pixels_hu(slices)
            pbar.update()

            # Apply the binarization function on the HU volume
            binarized_volume = binarize_volume(pixels_hu)
            pbar.update()

            # Get the largest connected component from the binarized volume
            processed_volume = get_largest_component_volume(binarized_volume)
            pbar.update()

            # Dilate the processed volume
            dilated_volume = dilate_volume(processed_volume)
            pbar.update()
            if replacer == "face":
                # Apply the mask to the original volume and get unique values list
                unique_values_list = apply_mask_and_get_values(pixels_hu, dilated_volume - processed_volume)
            elif replacer == "air":
                unique_values_list = [0]
            else:
                try:
                    replacer = int(replacer)
                    unique_values_list = [replacer]
                except:
                    print(
                        "replacer must be either air, face, or an integer number in Hounsfield units, but "
                        + str(replacer)
                        + " was provided."
                    )
                    print("replacing with face")
                    unique_values_list = apply_mask_and_get_values(pixels_hu, dilated_volume - processed_volume)

            pbar.update()

            # Apply random values to the dilated volume based on the unique values list
            new_volume = apply_random_values_optimized(pixels_hu, dilated_volume, unique_values_list)
            pbar.update()

            # Save the new DICOM files
            out_path_n = out_path + "/" + get_first_directory(_d)
            save_new_dicom_files(new_volume, _d, out_path_n)
            pbar.update()

        elapsed_time = time.time() - start_time
        print(f"Total elapsed time: {elapsed_time} seconds")


drown_volume("dcm/CT", "results/face_deid", replacer="face")
