import easyocr
import cv2
import os
import numpy as np


def display_save_images_tiled(images, window_name, save_path):
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


print("OCR3 Anonymize Pixel PHI with black rectangles")

# Initialize the EasyOCR reader with the desired language(s)
reader = easyocr.Reader(["en"])  # You can add more languages if needed

# Define the source directory containing the images
source_dir = "phi_imgs/input_1"
results_dir = "phi_imgs/results_1"

# Get a list of all .jpg .jpeg .png files in the directory
image_files = [f for f in os.listdir(source_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
image_files = sorted(image_files, key=lambda x: os.path.splitext(x)[0])

# Set the border size (in pixels)
border_size = 20

source_images = []
images_text_detected = []
images_anonymized = []

for image_file in image_files:
    print(f"Processing {image_file}")
    # Read the image
    image_path = os.path.join(source_dir, image_file)
    source_image = cv2.imread(image_path)

    image = source_image.copy()

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

    # Create a copy of the image to draw black rectangles over text areas
    anonymized_image = image.copy()

    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:
        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox
        top_left = tuple(map(int, top_left))
        bottom_right = tuple(map(int, bottom_right))

        # Draw a black rectangle over the detected text area to anonymize it
        cv2.rectangle(anonymized_image, top_left, bottom_right, (0, 0, 0), cv2.FILLED)

        # Determine the color of the bounding box based on confidence level
        box_color = (0, 255, 0) if prob >= 0.5 else (255, 0, 0)  # Green if confidence >= 0.5, else Blue

        # Draw the bounding box and the recognized word
        cv2.rectangle(image, top_left, bottom_right, box_color, 2)
        cv2.putText(image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

    source_images.append(source_image)
    images_text_detected.append(image)
    images_anonymized.append(anonymized_image)

display_save_images_tiled(
    source_images,
    "PHI Burnt-IN Image Samples from RSNA Synthetic & TJU Datasets",
    os.path.join(results_dir, "sample_images.jpg"),
)
display_save_images_tiled(
    images_text_detected, "Text Regions Detected by CRAFT", os.path.join(results_dir, "text_detect.jpg")
)
display_save_images_tiled(
    images_anonymized, "Burnt-IN PHI Blacked-out", os.path.join(results_dir, "anonymized_blacked.jpg")
)
