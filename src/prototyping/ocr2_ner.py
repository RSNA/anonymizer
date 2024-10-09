import easyocr
import cv2
import os
import numpy as np
import spacy
import re


def contains_date(text):
    # Regex pattern to match various date formats, including those with periods as separators
    date_pattern = r"\b(?:\d{1,2}[-./]\d{1,2}[-./]\d{2,4}|\d{2,4}[-./]\d{1,2}[-./]\d{1,2})\b"

    # Search for the pattern in the text
    if re.search(date_pattern, text):
        return True
    return False


def date_probability(text):
    # Regex pattern to match dates with or without separators
    date_pattern = r"\b(?:\d{1,2}[-/]?\d{1,2}[-/]?\d{2,4}|\d{2,4}[-/]?\d{1,2}[-/]?\d{1,2})\b"

    # Search for all matches in the text
    matches = re.findall(date_pattern, text)

    # Calculate probability based on matches and context
    probability = len(matches) / len(text.split())

    return probability if matches else 0.0


def contains_time(text):
    # Regex pattern to match time formats like "HH:MM", "HH.MM", "HH:MM:SS", "HH.MM.SS", with optional AM/PM
    # Avoids matching full date formats that use dots
    time_pattern = r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?:\s?[APap][Mm])?\b"

    # Search for the pattern in the text
    if re.search(time_pattern, text):
        return True
    return False


def time_probability(text):
    # Regex pattern to match times with or without separators
    time_pattern = r"\b(?:[01]?\d|2[0-3])[:.]?[0-5]\d[:.]?[0-5]?\d?(?:\s?[APap][Mm])?\b"

    # Search for all matches in the text
    matches = re.findall(time_pattern, text)

    # Calculate probability based on matches and context
    probability = len(matches) / len(text.split())

    return probability if matches else 0.0


# Load the spacy model
nlp = spacy.load("en_core_web_trf")


def display_save_images_tiled(images, window_name, save_path):
    """
    Displays a list of images with a small padded arrangement in a window.

    Args:
        images: A list of OpenCV images.
        padding: The padding between images (default: 10).
        window_name: The name of the window (default: "Images").
    """
    padding = 5
    num_images = len(images)
    if num_images == 0:
        print("No images to display.")
        return

    # Determine the best row and column arrangement
    rows = int(np.ceil(np.sqrt(num_images)))
    cols = int(np.ceil(num_images / rows))

    # Create a blank image to hold the tiled images
    height = max(image.shape[0] for image in images) + padding
    width = max(image.shape[1] for image in images) + padding
    canvas = np.zeros((rows * height, cols * width, 3), dtype=np.uint8)

    # Tile the images onto the canvas
    for i, image in enumerate(images):
        row = i // cols
        col = i % cols
        x = col * width + padding
        y = row * height + padding
        canvas[y : y + image.shape[0], x : x + image.shape[1]] = image

    # Save the tiled image
    print(f"Saving tiled images to: {save_path}")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    cv2.imwrite(save_path, canvas)

    # Display the tiled images
    cv2.imshow(window_name, canvas)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# Initialize the EasyOCR reader with the desired language(s)
reader = easyocr.Reader(["en"])  # You can add more languages if needed

# Define the source directory containing the images
source_dir = "phi_imgs/input"
results_dir = "phi_imgs/results"

# Get a list of all .jpg .jpeg .png files in the directory
image_files = [f for f in os.listdir(source_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
image_files = sorted(image_files, key=lambda x: os.path.splitext(x)[0])

# Set the border size (in pixels)
border_size = 40

images_text_detected = []
images_anonymized = []

for image_file in image_files:
    print(f"Processing {image_file}")
    # Read the image
    image_path = os.path.join(source_dir, image_file)
    image = cv2.imread(image_path)

    # Add a border to the resized image
    image = cv2.copyMakeBorder(
        image,
        border_size,
        border_size,
        border_size,
        border_size,
        cv2.BORDER_CONSTANT,
        value=[0, 0, 0],  # Black border
    )

    # Perform OCR on the bordered image
    results = reader.readtext(image)  # , width_ths=0.1)  # Set paragraph=False for word-level detection

    concat_text = ""
    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:
        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox
        top_left = tuple(map(int, top_left))
        bottom_right = tuple(map(int, bottom_right))

        doc = nlp(text)
        for ent in doc.ents:
            print(ent.text, ent.start_char, ent.end_char, ent.label_)

        concat_text += " " + text

        # Determine the color of the bounding box based on confidence level
        box_color = (0, 255, 0) if prob >= 0.5 else (255, 0, 0)  # Green if confidence >= 0.5, else Blue

        # Draw the bounding box and the recognized word
        cv2.rectangle(image, top_left, bottom_right, box_color, 2)
        cv2.putText(image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

    print(f"FULL IMAGE TEXT: {concat_text}")
    doc2 = nlp(concat_text)
    for ent in doc2.ents:
        print(ent.text, ent.start_char, ent.end_char, ent.label_)

    images_text_detected.append(image)


display_save_images_tiled(
    images_text_detected, "Text Regions Detected by CRAFT", os.path.join(results_dir, "text_detect.jpg")
)
